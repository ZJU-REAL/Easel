"""认证配置链路的回归测试。

钉住四个真实踩过的坑：

1. setup.sh 用 `-z ANTHROPIC_API_KEY` 判「没配 Anthropic」。.env.example 默认就带着
   `ANTHROPIC_API_KEY=sk-ant-REPLACE_ME`，用户照 README 加了 OpenAI 兼容服务但没删那行时，
   整条 OpenAI 分支被跳过 —— provider 一个字没写，却照样把 primary 设成了 openai/xxx，
   对话直接报 "No route-compatible authentication source is configured for openai"。
2. `easel doctor` 只静态查 .env，查不出上面那种「.env 填了但 openclaw 没写」，于是全绿。
3. setup.ps1 里 `if (Is-UsableKey $x -and $y.ContainsKey(...))` 会进命令解析模式，
   `-and` 被当成参数名静默吞掉，后半个守卫失效（PS 5.1 与 7 同样中招）。
4. install_tool 用 [Environment]::GetEnvironmentVariable 读用户 PATH 会展开 %VAR%，
   写回又是 REG_SZ，把用户 PATH 里的间接引用永久压平。

setup.sh 的用例是把脚本里那段**原文**抠出来跑（按内容锚点切，不写死行号），
$OC 换成记录器，所以测的是真代码、不是复制品。
"""
from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = PROJECT_ROOT / "setup.sh"
SETUP_PS1 = PROJECT_ROOT / "setup.ps1"

sys.path.insert(0, str(PROJECT_ROOT))
from easel.commands import doctor  # noqa: E402


# ── setup.sh：把真代码切出来在沙箱里跑 ────────────────────────────────


@functools.lru_cache(maxsize=1)
def _bash_works() -> bool:
    """有没有能真跑 POSIX 脚本的 bash。

    不能只看 `shutil.which("bash")`：Windows 上 System32\\bash.exe 是 WSL 的入口，
    没装发行版时它照样在 PATH 里，跑起来却只会打印「has no installed distributions」，
    于是断言拿到一串 UTF-16 的错误提示、报得莫名其妙。跑一下才算数。
    """
    try:
        p = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True,
                           timeout=30, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip() == "ok"


# setup.sh 是 Linux/macOS 的安装路径，Windows 走 setup.ps1（另有静态用例守着）。
needs_bash = pytest.mark.skipif(not _bash_works(), reason="没有可用的 bash，跳过 setup.sh 用例")


def _slice(lines: list[str], start: str, end: str, *, keep_end: bool) -> str:
    """按内容锚点截取，避免行号漂移后测试悄悄测了别的东西。"""
    i = next(n for n, line in enumerate(lines) if line.startswith(start))
    j = next(n for n, line in enumerate(lines) if n > i and line.startswith(end))
    return "\n".join(lines[i: j + 1 if keep_end else j])


def _auth_block() -> str:
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    helper = _slice(lines, "usable_key() {", "}", keep_end=True)
    body = _slice(lines, 'DEFAULT_PRIMARY_MODEL="anthropic',
                  "# 整个 agent run 的总时长上限", keep_end=False)
    return helper + "\n\n" + body


def _run_auth(tmp_path: Path, **env: str) -> tuple[str, dict[str, str]]:
    """跑认证段，返回 (stdout, 实际写进 openclaw 的配置)。"""
    calls = tmp_path / "oc-calls.log"
    script = textwrap.dedent(f"""
        set -u
        PROJECT_ROOT={tmp_path}
        CFG={calls}
        : > "$CFG"
        ok()   {{ echo "OK|$*"; }}
        warn() {{ echo "WARN|$*"; }}
        oc_write_anthropic() {{ echo "models.providers.anthropic.baseUrl = $1" >> "$CFG"; }}
        _oc() {{
            if [ "${{1:-}}" = "config" ] && [ "${{2:-}}" = "set" ]; then
                echo "$3 = $4" >> "$CFG"
            fi
            return 0
        }}
        OC=_oc
    """) + "\n" + _auth_block()

    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={"PATH": os.environ["PATH"], **env})
    assert proc.returncode == 0, f"认证段执行失败：{proc.stderr}"
    written: dict[str, str] = {}
    if calls.is_file():
        for line in calls.read_text(encoding="utf-8").splitlines():
            if " = " in line:
                k, v = line.split(" = ", 1)
                written[k] = v
    return proc.stdout, written


