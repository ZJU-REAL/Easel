"""Optional real-media check; no generated assets, remote APIs or platform calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="real-media smoke test requires ffmpeg and ffprobe")
@pytest.mark.parametrize("recover_failure", [False, True])
def test_real_image_assembly_reuses_verified_shots(tmp_path, recover_failure):
    script = Path(__file__).resolve().parents[1] / "skills/builtin/auto-short-video/scripts/assemble.py"
    project = tmp_path / "outputs" / "checkpoint-render"
    project.mkdir(parents=True)
    images = [project / "first.ppm", project / "second.ppm"]
    for image, color in zip(images, [bytes([255, 0, 0]), bytes([0, 0, 255])]):
        image.write_bytes(b"P6\n32 32\n255\n" + color * (32 * 32))
    storyboard = project / "storyboard.json"
    storyboard.write_text(json.dumps({"size": "160x160", "image_motion": "static", "shots": [
        {"image": str(image), "duration": 0.2} for image in images]}), encoding="utf-8")
    final = project / "final.mp4"
    env = {**os.environ, "EASEL_ROOT": str(tmp_path), "PYTHONUTF8": "1"}
    command = [sys.executable, str(script), "assemble", "--resume",
               "--storyboard", str(storyboard), "-o", str(final)]
    manifest = project / ".final.mp4.checkpoints" / "checkpoints.json"
    if recover_failure:
        valid_image = images[1].read_bytes()
        images[1].write_bytes(b"invalid image data")
        final.write_bytes(b"previous delivery")
        failed = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)
        assert failed.returncode != 0
        assert final.read_bytes() == b"previous delivery"
        partial = json.loads(manifest.read_text(encoding="utf-8"))
        assert set(partial["steps"]) == {"shot-0000"}
        committed = partial["steps"]["shot-0000"]
        images[1].write_bytes(valid_image)
    first = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert first.returncode == 0, first.stderr
    if recover_failure:
        assert first.stderr.count("已核验并复用分镜") == 1
        assert json.loads(manifest.read_text(encoding="utf-8"))["steps"]["shot-0000"] == committed
    before = manifest.read_bytes()
    second = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert second.returncode == 0, second.stderr
    assert second.stderr.count("已核验并复用分镜") == 2
    assert manifest.read_bytes() == before
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "json", str(final)], capture_output=True, text=True, timeout=10)
    assert probe.returncode == 0, probe.stderr
    assert 0.3 <= float(json.loads(probe.stdout)["format"]["duration"]) <= 0.6


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="real-media smoke test requires ffmpeg and ffprobe")
def test_corrupt_video_preserves_delivery_and_never_commits_shortened_shot(tmp_path):
    script = Path(__file__).resolve().parents[1] / "skills/builtin/auto-short-video/scripts/assemble.py"
    project = tmp_path / "outputs" / "damaged-video"
    project.mkdir(parents=True)
    source = project / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=160x160:rate=30:duration=2", "-c:v", "libx264", "-g", "60",
        "-pix_fmt", "yuv420p", str(source),
    ], check=True, timeout=20)
    valid_source = source.read_bytes()
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v", "-show_packets",
        "-of", "json", str(source),
    ], capture_output=True, text=True, check=True, timeout=10)
    damaged = bytearray(valid_source)
    for packet in json.loads(probe.stdout)["packets"][20:]:
        offset = int(packet["pos"])
        size = int(packet["size"])
        damaged[offset:offset + size] = bytes(size)
    source.write_bytes(damaged)
    storyboard = project / "storyboard.json"
    storyboard.write_text(json.dumps({"size": "160x160", "shots": [
        {"video": str(source), "duration": 2},
    ]}), encoding="utf-8")
    final = project / "final.mp4"
    final.write_bytes(b"previous complete delivery")
    command = [sys.executable, str(script), "assemble", "--resume",
               "--storyboard", str(storyboard), "-o", str(final)]
    env = {**os.environ, "EASEL_ROOT": str(tmp_path), "PYTHONUTF8": "1"}
    manifest = project / ".final.mp4.checkpoints" / "checkpoints.json"
    for _ in range(2):
        result = subprocess.run(command, env=env, capture_output=True, timeout=30)
        assert result.returncode != 0
        assert final.read_bytes() == b"previous complete delivery"
        assert not manifest.exists()
    source.write_bytes(valid_source)
    repaired = subprocess.run(command, env=env, capture_output=True, timeout=30)
    assert repaired.returncode == 0, repaired.stderr
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=duration", "-of", "json", str(final),
    ], capture_output=True, text=True, check=True, timeout=10)
    assert abs(float(json.loads(probe.stdout)["streams"][0]["duration"]) - 2) < 0.07
