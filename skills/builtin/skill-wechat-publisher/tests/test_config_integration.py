"""
Integration tests for config resolution across script entrypoints.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _prepare_isolated_skill_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True)

    for filename in ("config.py", "generate_image.py", "baoyu_image_gen_core.ts"):
        shutil.copy(repo_root / "scripts" / filename, scripts_dir / filename)

    (skill_root / "wechat-publisher.yaml").write_text(
        textwrap.dedent(
            """\
            default: main
            accounts:
              main:
                name: "Skill Root"
                app_id: "wx_skill_root"
                app_secret: "skill_root_secret"
                author: "root"
            image_generation:
              generator: "baoyu-danger-gemini-web"
              gemini_proxy:
                base_url: "https://skill-root.example"
                api_key: "skill-root-key"
                image_model: "gemini-3-pro-image-preview"
            """
        ),
        encoding="utf-8",
    )

    cwd_dir = tmp_path / "other-cwd"
    cwd_dir.mkdir()
    (cwd_dir / "wechat-publisher.yaml").write_text(
        textwrap.dedent(
            """\
            default: main
            accounts:
              main:
                name: "Wrong CWD"
                app_id: "wx_wrong_cwd"
                app_secret: "wrong_cwd_secret"
                author: "cwd"
            image_generation:
              generator: "baoyu-image-gen"
              gemini_proxy:
                base_url: "https://wrong-cwd.example"
                api_key: "wrong-cwd-key"
                image_model: "wrong-cwd-model"
            """
        ),
        encoding="utf-8",
    )

    home_dir = tmp_path / "home"
    home_cfg_dir = home_dir / ".wechat-publisher"
    home_cfg_dir.mkdir(parents=True)
    (home_cfg_dir / "wechat-publisher.yaml").write_text(
        textwrap.dedent(
            """\
            default: main
            accounts:
              main:
                name: "Wrong Home"
                app_id: "wx_wrong_home"
                app_secret: "wrong_home_secret"
                author: "home"
            image_generation:
              generator: "baoyu-image-gen"
              gemini_proxy:
                base_url: "https://wrong-home.example"
                api_key: "wrong-home-key"
                image_model: "wrong-home-model"
            """
        ),
        encoding="utf-8",
    )

    return skill_root, scripts_dir, cwd_dir


def test_generate_image_print_command_uses_skill_root_yaml_only(tmp_path):
    """generate_image.py should ignore cwd/home YAML and resolve config from its own skill root."""
    _, scripts_dir, cwd_dir = _prepare_isolated_skill_root(tmp_path)
    home_dir = tmp_path / "home"

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "generate_image.py"),
            "--account",
            "main",
            "--image",
            "out.png",
            "--print-command",
        ],
        cwd=cwd_dir,
        env={**os.environ, "HOME": str(home_dir)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "generator: baoyu-danger-gemini-web" in result.stdout


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun is not installed")
def test_bun_load_env_uses_skill_root_yaml_only(tmp_path):
    """baoyu_image_gen_core.loadEnv() should ignore cwd/home YAML and export from its own skill root."""
    _, scripts_dir, cwd_dir = _prepare_isolated_skill_root(tmp_path)
    home_dir = tmp_path / "home"

    code = textwrap.dedent(
        """\
        import { loadEnv, detectProvider, getDefaultModel } from "./scripts/baoyu_image_gen_core.ts";

        const args = {
          prompt: "x",
          promptFiles: [],
          imagePath: "out.png",
          provider: null,
          model: null,
          aspectRatio: null,
          size: null,
          quality: "normal",
          referenceImages: [],
          n: 1,
          json: false,
          help: false,
        };

        await loadEnv();
        console.log(JSON.stringify({
          provider: detectProvider(args),
          baseUrl: process.env.GEMINI_PROXY_BASE_URL,
          model: getDefaultModel("gemini-proxy"),
          generator: process.env.WECHAT_PUBLISHER_IMAGE_GENERATOR,
        }));
        """
    )

    result = subprocess.run(
        ["bun", "--eval", code],
        cwd=tmp_path / "skill",
        env={"PATH": os.environ["PATH"], "HOME": str(home_dir)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == (
        '{"provider":"gemini-proxy","baseUrl":"https://skill-root.example",'
        '"model":"gemini-3-pro-image-preview","generator":"baoyu-danger-gemini-web"}'
    )


@pytest.mark.skipif(shutil.which("bun") is None, reason="bun is not installed")
def test_bun_load_env_prefers_canonical_yaml_over_ambient_provider_env(tmp_path):
    """baoyu_image_gen_core.loadEnv() should let canonical YAML override conflicting shell provider env."""
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True)

    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "scripts" / "config.py", scripts_dir / "config.py")
    shutil.copy(repo_root / "scripts" / "baoyu_image_gen_core.ts", scripts_dir / "baoyu_image_gen_core.ts")

    (skill_root / "wechat-publisher.yaml").write_text(
        textwrap.dedent(
            """\
            image_generation:
              openai:
                api_key: "sk-canonical-openai"
                image_model: "gpt-image-1"
            """
        ),
        encoding="utf-8",
    )

    code = textwrap.dedent(
        """\
        import { loadEnv, detectProvider } from "./scripts/baoyu_image_gen_core.ts";

        const args = {
          prompt: "x",
          promptFiles: [],
          imagePath: "out.png",
          provider: null,
          model: null,
          aspectRatio: null,
          size: null,
          quality: "normal",
          referenceImages: [],
          n: 1,
          json: false,
          help: false,
        };

        await loadEnv();
        console.log(detectProvider(args));
        """
    )

    result = subprocess.run(
        ["bun", "--eval", code],
        cwd=skill_root,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "home"),
            "GEMINI_PROXY_API_KEY": "ambient-proxy-key",
        },
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "openai"


def test_generate_image_uses_global_generator_when_accounts_are_incomplete(tmp_path):
    """generate_image.py should still honor global image_generation.generator when account config is unavailable."""
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True)

    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "scripts" / "config.py", scripts_dir / "config.py")
    shutil.copy(repo_root / "scripts" / "generate_image.py", scripts_dir / "generate_image.py")

    (skill_root / "wechat-publisher.yaml").write_text(
        textwrap.dedent(
            """\
            image_generation:
              generator: "baoyu-danger-gemini-web"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "generate_image.py"),
            "--image",
            "out.png",
            "--print-command",
        ],
        cwd=skill_root,
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "generator: baoyu-danger-gemini-web" in result.stdout


