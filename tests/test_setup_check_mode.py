"""`EASEL_SETUP_MODE=check` 的回归测试。

check 模式会跑完 setup.sh 的全部探测与分支，但不改变任何状态，只向 stdout 吐一条
JSON 动作流。它存在的理由是让安装逻辑可以在 CI 上验证 —— 真跑一遍要下近 1GB
（pip 的 opencv/faster-whisper + npm + Chromium），挂在每个 PR 上并不现实。

但这个机制本身此前没有任何测试：手工验证过一次，之后就只能靠它自己不坏。
这里把它钉住，覆盖三件事：
  ① 真的不改变状态（配置文件、.env 都不能动）；
  ② 该走到的分支都走到了（按 .env 的不同配置断言动作流内容）；
  ③ 动作流不泄露密钥 —— 它会进 CI 日志，而整块写 provider 时密钥藏在 value 里。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = PROJECT_ROOT / "setup.sh"

FAKE_KEY = "ak-dummy-check-mode-key-000111222"


def _bash_works() -> bool:
    try:
        p = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True,
                           timeout=30, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip() == "ok"


# setup.sh 是 Linux/macOS 的安装器，在 Windows runner 上跑它没有意义（而且这里造的
# 假命令依赖 Unix 工具链）。Windows 侧由 tests/ps_tolerance_probe.ps1 与
# tests/test_setup_ps1_static.py 负责。
needs_bash = pytest.mark.skipif(
    os.name == "nt" or not _bash_works(),
    reason="需要非 Windows 的 bash 环境（setup.ps1 另有专门的测试）")


def _fake_bin(tmp_path: Path) -> Path:
    """造一套假的外部命令，让 check 模式能在没有真实工具链的机器/CI 上跑完。

    check 模式跳过的是「会改变状态」的操作；探测类调用（--version / --help）仍会
    真的执行，所以这些命令必须存在且行为可预期。
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    (bin_dir / "openclaw").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '    *"config set --help"*) echo "  --replace"; echo "  --batch-file"; exit 0 ;;\n'
        '    *"config --help"*)     echo "  validate"; echo "  get"; exit 0 ;;\n'
        '    *--version*)           echo "OpenClaw 2026.9.8 (fake)"; exit 0 ;;\n'
        '    *"config validate"*)   echo "Config valid"; exit 0 ;;\n'
        '    *"onboard --help"*)    echo "  --non-interactive"; exit 0 ;;\n'
        "esac\n"
        "exit 0\n", encoding="utf-8")
    (bin_dir / "node").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-v" ]; then echo "v24.21.0"; exit 0; fi\n'
        'if [ "$1" = "-p" ]; then echo "24.21.0"; exit 0; fi\n'
        "exit 0\n", encoding="utf-8")
    (bin_dir / "npm").write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in ping) exit 0 ;; esac\n'
        "exit 0\n", encoding="utf-8")
    (bin_dir / "ffmpeg").write_text(
        '#!/usr/bin/env bash\necho "ffmpeg version 6.0-fake"\n', encoding="utf-8")
    for f in bin_dir.iterdir():
        f.chmod(0o755)

    # python3 / git / curl 等沿用系统的：check 模式要用真 python3 生成 provider JSON。
    for tool in ("python3", "git", "curl", "sed", "awk", "grep", "tr", "head", "tail",
                 "date", "mktemp", "df", "basename", "dirname", "cut", "sort", "uniq",
                 "touch", "rm", "mkdir", "cp", "ln", "cat", "wc", "printf", "seq", "ss"):
        real = shutil.which(tool)
        if real and not (bin_dir / tool).exists():
            (bin_dir / tool).symlink_to(real)
    return bin_dir


def _run_check(tmp_path: Path, env_lines: str) -> tuple[subprocess.CompletedProcess, list[dict]]:
    """在沙箱里跑一遍 check 模式，返回 (进程结果, 解析出的动作流)。"""
    bin_dir = _fake_bin(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / ".env")  # 仅为显式说明：下面用的是沙箱里的 .env 副本

    work = tmp_path / "repo"
    shutil.copytree(PROJECT_ROOT, work, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", ".venv", "node_modules", "outputs", "dist", "__pycache__", "assets"))
    (work / ".env").write_text(env_lines, encoding="utf-8")

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "EASEL_SETUP_MODE": "check",
        "TERM": "dumb",
    }
    proc = subprocess.run(["bash", str(work / "setup.sh")], capture_output=True, text=True,
                          timeout=300, errors="replace", env=env, cwd=str(work))
    actions = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                actions.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return proc, actions


