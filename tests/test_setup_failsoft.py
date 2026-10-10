"""安装脚本的「版本假设落空不该搞挂整个安装」回归套。

setup.sh 对 OpenClaw 的 config schema 与子命令做了大量版本假设（memorySearch 放在
哪个前缀下、provider 的默认 api、config validate 是否存在、--replace 是否存在……），
每个假设只对某个版本区间成立。而脚本跑在 set -euo pipefail 下，历史上任何一个假设
落空都是整个安装当场中断 —— 实测连踩 4 个。

这里把那条容忍层（oc_supports / oc_try / oc_set / oc_set_first + warn_collect）按
内容锚点从 setup.sh 里切出来，配一个「指定 key 一律拒绝」的假 openclaw 直接跑，
逐个 key 断言安装不会中断。另有两条静态断言，防止以后又写回裸调用。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = PROJECT_ROOT / "setup.sh"


def _bash_works() -> bool:
    try:
        p = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True,
                           timeout=30, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip() == "ok"


needs_bash = pytest.mark.skipif(not _bash_works(), reason="没有可用的 bash")

SETUP_TEXT = SETUP_SH.read_text(encoding="utf-8")


def _helper_block() -> str:
    """按内容锚点切出容忍层 + 失败收集那一段，连同它依赖的颜色常量。"""
    lines = SETUP_TEXT.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith("# 安装模式、失败收集"))
    j = next(n for n, l in enumerate(lines) if n > i and l.startswith("# ---- 安装报告 ----"))
    return "\n".join(lines[i:j])


def _fake_openclaw(tmp_path: Path, reject_key: str = "") -> Path:
    """假 openclaw：`config set <reject_key>` 退出 1 并向 stderr 打印 Unrecognized key。

    其余子命令一律成功。`config set --help` 要吐出 --replace，好让 oc_supports 探得到。
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    oc = bin_dir / "openclaw"
    oc.write_text(
        "#!/usr/bin/env bash\n"
        "args=\"$*\"\n"
        'case "$args" in\n'
        '    *"config set --help"*|*"config --help"*)\n'
        '        echo "  --replace   Allow full replacement"; echo "  validate"; exit 0 ;;\n'
        "esac\n"
        f'REJECT={reject_key!r}\n'
        'if [ -n "$REJECT" ]; then\n'
        '    for a in "$@"; do\n'
        '        if [ "$a" = "$REJECT" ]; then\n'
        '            echo "Error: Config validation failed: $REJECT: Unrecognized key" >&2\n'
        "            exit 1\n"
        "        fi\n"
        "    done\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    oc.chmod(0o755)
    return bin_dir


def _run_helpers(tmp_path: Path, body: str, reject_key: str = "", strict: str = "") -> subprocess.CompletedProcess:
    bin_dir = _fake_openclaw(tmp_path, reject_key)
    script = tmp_path / "t.sh"
    script.write_text(
        "set -euo pipefail\n"
        # 容忍层只依赖这几个展示用变量
        "GREEN=''; RED=''; YELLOW=''; CYAN=''; DIM=''; NC=''\n"
        'oc() { openclaw --profile easel "$@"; }\n'
        "PROJECT_ROOT='%s'\n" % tmp_path
        + f"EASEL_SETUP_STRICT='{strict}'\n"
        + "warn() { echo \"WARN: $*\"; }\n"
        + "fatal() { echo \"FATAL: $*\"; exit 1; }\n"
        + "write_install_report() { :; }\n"
        + _helper_block()
        + "\n"
        + body
        + "\n",
        encoding="utf-8",
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    return subprocess.run(["bash", str(script)], capture_output=True, text=True,
                          timeout=120, errors="replace", env=env)


# ── ① 所有 config key：被拒绝时安装必须继续 ──────────────────────────

def _config_keys() -> list[str]:
    """从 setup.sh 里把所有经 oc_set / oc_try / oc_set_first 写出的 key 抓出来。

    只取字面量 key（含 $VAR 的动态 key 没法在这里枚举），这已经覆盖了历史上
    真正踩过的那几个（memorySearch.provider、memory.search.*、config validate）。
    """
    keys = set()
    for m in re.finditer(r"oc_set(?:_first)?\s+'[^']*'\s+([A-Za-z][\w.]*)", SETUP_TEXT):
        keys.add(m.group(1))
    for m in re.finditer(r"oc_try\s+([A-Za-z][\w.]*)", SETUP_TEXT):
        keys.add(m.group(1))
    # oc_set_first 的候选 key 跟在 --json / -- 之后，单独抓一遍
    for m in re.finditer(r"oc_set_first[^\n]*\\\n\s+([\w.\s]+)", SETUP_TEXT):
        keys.update(k for k in m.group(1).split() if re.fullmatch(r"[A-Za-z][\w.]*", k))
    return sorted(k for k in keys if "." in k)


@needs_bash
@pytest.mark.parametrize("key", _config_keys())
def test_rejected_config_key_never_aborts_install(key: str, tmp_path: Path) -> None:
    """任意一个 config key 被当前 OpenClaw 拒绝时，脚本都必须走完而不是中断。"""
    r = _run_helpers(
        tmp_path,
        # 关键：这里**不能**写 `|| true`。oc_set 在 set -e 下是否会中断脚本正是被测
        # 行为，加了 || true 就把它掩盖掉，测试在改坏的实现上也会通过（实测如此）。
        f"oc_set '测试项' {key} somevalue\n"
        "echo REACHED_END\n",
        reject_key=key,
    )
    assert r.returncode == 0, f"{key} 被拒绝时脚本以 {r.returncode} 中断：{r.stderr[-400:]}"
    assert "REACHED_END" in r.stdout, f"{key} 被拒绝后没走到结尾：{r.stdout[-300:]}"


@needs_bash
def test_config_keys_discovered() -> None:
    """守卫上面那条参数化：key 抽取失效时要立刻发现，而不是静默变成零用例。"""
    keys = _config_keys()
    assert len(keys) >= 8, f"只抽到 {len(keys)} 个 key，抽取逻辑可能失效了：{keys}"
    assert "agents.defaults.model.primary" in keys


# ── ② oc_set_first：多套 schema 全失败也只记一条警告 ─────────────────

@needs_bash
def test_oc_set_first_falls_through_to_second_schema(tmp_path: Path) -> None:
    """新 schema 被拒时自动退到老 schema，并且不记警告。"""
    r = _run_helpers(
        tmp_path,
        "oc_set_first '向量记忆' false --json "
        "memory.search.enabled agents.defaults.memorySearch.enabled\n"
        'echo "WARNS=${#WARN_LABELS[@]}"\n',
        reject_key="memory.search.enabled",
    )
    assert r.returncode == 0, r.stderr[-400:]
    assert "WARNS=0" in r.stdout, f"退到老 schema 成功时不该记警告：{r.stdout}"


@needs_bash
def test_oc_set_first_all_schemas_rejected_warns_once(tmp_path: Path) -> None:
    """候选 key 全被拒时只记一条警告（按意图计数，不是按 key 计数）。"""
    r = _run_helpers(
        tmp_path,
        "oc_set_first '向量记忆' false --json nope.one nope.two nope.three || true\n"
        'echo "WARNS=${#WARN_LABELS[@]}"\n',
        reject_key="",  # 假 openclaw 全成功 → 第一个就命中
    )
    assert "WARNS=0" in r.stdout


# ── ③ EASEL_SETUP_STRICT：把警告升回致命 ─────────────────────────────

@needs_bash
def test_strict_mode_turns_warning_into_fatal(tmp_path: Path) -> None:
    """依赖「失败即非零退出」的自动化可以用 EASEL_SETUP_STRICT=1 恢复旧行为。"""
    r = _run_helpers(
        tmp_path,
        "oc_set '测试项' gateway.mode local\n"
        "echo REACHED_END\n",
        reject_key="gateway.mode",
        strict="1",
    )
    assert r.returncode != 0, "strict 模式下警告必须变成致命"
    assert "REACHED_END" not in r.stdout


# ── ④ 静态断言：不许再出现裸的 config set ────────────────────────────

def test_no_naked_config_set_outside_chokepoint() -> None:
    """每个 config 写入都必须经过容忍层。

    裸写法（`$OC config set ... | sed '/^No change$/d'`）在 pipefail 下会让 openclaw
    的非零退出直接中断安装 —— sed 只过滤噪音，挡不住退出码。这正是历史故障的成因。
    """
    offenders = []
    for n, line in enumerate(SETUP_TEXT.splitlines(), 1):
        if "oc config set" not in line:
            continue
        # 唯一允许的位置：容忍层内部那一处真正的调用
        if "OC_LAST_OUT=" in line:
            continue
        if line.lstrip().startswith("#"):
            continue
        offenders.append(f"{n}: {line.strip()}")
    assert not offenders, "发现绕过容忍层的裸 config set：\n" + "\n".join(offenders)


def test_emit_action_redacts_secrets_in_value() -> None:
    """动作流会进 CI 日志；整块写 provider 时密钥藏在 value 里，必须按 value 也脱敏。

    实测早期版本只按 key 名脱敏，于是 models.providers.anthropic 这条把 apiKey
    明文打进了日志。
    """
    block = SETUP_TEXT[SETUP_TEXT.index("emit_action() {"):]
    block = block[: block.index("\n}\n") + 3]
    assert 'case "$value" in' in block, "emit_action 必须同时按 value 脱敏"
    assert "apiKey" in block
