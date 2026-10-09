from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from easel.moneyprinterturbo import (
    MoneyPrinterTurboError,
    MoneyPrinterTurboPaths,
    MoneyPrinterTurboRequest,
    build_command,
    prepare_request,
    render_managed_config,
)
from skills.shared.scripts import output_paths


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
