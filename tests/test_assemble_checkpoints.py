"""Exercise assembly recovery without any remote generation or paid API."""
import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def assembly(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "skills/builtin/auto-short-video/scripts/assemble.py"
    spec = importlib.util.spec_from_file_location("checkpoint_assemble", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(module.validate_output_path.__globals__, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(module.validate_output_path.__globals__, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(module, "_check_ffmpeg", lambda: None)
    monkeypatch.setattr(module, "_renderer_identity", lambda: {"version": "test renderer 1"})
    monkeypatch.setattr(module, "_validate_shot_clip", lambda *args: None)
    # Fake ffmpeg only materializes local outputs; cache/locks/files are real.
    monkeypatch.setattr(module, "_run", lambda cmd: Path(cmd[-1]).write_bytes(b"assembled video"))
    root = tmp_path / "outputs" / "恢复演示"
    root.mkdir(parents=True)
    images = [root / "first.png", root / "second.png"]
    for index, image in enumerate(images):
        image.write_bytes(str(index).encode())
    storyboard = root / "storyboard.json"
    storyboard.write_text(json.dumps({"size": "320x568", "shots": [
        {"image": str(p), "duration": 1} for p in images]}), encoding="utf-8")
    args = argparse.Namespace(storyboard=str(storyboard), output=str(root / "final.mp4"), resume=True)
    calls = []
    def render(shot, dur, w, h, output, *a, **kw):
        calls.append(shot["image"])
        output.write_bytes(Path(shot["image"]).read_bytes() + b" rendered")
    monkeypatch.setattr(module, "_make_shot_clip", render)
    return module, args, images, calls


def test_failure_then_resume_skips_completed_shot_and_preserves_previous_final(assembly, monkeypatch):
    module, args, images, calls = assembly
    final = Path(args.output)
    final.write_bytes(b"previous final")
    render = module._make_shot_clip
    def fail_second(shot, dur, w, h, output, *a, **kw):
        if shot["image"] == str(images[1]):
            output.write_bytes(b"half rendered")
            raise RuntimeError("injected interruption")
        return render(shot, dur, w, h, output, *a, **kw)
    monkeypatch.setattr(module, "_make_shot_clip", fail_second)
    with pytest.raises(RuntimeError):
        module.cmd_assemble(args)
    assert calls == [str(images[0])]
    assert final.read_bytes() == b"previous final"
    monkeypatch.setattr(module, "_make_shot_clip", render)
    assert module.cmd_assemble(args) == 0
    assert calls == [str(images[0]), str(images[1])]
    assert final.read_bytes() == b"assembled video"


@pytest.mark.parametrize("change", ["source", "duration", "motion", "size", "renderer", "artifact"])
def test_changed_inputs_or_corrupt_artifact_are_not_reused(assembly, monkeypatch, change):
    module, args, images, calls = assembly
    assert module.cmd_assemble(args) == 0
    calls.clear()
    storyboard = Path(args.storyboard)
    data = json.loads(storyboard.read_text(encoding="utf-8"))
    expected = [str(images[0])]
    if change == "source":
        images[0].write_bytes(b"changed")
    elif change in ("duration", "motion"):
        data["shots"][0][change] = 2 if change == "duration" else "static"
    elif change == "size":
        data["size"] = "640x360"
        expected = list(map(str, images))
    elif change == "renderer":
        monkeypatch.setattr(module, "_renderer_identity", lambda: {"version": "test renderer 2"})
        expected = list(map(str, images))
    else:
        directory = Path(args.output).parent / ".final.mp4.checkpoints"
        manifest = json.loads((directory / "checkpoints.json").read_text(encoding="utf-8"))
        (directory / manifest["steps"]["shot-0000"]["artifact"]).write_bytes(b"damaged")
    storyboard.write_text(json.dumps(data), encoding="utf-8")
    assert module.cmd_assemble(args) == 0
    assert calls == expected


def test_caption_change_reuses_clips_but_regenerates_delivery(assembly, monkeypatch):
    module, args, images, calls = assembly
    module.cmd_assemble(args)
    calls.clear()
    storyboard = Path(args.storyboard)
    data = json.loads(storyboard.read_text(encoding="utf-8"))
    data["shots"][0]["caption"] = "new caption"
    storyboard.write_text(json.dumps(data), encoding="utf-8")
    commands = []
    def render(cmd):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"new subtitled video")
    monkeypatch.setattr(module, "_run", render)
    assert module.cmd_assemble(args) == 0
    assert calls == []
    assert any("-vf" in cmd for cmd in commands)
    assert Path(args.output).read_bytes() == b"new subtitled video"


def test_final_render_failure_preserves_delivered_file_and_completed_clips(assembly, monkeypatch):
    module, args, images, calls = assembly
    data = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))
    data["shots"][0]["caption"] = "caption"
    Path(args.storyboard).write_text(json.dumps(data), encoding="utf-8")
    Path(args.output).write_bytes(b"old delivered video")
    original = module._run
    def fail(cmd):
        if "-vf" in cmd:
            Path(cmd[-1]).write_bytes(b"incomplete subtitle render")
            raise RuntimeError("interrupted final render")
        original(cmd)
    monkeypatch.setattr(module, "_run", fail)
    with pytest.raises(RuntimeError):
        module.cmd_assemble(args)
    assert Path(args.output).read_bytes() == b"old delivered video"
    calls.clear()
    monkeypatch.setattr(module, "_run", original)
    assert module.cmd_assemble(args) == 0
    assert calls == []


def test_resume_is_opt_in_and_output_path_must_stay_in_project(assembly):
    module, args, images, calls = assembly
    args.resume = False
    module.cmd_assemble(args)
    module.cmd_assemble(args)
    assert len(calls) == 4
    assert not (Path(args.output).parent / ".final.mp4.checkpoints").exists()
    args.resume = True
    args.output = str(Path(args.output).parents[2] / "outside.mp4")
    calls.clear()
    with pytest.raises(ValueError):
        module.cmd_assemble(args)
    assert not calls


def test_competing_assembly_fails_without_touching_output(assembly):
    module, args, images, calls = assembly
    Path(args.output).write_bytes(b"old final")
    directory = Path(args.output).parent / ".final.mp4.checkpoints"
    with module.ArtifactCheckpoints(directory):
        with pytest.raises(module.CheckpointError, match="lock"):
            module.cmd_assemble(args)
    assert not calls and Path(args.output).read_bytes() == b"old final"


def test_invalid_render_never_commits_checkpoint_or_replaces_delivery(assembly, monkeypatch):
    module, args, images, calls = assembly
    final = Path(args.output)
    final.write_bytes(b"old complete delivery")
    def reject(*args):
        raise module.CheckpointError("incomplete video")
    monkeypatch.setattr(module, "_validate_shot_clip", reject)
    with pytest.raises(module.CheckpointError, match="incomplete"):
        module.cmd_assemble(args)
    assert final.read_bytes() == b"old complete delivery"
    assert not (final.parent / ".final.mp4.checkpoints" / "checkpoints.json").exists()


def test_symlink_swap_renders_the_same_source_that_was_fingerprinted(assembly, monkeypatch):
    module, args, images, calls = assembly
    link = images[0].with_name("linked.png")
    try:
        link.symlink_to(images[0])
    except OSError:
        pytest.skip("symlink creation is unavailable")
    storyboard = Path(args.storyboard)
    data = json.loads(storyboard.read_text(encoding="utf-8"))
    data["shots"] = [{"image": str(link), "duration": 1}]
    storyboard.write_text(json.dumps(data), encoding="utf-8")
    rendered = []
    def render(shot, duration, width, height, output, *args, **kwargs):
        link.unlink()
        link.symlink_to(images[1])
        content = Path(shot["image"]).read_bytes()
        rendered.append(content)
        output.write_bytes(content + b" rendered")
    monkeypatch.setattr(module, "_make_shot_clip", render)
    assert module.cmd_assemble(args) == 0
    assert rendered == [images[0].read_bytes()]
    link.unlink()
    link.symlink_to(images[0])
    assert module.cmd_assemble(args) == 0
    assert rendered == [images[0].read_bytes()]


@pytest.mark.parametrize("invalid", ["short", "missing-stream", "wrong-size", "decode"])
def test_shot_validation_rejects_invalid_video_properties(tmp_path, monkeypatch, invalid):
    path = Path(__file__).resolve().parents[1] / "skills/builtin/auto-short-video/scripts/assemble.py"
    spec = importlib.util.spec_from_file_location("validation_assemble", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stream = {"duration": "2", "width": 320, "height": 568}
    if invalid == "short":
        stream["duration"] = "0.7"
    if invalid == "wrong-size":
        stream["width"] = 160
    payload = {"streams": [] if invalid == "missing-stream" else [stream]}
    def run(command, **kwargs):
        if command[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="decode error")
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(module.CheckpointError):
        module._validate_shot_clip(tmp_path / "clip.mp4", 2, 320, 568)
