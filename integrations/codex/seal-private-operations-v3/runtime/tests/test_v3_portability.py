"""Seal V3 self-containment and cross-platform media contracts."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from easel.paths import RUNTIME_ROOT, media_bin_dir, node_bin_dir, runtime_path_entries, venv_bin_dir


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_path_prefers_v3_owned_tools(monkeypatch, tmp_path):
    media = tmp_path / "media"
    monkeypatch.setenv("SEAL_MEDIA_BIN", str(media))
    entries = runtime_path_entries()
    assert entries == [str(media), str(venv_bin_dir()), str(node_bin_dir())]
    assert str(RUNTIME_ROOT) in str(venv_bin_dir())
    assert str(RUNTIME_ROOT) in str(node_bin_dir())


def test_relative_media_marker_stays_inside_v3(monkeypatch, tmp_path):
    monkeypatch.delenv("SEAL_MEDIA_BIN", raising=False)
    marker = RUNTIME_ROOT / ".seal-media-bin"
    original = marker.read_text(encoding="utf-8") if marker.is_file() else None
    try:
        marker.write_text("tools/media-macos\n", encoding="utf-8")
        assert media_bin_dir() == RUNTIME_ROOT / "tools" / "media-macos"
    finally:
        if original is None:
            marker.unlink(missing_ok=True)
        else:
            marker.write_text(original, encoding="utf-8")


def test_asr_word_timestamp_json_contract():
    asr = _load("seal_asr", RUNTIME_ROOT / "skills/shared/scripts/asr.py")
    rendered = json.loads(asr._render_json(
        [(0.0, 1.0, "你好")],
        {
            "language": "zh",
            "_word_segments": [{
                "start": 0.0,
                "end": 1.0,
                "text": "你好",
                "words": [{"start": 0.0, "end": 1.0, "word": "你好"}],
            }],
        },
    ))
    assert rendered["language"] == "zh"
    assert rendered["segments"][0]["words"][0]["word"] == "你好"
    assert not any(key.startswith("_") for key in rendered)


def test_clipify_pan_expression_and_empty_input():
    build_pan = _load("seal_build_pan", ROOT / "bundled-skills/clipify/scripts/build_pan.py")
    expression = build_pan.build_expression(
        [{"speaker": "left", "end": 1.25}, {"speaker": "right", "end": 2.5}],
        100,
        900,
    )
    assert expression == "if(lt(t\\,1.2500)\\,100\\,900)"
    with pytest.raises(ValueError, match="不能为空"):
        build_pan.build_expression([], 0, 10)


def test_installers_keep_third_party_hooks_disabled_but_install_bun_explicitly():
    macos = (ROOT / "scripts/install-macos.sh").read_text(encoding="utf-8")
    windows = (ROOT / "scripts/install-windows.ps1").read_text(encoding="utf-8")
    for installer in (macos, windows):
        lowered = installer.lower()
        assert "npm ci --ignore-scripts" in lowered
        assert "node_modules" in lowered and "bun" in lowered and "install.js" in lowered
        assert "openclaw" not in lowered
        assert ".claude" not in lowered
    assert "UTF8Encoding($false)" in windows


def test_installers_can_initialize_env_without_packaged_template():
    macos = (ROOT / "scripts/install-macos.sh").read_text(encoding="utf-8")
    windows = (ROOT / "scripts/install-windows.ps1").read_text(encoding="utf-8")
    assert '[[ -f "$RUNTIME/.env.example" ]]' in macos
    assert ': > "$RUNTIME/.env"' in macos
    assert "Test-Path $EnvTemplate" in windows
    assert "WriteAllText($EnvFile, '', $utf8NoBom)" in windows


def test_no_hardcoded_playwright_browser_path():
    tests_dir = RUNTIME_ROOT / "tests"
    assert not (tests_dir / "playwright-cli.json").exists()


def test_offline_package_validator_reuses_install_verifier():
    validator = (ROOT / "scripts/validate_capabilities.py").read_text(encoding="utf-8")
    assert "from verify_install import main" in validator


def test_package_verifier_allows_cookie_source_but_rejects_runtime_state():
    verifier = (ROOT / "scripts/verify_install.py").read_text(encoding="utf-8")
    assert '"browser-profiles", "outputs"' in verifier
    assert "COOKIE_DATA_SUFFIXES" in verifier
