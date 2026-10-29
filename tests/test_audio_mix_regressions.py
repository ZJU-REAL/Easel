import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/shared/scripts/audio_mix.py"
pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="audio regression tests require ffmpeg and ffprobe",
)


@pytest.fixture
def audio_mix():
    spec = importlib.util.spec_from_file_location("audio_mix_regressions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_tone(path, frequency, duration, sample_rate=44100, channels=1):
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        f"sine=frequency={frequency}:duration={duration}:sample_rate={sample_rate}",
        "-ac", str(channels),
        "-threads", "1", str(path),
    ], check=True, capture_output=True, timeout=15)


def samples(path):
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "44100",
        "-f", "f32le", "-",
    ], check=True, capture_output=True, timeout=15)
    return np.frombuffer(result.stdout, dtype="<f4")


def amplitude(signal, frequency, start, end):
    segment = signal[round(start * 44100):round(end * 44100)]
    assert len(segment) == round((end - start) * 44100)
    times = np.arange(len(segment)) / 44100
    return abs(2 * np.mean(segment * np.exp(-2j * np.pi * frequency * times)))


def mix_args(voice, output, **options):
    return argparse.Namespace(**{
        "voice": str(voice) if voice else None, "voice_volume": 1.0,
        "bgm": None, "bgm_volume": 0.25, "bgm_loop_off": False,
        "no_duck": False, "sfx": None, "sfx_at": None, "sfx_volume": 0.8,
        "duration": None, "output": str(output), **options,
    })


@pytest.mark.parametrize("background", ["none", "duck", "no-duck", "sfx"])
def test_ending_fade_preserves_voice(audio_mix, tmp_path, background):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    output = tmp_path / "mixed.wav"
    make_tone(voice, 300, 6)
    make_tone(music, 1000, 2.5 if background != "sfx" else 6)
    options = {}
    if background in {"duck", "no-duck"}:
        options = {"bgm": str(music), "no_duck": background == "no-duck"}
    elif background == "sfx":
        options = {"sfx": [str(music)], "sfx_at": ["0"]}
    assert audio_mix.cmd_mix(mix_args(voice, output, **options)) == 0
    original = samples(voice)
    mixed = samples(output)
    assert audio_mix._dur(output) == pytest.approx(6, abs=0.01)
    assert amplitude(mixed, 300, 5, 6) == pytest.approx(
        amplitude(original, 300, 5, 6), rel=0.01,
    )
    if background != "none":
        assert amplitude(mixed, 1000, 5.8, 6) < amplitude(mixed, 1000, 4, 4.2) * 0.15


def test_duck_control_extends_through_target_and_music_fades(audio_mix, tmp_path, capsys):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    output = tmp_path / "extended.wav"
    make_tone(voice, 300, 6)
    make_tone(music, 1000, 2.5)
    assert audio_mix.cmd_mix(mix_args(voice, output, bgm=str(music), duration=8)) == 0
    assert audio_mix._dur(output) == pytest.approx(8, abs=0.01)
    mixed = samples(output)
    assert amplitude(mixed, 300, 5, 6) == pytest.approx(
        amplitude(samples(voice), 300, 5, 6), rel=0.01,
    )
    assert amplitude(mixed, 1000, 6.3, 6.5) > 0.005
    assert amplitude(mixed, 1000, 7.8, 8) < amplitude(mixed, 1000, 6.3, 6.5) * 0.15
    assert "/ 8.0s /" in capsys.readouterr().out


def test_report_uses_actual_duration_without_padding_voice(audio_mix, tmp_path, capsys):
    voice = tmp_path / "voice.wav"
    output = tmp_path / "voice-only.wav"
    make_tone(voice, 300, 1)
    assert audio_mix.cmd_mix(mix_args(voice, output, duration=3)) == 0
    assert audio_mix._dur(output) == pytest.approx(1, abs=0.01)
    assert "/ 1.0s /" in capsys.readouterr().out


def test_nonlooping_music_is_not_extended_and_explicit_trim_still_works(audio_mix, tmp_path):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    output = tmp_path / "trimmed.wav"
    make_tone(voice, 300, 6)
    make_tone(music, 1000, 1)
    assert audio_mix.cmd_mix(mix_args(
        voice, output, bgm=str(music), bgm_loop_off=True, duration=3,
    )) == 0
    mixed = samples(output)
    assert audio_mix._dur(output) == pytest.approx(3, abs=0.01)
    assert amplitude(mixed, 1000, 2, 2.2) < 0.0001
    assert amplitude(mixed, 300, 2.8, 3) == pytest.approx(
        amplitude(samples(voice), 300, 2.8, 3), rel=0.01,
    )


def test_mixed_sample_rates_and_native_stereo_layout_are_preserved(audio_mix, tmp_path):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    output = tmp_path / "stereo.wav"
    make_tone(voice, 300, 3, sample_rate=48000, channels=2)
    make_tone(music, 1000, 1, sample_rate=22050)
    assert audio_mix.cmd_mix(mix_args(voice, output, bgm=str(music), duration=4)) == 0
    assert audio_mix._channel_layout(output) == "stereo"
    assert audio_mix._dur(output) == pytest.approx(4, abs=0.01)
    assert amplitude(samples(output), 300, 2, 3) == pytest.approx(
        amplitude(samples(voice), 300, 2, 3), rel=0.01,
    )


def test_delayed_sfx_extends_ducked_music_without_explicit_duration(audio_mix, tmp_path):
    voice = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    effect = tmp_path / "effect.wav"
    output = tmp_path / "delayed.wav"
    make_tone(voice, 300, 2)
    make_tone(music, 1000, 1)
    make_tone(effect, 1500, 0.5)
    assert audio_mix.cmd_mix(mix_args(
        voice, output, bgm=str(music), sfx=[str(effect)], sfx_at=["3.5"],
    )) == 0
    assert audio_mix._dur(output) == pytest.approx(4, abs=0.01)
    assert amplitude(samples(output), 1000, 2.8, 3) > 0.005
