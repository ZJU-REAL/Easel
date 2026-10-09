from __future__ import annotations

import json
import fcntl
import importlib.util
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from easel.moneyprinterturbo import (
    BridgeResult,
    MoneyPrinterTurboError,
    MoneyPrinterTurboBridge,
    MoneyPrinterTurboPaths,
    MoneyPrinterTurboRequest,
    atomic_deliver,
    build_command,
    parse_cli_result,
    prepare_request,
    render_managed_config,
)
from skills.shared.scripts import output_paths


ROOT = Path(__file__).resolve().parents[1]


def _paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MoneyPrinterTurboPaths:
    root = tmp_path / "easel"
    (root / "assets").mkdir(parents=True)
    (root / "outputs").mkdir()
    monkeypatch.setattr(output_paths, "PROJECT_ROOT", root)
    monkeypatch.setattr(output_paths, "OUTPUTS_DIR", root / "outputs")
    return MoneyPrinterTurboPaths.for_root(root)


def _request(**changes: object) -> MoneyPrinterTurboRequest:
    request = MoneyPrinterTurboRequest(
        project_name="Autumn city guide",
        aspect="9:16",
        source="pexels",
        topic="Three quiet places to visit this fall",
    )
    return replace(request, **changes)


def _media(path: Path, content: bytes = b"media") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_request_requires_exactly_one_topic_or_script_and_explicit_aspect(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)

    for invalid in (
        _request(topic=None),
        _request(topic="topic", script="script"),
        _request(topic="   "),
        _request(aspect=""),
        _request(aspect="4:3"),
    ):
        with pytest.raises(MoneyPrinterTurboError):
            prepare_request(paths, invalid)

    assert prepare_request(paths, _request()).topic.startswith("Three quiet")
    assert prepare_request(paths, _request(topic=None, script="Finished script")).script == "Finished script"


def test_project_name_uses_output_paths_gate(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)

    with pytest.raises(MoneyPrinterTurboError, match="project"):
        prepare_request(paths, _request(project_name="test"))
    with pytest.raises(MoneyPrinterTurboError, match="project"):
        prepare_request(paths, _request(project_name="../escape"))

    prepared = prepare_request(paths, _request(project_name="Autumn city guide"))
    assert prepared.output_dir == paths.root / "outputs" / "Autumn city guide"
    assert prepared.final_path == prepared.output_dir / "final.mp4"
    assert not prepared.output_dir.exists()


