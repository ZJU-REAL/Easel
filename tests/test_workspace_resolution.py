"""workspace 目标解析的回归测试（issue #19）。

钉住的坑：sync.sh（写入端）、setup.ps1（Windows 写入端）、doctor（检查端）各自硬编码了
一个 workspace 路径，而 OpenClaw 的默认布局在 2026.6.x / 2026.9.x 之间变过：

    2026.6.x  →  ~/.openclaw/workspace-easel
    2026.9.x  →  ~/.openclaw-easel/workspace   （见该版本 docs/concepts/agent-workspace.md）

于是在任一版本上必有一端写到 agent 不读的地方，而同步脚本照样打印 "synced"、doctor 照样
报绿（它查的是同一个错路径）—— 技能静默不生效，两处内容还会各自漂移。

修法是三端共用 easel/openclaw_workspace.py，且它不猜：直接问 openclaw 自己。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from easel import openclaw_workspace as ws  # noqa: E402
from easel.commands import doctor  # noqa: E402

SYNC_SH = PROJECT_ROOT / "openclaw" / "sync.sh"
SETUP_PS1 = PROJECT_ROOT / "setup.ps1"
DOCTOR_PY = PROJECT_ROOT / "easel" / "commands" / "doctor.py"


@pytest.fixture(autouse=True)
def _clear_cache():
    """workspace_dir 带 lru_cache，不清会把上一个用例的答案漏给下一个。"""
    ws.workspace_dir.cache_clear()
    yield
    ws.workspace_dir.cache_clear()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """把 HOME 和 state dir 都挪进 tmp，别碰真机配置。"""
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.delenv("EASEL_OPENCLAW_WORKSPACE", raising=False)
    # 默认让"问 openclaw"这一级失败，各用例再按需打开
    monkeypatch.setattr(ws, "_ask_openclaw", lambda: None)
    return tmp_path


def test_env_override_wins(isolated, monkeypatch):
    """显式覆盖优先级最高，连 openclaw 的话都盖掉 —— 用户拿它救场。"""
    monkeypatch.setattr(ws, "_ask_openclaw", lambda: Path("/from/openclaw"))
    monkeypatch.setenv("EASEL_OPENCLAW_WORKSPACE", "/my/ws")
    assert ws.workspace_dir() == Path("/my/ws")


def test_asks_openclaw_first(isolated, monkeypatch):
    """能问到 openclaw 就以它为准 —— 这是唯一跨版本可靠的答案。"""
    monkeypatch.setattr(ws, "_ask_openclaw", lambda: Path("/runtime/ws"))
    # 同时摆一个有内容的候选目录，确认它没被优先
    skills = isolated / "home" / ".openclaw" / "workspace-easel" / "skills"
    skills.mkdir(parents=True)
    (skills / "x").mkdir()
    assert ws.workspace_dir() == Path("/runtime/ws")


def test_falls_back_to_config(isolated):
    """问不到 openclaw 时，用配置里显式写死的 workspace。"""
    cfg = isolated / "state" / "openclaw.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"agents": {"defaults": {"workspace": "/cfg/ws"}}}), encoding="utf-8")
    assert ws.workspace_dir() == Path("/cfg/ws")


def test_prefers_existing_dir_with_content(isolated):
    """老机器已经同步过的目录原地不动，别无声无息给人搬家。"""
    old = isolated / "home" / ".openclaw" / "workspace-easel"
    (old / "skills" / "some-skill").mkdir(parents=True)
    assert ws.workspace_dir() == old


def test_empty_candidate_does_not_count(isolated, monkeypatch):
    """空的 skills/ 不算数，否则一个 mkdir 就能把解析结果钉死在错的那边。"""
    (isolated / "home" / ".openclaw" / "workspace-easel" / "skills").mkdir(parents=True)
    monkeypatch.setattr(doctor, "_openclaw_version", lambda: (2026, 9, 5))
    assert ws.workspace_dir() == isolated / "state" / "workspace"


@pytest.mark.parametrize("version,expected_new_layout", [
    ((2026, 6, 11), False),   # 旧版：~/.openclaw/workspace-easel
    ((2026, 9, 5), True),     # 新版：<state>/workspace
    (None, True),             # 版本读不出来时按新布局
])
def test_version_default_layout(isolated, monkeypatch, version, expected_new_layout):
    """全都问不出来时，按已装 openclaw 的版本推布局 —— 别再一个版本写死。"""
    monkeypatch.setattr(doctor, "_openclaw_version", lambda: version)
    got = ws.workspace_dir()
    if expected_new_layout:
        assert got == isolated / "state" / "workspace"
    else:
        assert got == isolated / "home" / ".openclaw" / "workspace-easel"


def test_ask_openclaw_picks_default_agent(monkeypatch):
    """status --json 里可能有多个 agent，必须取 defaultId 那条。"""
    payload = json.dumps({"agents": {
        "defaultId": "main",
        "agents": [{"id": "other", "workspaceDir": "/ws/other"},
                   {"id": "main", "workspaceDir": "/ws/main"}],
    }})

    class _Proc:
        returncode = 0
        stdout = payload

    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr("easel.openclaw_cmd.openclaw_base_cmd", lambda: ["openclaw"])
    assert ws._ask_openclaw() == Path("/ws/main")


def test_ask_openclaw_survives_garbage(monkeypatch):
    """openclaw 吐了非 JSON / 非零退出时必须返回 None 走退化，不能抛。"""
    class _Bad:
        returncode = 0
        stdout = "not json at all"

    monkeypatch.setattr(ws.subprocess, "run", lambda *a, **k: _Bad())
    monkeypatch.setattr("easel.openclaw_cmd.openclaw_base_cmd", lambda: ["openclaw"])
    assert ws._ask_openclaw() is None


def test_doctor_uses_resolver(isolated, monkeypatch):
    """doctor 必须查 agent 真正读的那个目录，而不是它自己记的老路径。"""
    target = isolated / "runtime-ws"
    (target / "skills" / "a").mkdir(parents=True)
    monkeypatch.setattr(ws, "_ask_openclaw", lambda: target)
    ok, detail = doctor._skills_synced()
    assert ok, detail

    ws.workspace_dir.cache_clear()
    empty = isolated / "empty-ws"
    empty.mkdir()
    monkeypatch.setattr(ws, "_ask_openclaw", lambda: empty)
    ok, detail = doctor._skills_synced()
    assert not ok
    assert str(empty) in detail, "失败提示必须说清到底查的是哪个目录"


# ── 三端不许再各写各的 ────────────────────────────────────────────────


SETUP_SH = PROJECT_ROOT / "setup.sh"
VIDEO_PIPELINE = PROJECT_ROOT / "skills" / "openclaw" / "video-production" / "scripts" / "video_pipeline.py"


def test_setup_ps1_does_not_redirect_stderr_of_resolver():
    """PS 5.1 + $ErrorActionPreference='Stop' 下，对原生命令做任何 stderr 重定向都会把
    stderr 的每一行包成 ErrorRecord 抛 NativeCommandError —— 脚本级终止，下面的回退分支
    根本轮不到。所以解析 workspace 这一段绝不能出现 2>$null / 2>&1 / *>。"""
    code = "\n".join(l for l in SETUP_PS1.read_text(encoding="utf-8-sig").splitlines()
                     if not l.lstrip().startswith("#"))   # 注释里当反例讲可以
    seg = code.split("openclaw_workspace.py")[1][:400]
    for bad in ("2>$null", "2>&1", "*>"):
        assert bad not in seg, f"解析 workspace 的调用带了 {bad}，Stop 模式下会直接掐断脚本"


def test_setup_ps1_pins_output_encoding():
    """PS 5.1 按 [Console]::OutputEncoding（中文系统是 OEM 936）解码原生命令 stdout，
    而 Python 输出 UTF-8 —— 路径含中文就是乱码。必须临时钉成 UTF-8。"""
    text = SETUP_PS1.read_text(encoding="utf-8-sig")
    assert "OutputEncoding" in text and "UTF8Encoding" in text


def test_setup_ps1_fallback_honors_env_override():
    """Python 都跑不起来时的兜底，至少得认用户显式给的 EASEL_OPENCLAW_WORKSPACE。"""
    text = SETUP_PS1.read_text(encoding="utf-8-sig")
    assert "$env:EASEL_OPENCLAW_WORKSPACE" in text


def test_setup_sh_does_not_swallow_sync_warnings():
    """sync.sh 解析不出 workspace 的警告只走 stderr 且不含 ✓/→。把 stderr 并进管道再 grep
    就会整条吃掉 —— 装完一声不吭，技能却同步到 agent 不读的目录（issue #19 重建版）。"""
    for line in SETUP_SH.read_text(encoding="utf-8").splitlines():
        if "openclaw/sync.sh" in line and not line.lstrip().startswith("#"):
            assert "2>&1" not in line, f"sync.sh 的 stderr 被并进管道后 grep 掉了：{line.strip()}"
            break
    else:
        pytest.fail("setup.sh 里找不到调用 openclaw/sync.sh 的那行")


