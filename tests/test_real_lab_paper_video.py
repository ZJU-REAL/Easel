"""CLI integration checks: use isolated output roots and no external services."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "skills/builtin/real-lab-paper2video-v1/scripts/easel_video.py"


def run(script, root, *args):
    (root / "outputs").mkdir(exist_ok=True)
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          cwd=ROOT, env=dict(os.environ, EASEL_ROOT=str(root), PYTHONUTF8="1"),
                          capture_output=True, text=True, encoding="utf-8", timeout=15)


def test_video_init_keeps_portable_project_and_refuses_overwrite(tmp_path):
    project = tmp_path / "outputs/research-video/assets/paper-video"
    result = run(VIDEO, tmp_path, "init", project)
    assert result.returncode == 0, result.stderr
    assert json.loads((project / "project.json").read_text())["demo"] is True
    assert (project / "scripts/render.cjs").is_file()
    assert (project / "vendor/paper2assets/scripts/extract_pdf.py").is_file()
    (project / "index.html").write_text("user revision")
    result = run(VIDEO, tmp_path, "init", project)
    assert result.returncode != 0
    assert (project / "index.html").read_text() == "user revision"


def test_video_rejects_output_outside_easel_before_rendering(tmp_path):
    result = run(VIDEO, tmp_path, "render", tmp_path / "missing-project", tmp_path / "bad.mp4")
    assert result.returncode != 0
    assert "输出必须位于" in result.stderr
    assert not (tmp_path / "bad.mp4").exists()
