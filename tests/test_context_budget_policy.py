"""issue #156：声明的 contextWindow 与压缩阈值脱节 —— 回归测试。

覆盖：
  ① doctor 的上下文预算诊断：声明窗口 → 压缩阈值的换算；只读、不改配置、不回显凭证；
  ② setup.sh 的 Gemini 分支：contextWindow / maxTokens 可被环境变量覆盖
     （此前写死 1048576，用户换模型后无法调整，也拿不到与 OpenAI 分支对等的旋钮）。
"""
from __future__ import annotations

import json
import os
import subprocess
import shlex
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SH = PROJECT_ROOT / "setup.sh"

sys.path.insert(0, str(PROJECT_ROOT))

from easel.commands import doctor  # noqa: E402


def _bash_works() -> bool:
    try:
        p = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True,
                           timeout=30, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return p.returncode == 0 and p.stdout.strip() == "ok"


needs_bash = pytest.mark.skipif(not _bash_works(), reason="没有可用的 bash")


@pytest.fixture
def config(tmp_path, monkeypatch):
    # 走共享的 profile 解析器，不另写一条硬编码的 config 路径。
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    return tmp_path / "openclaw.json"


# ── ① doctor：声明窗口 → 压缩阈值 ──────────────────────────────────

@pytest.mark.parametrize("window,expected", [
    (1_048_576, 1_028_576),   # 声明 1M：阈值 1M−20_000，压缩几乎永不触发
    (128_000, 108_000),       # 声明 128k：阈值 128k−20_000
    (32_768, 24_576),         # 窗口小到 25% 封顶生效：32_768−8_192
    (100_000, 80_000),        # 100_000×0.25=25_000 > 20_000，按 20_000 封顶
])
def test_compaction_threshold_matches_openclaw_formula(window, expected):
    """阈值 = 窗口 − min(20_000, 窗口×0.25)，与 OpenClaw shouldCompact 一致。"""
    assert doctor._compaction_threshold(window) == expected


def test_context_budget_reports_declared_window_and_threshold(config):
    config.write_text(json.dumps({
        "models": {"providers": {"deepseek": {"models": [
            {"id": "deepseek-flash", "contextWindow": 128_000, "maxTokens": 32_768},
        ]}}},
    }), encoding="utf-8")
    lines = doctor._context_budget_policy()
    joined = "\n".join(lines)
    assert "deepseek/deepseek-flash" in joined
    assert "128,000" in joined
    assert "108,000" in joined


def test_context_budget_flags_undeclared_window(config):
    config.write_text(json.dumps({
        "models": {"providers": {"openai": {"models": [{"id": "mimo-v2.6-pro"}]}}},
    }), encoding="utf-8")
    joined = "\n".join(doctor._context_budget_policy())
    assert "未声明 contextWindow" in joined


def test_context_budget_reports_skill_limits(config):
    config.write_text(json.dumps({
        "models": {"providers": {}},
        "skills": {"limits": {"maxSkillsPromptChars": 60_000, "maxSkillsInPrompt": 200}},
    }), encoding="utf-8")
    joined = "\n".join(doctor._context_budget_policy())
    assert "skills.limits" in joined
    assert "60,000" in joined
    assert "200" in joined


def test_context_budget_reports_unset_skill_limits(config):
    config.write_text(json.dumps({"models": {"providers": {}}}), encoding="utf-8")
    joined = "\n".join(doctor._context_budget_policy())
    assert "skills.limits" in joined
    assert "未设置" in joined


@pytest.mark.parametrize("source", [b"{invalid PRIVATE-KEY", b"\xff", b"[]"])
def test_unreadable_or_invalid_config_does_not_leak_payload(config, source):
    config.write_bytes(source)
    lines = doctor._context_budget_policy()
    assert len(lines) == 1 and "未知" in lines[0]
    assert "PRIVATE-KEY" not in "\n".join(lines)


def test_context_budget_is_read_only_and_hides_credentials(config):
    source = json.dumps({
        "models": {"providers": {"deepseek": {
            "apiKey": "sk-private",
            "models": [{"id": "deepseek-flash", "contextWindow": 128_000}],
        }}},
    }).encode()
    config.write_bytes(source)
    before = config.stat().st_mtime_ns
    lines = doctor._context_budget_policy()
    assert config.read_bytes() == source
    assert config.stat().st_mtime_ns == before
    assert "sk-private" not in "\n".join(lines)


def test_context_cap_and_disabled_compaction_are_not_reported_as_active_threshold(config):
    config.write_text(json.dumps({"agents": {"defaults": {
        "contextTokens": 32000, "compaction": {"enabled": False},
    }}, "models": {"providers": {"custom": {"models": [
        {"id": "model", "contextWindow": 128000},
    ]}}}}), encoding="utf-8")
    output = "\n".join(doctor._context_budget_policy())
    assert "显式关闭" in output and "参考" in output
    assert "contextTokens 上限 32,000" in output
    assert "24,000" in output