@pytest.mark.parametrize(
    "yaml_text",
    [
        "default: [broken\naccounts:\n  main: {}\n",
        "",
        "{}\n",
    ],
)
@pytest.mark.skipif(shutil.which("bun") is None, reason="bun is not installed")
def test_bun_load_env_does_not_mask_invalid_skill_root_yaml(tmp_path, yaml_text):
    """baoyu_image_gen_core.loadEnv() should fail on invalid or empty skill-root YAML even if shell provider env exists."""
    skill_root = tmp_path / "skill"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True)

    repo_root = Path(__file__).resolve().parents[1]
    shutil.copy(repo_root / "scripts" / "config.py", scripts_dir / "config.py")
    shutil.copy(repo_root / "scripts" / "baoyu_image_gen_core.ts", scripts_dir / "baoyu_image_gen_core.ts")

    (skill_root / "wechat-publisher.yaml").write_text(yaml_text, encoding="utf-8")

    code = textwrap.dedent(
        """\
        import { loadEnv, detectProvider } from "./scripts/baoyu_image_gen_core.ts";

        const args = {
          prompt: "x",
          promptFiles: [],
          imagePath: "out.png",
          provider: null,
          model: null,
          aspectRatio: null,
          size: null,
          quality: "normal",
          referenceImages: [],
          n: 1,
          json: false,
          help: false,
        };

        await loadEnv();
        console.log(detectProvider(args));
        """
    )

    result = subprocess.run(
        ["bun", "--eval", code],
        cwd=skill_root,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path / "home"),
            "OPENAI_API_KEY": "sk-test",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "openai" not in result.stdout
