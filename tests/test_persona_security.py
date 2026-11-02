"""Regression tests for profile path validation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import web.app as web  # noqa: E402
import easel.persona as persona  # noqa: E402


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    directory = tmp_path / "profiles"
    directory.mkdir()
    (tmp_path / "REVIEW_MARKER.md").write_text("outside-profile-marker", encoding="utf-8")
    monkeypatch.setattr(persona, "PROFILES_DIR", directory)
    monkeypatch.setattr(web, "PROFILES_DIR", directory)
    return directory


@pytest.mark.parametrize("name", [
    "", "..", ".", "_internal", ".hidden", "nested/profile", r"nested\profile",
    "/absolute", "C:relative", "bad\x00name", "bad\nname", None, 123,
])
def test_profile_helpers_reject_path_segments(profiles, name):
    assert persona.valid_persona_name(name) is False
    assert persona.profile_exists(name) is False
    assert persona.load_profile_text(name) == ""


def test_encoded_parent_profile_routes_do_not_expose_project_files(profiles):
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as client:
        for path in (
            "/api/persona/%2E%2E", "/api/persona/%2E%2E/files",
            "/api/persona/%2E", "/api/persona/%2E/files",
            "/api/persona/bad%00name", "/api/persona/bad%00name/files",
        ):
            response = client.get(path)
            assert response.status_code == 404, (path, response.status_code, response.text[:200])
            assert "outside-profile-marker" not in response.text


@pytest.mark.parametrize("name", ["中文画像", "creator-01", "my profile", "name.with.dots"])
def test_normal_profiles_remain_readable(profiles, name):
    directory = profiles / name
    directory.mkdir()
    (directory / "identity.md").write_text("normal-profile-marker", encoding="utf-8")
    assert persona.profile_exists(name)
    assert persona.load_profile_text(name) == "normal-profile-marker"
    local = "http://127.0.0.1:7860"
    client = TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                        headers={"Origin": local})
    assert client.get(f"/api/persona/{name}").status_code == 200
    assert client.get(f"/api/persona/{name}/files").status_code == 200


def test_listings_only_return_valid_directories(profiles):
    for name in ("正常画像", "_internal", ".hidden"):
        (profiles / name).mkdir()
    (profiles / "not-a-profile.md").write_text("not a directory", encoding="utf-8")
    assert persona.list_personas() == ["正常画像"]
    assert [row["name"] for row in web.list_personas()] == ["正常画像"]


def test_missing_profile_routes_return_real_404_without_mutating_other_profiles(profiles):
    remaining = profiles / "保留画像"
    remaining.mkdir()
    identity = remaining / "identity.md"
    identity.write_text("keep this profile", encoding="utf-8")
    with TestClient(web.app, base_url="http://127.0.0.1:7860",
                    client=("127.0.0.1", 51234)) as client:
        assert client.get("/api/persona/AI 博主/files").status_code == 404
        response = client.delete("/api/persona/AI 博主")
        assert response.status_code == 404
        assert response.json() == {"detail": "画像不存在"}
    assert identity.read_text(encoding="utf-8") == "keep this profile"


@pytest.mark.parametrize("name", ["%2E%2E", "%2E", "nested%5Cprofile", "C%3Arelative", "bad%00name", "_template"])
def test_delete_rejects_invalid_names_without_touching_siblings(profiles, name):
    directory = profiles / "保留画像"
    directory.mkdir()
    with TestClient(web.app, base_url="http://127.0.0.1:7860",
                    client=("127.0.0.1", 51234)) as client:
        assert client.delete(f"/api/persona/{name}").status_code in (400, 404)
    assert directory.is_dir()
    assert (profiles.parent / "REVIEW_MARKER.md").read_text(encoding="utf-8") == "outside-profile-marker"


def test_profile_delete_blocks_cross_origin_writes_and_supports_local_unicode_names(profiles):
    directory = profiles / "AI 博主"
    directory.mkdir()
    (directory / "identity.md").write_text("local test only", encoding="utf-8")
    with TestClient(web.app, base_url="http://127.0.0.1:7860",
                    client=("127.0.0.1", 51234)) as client:
        assert client.delete("/api/persona/AI 博主", headers={"Origin": "https://example.invalid"}).status_code == 403
        assert directory.is_dir()
        response = client.delete("/api/persona/AI 博主", headers={"Origin": "http://127.0.0.1:7860"})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "deleted": "AI 博主"}
        assert client.delete("/api/persona/AI 博主").status_code == 404
    assert not directory.exists()
