import asyncio
from pathlib import Path
from web import app as web


def test_v3_registry_contains_exactly_113_and_only_internal_storage():
    skills = web.get_skills()
    assert len(skills) == 113
    assert web.find_skill("seal-xhs-public-research") == "seal-xhs-public-research"
    assert web.find_skill("../easel") is None
    assert web.SKILLS_DIR == (Path(__file__).resolve().parents[2] / "bundled-skills")


def test_redfox_requires_key_without_exposing_secret(monkeypatch):
    monkeypatch.delenv("REDFOX_API_KEY", raising=False)
    detail = asyncio.run(web.api_skill_detail("seal-xhs-public-research"))
    assert detail["needsApi"] is True
    assert detail["apiConfigured"] is False
    assert "REDFOX_API_KEY" in str(detail["apiSpec"])