PLACEHOLDER = "sk-ant-REPLACE_ME"
DEEPSEEK = {
    "OPENAI_API_KEY": "sk-deepseek-fake",
    "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
    "OPENAI_MODEL": "deepseek-chat",
    "CLAUDE_MODEL": "openai/deepseek-chat",
}


@needs_bash
def test_placeholder_does_not_block_openai_branch(tmp_path):
    """核心回归：占位符没删 + 配了 OpenAI 兼容服务 → provider 必须真的写出来。"""
    out, written = _run_auth(tmp_path, ANTHROPIC_API_KEY=PLACEHOLDER, **DEEPSEEK)
    assert written.get("models.providers.openai.apiKey") == "sk-deepseek-fake"
    assert written.get("models.providers.openai.baseUrl") == "https://api.deepseek.com/v1"
    assert written.get("agents.defaults.model.primary") == "openai/deepseek-chat"
    assert "WARN|认证未配置" not in out


@needs_bash
def test_placeholder_present_or_absent_gives_same_result(tmp_path):
    """删不删那行占位符，结果必须完全一致 —— 用户没义务知道要删它。"""
    _, with_ph = _run_auth(tmp_path, ANTHROPIC_API_KEY=PLACEHOLDER, **DEEPSEEK)
    _, without = _run_auth(tmp_path, **DEEPSEEK)
    assert with_ph == without


@needs_bash
def test_nothing_configured_writes_no_primary(tmp_path):
    """什么都没配时不许写 primary：写了只会指向不存在的 provider，比「没配置」更难查。"""
    out, written = _run_auth(tmp_path, ANTHROPIC_API_KEY=PLACEHOLDER,
                             CLAUDE_MODEL="openai/deepseek-chat")
    assert written == {}, f"不该写任何配置，实际写了 {written}"
    assert "WARN|认证未配置" in out


@needs_bash
def test_real_anthropic_key_still_works(tmp_path):
    """别把闸修成谁都过不去：正经 key 必须照常同步。"""
    out, written = _run_auth(tmp_path, ANTHROPIC_API_KEY="sk-ant-real",
                             CLAUDE_MODEL="anthropic/claude-sonnet-4-6")
    assert written["models.providers.anthropic.baseUrl"] == "https://api.anthropic.com"
    assert written["agents.defaults.model.primary"] == "anthropic/claude-sonnet-4-6"


@needs_bash
def test_anthropic_takes_priority_over_openai(tmp_path):
    """两个都配了真 key 时，优先级保持原样（Anthropic 胜出）。"""
    _, written = _run_auth(tmp_path, ANTHROPIC_API_KEY="sk-ant-real", **DEEPSEEK)
    assert "models.providers.openai.apiKey" not in written
    assert "models.providers.anthropic.baseUrl" in written


@pytest.mark.parametrize("value", [
    "REPLACE_ME", "sk-ant-REPLACE_ME", "replace_me",
    "your-api-key", "YOUR_API_KEY", "your api key", "",
])
@needs_bash
def test_usable_key_rejects_placeholders(tmp_path, value):
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    helper = _slice(lines, "usable_key() {", "}", keep_end=True)
    proc = subprocess.run(
        ["bash", "-c", helper + '\nif usable_key "$1"; then echo YES; else echo NO; fi',
         "_", value],
        capture_output=True, text=True, timeout=30)
    assert proc.stdout.strip() == "NO", f"{value!r} 不该被当成可用 key"


