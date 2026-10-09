"""Safe Easel adapter for the pinned MoneyPrinterTurbo runtime."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from skills.shared.scripts import output_paths


SAFE_SOURCES = frozenset({"local", "pexels", "pixabay", "coverr"})
PAID_SOURCE_CONFIRMATIONS = {
    "volcengine_seedance": "confirm_seedance_charge",
    "ofox": "confirm_ofox_charge",
    "metaso_minimax": "confirm_metaso_minimax_charge",
}
ALL_SOURCES = SAFE_SOURCES | PAID_SOURCE_CONFIRMATIONS.keys()
MEDIA_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".mkv", ".avi", ".webm", ".jpg", ".jpeg", ".png", ".webp"}
)
ASPECTS = frozenset({"9:16", "16:9", "1:1"})


class MoneyPrinterTurboError(RuntimeError):
    """Raised when an integration request or runtime result is unsafe."""


@dataclass(frozen=True)
class MoneyPrinterTurboPaths:
    root: Path
    source: Path
    state: Path
    config: Path
    storage: Path
    task_root: Path
    lock: Path

    @classmethod
    def for_root(cls, root: Path) -> "MoneyPrinterTurboPaths":
        resolved = Path(root).expanduser().resolve()
        state = resolved / ".state" / "moneyprinterturbo"
        storage = state / "storage"
        return cls(
            root=resolved,
            source=resolved / ".tools" / "moneyprinterturbo" / "source",
            state=state,
            config=state / "config.toml",
            storage=storage,
            task_root=storage / "tasks",
            lock=state / "bridge.lock",
        )


@dataclass(frozen=True)
class MoneyPrinterTurboRequest:
    project_name: str
    aspect: str
    source: str
    topic: str | None = None
    script: str | None = None
    materials: tuple[Path, ...] = ()
    confirm_seedance_charge: bool = False
    confirm_ofox_charge: bool = False
    confirm_metaso_minimax_charge: bool = False


@dataclass(frozen=True)
class PreparedMoneyPrinterTurboRequest:
    project_name: str
    aspect: str
    source: str
    topic: str | None
    script: str | None
    materials: tuple[Path, ...]
    output_dir: Path
    final_path: Path
    confirm_seedance_charge: bool
    confirm_ofox_charge: bool
    confirm_metaso_minimax_charge: bool


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _has_symlink_component(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _prepare_materials(
    paths: MoneyPrinterTurboPaths,
    request: MoneyPrinterTurboRequest,
    output_dir: Path,
) -> tuple[Path, ...]:
    if request.source != "local":
        if request.materials:
            raise MoneyPrinterTurboError("materials are allowed only with the local source")
        return ()
    if not request.materials:
        raise MoneyPrinterTurboError("the local source requires at least one material")

    root = paths.root.resolve()
    allowed_roots = (
        (root / "assets").resolve(),
        (output_dir / "assets").resolve(),
    )
    prepared: list[Path] = []
    for supplied in request.materials:
        candidate = Path(supplied).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        if _has_symlink_component(candidate, root):
            raise MoneyPrinterTurboError(f"material paths may not contain a symlink: {candidate}")
        if not candidate.exists() or not candidate.is_file():
            raise MoneyPrinterTurboError(f"material is missing or not a file: {candidate}")
        resolved = candidate.resolve()
        if not any(_is_within(resolved, allowed) for allowed in allowed_roots):
            raise MoneyPrinterTurboError("material is outside the allowed assets directories")
        if resolved.suffix.casefold() not in MEDIA_EXTENSIONS:
            raise MoneyPrinterTurboError(f"unsupported material type: {resolved.suffix or '(none)'}")
        if resolved.stat().st_size <= 0:
            raise MoneyPrinterTurboError(f"material is empty: {resolved}")
        prepared.append(resolved)
    return tuple(prepared)


def _validate_confirmation(request: MoneyPrinterTurboRequest) -> None:
    confirmations = {
        "confirm_seedance_charge": request.confirm_seedance_charge,
        "confirm_ofox_charge": request.confirm_ofox_charge,
        "confirm_metaso_minimax_charge": request.confirm_metaso_minimax_charge,
    }
    expected = PAID_SOURCE_CONFIRMATIONS.get(request.source)
    enabled = {name for name, value in confirmations.items() if value}
    if expected is None:
        if enabled:
            raise MoneyPrinterTurboError("paid confirmation does not match the selected source")
        return
    if enabled != {expected}:
        raise MoneyPrinterTurboError(
            f"the selected paid source requires only its matching confirmation: {expected}"
        )


def prepare_request(
    paths: MoneyPrinterTurboPaths,
    request: MoneyPrinterTurboRequest,
) -> PreparedMoneyPrinterTurboRequest:
    topic = request.topic.strip() if request.topic and request.topic.strip() else None
    script = request.script.strip() if request.script and request.script.strip() else None
    if (topic is None) == (script is None):
        raise MoneyPrinterTurboError("provide exactly one non-empty topic or script")
    if request.aspect not in ASPECTS:
        raise MoneyPrinterTurboError("aspect must be explicitly set to 9:16, 16:9, or 1:1")
    if request.source not in ALL_SOURCES:
        raise MoneyPrinterTurboError(f"unsupported material source: {request.source}")

    project_name = request.project_name.strip()
    if not project_name or Path(project_name).name != project_name or project_name in {".", ".."}:
        raise MoneyPrinterTurboError("project name must be one human-readable directory name")
    try:
        output_dir = output_paths.validate_project_dir(
            paths.root / "outputs" / project_name,
            create=False,
        )
    except (ValueError, OSError) as exc:
        raise MoneyPrinterTurboError(f"invalid project name: {exc}") from exc
    expected_output = (paths.root / "outputs" / project_name).resolve()
    if output_dir.resolve() != expected_output:
        raise MoneyPrinterTurboError("project destination does not match this Easel root")

    _validate_confirmation(request)
    materials = _prepare_materials(paths, request, output_dir)
    return PreparedMoneyPrinterTurboRequest(
        project_name=project_name,
        aspect=request.aspect,
        source=request.source,
        topic=topic,
        script=script,
        materials=materials,
        output_dir=output_dir,
        final_path=output_dir / "final.mp4",
        confirm_seedance_charge=request.confirm_seedance_charge,
        confirm_ofox_charge=request.confirm_ofox_charge,
        confirm_metaso_minimax_charge=request.confirm_metaso_minimax_charge,
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_managed_config(
    example_text: str,
    *,
    llm_base_url: str,
    llm_model: str,
) -> str:
    if not llm_base_url.strip() or not llm_model.strip():
        raise MoneyPrinterTurboError("the local Qwen base URL and model must be non-empty")
    owned = {
        None: {"listen_host": _toml_string("127.0.0.1")},
        "app": {
            "llm_provider": _toml_string("openai"),
            "openai_api_key": _toml_string("local-easel"),
            "openai_base_url": _toml_string(llm_base_url.strip()),
            "openai_model_name": _toml_string(llm_model.strip()),
            "upload_post_enabled": "false",
            "upload_post_auto_upload": "false",
        },
    }
    seen: dict[str | None, set[str]] = {None: set(), "app": set()}
    output: list[str] = []
    section: str | None = None
    top_flushed = False
    app_flushed = False

    def append_missing(target: str | None) -> None:
        for key, value in owned[target].items():
            if key not in seen[target]:
                output.append(f"{key} = {value}")

    for line in example_text.splitlines():
        section_match = re.match(r"^\s*\[([^]]+)]\s*(?:#.*)?$", line)
        if section_match:
            if section is None and not top_flushed:
                append_missing(None)
                top_flushed = True
            if section == "app" and not app_flushed:
                append_missing("app")
                app_flushed = True
            section = section_match.group(1).strip()
            output.append(line)
            continue

        key_match = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        key = key_match.group(1) if key_match else None
        if section in owned and key in owned[section]:
            output.append(f"{key} = {owned[section][key]}")
            seen[section].add(key)
        else:
            output.append(line)

    if not top_flushed:
        append_missing(None)
    if section == "app" and not app_flushed:
        append_missing("app")
    if not any(re.match(r"^\s*\[app]\s*(?:#.*)?$", line) for line in output):
        output.extend(["", "[app]"])
        append_missing("app")
    return "\n".join(output).rstrip() + "\n"


def configure_managed_runtime(
    paths: MoneyPrinterTurboPaths,
    *,
    llm_base_url: str,
    llm_model: str,
) -> None:
    if paths.config.is_symlink() or not paths.config.is_file():
        raise MoneyPrinterTurboError("managed MoneyPrinterTurbo config is missing or unsafe")
    rendered = render_managed_config(
        paths.config.read_text(encoding="utf-8"),
        llm_base_url=llm_base_url,
        llm_model=llm_model,
    )
    stage_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=paths.config.parent,
            prefix=".config.toml.partial.",
            delete=False,
        ) as stage:
            stage_path = Path(stage.name)
            os.chmod(stage.name, 0o600)
            stage.write(rendered)
            stage.flush()
            os.fsync(stage.fileno())
        os.replace(stage_path, paths.config)
        stage_path = None
    except OSError as exc:
        raise MoneyPrinterTurboError(f"could not update managed config: {exc.strerror or exc}") from exc
    finally:
        if stage_path is not None:
            stage_path.unlink(missing_ok=True)


def build_command(
    paths: MoneyPrinterTurboPaths,
    request: PreparedMoneyPrinterTurboRequest,
    task_id: str,
) -> list[str]:
    if not task_id:
        raise MoneyPrinterTurboError("task ID must be non-empty")
    command = [
        str(paths.source / ".venv" / "bin" / "python"),
        str(paths.source / "cli.py"),
        "--task-id",
        task_id,
    ]
    if request.topic is not None:
        command.extend(["--video-subject", request.topic])
    else:
        command.extend(["--video-script", request.script or ""])
    command.extend(
        [
            "--video-source",
            request.source,
            "--video-aspect",
            request.aspect,
            "--video-count",
            "1",
        ]
    )
    if request.materials:
        command.extend(["--video-materials", ",".join(str(path) for path in request.materials)])
    confirmation_flags = {
        "volcengine_seedance": "--confirm-seedance-charge",
        "ofox": "--confirm-ofox-charge",
        "metaso_minimax": "--confirm-metaso-minimax-charge",
    }
    if request.source in confirmation_flags:
        command.append(confirmation_flags[request.source])
    return command
