import importlib.util
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/builtin/auto-short-video/scripts/assemble.py"


@pytest.fixture
def assemble():
    spec = importlib.util.spec_from_file_location("assemble_subtitle_regressions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("font_size", [54, 84, 96])
def test_chinese_closing_punctuation_never_starts_line(assemble, font_size):
    caption = "胶原蛋白，到底早上喝，还是晚上喝？"
    lines = assemble.wrap_caption(caption, 950 / font_size * 0.94)
    assert "".join(lines) == caption
    assert all(line[0] not in "，。！？；：、）】》”" for line in lines)
    assert all(sum(assemble._char_units(character) for character in line) <= 950 / font_size * 0.94
               for line in lines)


@pytest.mark.parametrize("font_size", [54, 84, 96])
def test_english_space_at_wrap_boundary_is_preserved(assemble, font_size):
    caption = "Collagen, morning or night?"
    lines = assemble.wrap_caption(caption, 950 / font_size * 0.94)
    assert " ".join(lines) == caption


@pytest.mark.parametrize("caption,max_units", [
    ("hello world", 5), ("你好，世界！", 3), ("甲乙（丙丁）戊", 4),
    ("alpha beta gamma delta", 4), ("abcdefghij", 2),
    ("第一句\\N第二句", 4), ("", 5),
])
def test_wrapping_keeps_text_and_available_width(assemble, caption, max_units):
    lines = assemble.wrap_caption(caption, max_units)
    assert "".join(lines).replace(" ", "") == caption.replace("\\N", "").replace(" ", "")
    assert all(line and line == line.strip() for line in lines)
    assert all(line[0] not in "，。！？；：、）】》”" for line in lines)
    assert all(line[-1] not in "（【《“" for line in lines)
    assert all(sum(assemble._char_units(character) for character in line) <= max_units
               for line in lines)


def noto_font_available():
    if not shutil.which("fc-match"):
        return False
    result = subprocess.run(["fc-match", "-f", "%{family}", "Noto Sans CJK SC"],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and "Noto Sans CJK SC" in result.stdout


def test_font_measurement_falls_back_without_fontconfig(assemble, monkeypatch, tmp_path):
    monkeypatch.setattr(assemble.shutil, "which", lambda tool: None)
    assert assemble._font_width_units(assemble.DEFAULT_SUB_FONT) is None
    source = tmp_path / "input.srt"
    output = tmp_path / "output.ass"
    source.write_text("1\n00:00:00,000 --> 00:00:01,000\nCollagen, morning or night?\n", encoding="utf-8")
    assemble._srt_to_ass(source, output, 1080, 1920, font_size=96)
    event = next(line for line in output.read_text(encoding="utf-8").splitlines()
                 if line.startswith("Dialogue:"))
    assert event.split(",", 9)[-1].replace("\\N", " ") == "Collagen, morning or night?"


@pytest.mark.skipif(not noto_font_available(), reason="font measurement requires installed Noto CJK")
def test_measured_width_distinguishes_glyphs_and_preserves_more_than_two_lines(assemble, tmp_path):
    measure = assemble._font_width_units(assemble.DEFAULT_SUB_FONT)
    assert measure is not None
    assert measure("WWW") > measure("iii")
    source = tmp_path / "input.srt"
    output = tmp_path / "output.ass"
    caption = "这是长字幕，用于确认原来的多行能力仍然保留。" * 5
    source.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{caption}\n", encoding="utf-8")
    assemble._srt_to_ass(source, output, 1080, 1920, font_size=96)
    event = next(line for line in output.read_text(encoding="utf-8").splitlines()
                 if line.startswith("Dialogue:"))
    lines = event.split(",", 9)[-1].split("\\N")
    assert len(lines) > 2
    assert "".join(lines) == caption
    assert all(measure(line) <= 950 / 96 * 0.94 for line in lines)
    assert all(line[0] not in "，。！？；：、）】》”" for line in lines)


@pytest.mark.skipif(not noto_font_available(), reason="font measurement requires installed Noto CJK")
@pytest.mark.parametrize("font_size", [54, 84, 96])
def test_ass_width_uses_font_metrics_not_font_line_height(assemble, tmp_path, font_size):
    caption = "这是测试字幕真实字体宽度的一段中文共二十四字"
    source = tmp_path / "input.srt"
    output = tmp_path / "output.ass"
    source.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{caption}\n", encoding="utf-8")
    assemble._srt_to_ass(source, output, 1080, 1920, font_size=font_size)
    event = next(line for line in output.read_text(encoding="utf-8").splitlines()
                 if line.startswith("Dialogue:"))
    lines = event.split(",", 9)[-1].split("\\N")
    assert "".join(lines) == caption
    assert len(lines) == (1 if font_size == 54 else 2)


@pytest.mark.skipif(not (shutil.which("ffmpeg") and noto_font_available()),
                    reason="subtitle render requires ffmpeg/libass and installed Noto CJK")
def test_real_libass_render_fills_width_without_extra_lines(assemble, tmp_path):
    caption = "这是用于测试字幕真实字体宽度的一段中文共二十四字"
    source = tmp_path / "input.srt"
    output = tmp_path / "output.ass"
    source.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{caption}\n", encoding="utf-8")
    assemble._srt_to_ass(source, output, 1080, 1920, font_size=96)
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-filter_threads", "1", "-f", "lavfi", "-i",
        "color=black:size=1080x1920:duration=1", "-vf", f"ass={output}",
        "-frames:v", "1", "-threads", "1", "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ], check=True, capture_output=True, timeout=20)
    pixels = np.frombuffer(result.stdout, dtype=np.uint8).reshape(1920, 1080)
    rows, columns = np.nonzero(pixels > 180)
    assert len(rows)
    assert columns.min() >= 65 and columns.max() <= 1015
    assert columns.max() - columns.min() > 950 * 0.8
    assert rows.max() - rows.min() < 96 * 2.1