@pytest.mark.parametrize("value", ["sk-ant-abc123", "sk-proj-xyz", "local-adapter"])
@needs_bash
def test_usable_key_accepts_real_keys(tmp_path, value):
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    helper = _slice(lines, "usable_key() {", "}", keep_end=True)
    proc = subprocess.run(
        ["bash", "-c", helper + '\nif usable_key "$1"; then echo YES; else echo NO; fi',
         "_", value],
        capture_output=True, text=True, timeout=30)
    assert proc.stdout.strip() == "YES", f"{value!r} 该被当成可用 key"


def test_setup_sh_has_no_bare_placeholder_comparisons():
    """别再回到「各写各的 != 占位符」：认证判定统一走 usable_key。"""
    text = SETUP_SH.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "sk-ant-REPLACE_ME" not in body, "认证判定里仍有硬编码占位符比较"


# ── doctor：.env 填了 ≠ openclaw 真写了 ────────────────────────────────


def _routable(tmp_path, cfg: dict | None, monkeypatch) -> tuple[bool, str]:
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    if cfg is not None:
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg), encoding="utf-8")
    return doctor._primary_model_routable()


def _cfg(primary: str, providers: dict) -> dict:
    return {"agents": {"defaults": {"model": {"primary": primary}}},
            "models": {"providers": providers}}


def test_doctor_catches_primary_without_provider(tmp_path, monkeypatch):
    """就是坑 1 留下的残局：primary 指着 openai，但根本没有 openai provider。"""
    ok, detail = _routable(tmp_path, _cfg("openai/deepseek-chat", {}), monkeypatch)
    assert not ok
    assert "models.providers.openai 不存在" in detail


def test_doctor_catches_provider_without_key(tmp_path, monkeypatch):
    ok, detail = _routable(
        tmp_path, _cfg("openai/gpt-4o", {"openai": {"baseUrl": "https://x/v1", "apiKey": ""}}),
        monkeypatch)
    assert not ok and "没有 apiKey" in detail


def test_doctor_catches_missing_primary(tmp_path, monkeypatch):
    ok, _ = _routable(tmp_path, {"models": {"providers": {"openai": {"apiKey": "sk-x"}}}}, monkeypatch)
    assert not ok


def test_doctor_catches_missing_config(tmp_path, monkeypatch):
    ok, detail = _routable(tmp_path, None, monkeypatch)
    assert not ok and "不存在" in detail


@pytest.mark.parametrize("primary,providers", [
    ("openai/gpt-4o", {"openai": {"apiKey": "sk-x"}}),
    # 本地适配器：apiKey 是占位的 local-adapter，靠 localService 起真服务
    ("rednote-openai/gpt-5.5",
     {"rednote-openai": {"apiKey": "local-adapter", "localService": {"command": "python3"}}}),
    # OAuth 型 provider 配置里没有 apiKey，不能误判成坏配置
    ("anthropic/claude-sonnet-4-6", {"anthropic": {"oauthToken": "tok"}}),
    # 非 provider/model 形式：解析不出 provider 就别猜，交给 easel ping
    ("some-bare-model", {}),
])
def test_doctor_passes_valid_configs(tmp_path, monkeypatch, primary, providers):
    ok, detail = _routable(tmp_path, _cfg(primary, providers), monkeypatch)
    assert ok, f"{primary} 被误判为不可路由：{detail}"


# ── setup.ps1：-and 必须处在表达式模式 ────────────────────────────────


def test_ps1_logical_and_not_in_command_position():
    """`if (Foo $x -and $y)` 里 -and 会被当成 Foo 的参数名静默吞掉，函数调用必须加括号。"""
    offenders = [
        (n, line) for n, line in enumerate(SETUP_PS1.read_text(encoding="utf-8").splitlines(), 1)
        if not line.lstrip().startswith("#")
        and re.search(r"\(\s*[A-Z]\w*-\w+[^()]*\s-(and|or)\s", line)
    ]
    assert not offenders, "这些行的 -and/-or 处在命令参数位，守卫会被静默丢弃：\n" + \
        "\n".join(f"  {n}: {line.strip()}" for n, line in offenders)