def test_sync_sh_takes_last_line_only():
    """import 链上任何一句废话混进 stdout，整段拿去当路径就会 mkdir 出鬼目录还报成功。"""
    line = next(l for l in SYNC_SH.read_text(encoding="utf-8").splitlines()
                if "openclaw_workspace.py" in l and not l.lstrip().startswith("#"))
    assert "tail -n 1" in line, f"没有只取最后一行：{line.strip()}"


def test_video_pipeline_resolves_workspace(monkeypatch, tmp_path):
    """技能层也不许自己写死 6.x 布局（产物会落进 agent 不读的目录，而 mkdir 照样成功）。"""
    code = "\n".join(l for l in VIDEO_PIPELINE.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))
    assert "openclaw_workspace" in code, "video_pipeline.py 没走统一解析器"

    import importlib.util
    spec = importlib.util.spec_from_file_location("_vp_under_test", VIDEO_PIPELINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(ws, "_ask_openclaw", lambda: tmp_path / "runtime-ws")
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("EASEL_OPENCLAW_WORKSPACE", raising=False)
    assert mod._workspace_root() == tmp_path / "runtime-ws"


@pytest.mark.parametrize("path", [SYNC_SH, SETUP_PS1, DOCTOR_PY])
def test_no_hardcoded_workspace_targets(path):
    """写入端/检查端都不许再出现写死的 workspace 路径（注释里当反例讲可以）。"""
    code = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    for bad in ("workspace-easel", "workspace-${PROFILE}", ".openclaw-easel/workspace"):
        # 回退分支里允许保留一个兜底常量，但必须同时引用解析器
        if bad in code:
            assert "openclaw_workspace" in code, \
                f"{path.name} 仍硬编码 {bad!r} 且没有走统一解析器"
