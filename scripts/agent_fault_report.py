"""Summarize deterministic agent fault regressions from pytest JUnit XML.

Does not execute tools, models or tests. Missing evidence is never a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


SCENARIOS = (
    {
        "id": "resume-identity", "fault_stage": "native session resume",
        "expected": "reject a replacement native identity",
        "forbidden_effect": "silently replace existing conversation history",
        "tests": ["tests.test_agent_harnesses::test_codex_rejects_replacement_thread_on_resume",
                  "tests.test_agent_harnesses::test_acp_rejects_replacement_session_on_resume"],
    },
    {
        "id": "pooled-session-ownership", "fault_stage": "concurrent pooled turn and cancellation",
        "expected": "reject concurrent ownership and clean up the cancelled process",
        "forbidden_effect": "reuse a busy or cancelled process for another turn",
        "tests": ["tests.test_agent_harnesses::test_pooled_connections_reject_concurrent_turn_and_clean_cancelled_process"],
    },
    {
        "id": "native-fatal-event", "fault_stage": "fatal native protocol event",
        "expected": "surface the failure without waiting for the full turn timeout",
        "forbidden_effect": "report success or automatically repeat the prompt",
        "tests": ["tests.test_agent_harnesses::test_codex_fatal_event_does_not_wait_until_timeout"],
    },
    {
        "id": "event-log-truncation", "fault_stage": "damaged chat event log record",
        "expected": "preserve the valid events around the damage and still reach the terminal event",
        "forbidden_effect": "discard valid events or rewrite the source log",
        "tests": ["tests.test_chat_event_log_recovery::*"],
    },
    {
        "id": "stream-completion-ordering", "fault_stage": "gateway completion racing buffered response tokens",
        "expected": "deliver every token before the completion sentinel and release session locks",
        "forbidden_effect": "drop buffered tokens or signal completion early",
        "tests": ["tests.test_gateway_stream_completion::*"],
    },
    {
        "id": "snapshot-ownership", "fault_stage": "queued turn, cancellation and cross-process contention",
        "expected": "claim the recovery snapshot only under both session locks and release only its own ownership",
        "forbidden_effect": "overwrite another turn's snapshot or steal a live process lock",
        "tests": ["tests.test_gateway_snapshot_ownership::*"],
    },
    {
        "id": "native-failure-fail-closed", "fault_stage": "native tool failure, malformed RPC output or corrupt settings",
        "expected": "fail closed with a safe, non-success report",
        "forbidden_effect": "report success or leak keys, payloads or settings contents",
        "tests": ["tests.test_agent_harnesses::test_native_failure_never_succeeds_or_leaks_keys*",
                  "tests.test_agent_harnesses::test_rpc_stderr_and_invalid_json",
                  "tests.test_agent_harnesses::test_corrupt_settings_fail_closed*"],
    },
    {
        "id": "process-interruption-recovery", "fault_stage": "process death between artifact checkpoint commits",
        "expected": "reuse only committed steps, release locks and preserve the previous final artifact",
        "forbidden_effect": "treat uncommitted or invalid steps as reusable receipts",
        "tests": ["tests.test_artifact_checkpoints::*", "tests.test_assemble_checkpoints::*"],
    },
)


def _entry_matches(entry: str, classname: str, name: str) -> bool:
    """Match ``classname::name`` where the name part may end with ``*`` (prefix wildcard,
    e.g. parametrized cases or a whole-module ``classname::*``)."""
    expected_classname, separator, expected_name = entry.partition("::")
    if not separator or classname != expected_classname:
        return False
    if expected_name.endswith("*"):
        return name.startswith(expected_name[:-1])
    return name == expected_name


def report(source: bytes, *, revision: str | None = None) -> dict:
    if len(source) > 32 * 1024 * 1024:
        raise ValueError("JUnit input exceeds 32 MiB")
    # pytest writes UTF-8. Do not expand external/internal document entities.
    text = source.decode("utf-8-sig")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("JUnit document declarations are unsupported")
    root = ET.fromstring(text)
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("Expected a JUnit testsuite or testsuites root")
    evidence: dict[tuple[str, str], list[tuple[str, float | None]]] = {}
    for case in root.iter("testcase"):
        key = (case.get("classname", ""), case.get("name", ""))
        if not any(_entry_matches(entry, *key) for scenario in SCENARIOS for entry in scenario["tests"]):
            continue
        duration = float(case.get("time")) if "time" in case.attrib else None
        if duration is not None and (not math.isfinite(duration) or duration < 0):
            raise ValueError("Invalid test duration")
        status = next((state for tag, state in (("error", "error"), ("failure", "failed"),
                                                ("skipped", "skipped")) if case.find(tag) is not None), "passed")
        evidence.setdefault(key, []).append((status, duration))
    scenarios = []
    for definition in SCENARIOS:
        missing = [entry for entry in definition["tests"]
                   if not any(_entry_matches(entry, *key) for key in evidence)]
        cases = [item for key in evidence if any(_entry_matches(entry, *key) for entry in definition["tests"])
                 for item in evidence[key]]
        counts = {state: sum(result == state for result, _ in cases)
                  for state in ("passed", "failed", "error", "skipped")}
        status = ("error" if counts["error"] else "failed" if counts["failed"] else
                  "not_run" if missing else "skipped" if counts["skipped"] else "passed")
        scenarios.append({**definition, "status": status, "case_counts": counts,
                          "missing_tests": missing,
                          "test_duration_seconds": (round(sum(seconds for _, seconds in cases), 6)
                                                    if cases and all(seconds is not None for _, seconds in cases) else None),
                          "model_calls": None, "duplicate_external_effects": None,
                          "recovery_latency_seconds": None})
    return {"schema_version": 1, "kind": "deterministic_fault_regression",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "revision_label": revision, "revision_verified": False,
            "complete": all(item["status"] == "passed" for item in scenarios),
            "scenarios": scenarios}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path, help="pytest --junitxml output (UTF-8)")
    parser.add_argument("--revision", help="revision label recorded by the test runner; not independently verified")
    args = parser.parse_args(argv)
    try:
        with args.junit.open("rb") as handle:
            payload = report(handle.read(32 * 1024 * 1024 + 1), revision=args.revision)
    except (OSError, ValueError, ET.ParseError):
        print("Cannot read a supported, valid JUnit report; preserve the original evidence.", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if payload["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
