"""Selected/edited Python code is checked in a worker and stored only at a managed path."""
import json
import os
from pathlib import Path

import pytest

from easel.trends import management
from easel.trends.protocol import MAX_SCRIPT_BYTES, CollectorError, utc_now
from easel.trends.runner import collect
from easel.trends.sources import ConfigError, load_sources


def setup(root):
    path = root / "config/trend-sources.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"version":1,"include_builtin":false,"sources":[]}', encoding="utf-8")
    return path


def test_uploaded_script_with_unicode_and_spaces_is_checked_without_running(tmp_path):
    setup(tmp_path)
    marker = tmp_path / "should not run during check.txt"
    payload = {"version": 1, "fetched_at": utc_now(), "items": [{"title": "用户脚本"}]}
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nprint({json.dumps(payload)!r})\n"
    result = management.update(tmp_path, dict(os.environ), {"action": "add", "type": "python", "label": "用户采集",
        "script_name": "我的 脚本.py", "script_code": code, "python": "untrusted-interpreter", "script": "../../forbidden.py"})
    assert not marker.exists()
    source = load_sources(tmp_path, {})[0]
    stored = Path(source.options["script"])
    assert stored.parent == tmp_path / "config/trend-collectors"
    assert stored.name == result["id"] + ".py"
    assert collect(source, dict(os.environ))["items"][0]["title"] == "用户脚本"
    assert marker.exists()
    management.update(tmp_path, {}, {"action": "delete", "id": result["id"]})
    assert not stored.exists()


@pytest.mark.parametrize("name,code", [("../outside.py", "pass"), ("x\\outside.py", "pass"),
    ("file.txt", "pass"), ("file.py", "def broken(:"), ("file.py", "x" * (MAX_SCRIPT_BYTES + 1)),
    ("file.py", "\ud800"), ("file.py", "\x00"), ("file.py", " ")],
    ids=["posix-traversal","windows-traversal","extension","syntax","oversized","surrogate","nul","blank"])
def test_invalid_selected_or_edited_scripts_preserve_config_and_leave_no_files(tmp_path, name, code):
    config = setup(tmp_path)
    before = config.read_bytes()
    with pytest.raises(ConfigError):
        management.update(tmp_path, dict(os.environ), {"action": "add", "type": "python", "label": "bad",
            "script_name": name, "script_code": code})
    assert config.read_bytes() == before
    assert not list((tmp_path / "config/trend-collectors").glob("*.py"))


def test_uploaded_file_is_removed_when_atomic_config_save_fails(tmp_path, monkeypatch):
    config = setup(tmp_path)
    before = config.read_bytes()
    monkeypatch.setattr(management.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        management.update(tmp_path, dict(os.environ), {"action": "add", "type": "python", "label": "test",
            "script_code": "pass"})
    assert config.read_bytes() == before
    assert not list((tmp_path / "config/trend-collectors").glob("*.py"))


def test_deleting_legacy_source_never_deletes_its_original_file(tmp_path):
    config = setup(tmp_path)
    original = tmp_path / "original.py"
    original.write_text("pass", encoding="utf-8")
    config.write_text(json.dumps({"version":1,"include_builtin":False,"sources":[
        {"id":"legacy","label":"legacy","type":"python","script":str(original)}]}),encoding="utf-8")
    management.update(tmp_path, {}, {"action":"delete","id":"legacy"})
    assert original.exists()


def test_server_template_runs_and_matches_the_documented_protocol(tmp_path):
    setup(tmp_path)
    template = management.describe(tmp_path, {})["python_template"]
    assert "def collect()" in template and "def main()" in template and '"version": 1' in template
    # The packaged template is available even if repository example files aren't present.
    result = management.update(tmp_path, dict(os.environ), {"action":"add","type":"python","label":"示例","script_code":template})
    source = load_sources(tmp_path,{})[0]
    assert source.id == result["id"]
    assert collect(source,dict(os.environ))["items"][0]["title"]