ANTHROPIC_ENV = (
    f"EASEL_LLM_API_KEY={FAKE_KEY}\n"
    "EASEL_LLM_BASE_URL=https://example.invalid/v1\n"
    "EASEL_LLM_API_KEY_HEADER=x-api-key\n"
    "CLAUDE_MODEL=anthropic/claude-opus-4-7\n"
)
OPENAI_ENV = (
    f"OPENAI_API_KEY={FAKE_KEY}\n"
    "OPENAI_BASE_URL=https://example.invalid/v1\n"
    "OPENAI_MODEL=gpt-5.5\n"
)


@needs_bash
def test_check_mode_exits_zero_and_emits_actions(tmp_path: Path) -> None:
    proc, actions = _run_check(tmp_path, ANTHROPIC_ENV)
    assert proc.returncode == 0, f"check 模式应当退出 0：\n{proc.stdout[-1500:]}\n{proc.stderr[-800:]}"
    assert actions, f"没有产出动作流：\n{proc.stdout[-1500:]}"


@needs_bash
def test_check_mode_changes_no_state(tmp_path: Path) -> None:
    """check 模式必须不改变任何状态：openclaw 配置目录不该被创建，.env 不该被改。"""
    proc, _ = _run_check(tmp_path, ANTHROPIC_ENV)
    assert proc.returncode == 0, proc.stderr[-500:]
    env_after = (tmp_path / "repo" / ".env").read_text(encoding="utf-8")
    assert env_after == ANTHROPIC_ENV, "check 模式改写了 .env"
    cfg = tmp_path / "home" / ".openclaw-easel" / "openclaw.json"
    assert not cfg.exists(), "check 模式写出了 openclaw 配置"


@needs_bash
def test_check_mode_skips_expensive_steps(tmp_path: Path) -> None:
    """重操作必须只被记录、不被执行 —— 这正是 CI 用得起它的原因。"""
    _, actions = _run_check(tmp_path, ANTHROPIC_ENV)
    skipped = {a["key"] for a in actions if a["action"] == "run_step"}
    for expected in ("pip install", "前端依赖与构建", "playwright chromium", "gateway start"):
        assert expected in skipped, f"{expected} 没有被跳过（实际跳过了 {skipped}）"


@needs_bash
def test_check_mode_covers_anthropic_branch(tmp_path: Path) -> None:
    """EASEL_LLM_* 配置要落到 anthropic provider，并设好主模型。"""
    _, actions = _run_check(tmp_path, ANTHROPIC_ENV)
    keys = [a["key"] for a in actions if a["action"].startswith("config_set")]
    assert "models.providers.anthropic" in keys
    assert "agents.defaults.model.primary" in keys
    assert not any(k.startswith("models.providers.openai") for k in keys), \
        f"不该碰 openai provider：{keys}"


@needs_bash
def test_check_mode_covers_openai_branch(tmp_path: Path) -> None:
    """只配 OPENAI_* 时要走 openai provider 分支，且带上 contextWindow/maxTokens。"""
    _, actions = _run_check(tmp_path, OPENAI_ENV)
    sets = {a["key"]: a["value"] for a in actions if a["action"].startswith("config_set")}
    assert "models.providers.openai.api" in sets
    assert "models.providers.openai.models" in sets
    models_val = sets["models.providers.openai.models"]
    assert "contextWindow" in models_val and "maxTokens" in models_val, \
        f"models[] 必须声明上下文与最大输出（部分网关据此 400）：{models_val}"
    assert not any(k == "models.providers.anthropic" for k in sets), \
        f"不该碰 anthropic provider：{list(sets)}"


@needs_bash
def test_check_mode_never_leaks_secrets(tmp_path: Path) -> None:
    """动作流会进 CI 日志，不能出现明文密钥。

    这条不是假想：早期版本只按 key 名脱敏，而整块写 provider 时 key 是
    models.providers.anthropic、密钥藏在 value 的 JSON 里，实测把 apiKey 打进了日志。
    """
    proc, actions = _run_check(tmp_path, ANTHROPIC_ENV)
    assert FAKE_KEY not in json.dumps(actions, ensure_ascii=False), "动作流泄露了密钥"
    assert FAKE_KEY not in proc.stdout, "stdout 泄露了密钥"
    assert FAKE_KEY not in proc.stderr, "stderr 泄露了密钥"


@needs_bash
def test_check_mode_without_key_warns_and_still_exits_zero(tmp_path: Path) -> None:
    """没有可用 Key 时要降级提示并引导去浏览器，而不是中断。"""
    proc, actions = _run_check(tmp_path, "ANTHROPIC_API_KEY=sk-ant-REPLACE_ME\n")
    assert proc.returncode == 0, f"无 key 不该让安装失败：\n{proc.stdout[-1200:]}"
    assert "模型配置" in proc.stdout or "浏览器" in proc.stdout, \
        "应当提示去浏览器配置模型"
    keys = [a["key"] for a in actions if a["action"].startswith("config_set")]
    assert "agents.defaults.model.primary" not in keys, \
        "没有可用认证时不该写 primary（指向无认证的 provider 比不写更难查）"
