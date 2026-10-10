"""issue #26 剩余项的回归测试：安装链路的三处静默失败 / 硬链接写穿。

覆盖：
  ① setup.sh step 2 的 npm registry 设置失败时，安装必须继续并给出 warn；
  ② OpenAI 兼容分支写出的 models[] 必须带 contextWindow / maxTokens（可被 .env 覆盖）；
  ③ openclaw/sync.sh 同步 bootstrap 文件时，目标若是硬链接必须替换成 nlink=1。

①③ 用真脚本 / 真文件系统跑，②按内容锚点切出 setup.sh 的真实片段在沙箱里跑。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = PROJECT_ROOT / "setup.sh"
SYNC_SH = PROJECT_ROOT / "openclaw" / "sync.sh"

sys.path.insert(0, str(PROJECT_ROOT))


def _bash_works() -> bool:
    try:
        p = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True,
                           timeout=30, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip() == "ok"


needs_bash = pytest.mark.skipif(not _bash_works(), reason="没有可用的 bash")


def _slice(lines: list[str], start: str, end: str, *, keep_end: bool) -> str:
    i = next(n for n, line in enumerate(lines) if line.startswith(start))
    j = next(n for n, line in enumerate(lines) if n > i and line.startswith(end))
    return "\n".join(lines[i: j + 1 if keep_end else j])


# ── ① step 2：npm registry 失败不再静默杀掉安装 ──────────────────

@needs_bash
def test_npm_registry_failure_does_not_abort_setup(tmp_path: Path) -> None:
    """npm 写 registry 失败时，脚本必须继续（带 warn），而不是无提示退出。"""
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    block = _slice(lines, "# ---- 2. npm 源 ----", "# ---- 3. 检测/安装 OpenClaw", keep_end=False)

    # 假的 npm：写 registry 一律失败（模拟 ~/.npmrc 跨会话不可写）。
    fake_npm = tmp_path / "npm"
    fake_npm.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")
    fake_npm.chmod(0o755)

    script = textwrap.dedent(f"""
        set -euo pipefail
        info()  {{ echo "[easel] $*"; }}
        ok()    {{ echo "OK|$*"; }}
        warn()  {{ echo "WARN|$*"; }}
        step()  {{ echo "STEP|$*"; }}
        npm()   {{ "{fake_npm}" "$@"; }}
    """) + "\n" + block + "\necho REACHED_END\n"

    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={"PATH": os.environ["PATH"]})
    assert proc.returncode == 0, f"npm 失败后脚本应继续，实际退出码 {proc.returncode}：{proc.stderr}"
    assert "REACHED_END" in proc.stdout, f"脚本提前终止：{proc.stdout}"
    assert "WARN|" in proc.stdout, "失败时应给出 warn，而不是静默"
    assert "OK|npm registry" not in proc.stdout, "npm 实际失败却报了成功"


@needs_bash
def test_npm_registry_success_still_reports_ok(tmp_path: Path) -> None:
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    block = _slice(lines, "# ---- 2. npm 源 ----", "# ---- 3. 检测/安装 OpenClaw", keep_end=False)
    script = textwrap.dedent("""
        set -euo pipefail
        info()  { echo "[easel] $*"; }
        ok()    { echo "OK|$*"; }
        warn()  { echo "WARN|$*"; }
        step()  { echo "STEP|$*"; }
        npm()   { return 0; }
    """) + "\n" + block + "\necho REACHED_END\n"
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={"PATH": os.environ["PATH"]})
    assert proc.returncode == 0
    assert "OK|npm registry: npmjs.org" in proc.stdout


# ── ② OpenAI models[] 必须带 contextWindow / maxTokens ────────────

def _openai_models_written(tmp_path: Path, **env: str) -> str:
    """跑 setup.sh 的 OpenAI 分支，返回写进 models 的那条 JSON。"""
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    helper = _slice(lines, "usable_key() {", "}", keep_end=True)
    body = _slice(lines, 'if [ "${LOCAL_API_CONFIGURED:-false}" = true ]; then',
                  "# ---- 10. OpenClaw agent 模型", keep_end=False)
    calls = tmp_path / "oc.log"
    script = textwrap.dedent(f"""
        set -u
        PROJECT_ROOT={tmp_path}
        CFG={calls}
        : > "$CFG"
        ok()   {{ echo "OK|$*"; }}
        warn() {{ echo "WARN|$*"; }}
        info() {{ echo "[easel] $*"; }}
        _oc() {{
            if [ "${{1:-}}" = "config" ] && [ "${{2:-}}" = "set" ]; then
                echo "$3 = $4" >> "$CFG"
            fi
            return 0
        }}
        # setup.sh 的 config 写入现在统一经过容忍层（oc_set / oc_try / oc_set_first）。
        # 这里按签名 stub 成「把 key = value 记进 CFG」，断言对象仍是「写了哪些 key」，
        # 不依赖容忍层的内部实现。
        oc_set()       {{ shift; echo "$1 = $2" >> "$CFG"; }}
        oc_try()       {{ echo "$1 = $2" >> "$CFG"; return 0; }}
        oc_set_first() {{ v="$2"; shift 3; echo "$1 = $v" >> "$CFG"; return 0; }}
        oc_supports()  {{ return 1; }}
        warn_collect() {{ echo "WARN|$1：$2"; }}
        OC=_oc
    """) + "\n" + helper + "\n\n" + body
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={"PATH": os.environ["PATH"], **env})
    assert proc.returncode == 0, f"OpenAI 分支执行失败：{proc.stderr}"
    for line in calls.read_text(encoding="utf-8").splitlines():
        if line.startswith("models.providers.openai.models = "):
            return line.split(" = ", 1)[1]
    return ""


@needs_bash
def test_openai_models_declare_context_window_and_max_tokens(tmp_path: Path) -> None:
    """P0-2：models[] 必须声明 maxTokens / contextWindow，否则部分网关 400。"""
    raw = _openai_models_written(
        tmp_path,
        OPENAI_API_KEY="sk-real",
        OPENAI_BASE_URL="https://api.deepseek.com/v1",
        OPENAI_MODEL="deepseek-chat",
        CLAUDE_MODEL="openai/deepseek-chat",
    )
    assert raw, "OpenAI provider 的 models 没有被写入"
    assert '"contextWindow":128000' in raw
    assert '"maxTokens":16384' in raw


@needs_bash
def test_openai_models_respect_env_overrides(tmp_path: Path) -> None:
    raw = _openai_models_written(
        tmp_path,
        OPENAI_API_KEY="sk-real",
        OPENAI_BASE_URL="https://api.example.com/v1",
        OPENAI_MODEL="my-model",
        OPENAI_CONTEXT_WINDOW="64000",
        OPENAI_MAX_TOKENS="8192",
    )
    assert '"contextWindow":64000' in raw
    assert '"maxTokens":8192' in raw


# ── ③ sync.sh：硬链接目标必须被替换 ──────────────────────────────

@needs_bash
def test_sync_replaces_hardlinked_workspace_files(tmp_path: Path) -> None:
    """P1-5：目标文件是硬链接时，同步后 nlink 必须变成 1（否则 OpenClaw 拒收）。"""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "AGENTS.md").write_text("from source\n", encoding="utf-8")
    (src / "SOUL.md").write_text("soul\n", encoding="utf-8")

    # 造出 nlink=2 的目标：先写一份真实文件，再硬链接到别处（onboard 的效果）。
    for name in ("AGENTS.md", "SOUL.md"):
        target = dst / name
        target.write_text("stale hardlinked content\n", encoding="utf-8")
        os.link(target, tmp_path / f"{name}.other")

    script = textwrap.dedent(f"""
        set -euo pipefail
        OPENCLAW_WORKSPACE_SRC="{src}"
        OPENCLAW_WORKSPACE_DST="{dst}"
    """) + "\n" + _sync_workspace_block() + "\n"
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={"PATH": os.environ["PATH"]})
    assert proc.returncode == 0, proc.stderr
    for name in ("AGENTS.md", "SOUL.md"):
        assert (dst / name).read_text(encoding="utf-8") == _expected(name)
        assert os.stat(dst / name).st_nlink == 1, f"{name} 仍是硬链接，OpenClaw 会拒收"


def _expected(name: str) -> str:
    return "soul\n" if name == "SOUL.md" else "from source\n"


def _sync_workspace_block() -> str:
    """按锚点切出 sync.sh 里同步 workspace 文件的那段真代码（不含后续 AGENTS 追加段）。"""
    lines = SYNC_SH.read_text(encoding="utf-8").splitlines()
    return _slice(lines, "for f in \"$OPENCLAW_WORKSPACE_SRC\"/*.md; do",
                  "# AGENTS.md is injected every turn", keep_end=False)


@needs_bash
def test_sync_fails_loudly_when_target_cannot_be_replaced(tmp_path: Path) -> None:
    """替换失败（目录占位）时必须明着失败，不能留下起不来的 gateway 还以为同步成功。"""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "AGENTS.md").write_text("ok\n", encoding="utf-8")
    (src / "SOUL.md").write_text("ok\n", encoding="utf-8")
    # AGENTS.md 位置放一个非空目录：rm -f 删不掉，cp 必失败。
    (dst / "AGENTS.md").mkdir()
    (dst / "AGENTS.md" / "x").write_text("block\n", encoding="utf-8")

    script = textwrap.dedent(f"""
        set -euo pipefail
        OPENCLAW_WORKSPACE_SRC="{src}"
        OPENCLAW_WORKSPACE_DST="{dst}"
    """) + "\n" + _sync_workspace_block() + "\n"
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={"PATH": os.environ["PATH"]})
    assert proc.returncode != 0, "替换失败却返回 0，会静默留下坏的 workspace"


def test_sync_has_hardlink_guard() -> None:
    """源码级守卫：同步段必须保留「先删再拷 + nlink 校验」。"""
    text = SYNC_SH.read_text(encoding="utf-8")
    assert re.search(r'rm -f "\$dst"', text), "缺少 cp 前的 rm -f（硬链接会写穿）"
    assert "nlink" in text
    assert 'stat -c %h' in text