def test_local_source_requires_real_non_symlink_media_in_allowed_roots(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    global_media = _media(paths.root / "assets" / "clip.mp4")
    project_media = _media(paths.root / "outputs" / "Autumn city guide" / "assets" / "still.png")

    with pytest.raises(MoneyPrinterTurboError, match="material"):
        prepare_request(paths, _request(source="local"))
    with pytest.raises(MoneyPrinterTurboError, match="material"):
        prepare_request(paths, _request(source="local", materials=(paths.root / "assets" / "missing.mp4",)))

    symlink = paths.root / "assets" / "linked.mp4"
    symlink.symlink_to(global_media)
    with pytest.raises(MoneyPrinterTurboError, match="symlink"):
        prepare_request(paths, _request(source="local", materials=(symlink,)))

    empty = _media(paths.root / "assets" / "empty.mp4", b"")
    with pytest.raises(MoneyPrinterTurboError, match="empty"):
        prepare_request(paths, _request(source="local", materials=(empty,)))

    prepared = prepare_request(paths, _request(source="local", materials=(global_media, project_media)))
    assert prepared.materials == (global_media.resolve(), project_media.resolve())


def test_project_secrets_state_source_and_other_output_projects_are_not_media(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    invalid_paths = (
        _media(paths.root / ".env"),
        _media(paths.root / ".state" / "moneyprinterturbo" / "secret.mp4"),
        _media(paths.root / ".tools" / "moneyprinterturbo" / "source" / "sample.mp4"),
        _media(paths.root / "outputs" / "Different project" / "assets" / "clip.mp4"),
        _media(paths.root / "README.mp4"),
    )

    for material in invalid_paths:
        with pytest.raises(MoneyPrinterTurboError, match="allowed"):
            prepare_request(paths, _request(source="local", materials=(material,)))


def test_safe_stock_sources_need_no_charge_confirmation(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)

    for source in ("pexels", "pixabay", "coverr"):
        prepared = prepare_request(paths, _request(source=source))
        assert prepared.source == source

    with pytest.raises(MoneyPrinterTurboError, match="confirmation"):
        prepare_request(paths, _request(source="pexels", confirm_ofox_charge=True))


def test_each_paid_source_requires_only_its_matching_confirmation(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    cases = (
        ("volcengine_seedance", "confirm_seedance_charge"),
        ("ofox", "confirm_ofox_charge"),
        ("metaso_minimax", "confirm_metaso_minimax_charge"),
    )

    for source, confirmation in cases:
        with pytest.raises(MoneyPrinterTurboError, match="confirmation"):
            prepare_request(paths, _request(source=source))
        prepared = prepare_request(paths, _request(source=source, **{confirmation: True}))
        assert prepared.source == source

    with pytest.raises(MoneyPrinterTurboError, match="confirmation"):
        prepare_request(
            paths,
            _request(source="ofox", confirm_ofox_charge=True, confirm_seedance_charge=True),
        )


CONFIG_SAMPLE = """\
listen_host = "0.0.0.0"
listen_port = 8080

[app]
llm_provider = "moonshot"
openai_api_key = "old-value"
openai_base_url = "https://example.invalid/v1"
openai_model_name = "old-model"
pexels_api_keys = ["preserve-pexels"]
pixabay_api_keys = ["preserve-pixabay"]
upload_post_enabled = true
upload_post_auto_upload = true

[whisper]
model_size = "large-v3"
"""


def _runtime(paths: MoneyPrinterTurboPaths) -> None:
    (paths.source / ".venv" / "bin").mkdir(parents=True)
    _media(paths.source / ".venv" / "bin" / "python")
    (paths.source / "cli.py").write_text("# fixture\n", encoding="utf-8")
    paths.state.mkdir(parents=True)
    paths.config.write_text(CONFIG_SAMPLE, encoding="utf-8")
    paths.task_root.mkdir(parents=True)


def test_managed_config_sets_loopback_local_qwen_and_disables_upload():
    rendered = render_managed_config(
        CONFIG_SAMPLE,
        llm_base_url="http://127.0.0.1:8081/v1",
        llm_model="qwen38-27b-mythos-agentic",
    )

    assert 'listen_host = "127.0.0.1"' in rendered
    assert 'llm_provider = "openai"' in rendered
    assert 'openai_api_key = "local-easel"' in rendered
    assert 'openai_base_url = "http://127.0.0.1:8081/v1"' in rendered
    assert 'openai_model_name = "qwen38-27b-mythos-agentic"' in rendered
    assert "upload_post_enabled = false" in rendered
    assert "upload_post_auto_upload = false" in rendered
    assert 'listen_host = "0.0.0.0"' not in rendered


def test_managed_config_preserves_unowned_provider_credentials():
    rendered = render_managed_config(
        CONFIG_SAMPLE,
        llm_base_url="http://127.0.0.1:8081/v1",
        llm_model="qwen38-27b-mythos-agentic",
    )

    assert 'pexels_api_keys = ["preserve-pexels"]' in rendered
    assert 'pixabay_api_keys = ["preserve-pixabay"]' in rendered
    assert 'model_size = "large-v3"' in rendered
    assert "listen_port = 8080" in rendered


def test_local_command_is_an_argv_array_with_explicit_aspect_and_materials(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    first = _media(paths.root / "assets" / "first clip.mp4")
    second = _media(paths.root / "outputs" / "Autumn city guide" / "assets" / "still.png")
    request = prepare_request(paths, _request(source="local", materials=(first, second)))

    command = build_command(paths, request, "12345678-1234-1234-1234-123456789abc")

    assert command[:4] == [
        str(paths.source / ".venv" / "bin" / "python"),
        str(paths.source / "cli.py"),
        "--task-id",
        "12345678-1234-1234-1234-123456789abc",
    ]
    assert command[command.index("--video-aspect") + 1] == "9:16"
    assert command[command.index("--video-source") + 1] == "local"
    assert command[command.index("--video-materials") + 1] == f"{first.resolve()},{second.resolve()}"
    assert isinstance(command, list)


def test_safe_stock_commands_have_no_paid_flags(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    paid_flags = {
        "--confirm-seedance-charge",
        "--confirm-ofox-charge",
        "--confirm-metaso-minimax-charge",
    }

    for source in ("pexels", "pixabay", "coverr"):
        command = build_command(paths, prepare_request(paths, _request(source=source)), "task-id")
        assert paid_flags.isdisjoint(command)


def test_paid_commands_add_only_the_matching_upstream_confirmation(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    cases = (
        ("volcengine_seedance", "confirm_seedance_charge", "--confirm-seedance-charge"),
        ("ofox", "confirm_ofox_charge", "--confirm-ofox-charge"),
        ("metaso_minimax", "confirm_metaso_minimax_charge", "--confirm-metaso-minimax-charge"),
    )
    all_flags = {flag for _, _, flag in cases}

    for source, field, flag in cases:
        command = build_command(
            paths,
            prepare_request(paths, _request(source=source, **{field: True})),
            "task-id",
        )
        assert set(command) & all_flags == {flag}


def test_topic_and_script_map_to_distinct_upstream_arguments(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    topic_command = build_command(paths, prepare_request(paths, _request()), "topic-task")
    script_command = build_command(
        paths,
        prepare_request(paths, _request(topic=None, script="A finished script")),
        "script-task",
    )

    assert topic_command[topic_command.index("--video-subject") + 1] == _request().topic
    assert "--video-script" not in topic_command
    assert script_command[script_command.index("--video-script") + 1] == "A finished script"
    assert "--video-subject" not in script_command


def _result_payload(task_id: str, video: Path, warnings: list[object] | None = None) -> str:
    return json.dumps(
        {
            "task_id": task_id,
            "result": {"videos": [str(video)], "warnings": warnings or []},
        }
    )


def test_result_accepts_one_matching_completed_task_video(tmp_path):
    task_root = tmp_path / "tasks"
    video = _media(task_root / "matching-task" / "final-1.mp4")

    parsed, warnings = parse_cli_result(
        _result_payload("matching-task", video, ["subtitle fallback"]),
        expected_task_id="matching-task",
        task_root=task_root,
    )

    assert parsed == video.resolve()
    assert warnings == ("subtitle fallback",)


def test_result_rejects_malformed_multiple_or_mismatched_json(tmp_path):
    task_root = tmp_path / "tasks"
    video = _media(task_root / "expected" / "final.mp4")
    valid = _result_payload("expected", video)

    for stdout in (
        "not-json",
        "{}",
        valid + "\n" + valid,
        _result_payload("different", video),
        json.dumps({"task_id": "expected", "result": []}),
        json.dumps({"task_id": "expected", "result": {"videos": [str(video), str(video)]}}),
    ):
        with pytest.raises(MoneyPrinterTurboError):
            parse_cli_result(stdout, expected_task_id="expected", task_root=task_root)


def test_result_rejects_missing_empty_non_mp4_and_out_of_task_paths(tmp_path):
    task_root = tmp_path / "tasks"
    task_dir = task_root / "expected"
    missing = task_dir / "missing.mp4"
    empty = _media(task_dir / "empty.mp4", b"")
    wrong_type = _media(task_dir / "video.mov")
    outside = _media(tmp_path / "outside.mp4")

    for video in (missing, empty, wrong_type, outside):
        with pytest.raises(MoneyPrinterTurboError):
            parse_cli_result(
                _result_payload("expected", video),
                expected_task_id="expected",
                task_root=task_root,
            )


def test_atomic_delivery_replaces_only_after_complete_copy(tmp_path, monkeypatch):
    source = _media(tmp_path / "source.mp4", b"new-complete-video")
    destination = _media(tmp_path / "project" / "final.mp4", b"old-video")
    import easel.moneyprinterturbo as module

    real_replace = module.os.replace
    observations: list[tuple[bytes, bytes]] = []

    def observing_replace(stage: Path, final: Path) -> None:
        observations.append((final.read_bytes(), Path(stage).read_bytes()))
        real_replace(stage, final)

    monkeypatch.setattr(module.os, "replace", observing_replace)
    atomic_deliver(source, destination)

    assert observations == [(b"old-video", b"new-complete-video")]
    assert destination.read_bytes() == b"new-complete-video"
    assert not list(destination.parent.glob(".final.mp4.partial.*"))


def test_atomic_delivery_preserves_existing_final_when_copy_fails(tmp_path, monkeypatch):
    source = _media(tmp_path / "source.mp4", b"new-video")
    destination = _media(tmp_path / "project" / "final.mp4", b"old-video")
    import easel.moneyprinterturbo as module

    def failing_copy(*_args, **_kwargs):
        raise OSError("simulated copy failure")

    monkeypatch.setattr(module.shutil, "copyfileobj", failing_copy)
    with pytest.raises(MoneyPrinterTurboError, match="deliver"):
        atomic_deliver(source, destination)

    assert destination.read_bytes() == b"old-video"
    assert not list(destination.parent.glob(".final.mp4.partial.*"))


def test_dry_run_returns_redacted_argv_without_launching(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("dry-run launched a subprocess")

    bridge = MoneyPrinterTurboBridge(
        paths,
        runner=must_not_run,
        task_id_factory=lambda: "dry-task",
        secret_values=("Three quiet places to visit this fall",),
    )
    command = bridge.run(_request(), dry_run=True)

    assert isinstance(command, list)
    assert "[REDACTED]" in command
    assert "Three quiet places to visit this fall" not in command


def test_bridge_writes_managed_config_runs_once_and_delivers_brief(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def successful_runner(command, **kwargs):
        calls.append((command, kwargs))
        video = _media(paths.task_root / "fixed-task" / "final.mp4", b"finished-video")
        return subprocess.CompletedProcess(
            command,
            0,
            _result_payload("fixed-task", video, ["fallback preserve-pexels"]),
            "",
        )

    bridge = MoneyPrinterTurboBridge(
        paths,
        runner=successful_runner,
        task_id_factory=lambda: "fixed-task",
    )
    result = bridge.run(_request())

    assert result == BridgeResult(
        status="completed",
        task_id="fixed-task",
        final_path=paths.root / "outputs" / "Autumn city guide" / "final.mp4",
        warnings=("fallback [REDACTED]",),
    )
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert kwargs == {
        "cwd": paths.source,
        "capture_output": True,
        "text": True,
        "shell": False,
        "timeout": 1200,
    }
    assert command[command.index("--task-id") + 1] == "fixed-task"
    assert result.final_path.read_bytes() == b"finished-video"
    assert 'listen_host = "127.0.0.1"' in paths.config.read_text(encoding="utf-8")
    brief = (result.final_path.parent / "brief.md").read_text(encoding="utf-8")
    assert "v1.3.7" in brief
    assert "9:16" in brief
    assert "pexels" in brief
    assert "fallback" in brief
    assert "local-easel" not in brief
    assert "preserve-pexels" not in brief


def test_single_job_lock_rejects_concurrent_run(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    paths.lock.touch()

    with paths.lock.open("a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        bridge = MoneyPrinterTurboBridge(paths, runner=lambda *_a, **_k: None)
        with pytest.raises(MoneyPrinterTurboError, match="already running"):
            bridge.run(_request())


def test_nonzero_exit_reports_bounded_redacted_error(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    secret = "preserve-pexels"
    calls = 0

    def failing_runner(command, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 9, "", (secret + " failure ") * 200)

    bridge = MoneyPrinterTurboBridge(paths, runner=failing_runner, task_id_factory=lambda: "failed-task")
    with pytest.raises(MoneyPrinterTurboError) as raised:
        bridge.run(_request())

    message = str(raised.value)
    assert calls == 1
    assert secret not in message
    assert "[REDACTED]" in message
    assert len(message) <= 1_100


def test_safe_timeout_is_not_retried(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    calls = 0

    def timing_out(command, **_kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, 1200)

    bridge = MoneyPrinterTurboBridge(paths, runner=timing_out, task_id_factory=lambda: "timeout-task")
    with pytest.raises(MoneyPrinterTurboError, match="timed out") as raised:
        bridge.run(_request(source="pexels"))
    assert "ambiguous" not in str(raised.value).lower()
    assert calls == 1


def test_paid_timeout_is_ambiguous_and_is_not_retried(tmp_path, monkeypatch):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    calls = 0

    def timing_out(command, **_kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, 1200)

    bridge = MoneyPrinterTurboBridge(paths, runner=timing_out, task_id_factory=lambda: "paid-timeout")
    with pytest.raises(MoneyPrinterTurboError, match="ambiguous"):
        bridge.run(_request(source="ofox", confirm_ofox_charge=True))
    assert calls == 1


def _load_bridge_cli():
    path = ROOT / "skills" / "openclaw" / "moneyprinterturbo-video" / "scripts" / "mpt_bridge.py"
    spec = importlib.util.spec_from_file_location("mpt_bridge_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bridge_cli_configure_run_and_dry_run_contract(tmp_path, monkeypatch, capsys):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    module = _load_bridge_cli()
    invocations: list[tuple[str, bool]] = []
    constructors: list[dict[str, str]] = []
    monkeypatch.setenv("EASEL_MPT_LLM_BASE_URL", "http://127.0.0.1:18081/v1")
    monkeypatch.setenv("EASEL_MPT_LLM_MODEL", "test-qwen")

    class FakeBridge:
        def __init__(self, supplied_paths, **kwargs):
            assert supplied_paths == paths
            constructors.append(kwargs)

        def run(self, request, *, dry_run=False):
            invocations.append((request.project_name, dry_run))
            if dry_run:
                return ["python", "cli.py", "--video-subject", "topic"]
            return BridgeResult("completed", "cli-task", request_path, ())

    request_path = paths.root / "outputs" / "CLI project" / "final.mp4"
    monkeypatch.setattr(module, "MoneyPrinterTurboBridge", FakeBridge)

    common = [
        "--root", str(paths.root), "--project", "CLI project", "--aspect", "1:1",
        "--source", "pexels", "--topic", "topic",
    ]
    assert module.main(["dry-run", *common]) == 0
    dry_payload = json.loads(capsys.readouterr().out)
    assert dry_payload["status"] == "dry-run"
    assert module.main(["run", *common]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload == {
        "status": "completed",
        "task_id": "cli-task",
        "final_path": str(request_path),
        "warnings": [],
    }
    assert invocations == [("CLI project", True), ("CLI project", False)]
    assert constructors == [
        {"llm_base_url": "http://127.0.0.1:18081/v1", "llm_model": "test-qwen"},
        {"llm_base_url": "http://127.0.0.1:18081/v1", "llm_model": "test-qwen"},
    ]

    assert module.main(["configure", "--root", str(paths.root)]) == 0
    configure_payload = json.loads(capsys.readouterr().out)
    assert configure_payload == {"status": "configured"}


def test_bridge_cli_prints_only_small_result_json(tmp_path, monkeypatch, capsys):
    paths = _paths(tmp_path, monkeypatch)
    _runtime(paths)
    module = _load_bridge_cli()

    class FakeBridge:
        def __init__(self, _paths, **_kwargs):
            pass

        def run(self, request, *, dry_run=False):
            return BridgeResult("completed", "small-task", request_path, ("one warning",))

    request_path = paths.root / "outputs" / "Compact result" / "final.mp4"
    monkeypatch.setattr(module, "MoneyPrinterTurboBridge", FakeBridge)
    exit_code = module.main(
        [
            "run", "--root", str(paths.root), "--project", "Compact result",
            "--aspect", "16:9", "--source", "pixabay", "--script", "script",
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 0
    assert not output.err
    assert len(output.out) < 500
    assert json.loads(output.out)["task_id"] == "small-task"