def test_invalid_skill_budgets_are_not_reported_as_usable(config):
    config.write_text(json.dumps({"skills": {"limits": {
        "maxSkillsPromptChars": -1, "maxSkillsInPrompt": True,
    }}}), encoding="utf-8")
    assert "格式异常" in "\n".join(doctor._context_budget_policy())


def test_large_context_window_uses_integer_math():
    assert doctor._compaction_threshold(10 ** 309) == 10 ** 309 - 20000


# ── ② setup.sh：Gemini 分支的 contextWindow / maxTokens 可覆盖 ──────

def _gemini_models_written(tmp_path: Path, **env: str) -> str:
    """跑 setup.sh 的 Gemini 分支，返回写进 models 的那条 JSON。"""
    lines = SETUP_SH.read_text(encoding="utf-8").splitlines()
    i = next(n for n, line in enumerate(lines)
             if line.startswith('elif [ "$STANDARD_LLM_CONFIGURED" = false ]')
             and "GEMINI_MAAS_API_KEY" in line)
    j = next(n for n, line in enumerate(lines) if n > i and line.startswith("elif usable_key"))
    # 独立片段里开头的 `elif` 没有配对的 `if`，改写成 `if` 并补 `fi` 才能单独跑。
    branch = "\n".join(lines[i:j]).replace(
        'elif [ "$STANDARD_LLM_CONFIGURED" = false ]', 'if [ "$STANDARD_LLM_CONFIGURED" = false ]', 1)
    branch += "\nfi"
    calls = tmp_path / "oc.log"
    script = textwrap.dedent(f"""
        set -u
        PROJECT_ROOT={shlex.quote(tmp_path.as_posix())}
        CFG={shlex.quote(calls.as_posix())}
        : > "$CFG"
        STANDARD_LLM_CONFIGURED=false
        ok()   {{ echo "OK|$*"; }}
        warn() {{ echo "WARN|$*"; }}
        info() {{ echo "[easel] $*"; }}
        python3() {{ {shlex.quote(Path(sys.executable).as_posix())} "$@"; }}
        usable_key() {{ [ -n "${{1:-}}" ]; }}
        oc_set()       {{ shift; echo "$1 = $2" >> "$CFG"; }}
        oc_try()       {{ echo "$1 = $2" >> "$CFG"; return 0; }}
        oc_set_first() {{ v="$2"; shift 3; echo "$1 = $v" >> "$CFG"; return 0; }}
        oc_supports()  {{ return 1; }}
        warn_collect() {{ echo "WARN|$1：$2"; }}
    """) + "\n" + branch + "\n"
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, env={**os.environ, **env})
    assert proc.returncode == 0, f"Gemini 分支执行失败：{proc.stderr}"
    for line in calls.read_text(encoding="utf-8").splitlines():
        if line.startswith("models.providers.rednote-gemini.models = "):
            return line.split(" = ", 1)[1]
    return ""


@needs_bash
def test_gemini_models_declare_context_window_and_max_tokens(tmp_path: Path) -> None:
    """models[] 必须声明 contextWindow / maxTokens，否则部分网关 400。"""
    raw = _gemini_models_written(tmp_path, GEMINI_MAAS_API_KEY="sk-real",
                                 GEMINI_MAAS_ENDPOINT="https://example.invalid/v1")
    assert raw, "Gemini provider 的 models 没有被写入"
    assert '"contextWindow":1048576' in raw
    assert '"maxTokens":65535' in raw


@needs_bash
def test_gemini_models_respect_env_overrides(tmp_path: Path) -> None:
    """声明值必须可被环境变量覆盖：换模型或想收紧上下文时用户才有旋钮。"""
    raw = _gemini_models_written(
        tmp_path,
        GEMINI_MAAS_API_KEY="sk-real",
        GEMINI_MAAS_ENDPOINT="https://example.invalid/v1",
        GEMINI_CONTEXT_WINDOW="128000",
        GEMINI_MAX_TOKENS="16384",
    )
    assert '"contextWindow":128000' in raw
    assert '"maxTokens":16384' in raw


@needs_bash
@pytest.mark.parametrize("window,tokens", [("0", "1"), ("128000", "0"),
    ("small", "100"), ("100", "101"), ("100,\"extra\":1", "50")])
def test_gemini_invalid_budget_rejected_before_models_are_written(tmp_path, window, tokens):
    with pytest.raises(AssertionError, match="Gemini 分支执行失败"):
        _gemini_models_written(tmp_path, GEMINI_MAAS_API_KEY="fixture-key",
            GEMINI_MAAS_ENDPOINT="https://example.invalid/v1",
            GEMINI_CONTEXT_WINDOW=window, GEMINI_MAX_TOKENS=tokens)
    assert (tmp_path / "oc.log").read_text(encoding="utf-8") == ""


@needs_bash
def test_gemini_model_id_and_paths_are_json_escaped(tmp_path):
    directory = tmp_path / "space in directory"
    directory.mkdir()
    raw = _gemini_models_written(directory, GEMINI_MAAS_API_KEY="fixture-key",
        GEMINI_MAAS_ENDPOINT="https://example.invalid/v1", GEMINI_MAAS_MODEL='custom/"quoted"')
    assert json.loads(raw)[0]["id"] == 'custom/"quoted"'
