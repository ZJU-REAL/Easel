from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "openclaw" / "moneyprinterturbo-video" / "SKILL.md"
META = ROOT / "skills" / "openclaw" / "moneyprinterturbo-video" / "EASEL-META.md"
LAUNCHER = ROOT / "start-moneyprinterturbo.command"


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def _launcher() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def test_skill_routes_explicit_moneyprinterturbo_and_stock_video_requests():
    text = _skill().casefold()

    assert "name: moneyprinterturbo-video" in text
    assert "moneyprinterturbo" in text
    assert "pexels" in text
    assert "pixabay" in text
    assert "coverr" in text
    assert "stock video" in text or "stock footage" in text
    assert META.is_file()


def test_skill_requires_aspect_profile_checks_and_paid_confirmation():
    text = _skill()
    lowered = text.casefold()

    assert "9:16" in text and "16:9" in text and "1:1" in text
    assert "confirm" in lowered and "aspect" in lowered
    for profile_file in ("identity.md", "style.md", "audience.md", "preferences.md", "memory.md"):
        assert profile_file in text
    assert "volcengine_seedance" in text and "--confirm-seedance-charge" in text
    assert "ofox" in text and "--confirm-ofox-charge" in text
    assert "metaso_minimax" in text and "--confirm-metaso-minimax-charge" in text
    assert "cost" in lowered or "paid" in lowered


def test_skill_delivers_to_easel_outputs_and_never_publishes():
    text = _skill()

    assert "outputs/<project>/final.mp4" in text
    assert "ffprobe" in text
    assert "nonzero" in text.casefold() or "non-empty" in text.casefold()
    assert "never publish automatically" in text.casefold()
    assert "publisher skill" in text.casefold()
    assert "cd" in text and ".env" in text and "skills/shared/scripts/" in text
    assert "install-moneyprinterturbo.sh --check" in text
    assert "mpt_bridge.py run" in text


def test_launcher_checks_installation_and_binds_loopback_only():
    text = _launcher()

    assert "install-moneyprinterturbo.sh --check" in text
    assert "mpt_bridge.py configure" in text
    assert "mpt_bridge.py reconcile" in text
    assert "MPT_WEBUI_HOST=127.0.0.1" in text
    assert "MPT_WEBUI_PORT=8501" in text
    assert "0.0.0.0" not in text
    assert ".env" in text and "skills/shared/scripts" in text


def test_launcher_starts_only_webui_in_foreground():
    text = _launcher()
    lowered = text.casefold()

    assert "webui.sh" in lowered
    assert "trap " in lowered
    assert "main.py" not in lowered
    assert "api.py" not in lowered
    assert "nohup" not in lowered
    assert "&" not in text
