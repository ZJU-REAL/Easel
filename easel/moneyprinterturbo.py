"""Safe Easel adapter for the pinned MoneyPrinterTurbo runtime."""

from __future__ import annotations

import json
import fcntl
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

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
MPT_VERSION = "v1.3.7"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8081/v1"
DEFAULT_LLM_MODEL = "qwen38-27b-mythos-agentic"
DEFAULT_TIMEOUT_SECONDS = 20 * 60


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


@dataclass(frozen=True)
class BridgeResult:
    status: str
    task_id: str
    final_path: Path
    warnings: tuple[str, ...]


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


def _warning_text(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise MoneyPrinterTurboError("upstream warnings contain an unsupported value") from exc
    return text[:500]


def parse_cli_result(
    stdout: str,
    *,
    expected_task_id: str,
    task_root: Path,
) -> tuple[Path, tuple[str, ...]]:
    if not stdout.strip():
        raise MoneyPrinterTurboError("MoneyPrinterTurbo returned no result JSON")
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MoneyPrinterTurboError("MoneyPrinterTurbo returned malformed or multiple result JSON") from exc
    if not isinstance(payload, dict):
        raise MoneyPrinterTurboError("MoneyPrinterTurbo result must be one JSON object")
    if payload.get("task_id") != expected_task_id:
        raise MoneyPrinterTurboError("MoneyPrinterTurbo returned a mismatched task ID")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise MoneyPrinterTurboError("MoneyPrinterTurbo result payload is missing")
    videos = result.get("videos")
    if not isinstance(videos, list) or len(videos) != 1 or not isinstance(videos[0], str):
        raise MoneyPrinterTurboError("MoneyPrinterTurbo must return exactly one video path")

    raw_video = Path(videos[0]).expanduser()
    expected_dir = (Path(task_root).resolve() / expected_task_id).resolve()
    if raw_video.is_symlink():
        raise MoneyPrinterTurboError("MoneyPrinterTurbo returned a symlink instead of a final video")
    video = raw_video.resolve() if raw_video.is_absolute() else (expected_dir / raw_video).resolve()
    if not _is_within(video, expected_dir):
        raise MoneyPrinterTurboError("MoneyPrinterTurbo video is outside the matching task directory")
    if video.suffix.casefold() != ".mp4":
        raise MoneyPrinterTurboError("MoneyPrinterTurbo final video is not an MP4")
    if not video.is_file() or video.stat().st_size <= 0:
        raise MoneyPrinterTurboError("MoneyPrinterTurbo final video is missing or empty")

    raw_warnings = result.get("warnings", [])
    if not isinstance(raw_warnings, list):
        raise MoneyPrinterTurboError("MoneyPrinterTurbo warnings must be a list")
    return video, tuple(_warning_text(item) for item in raw_warnings)


def atomic_deliver(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file() or source.stat().st_size <= 0:
        raise MoneyPrinterTurboError("cannot deliver a missing, empty, or symlinked source video")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.partial.",
            delete=False,
        ) as stage, source.open("rb") as source_file:
            stage_path = Path(stage.name)
            shutil.copyfileobj(source_file, stage)
            stage.flush()
            os.fsync(stage.fileno())
        os.replace(stage_path, destination)
        stage_path = None
    except OSError as exc:
        raise MoneyPrinterTurboError(f"could not deliver final video: {exc}") from exc
    finally:
        if stage_path is not None:
            stage_path.unlink(missing_ok=True)


def _configured_secret_values(config: Path) -> tuple[str, ...]:
    try:
        payload = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    secrets: set[str] = set()

    def visit(value: object, key: str = "") -> None:
        sensitive = any(marker in key.casefold() for marker in ("key", "token", "secret", "password"))
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                if sensitive and isinstance(child, str) and len(child) >= 4:
                    secrets.add(child)
        elif sensitive and isinstance(value, str) and len(value) >= 4:
            secrets.add(value)

    visit(payload)
    return tuple(sorted(secrets, key=len, reverse=True))


def _redact(text: str, secrets: Sequence[str]) -> str:
    redacted = text
    for secret in sorted({value for value in secrets if len(value) >= 4}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _write_brief(request: PreparedMoneyPrinterTurboRequest, result: BridgeResult) -> None:
    request.output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MoneyPrinterTurbo delivery",
        "",
        f"- Engine: MoneyPrinterTurbo {MPT_VERSION}",
        f"- Task: {result.task_id}",
        f"- Aspect: {request.aspect}",
        f"- Source: {request.source}",
    ]
    if result.warnings:
        lines.extend(["- Warnings:", *(f"  - {warning}" for warning in result.warnings)])
    else:
        lines.append("- Warnings: none")
    content = "\n".join(lines) + "\n"
    destination = request.output_dir / "brief.md"
    stage_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=request.output_dir,
            prefix=".brief.md.partial.",
            delete=False,
        ) as stage:
            stage_path = Path(stage.name)
            stage.write(content)
            stage.flush()
            os.fsync(stage.fileno())
        os.replace(stage_path, destination)
        stage_path = None
    except OSError as exc:
        raise MoneyPrinterTurboError(f"could not write delivery brief: {exc}") from exc
    finally:
        if stage_path is not None:
            stage_path.unlink(missing_ok=True)


