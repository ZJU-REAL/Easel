"""CLI integration checks: use isolated output roots and no external services."""
from pathlib import Path
import json
import os
import subprocess
import sys
import shutil
import pytest

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
    skill = VIDEO.parents[1]
    for relative in ("LICENSE", "NOTICE", "vendor/paper2assets/LICENSE",
                     "vendor/paper2assets/UPSTREAM.json"):
        assert (project / relative).read_bytes() == (skill / relative).read_bytes()
    (project / "index.html").write_text("user revision")
    result = run(VIDEO, tmp_path, "init", project)
    assert result.returncode != 0
    assert (project / "index.html").read_text() == "user revision"


def test_video_rejects_output_outside_easel_before_rendering(tmp_path):
    result = run(VIDEO, tmp_path, "render", tmp_path / "missing-project", tmp_path / "bad.mp4")
    assert result.returncode != 0
    assert "输出必须位于" in result.stderr
    assert not (tmp_path / "bad.mp4").exists()


def test_video_refuses_a_render_report_symlink_outside_outputs(tmp_path):
    dest=tmp_path/'outputs/research-video/final.mp4'
    dest.parent.mkdir(parents=True)
    outside=tmp_path/'private.json'
    outside.write_text('keep',encoding='utf-8')
    try:
        Path(str(dest)+'.render.json').symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation unavailable')
    result=run(VIDEO,tmp_path,'render',tmp_path/'missing-project',dest)
    assert result.returncode!=0 and '输出必须位于' in result.stderr
    assert outside.read_text(encoding='utf-8')=='keep'


def test_crop_refuses_an_external_backup_directory_before_modifying_image(tmp_path):
    from PIL import Image
    image=tmp_path/'outputs/paper/assets/figures/source.png'
    image.parent.mkdir(parents=True)
    Image.new('RGB',(64,64),'white').save(image)
    original=image.read_bytes()
    outside=tmp_path/'private'
    outside.mkdir()
    try:
        (image.parent/'_debug').symlink_to(outside,target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation unavailable')
    result=run(VIDEO,tmp_path,'assets','crop','box',image,'--box','2','2','32','32')
    assert result.returncode!=0
    assert image.read_bytes()==original and not list(outside.iterdir())


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg/FFprobe unavailable')
@pytest.mark.parametrize('silent',[False,True])
def test_verify_decodes_real_frames_and_rejects_silent_audio(tmp_path,silent):
    video=tmp_path/'outputs/paper/final.mp4'
    video.parent.mkdir(parents=True)
    audio='anullsrc=r=48000:cl=mono' if silent else 'sine=frequency=440:sample_rate=48000:duration=1'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc=size=384x216:rate=5:duration=1',
                    '-f','lavfi','-i',audio,'-t','1','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',
                    '-c:a','aac',str(video)],check=True,capture_output=True,timeout=30)
    report=tmp_path/'outputs/paper/qa/report.json'
    result=run(VIDEO,tmp_path,'verify',video,'--report',report,'--duration','1','--fps','5','--width','384','--height','216')
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['decoded_frames']==5
    assert data['technical_pass'] is (not silent)
    assert result.returncode==(1 if silent else 0)
    if silent:
        assert 'Audio track is silent' in data['technical_errors']
