import zipfile

import pytest
from fastapi import HTTPException

import web.app as web


def make_archive(directory, entries):
    archive = directory / "artifacts.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, content in entries:
            output.writestr(name, content)
    return archive


def test_gallery_indexes_only_existing_preview_files_named_in_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "one.png").write_bytes(b"one")
    (project / "two.html").write_bytes(b"two")
    (project / "unrelated.png").write_bytes(b"other")
    make_archive(project, [("one.png", b"one"), ("two.html", b"two"),
                           ("absent.png", b"absent"), ("report.md", b"text")])
    assert web.api_artifact_archive("project/artifacts.zip") == {
        "paths": ["project/one.png", "project/two.html"],
    }


def test_gallery_never_extracts_archive_or_exposes_traversal_and_hidden_files(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside.png").write_bytes(b"secret")
    (project / ".private.png").write_bytes(b"private")
    (project / "one.png").write_bytes(b"changed")
    make_archive(project, [("../outside.png", b"secret"), ("/outside.png", b"secret"),
                           (r"..\outside.png", b"secret"), (".private.png", b"private"),
                           ("one.png", b"original"), ("new.png", b"new")])
    assert web.api_artifact_archive("project/artifacts.zip") == {"paths": []}
    assert not (project / "new.png").exists()


def test_gallery_rejects_archive_symlink_member_outside_outputs(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(web, "OUTPUTS_DIR", outputs)
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret")
    try:
        (outputs / "link.png").symlink_to(secret)
    except OSError:
        pytest.skip("Symlinks unavailable")
    make_archive(outputs, [("link.png", b"secret")])
    assert web.api_artifact_archive("artifacts.zip") == {"paths": []}


@pytest.mark.parametrize("name,content,status", [
    ("missing.zip", None, 404), ("bad.zip", b"not zip", 400),
    ("image.png", b"image", 400), ("../outside.zip", None, 403),
])
def test_archive_api_rejects_invalid_requests(tmp_path, monkeypatch, name, content, status):
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path)
    if content:
        (tmp_path / name).write_bytes(content)
    with pytest.raises(HTTPException) as error:
        web.api_artifact_archive(name)
    assert error.value.status_code == status


def test_archive_gallery_bounds_member_count(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path)
    entries = []
    for index in range(105):
        name = f"card-{index:03}.png"
        (tmp_path / name).write_bytes(b"image")
        entries.append((name, b"image"))
    make_archive(tmp_path, entries)
    assert len(web.api_artifact_archive("artifacts.zip")["paths"]) == 100
