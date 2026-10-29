from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from easel.commands import doctor


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for variable in doctor._SKILLS_BUDGET_ENV.values():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("EASEL_OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path / "state"))
    config = tmp_path / "state" / "openclaw.json"
    config.parent.mkdir()
    config.write_text("{}", encoding="utf-8")
    root = tmp_path / "repo with spaces"
    root.mkdir()
    return root, config


def test_defaults_fit_all_builtin_descriptions(isolated):
    count, chars = doctor._builtin_skills_estimate({})
    updates = doctor._skills_budget_updates({}, {})
    assert count == 115
    assert updates["maxSkillsInPrompt"] >= count
    assert updates["maxSkillsPromptChars"] >= chars + 8192
    assert updates["maxSkillsInPrompt"] == 200
    assert updates["maxSkillsPromptChars"] == max(80000, chars + 8192)


@pytest.mark.parametrize("limits", [
    {"maxSkillsInPrompt": 1, "maxSkillsPromptChars": 100},
    {"maxSkillsInPrompt": 0, "maxSkillsPromptChars": 0},
    {"maxSkillsInPrompt": None, "maxSkillsPromptChars": False},
])
def test_saved_limits_are_never_silently_overwritten(isolated, limits):
    config = {"skills": {"limits": limits}}
    source = json.dumps(config)
    assert doctor._skills_budget_updates(config, {}) == {}
    assert json.dumps(config) == source


def test_partial_budget_preserves_other_fields(isolated):
    config = {"skills": {"limits": {"maxSkillsInPrompt": 37, "maxSkillFileBytes": 1234},
                         "entries": {"custom": {"enabled": False}}},
              "agents": {"list": [{"id": "main", "skillsLimits": {"maxSkillsPromptChars": 99}}]}}
    source = json.dumps(config)
    assert doctor._skills_budget_updates(config, {}) == {
        "maxSkillsPromptChars": doctor._skills_budget_updates({}, {})["maxSkillsPromptChars"]}
    assert json.dumps(config) == source


def test_explicit_override_applies_only_to_requested_field(isolated):
    config = {"skills": {"limits": {"maxSkillsInPrompt": 13, "maxSkillsPromptChars": 44}}}
    assert doctor._skills_budget_updates(config, {"EASEL_MAX_SKILLS_IN_PROMPT": "250"}) == {
        "maxSkillsInPrompt": 250}
    assert doctor._skills_budget_updates(config, {"EASEL_MAX_SKILLS_PROMPT_CHARS": "0"}) == {
        "maxSkillsPromptChars": 0}


@pytest.mark.parametrize("raw", ["-1", "1.2", "true", " 200", "200;echo secret", "١٢", "9007199254740992"])
def test_bad_overrides_reject_the_entire_plan_before_writing(isolated, raw):
    with pytest.raises(ValueError):
        doctor._skills_budget_updates({}, {"EASEL_MAX_SKILLS_PROMPT_CHARS": raw})


@pytest.mark.parametrize("config", [[], {"skills": None}, {"skills": []}, {"skills": {"limits": None}},
                                    {"$include": "private.json"}, {"skills": {"$include": "skills.json"}},
                                    {"skills": {"limits": {"$include": "limits.json"}}}])
def test_invalid_config_is_not_replaced_by_defaults(isolated, config):
    with pytest.raises(ValueError):
        doctor._skills_budget_updates(config, {})


def test_long_unicode_workspace_expands_default_budget(isolated, monkeypatch):
    monkeypatch.setenv("EASEL_OPENCLAW_WORKSPACE", "/" + "路径😀&" * 150)
    count, chars = doctor._builtin_skills_estimate({})
    assert count == 115 and chars > 80000
    assert doctor._skills_budget_updates({}, {})["maxSkillsPromptChars"] >= chars + 8192


def test_doctor_distinguishes_estimates_from_runtime_visibility(isolated):
    root, config = isolated
    source = json.dumps({"skills": {"limits": {"maxSkillsInPrompt": 1}},
                         "models": {"providers": {"private": {"apiKey": "PRIVATE-KEY"}}}}).encode()
    config.write_bytes(source)
    before = config.stat().st_mtime_ns
    output = "\n".join(doctor._context_budget_policy())
    assert "115 个" in output and "离线上界估算" in output
    assert "不含第三方技能" in output and "风险" in output
    assert "实际遗漏不能由此推定" in output
    assert "运行时可见性未知" in output and "Eligible 数不等于" in output
    assert "maxSkillsPromptChars 未设置" in output
    assert "PRIVATE-KEY" not in output
    assert config.read_bytes() == source and config.stat().st_mtime_ns == before


def test_doctor_reports_zero_and_agent_overrides(isolated):
    output = "\n".join(doctor._skills_catalog_policy({
        "skills": {"limits": {"maxSkillsInPrompt": 0, "maxSkillsPromptChars": 0}},
        "agents": {"entries": {"main": {"skillsLimits": {"maxSkillsPromptChars": 17}}}},
    }))
    assert "显式为 0" in output and "格式异常" not in output
    assert "Agent 级" in output and "不能代表" in output


def test_doctor_large_budget_does_not_claim_runtime_success(isolated):
    output = "\n".join(doctor._skills_catalog_policy({"skills": {"limits": {
        "maxSkillsInPrompt": 200, "maxSkillsPromptChars": 80000}}}))
    assert "覆盖此离线估算" in output and "不保证运行时" in output


def _run_installer_plan(isolated, shell, *, env_text="", reject=False):
    root, config = isolated
    (root / ".env").write_text(env_text, encoding="utf-8")
    environment = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "REJECT_SKILLS": "1" if reject else ""}
    if shell == "bash":
        if not shutil.which("bash"):
            pytest.skip("bash unavailable")
        source = (PROJECT_ROOT / "setup.sh").read_text(encoding="utf-8")
        start = source.index("oc_configure_skills_budget() {")
        body = source[start:source.index("\n# ---- 安装报告 ----", start)]
        script = (
            "set -euo pipefail\n"
            f"PROJECT_ROOT={shlex.quote(root.as_posix())}\n"
            f"python3() {{ {shlex.quote(Path(sys.executable).as_posix())} \"$@\"; }}\n"
            'oc_try() { if [ -n "$REJECT_SKILLS" ]; then return 1; fi; echo "SET|$1|$2"; }\n'
            'warn_collect() { echo "WARN|$1|$2"; }\n'
            + body + "\noc_configure_skills_budget\necho DONE\n"
        )
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                env=environment, timeout=30)
    else:
        executable = shutil.which(shell)
        if not executable:
            pytest.skip(f"{shell} unavailable")
        source = (PROJECT_ROOT / "setup.ps1").read_text(encoding="utf-8-sig")
        start = source.index("function Set-OpenClawSkillsBudget {")
        body = source[start:source.index("\nfunction Set-OpenClawConfigQuiet", start)]
        script = root / "probe.ps1"
        script.write_text(
            "param($Python, $Root)\n$ErrorActionPreference = 'Stop'\n"
            "function Add-Warning($Label, $Detail, $Fix) { Write-Output \"WARN|$Label|$Detail\" }\n"
            "function Set-OpenClawConfig($Key, $Value, [switch]$Json, $Label) {\n"
            "if ($env:REJECT_SKILLS) { Add-Warning $Label 'Unrecognized key' ''; return }\n"
            "Write-Output \"SET|$Key|$Value\"\n}\n"
            + body + "\nSet-OpenClawSkillsBudget\nWrite-Output DONE\n", encoding="utf-8-sig")
        result = subprocess.run([executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(script), sys.executable, str(root)],
                                capture_output=True, text=True, env=environment, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DONE" in result.stdout
    return result.stdout


@pytest.mark.parametrize("shell", ["bash", "pwsh", "powershell"])
def test_installers_defaults_and_env_file_overrides(isolated, shell, monkeypatch):
    output = _run_installer_plan(isolated, shell)
    assert "SET|skills.limits.maxSkillsInPrompt|200" in output
    chars = doctor._skills_budget_updates({}, {})["maxSkillsPromptChars"]
    assert f"SET|skills.limits.maxSkillsPromptChars|{chars}" in output
    output = _run_installer_plan(isolated, shell, env_text="EASEL_MAX_SKILLS_IN_PROMPT=230\nEASEL_MAX_SKILLS_PROMPT_CHARS=90000\n")
    assert "SET|skills.limits.maxSkillsInPrompt|230" in output
    assert "SET|skills.limits.maxSkillsPromptChars|90000" in output
    monkeypatch.setenv("EASEL_MAX_SKILLS_IN_PROMPT", "250")
    output = _run_installer_plan(isolated, shell, env_text="EASEL_MAX_SKILLS_IN_PROMPT=230\n")
    assert "SET|skills.limits.maxSkillsInPrompt|250" in output


@pytest.mark.parametrize("shell", ["bash", "pwsh", "powershell"])
def test_installers_preserve_saved_values_and_other_config(isolated, shell):
    root, config = isolated
    source = json.dumps({"skills": {"entries": {"private": {"apiKey": "PRIVATE-KEY"}},
                                    "limits": {"maxSkillsInPrompt": 12, "maxSkillsPromptChars": 99}},
                         "agents": {"defaults": {"timeoutSeconds": 86400}}}).encode()
    config.write_bytes(b"\xef\xbb\xbf" + source)
    output = _run_installer_plan(isolated, shell)
    assert "SET|" not in output and "PRIVATE-KEY" not in output
    output = _run_installer_plan(isolated, shell, env_text="EASEL_MAX_SKILLS_IN_PROMPT=251\n")
    assert "SET|skills.limits.maxSkillsInPrompt|251" in output
    assert "SET|skills.limits.maxSkillsPromptChars" not in output
    assert config.read_bytes() == b"\xef\xbb\xbf" + source


@pytest.mark.parametrize("shell", ["bash", "pwsh", "powershell"])
def test_installers_degrade_on_invalid_input_and_unsupported_schema(isolated, shell):
    output = _run_installer_plan(isolated, shell, env_text="EASEL_MAX_SKILLS_PROMPT_CHARS=-1\n")
    assert "WARN|" in output and "SET|" not in output
    output = _run_installer_plan(isolated, shell, reject=True)
    assert "WARN|" in output and "SET|" not in output
    root, config = isolated
    config.write_text("{invalid PRIVATE-KEY", encoding="utf-8")
    output = _run_installer_plan(isolated, shell)
    assert "WARN|" in output and "SET|" not in output and "PRIVATE-KEY" not in output


def test_windows_budget_is_only_called_after_openclaw_initialization():
    source = (PROJECT_ROOT / "setup.ps1").read_text(encoding="utf-8-sig")
    call = source.index("\nSet-OpenClawSkillsBudget\n")
    assert source.index("Step '7/8'") < call
    assert source.index("$onboard =") < call
    assert source.index("if ($SkipOpenClaw) {\n    Step '6/8'") < call

