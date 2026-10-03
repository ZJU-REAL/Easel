"""Regression tests for profile path validation."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app as web  # noqa: E402
from easel.persona import load_profile_text, profile_exists, valid_persona_name  # noqa: E402


def test_profile_helpers_reject_path_segments():
    for name in ("..", ".", "_internal", "nested/profile", r"nested\\profile"):
        assert valid_persona_name(name) is False
        assert profile_exists(name) is False
        assert load_profile_text(name) == ""


def test_encoded_parent_profile_routes_do_not_expose_project_files():
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as client:
        for path in ("/api/persona/%2E%2E", "/api/persona/%2E%2E/files"):
            response = client.get(path)
            assert response.status_code == 404, (path, response.status_code, response.text[:200])
