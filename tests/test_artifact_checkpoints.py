"""Durable reuse is allowed only for verified local step outputs."""
from pathlib import Path
import subprocess
import sys
import time

import pytest

from skills.shared.scripts import artifact_checkpoints as checkpoints


def test_reopen_reuses_output_but_input_or_artifact_change_recomputes(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"first")
    signature = lambda: checkpoints.fingerprint({"size": 10}, [source])
    calls = []
    def produce(path):
        calls.append(path)
        path.write_bytes(source.read_bytes() + b" rendered")
    directory = tmp_path / "steps"
    with checkpoints.ArtifactCheckpoints(directory) as store:
        original, reused = store.run("shot", signature, produce)
        assert not reused and original.read_bytes() == b"first rendered"
    with checkpoints.ArtifactCheckpoints(directory) as store:
        assert store.run("shot", signature, produce) == (original, True)
        source.write_bytes(b"other")  # Same length; mtime/size are not identity.
        changed, reused = store.run("shot", signature, produce)
        assert not reused and changed != original
        changed.write_bytes(b"damaged")
        repaired, reused = store.run("shot", signature, produce)
        assert not reused and repaired.read_bytes() == b"other rendered"
        repaired.unlink()
        assert not store.run("shot", signature, produce)[1]
    assert len(calls) == 4


@pytest.mark.parametrize("failure", ["exception", "empty", "changed-input"])
def test_incomplete_step_never_gets_a_receipt(tmp_path, failure):
    source = tmp_path / "input"
    source.write_bytes(b"original")
    signature = lambda: checkpoints.fingerprint({}, [source])
    def produce(path):
        if failure == "empty":
            return
        path.write_bytes(b"partial")
        if failure == "exception":
            raise RuntimeError("render interrupted")
        source.write_bytes(b"changed")
    with checkpoints.ArtifactCheckpoints(tmp_path / "steps") as store:
        with pytest.raises(RuntimeError):
            store.run("shot", signature, produce)
    assert not (tmp_path / "steps" / "checkpoints.json").exists()


@pytest.mark.parametrize("content", ["{", '{"schema":99,"steps":{}}',
    '{"schema":true,"steps":{}}', '{"schema":1,"steps":{"shot":{"artifact":"../outside"}}}'])
def test_invalid_manifest_is_preserved_and_releases_lock(tmp_path, content):
    path = tmp_path / "checkpoints.json"
    path.write_text(content, encoding="utf-8")
    for _ in range(2):
        with pytest.raises(checkpoints.CheckpointError):
            with checkpoints.ArtifactCheckpoints(tmp_path):
                pytest.fail("invalid manifest accepted")
        assert path.read_text(encoding="utf-8") == content
    path.unlink()
    with checkpoints.ArtifactCheckpoints(tmp_path):
        pass


def test_failed_manifest_replace_keeps_old_committed_receipt(tmp_path, monkeypatch):
    signature = lambda: checkpoints.fingerprint({"revision": 1})
    with checkpoints.ArtifactCheckpoints(tmp_path) as store:
        old, _ = store.run("shot", signature, lambda p: p.write_bytes(b"old"))
        before = (tmp_path / "checkpoints.json").read_bytes()
        replace = checkpoints.os.replace
        def fail(source, target):
            if Path(target).name == "checkpoints.json":
                raise OSError("injected commit failure")
            return replace(source, target)
        monkeypatch.setattr(checkpoints.os, "replace", fail)
        with pytest.raises(OSError):
            store.run("shot", lambda: checkpoints.fingerprint({"revision": 2}), lambda p: p.write_bytes(b"new"))
        assert (tmp_path / "checkpoints.json").read_bytes() == before
        assert store.run("shot", signature, lambda p: pytest.fail("old receipt was lost")) == (old, True)


def test_atomic_delivery_preserves_existing_result_on_failure(tmp_path):
    target = tmp_path / "final.mp4"
    target.write_bytes(b"previous final")
    with pytest.raises(RuntimeError):
        with checkpoints.atomic_output(target) as temporary:
            temporary.write_bytes(b"half new final")
            raise RuntimeError("render failed")
    assert target.read_bytes() == b"previous final"
    with checkpoints.atomic_output(target) as temporary:
        temporary.write_bytes(b"new final")
    assert target.read_bytes() == b"new final"


def test_parameters_and_file_bytes_both_participate_in_identity(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"input")
    base = checkpoints.fingerprint({"duration": 3, "motion": "static"}, [source])
    assert base == checkpoints.fingerprint({"motion": "static", "duration": 3}, [source])
    assert base != checkpoints.fingerprint({"duration": 4, "motion": "static"}, [source])
    with pytest.raises(ValueError):
        checkpoints.fingerprint({"duration": float("nan")})


@pytest.mark.parametrize("phase", ["before-commit", "after-commit"])
def test_process_death_releases_lock_and_only_committed_steps_are_reused(tmp_path, phase):
    child = r'''
import sys, time
from pathlib import Path
from skills.shared.scripts.artifact_checkpoints import ArtifactCheckpoints, fingerprint
directory, ready = Path(sys.argv[1]), Path(sys.argv[2])
def produce(path):
    path.write_bytes(b"rendered locally")
    if sys.argv[3] == "before-commit":
        ready.write_text("ready")
        while True: time.sleep(1)
with ArtifactCheckpoints(directory) as store:
    store.run("shot", lambda: fingerprint({}), produce)
    ready.write_text("ready")
    while True: time.sleep(1)
'''
    ready = tmp_path / "ready"
    directory = tmp_path / "steps"
    process = subprocess.Popen([sys.executable, "-c", child, str(directory), str(ready), phase],
                               cwd=Path(__file__).resolve().parents[1],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child did not reach the crash boundary"
        with pytest.raises(checkpoints.CheckpointError, match="lock"):
            with checkpoints.ArtifactCheckpoints(directory):
                pytest.fail("second process stole the writer lock")
        process.terminate()
        process.wait(timeout=5)
        calls = []
        def produce(path):
            calls.append(path)
            path.write_bytes(b"rendered locally")
        with checkpoints.ArtifactCheckpoints(directory) as store:
            output, reused = store.run("shot", lambda: checkpoints.fingerprint({}), produce)
            assert reused == (phase == "after-commit")
            assert len(calls) == (0 if reused else 1)
            assert output.read_bytes() == b"rendered locally"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_unlocked_or_invalid_step_cannot_write(tmp_path):
    store = checkpoints.ArtifactCheckpoints(tmp_path)
    with pytest.raises(checkpoints.CheckpointError, match="lock"):
        store.run("shot", lambda: checkpoints.fingerprint({}), lambda p: None)
    with store:
        for key in ("../escape", "a/b", "CON", ""):
            with pytest.raises(ValueError):
                store.run(key, lambda: checkpoints.fingerprint({}), lambda p: None)