def test_ps1_auth_branches_guard_base_url():
    """三条分支都得真的检查配套的 BASE_URL/ENDPOINT 在不在。"""
    text = SETUP_PS1.read_text(encoding="utf-8")
    for key, companion in [
        ("OPENAI_MAAS_API_KEY", "OPENAI_MAAS_ENDPOINT"),
        ("EASEL_LLM_API_KEY", "EASEL_LLM_BASE_URL"),
        ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"),
    ]:
        pattern = rf"\(\(Is-UsableKey \$envValues\['{key}'\]\) -and " \
                  rf"\$envValues\.ContainsKey\('{companion}'\)\)"
        assert re.search(pattern, text), f"{key} 分支缺少括号化的 {companion} 守卫"


# ── install_tool：别展开、别降级用户 PATH ──────────────────────────────


def _install_tool_code() -> str:
    """只取代码行 —— 注释里会原样引用那两个被淘汰的 API 名来解释「为什么不用」。"""
    src = (PROJECT_ROOT / "skills" / "shared" / "scripts" / "install_tool.py").read_text(encoding="utf-8")
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))


def test_user_path_read_does_not_expand_env_refs():
    """读用户 PATH 必须拿原值：GetEnvironmentVariable 会把 %USERPROFILE% 展开成字面路径。"""
    code = _install_tool_code()
    assert "GetEnvironmentVariable('Path','User')" not in code, \
        "又用回了会展开 %VAR% 的 API"
    assert "DoNotExpandEnvironmentNames" in code, "没有按原值读取用户 PATH"


def test_user_path_write_preserves_value_kind():
    """写回必须沿用原 ValueKind，否则 REG_EXPAND_SZ 会被降级成 REG_SZ。"""
    code = _install_tool_code()
    assert "SetEnvironmentVariable('Path'" not in code, "又用回了固定写 REG_SZ 的 API"
    assert re.search(r"SetValue\('Path',.*\$kind\)", code), "写回时没有沿用原 ValueKind"


def test_user_path_dir_never_interpolated_into_script():
    """目录只能经环境变量递进去：PATH 里一个单引号就能让拼串写法变成代码执行。"""
    sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
    import install_tool

    assert "$env:EASEL_NEW_DIR" in install_tool._PS_APPEND_USER_PATH
    # 脚本是模块级常量，不带任何格式化占位，不可能把目录拼进去
    assert "%s" not in install_tool._PS_APPEND_USER_PATH
    assert ".format(" not in install_tool._PS_APPEND_USER_PATH


def test_json_output_survives_non_utf8_locale():
    """配方表输出全是中文，stdout 是管道时不能被系统 locale 编码噎死。

    Windows 上 stdout 一旦被面板/agent 捕获，Python 就按 cp936/cp1252 写，中文直接
    UnicodeEncodeError、stdout 一个字节不出 —— 调用方只看到「配方表是空的」，
    安装接口的 id 白名单随之永远为空，装什么都被拒。这里用 PYTHONIOENCODING
    在 Linux 上复现同一条件。
    """
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "skills" / "shared" / "scripts" / "install_tool.py"),
         "--json", "list"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    assert proc.returncode == 0, f"非 UTF-8 locale 下崩了：{proc.stderr[-500:]}"
    ids = {t["id"] for t in json.loads(proc.stdout)["tools"]}
    assert "node" in ids, f"配方表没出来：{ids}"


@pytest.mark.skipif(os.name == "nt", reason="Windows 上这个调用会真改注册表，不能在测试里跑")
def test_user_path_is_noop_off_windows():
    """非 Windows 平台一律不碰系统配置。

    注意别把这条写成无条件跑：`_ensure_user_path` 在 Windows 上是**真的**去改当前
    用户的 PATH 注册表项的，测试里调一次就会把参数里那个假目录永久写进去。
    """
    sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
    import install_tool

    assert install_tool._ensure_user_path("/tmp/whatever") == "skip"