Runner = Callable[..., subprocess.CompletedProcess[str]]


class MoneyPrinterTurboBridge:
    def __init__(
        self,
        paths: MoneyPrinterTurboPaths,
        *,
        runner: Runner = subprocess.run,
        task_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        llm_base_url: str = DEFAULT_LLM_BASE_URL,
        llm_model: str = DEFAULT_LLM_MODEL,
        secret_values: Sequence[str] = (),
    ) -> None:
        self.paths = paths
        self.runner = runner
        self.task_id_factory = task_id_factory
        self.timeout = timeout
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.secret_values = tuple(secret_values)

    def _redacted_command(self, command: Sequence[str]) -> list[str]:
        secrets = (*self.secret_values, *_configured_secret_values(self.paths.config))
        return [_redact(item, secrets) for item in command]

    def _run_once(self, command: list[str], request: PreparedMoneyPrinterTurboRequest):
        try:
            return self.runner(
                command,
                cwd=self.paths.source,
                capture_output=True,
                text=True,
                shell=False,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            if request.source in PAID_SOURCE_CONFIRMATIONS:
                raise MoneyPrinterTurboError(
                    "paid MoneyPrinterTurbo run timed out; provider charge state is ambiguous and the run was not retried"
                ) from exc
            raise MoneyPrinterTurboError("MoneyPrinterTurbo run timed out and was not retried") from exc
        except OSError as exc:
            raise MoneyPrinterTurboError(f"could not launch MoneyPrinterTurbo: {exc}") from exc

    def run(
        self,
        request: MoneyPrinterTurboRequest,
        *,
        dry_run: bool = False,
    ) -> BridgeResult | list[str]:
        prepared = prepare_request(self.paths, request)
        task_id = self.task_id_factory()
        command = build_command(self.paths, prepared, task_id)
        if dry_run:
            return self._redacted_command(command)

        if not self.paths.state.is_dir() or self.paths.state.is_symlink():
            raise MoneyPrinterTurboError("managed MoneyPrinterTurbo state directory is missing or unsafe")
        try:
            lock_file = self.paths.lock.open("a+", encoding="utf-8")
        except OSError as exc:
            raise MoneyPrinterTurboError(f"could not open MoneyPrinterTurbo job lock: {exc}") from exc
        with lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MoneyPrinterTurboError("another MoneyPrinterTurbo job is already running") from exc

            configure_managed_runtime(
                self.paths,
                llm_base_url=self.llm_base_url,
                llm_model=self.llm_model,
            )
            completed = self._run_once(command, prepared)
            secrets = (*self.secret_values, *_configured_secret_values(self.paths.config))
            if completed.returncode != 0:
                excerpt = _redact((completed.stderr or completed.stdout or "upstream failure").strip(), secrets)
                excerpt = excerpt[:1_000]
                raise MoneyPrinterTurboError(
                    f"MoneyPrinterTurbo exited with status {completed.returncode}: {excerpt}"
                )
            video, warnings = parse_cli_result(
                completed.stdout,
                expected_task_id=task_id,
                task_root=self.paths.task_root,
            )
            warnings = tuple(_redact(warning, secrets)[:500] for warning in warnings)
            atomic_deliver(video, prepared.final_path)
            result = BridgeResult(
                status="completed",
                task_id=task_id,
                final_path=prepared.final_path,
                warnings=warnings,
            )
            _write_brief(prepared, result)
            return result
