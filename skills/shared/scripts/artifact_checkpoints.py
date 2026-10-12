"""Checkpoints for explicitly replayable local file-producing steps.

This is not an executor for arbitrary tools. A step without a committed receipt
may run again after a crash; use only for local computation, never paid requests
or publishing. Callers must validate their output directory before opening it.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid


class CheckpointError(RuntimeError):
    """A checkpoint cannot safely be read, written or reused."""


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(parameters: dict, inputs=()) -> str:
    """Hash all rendering parameters and input bytes, not file timestamps."""
    payload = {"parameters": parameters, "inputs": [file_digest(Path(p)) for p in inputs]}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@contextmanager
def atomic_output(destination: Path):
    """Keep the previous output until a complete, nonempty new file is ready."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".checkpoint-", suffix=destination.suffix,
                                dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        if temporary.is_symlink() or temporary.stat().st_size == 0:
            raise CheckpointError("Step produced no regular, nonempty artifact")
        with temporary.open("r+b") as output:
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
_HASH = re.compile(r"[a-f0-9]{64}")
_ARTIFACT = re.compile(r"[a-f0-9]{32}\.[a-z0-9]{1,10}")


class ArtifactCheckpoints:
    """One exclusive local writer; committed immutable artifacts can be reused.

    Enter the context for the entire workflow, including final delivery. Locks
    are released by the OS on process exit. Do not delete the lock file while
    an executor may be alive. Unreferenced files are never treated as complete.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()
        self._lock = None
        self._manifest = None

    def __enter__(self):
        if self._lock is not None:
            raise CheckpointError("Checkpoint context is already open")
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = (self.directory / "writer.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0, os.SEEK_END)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            lock.close()
            raise CheckpointError("Cannot acquire checkpoint writer lock") from error
        self._lock = lock
        try:
            path = self.directory / "checkpoints.json"
            self._manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
                "schema": 1, "steps": {}}
            self._validate_manifest()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        if self._lock is not None:
            self._lock.close()  # Closing the descriptor releases its OS lock.
            self._lock = None
        self._manifest = None

    def _validate_manifest(self):
        data = self._manifest
        if (not isinstance(data, dict) or type(data.get("schema")) is not int
                or data["schema"] != 1 or not isinstance(data.get("steps"), dict)):
            raise CheckpointError("Unsupported or damaged checkpoint manifest")
        for key, record in data["steps"].items():
            if (not _KEY.fullmatch(key) or not isinstance(record, dict)
                    or any(not isinstance(record.get(field), str)
                           for field in ("fingerprint", "sha256", "artifact"))
                    or not _HASH.fullmatch(record["fingerprint"])
                    or not _HASH.fullmatch(record["sha256"])
                    or not _ARTIFACT.fullmatch(record["artifact"])):
                raise CheckpointError("Damaged checkpoint step record")

    def run(self, key: str, input_fingerprint, produce, *, suffix=".mp4") -> tuple[Path, bool]:
        """Reuse a verified artifact or run one replayable local step.

        input_fingerprint is called before execution and again before commit to
        detect changed inputs. produce writes only the supplied unique path.
        Renderers must close all writers before returning. Never mutate a
        returned artifact. The bool indicates that the artifact was reused.
        """
        if self._lock is None:
            raise CheckpointError("Checkpoint writer lock is not held")
        if not _KEY.fullmatch(key) or not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            raise ValueError("Invalid step key or artifact suffix")
        signature = input_fingerprint()
        if not isinstance(signature, str) or not _HASH.fullmatch(signature):
            raise ValueError("Expected a SHA-256 input fingerprint")
        previous = self._manifest["steps"].get(key)
        if previous and previous["fingerprint"] == signature and previous["artifact"].endswith(suffix):
            artifact = self.directory / previous["artifact"]
            if artifact.is_symlink():
                raise CheckpointError("Checkpoint artifact must not be a symlink")
            if (artifact.is_file() and artifact.stat().st_size
                    and file_digest(artifact) == previous["sha256"]
                    and input_fingerprint() == signature):
                return artifact, True

        artifact = self.directory / (uuid.uuid4().hex + suffix)
        with atomic_output(artifact) as temporary:
            produce(temporary)
            if input_fingerprint() != signature:
                raise CheckpointError("Inputs changed during execution; checkpoint not committed")
        record = {"fingerprint": signature, "artifact": artifact.name, "sha256": file_digest(artifact)}
        updated = {"schema": 1, "steps": {**self._manifest["steps"], key: record}}
        with atomic_output(self.directory / "checkpoints.json") as temporary:
            temporary.write_text(json.dumps(updated, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        self._manifest = updated
        return artifact, False
