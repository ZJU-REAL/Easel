import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/agent_fault_report.py"
spec = importlib.util.spec_from_file_location("agent_fault_report", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def evidence():
    root = ET.Element("testsuites")
    for scenario in module.SCENARIOS:
        suite = ET.SubElement(root, "testsuite")
        for key in scenario["tests"]:
            if key.endswith("::*"):
                classname, name = key[:-3], "test_covered_case"
            else:
                classname, name = key.split("::")
            ET.SubElement(suite, "testcase", classname=classname, name=name, time="0.25")
    return root


def convert(root):
    return module.report(ET.tostring(root), revision="example-revision")


def test_complete_report_is_repeatable_and_does_not_invent_metrics():
    root = evidence()
    result = convert(root)
    assert result == convert(root) and result["complete"] is True
    assert len(result["scenarios"]) == len(module.SCENARIOS) and result["revision_verified"] is False
    assert result["scenarios"][0]["test_duration_seconds"] == 0.5
    for scenario in result["scenarios"]:
        assert scenario["model_calls"] is None
        assert scenario["duplicate_external_effects"] is None
        assert scenario["recovery_latency_seconds"] is None


@pytest.mark.parametrize("tag,status", [("failure", "failed"), ("error", "error"), ("skipped", "skipped")])
def test_failures_and_skips_are_not_passes_and_raw_details_are_omitted(tag, status):
    root = evidence()
    ET.SubElement(next(root.iter("testcase")), tag, message="private-tool-output").text = "private-token"
    result = convert(root)
    assert result["complete"] is False and result["scenarios"][0]["status"] == status
    assert "private-" not in json.dumps(result)


def test_missing_or_partial_evidence_is_explicitly_not_run():
    root = evidence()
    root[0].remove(root[0][0])
    result = convert(root)
    assert result["scenarios"][0]["status"] == "not_run"
    assert len(result["scenarios"][0]["missing_tests"]) == 1
    assert not module.report(b"<testsuites/>")["complete"]


def test_repeated_case_cannot_hide_an_earlier_failure():
    root = evidence()
    duplicate = ET.SubElement(root[0], "testcase", **root[0][0].attrib)
    ET.SubElement(duplicate, "failure")
    assert convert(root)["scenarios"][0]["status"] == "failed"


def test_missing_duration_is_not_reported_as_zero():
    root = evidence()
    del root[0][0].attrib["time"]
    assert convert(root)["scenarios"][0]["test_duration_seconds"] is None
    assert module.report(b"<testsuites/>")["scenarios"][0]["test_duration_seconds"] is None


@pytest.mark.parametrize("value", ["NaN", "inf", "-1", "invalid"])
def test_invalid_durations_are_rejected(value):
    root = evidence()
    root[0][0].set("time", value)
    with pytest.raises(ValueError):
        convert(root)


@pytest.mark.parametrize("payload", [b"broken", b"<unrelated/>", b'<!DOCTYPE x [<!ENTITY e "x">]><testsuites/>'])
def test_cli_rejects_invalid_input_without_emitting_a_success_report(tmp_path, payload):
    source = tmp_path / "input.xml"
    source.write_bytes(payload)
    result = subprocess.run([sys.executable, str(SCRIPT), str(source)], capture_output=True, text=True)
    assert result.returncode == 2 and not result.stdout
    assert source.read_bytes() == payload


@pytest.mark.parametrize("complete,expected", [(True, 0), (False, 1)])
def test_cli_status_agrees_with_its_report(tmp_path, complete, expected):
    source = tmp_path / "input.xml"
    source.write_bytes(ET.tostring(evidence()) if complete else b"<testsuites/>")
    result = subprocess.run([sys.executable, str(SCRIPT), str(source), "--revision", "abc"], capture_output=True, text=True)
    assert result.returncode == expected
    assert json.loads(result.stdout)["complete"] is complete


def test_module_wildcard_matches_parametrized_case_names():
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for name in ("test_one", "test_two[param]", "test_three[a::b]"):
        ET.SubElement(suite, "testcase", classname="tests.test_gateway_stream_completion", name=name, time="0.1")
    result = convert(root)
    scenario = next(item for item in result["scenarios"] if item["id"] == "stream-completion-ordering")
    assert scenario["status"] == "passed" and scenario["case_counts"]["passed"] == 3


def test_module_wildcard_failure_among_passes_is_not_a_pass():
    root = evidence()
    for case in root.iter("testcase"):
        if case.get("classname") == "tests.test_gateway_stream_completion":
            ET.SubElement(case, "failure", message="private-tool-output").text = "private-token"
            break
    result = convert(root)
    scenario = next(item for item in result["scenarios"] if item["id"] == "stream-completion-ordering")
    assert result["complete"] is False and scenario["status"] == "failed"
    assert "private-" not in json.dumps(result)


def test_module_wildcard_requires_the_exact_module_prefix():
    root = evidence()
    for case in root.iter("testcase"):
        if case.get("classname") == "tests.test_chat_event_log_recovery":
            case.set("classname", "tests.test_chat_event_log_recovery_extra")
    result = convert(root)
    scenario = next(item for item in result["scenarios"] if item["id"] == "event-log-truncation")
    assert scenario["status"] == "not_run"
    assert scenario["missing_tests"] == ["tests.test_chat_event_log_recovery::*"]


def test_function_prefix_wildcard_matches_parametrized_cases_only():
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    ET.SubElement(suite, "testcase", classname="tests.test_agent_harnesses",
                  name="test_native_failure_never_succeeds_or_leaks_keys[mode0]", time="0.1")
    ET.SubElement(suite, "testcase", classname="tests.test_agent_harnesses",
                  name="test_unrelated_lookalike_native_failure_never_succeeds_or_leaks", time="0.1")
    result = convert(root)
    scenario = next(item for item in result["scenarios"] if item["id"] == "native-failure-fail-closed")
    assert scenario["case_counts"]["passed"] == 1 and scenario["status"] == "not_run"
