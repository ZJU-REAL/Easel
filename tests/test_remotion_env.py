import json
import os
from pathlib import Path
from subprocess import CompletedProcess

from PIL import Image
import pytest

from easel import remotion_env
from easel.harnesses.store import write_json


def external_project(root):
    project = root / "existing-project"
    for name in remotion_env.PACKAGES:
        package = project / "node_modules" / name
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"name": name, "version": "4.0.542"}))
    (project / "node_modules/@remotion/cli/remotion-cli.js").touch()
    (project / "package.json").write_text("{}")
    write_json(root / "outputs/_harness/remotion.json", {"path": str(project)})
    return project


def test_existing_project_works_independently_of_bundled_template(tmp_path):
    project = external_project(tmp_path)
    status = remotion_env.discover(tmp_path, {})
    assert status["selected"]["path"] == str(project)
    assert status["selected"]["ready"] and status["selected"]["version"] == "4.0.542"
    assert status["probe"] is None
    assert remotion_env.environment(tmp_path, {})["REMOTION_PROJECT"] == str(project)
    (project / "node_modules/.bin").mkdir()
    assert remotion_env.environment(tmp_path, {"PATH": "system-tools"})["PATH"] == "system-tools"
    (project / "node_modules/@remotion/renderer/package.json").unlink()
    status = remotion_env.discover(tmp_path, {})
    assert not status["selected"]["ready"]
    assert status["selected"]["missing"] == ["@remotion/renderer"]


def test_failed_frame_probe_invalidates_previous_success(tmp_path, monkeypatch):
    project = external_project(tmp_path)
    monkeypatch.setattr(remotion_env.shutil, "which", lambda *a, **kw: "node")
    size = (160, 90)

    def still(command, **options):
        assert options["cwd"] == project
        destination = Path(command[command.index("EaselProbe") + 1])
        Image.new("RGB", size).save(destination)
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(remotion_env.subprocess, "run", still)
    remotion_env.render_frame(tmp_path, dict(os.environ))
    assert remotion_env.discover(tmp_path, {})["probe"]["size"] == "160 × 90"
    size = (1, 1)
    with pytest.raises(ValueError, match="PNG"):
        remotion_env.render_frame(tmp_path, dict(os.environ))
    assert remotion_env.discover(tmp_path, {})["probe"] is None


def test_local_selection_reports_existing_project_without_running_it(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import web.app as web

    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path / "outputs")
    project = external_project(tmp_path)
    (tmp_path / "outputs/_harness/remotion.json").unlink()
    url = "/api/env/remotion"
    with TestClient(web.app, base_url="http://localhost", client=("127.0.0.1", 8000)) as client:
        assert client.post(url, json={"path": "relative"}).status_code == 400
        response = client.post(url, json={"path": str(project)})
        assert response.status_code == 200 and response.json()["selected"]["ready"]
        assert response.json()["probe"] is None
        assert client.post(url, json={"path": ""}).json()["selected"] is None
