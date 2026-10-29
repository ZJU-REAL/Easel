from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/builtin/skill-record-card/scripts/card.py"


@pytest.fixture
def card_module():
    spec = importlib.util.spec_from_file_location("record_cards_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fields(card_module):
    return {field: "用户已确认的正文" for field in card_module.FIELDS}


def create(module, directory, fields, **updates):
    values = {"title": "创作复盘", "did": "完成内容制作", "fields": fields,
              "quotes": [], "ai_notes": [], "day": "2026-10-23"}
    values.update(updates)
    return module.create_card(directory, **values)


def test_create_revise_preserves_multiline_text_and_old_version(card_module, fields, tmp_path):
    fields["method"] = "先做验证\n### 特殊标题\n## v3 · 2026-10-23\n\\原话"
    quotes = ["第一句\n第二句", "变更：这也是用户原话"]
    path, identity = create(card_module, tmp_path, fields, quotes=quotes, ai_notes=["补充\n边界"])
    before = path.read_text(encoding="utf-8")
    parsed = card_module.parse_versions(before)
    assert identity == "card-001" and len(parsed) == 1
    assert parsed[0]["fields"] == fields
    assert parsed[0]["quotes"] == quotes
    assert parsed[0]["ai_notes"] == ["补充\n边界"]
    revised, version = card_module.revise_card(tmp_path, "001", change="补充适用边界",
        overrides={"scope_nouse": "高风险场景"}, new_quotes=["新的原话"],
        new_ai_notes=[], day="2026-10-24")
    assert revised == path and version == 2
    after = path.read_text(encoding="utf-8")
    assert before[before.index("## v1"):].rstrip() in after
    latest = card_module.parse_versions(after)[-1]
    assert latest["fields"]["method"] == fields["method"]
    assert latest["quotes"] == quotes + ["新的原话"]


@pytest.mark.parametrize("identifier", ["../outside.md", "/tmp/private", "1/2", "0", "x1", ""])
def test_invalid_identifiers_cannot_read_other_files(card_module, tmp_path, identifier):
    with pytest.raises(ValueError):
        card_module._find_card(tmp_path, identifier)


def test_symlink_card_cannot_read_or_modify_target(card_module, fields, tmp_path):
    outside = tmp_path / "private.md"
    outside.write_text("private", encoding="utf-8")
    cards = tmp_path / "cards"
    cards.mkdir()
    try:
        (cards / "card-001.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        card_module._find_card(cards, "001")
    assert outside.read_text() == "private"


def test_ids_continue_after_999(card_module, fields, tmp_path):
    (tmp_path / "card-999.md").write_text("reserved")
    first, first_id = create(card_module, tmp_path, fields)
    second, second_id = create(card_module, tmp_path, fields)
    assert (first_id, second_id) == ("card-1000", "card-1001")
    assert card_module._find_card(tmp_path, first_id) == first
    assert first != second


@pytest.mark.parametrize("updates", [{"title": " "}, {"did": "x\ny"}, {"day": "2026-02-30"},
    {"quotes": "not a list"}, {"ai_notes": [None]}])
def test_invalid_metadata_rejected_before_writing(card_module, fields, tmp_path, updates):
    with pytest.raises(ValueError):
        create(card_module, tmp_path, fields, **updates)
    assert not list(tmp_path.glob("card-*.md"))


def test_failed_atomic_revision_preserves_history(card_module, fields, tmp_path, monkeypatch):
    path, _ = create(card_module, tmp_path, fields)
    before = path.read_bytes()
    def failed_replace(*args):
        raise OSError("injected replacement failure")
    monkeypatch.setattr(card_module.os, "replace", failed_replace)
    with pytest.raises(OSError):
        card_module.revise_card(tmp_path, "1", change="修订", overrides={"point": "新要点"},
                                new_quotes=[], new_ai_notes=[], day="2026-10-24")
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_competing_writer_fails_without_overwriting(card_module, fields, tmp_path):
    path, _ = create(card_module, tmp_path, fields)
    before = path.read_bytes()
    child = """
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('card_child', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
with module._writer_lock(Path(sys.argv[2])):
    print('ready', flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen([sys.executable, "-c", child, str(SCRIPT), str(tmp_path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(OSError):
            create(card_module, tmp_path, fields)
        assert path.read_bytes() == before
    finally:
        process.communicate("exit\n", timeout=10)
    assert create(card_module, tmp_path, fields)[1] == "card-002"


@pytest.mark.parametrize("data", [[], {"point": None}, {"quotes": "not-list"}, {"ai_notes": [3]}])
def test_json_payload_types_are_not_coerced_into_fake_content(card_module, tmp_path, data):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    args = SimpleNamespace(data=str(path), title=None, did=None, quote=None, ai_note=None)
    with pytest.raises(ValueError):
        card_module._merge_data(args)


@pytest.mark.parametrize("topic", ["..", "a/b", "a\\b", "../_sessions"])
def test_topic_must_be_one_project_name(card_module, topic):
    with pytest.raises(ValueError):
        card_module._cards_dir(topic)


def test_list_does_not_create_empty_project(card_module, tmp_path, monkeypatch):
    monkeypatch.setitem(card_module.validate_output_path.__globals__, "PROJECT_ROOT", tmp_path)
    monkeypatch.setitem(card_module.validate_output_path.__globals__, "OUTPUTS_DIR", tmp_path / "outputs")
    card_module.cmd_list(SimpleNamespace(topic="经验整理"))
    assert not (tmp_path / "outputs").exists()


def test_damaged_versions_rejected_without_rewriting(card_module, fields, tmp_path):
    path, _ = create(card_module, tmp_path, fields)
    path.write_text(path.read_text(encoding="utf-8").replace("## v1", "## v2"), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        card_module.revise_card(tmp_path, "1", change="修订", overrides={},
                                new_quotes=["新理解"], new_ai_notes=[], day="2026-10-24")
    assert path.read_bytes() == before


def test_retracted_ai_notes_replaced_only_in_new_version(card_module, fields, tmp_path):
    path, _ = create(card_module, tmp_path, fields, ai_notes=["先发布再测试"])
    card_module.revise_card(tmp_path, "1", change="撤回旧观点", overrides={"point": "先测试再发布"},
                            new_quotes=[], new_ai_notes=["先测试再发布"], day="2026-10-24",
                            replace_ai_notes=True)
    versions = card_module.parse_versions(path.read_text(encoding="utf-8"))
    assert versions[0]["ai_notes"] == ["先发布再测试"]
    assert versions[1]["ai_notes"] == ["先测试再发布"]
    card_module.revise_card(tmp_path, "1", change="只保留用户原话", overrides={},
                            new_quotes=[], new_ai_notes=[], day="2026-10-25", replace_ai_notes=True)
    assert card_module.parse_versions(path.read_text(encoding="utf-8"))[-1]["ai_notes"] == []


def test_incomplete_old_version_rejected_even_if_latest_is_valid(card_module, fields, tmp_path):
    path, _ = create(card_module, tmp_path, fields)
    card_module.revise_card(tmp_path, "1", change="更新", overrides={}, new_quotes=["新原话"],
                            new_ai_notes=[], day="2026-10-24")
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("### 核心要点\n用户已确认的正文", "### 核心要点\n", 1), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        card_module.revise_card(tmp_path, "1", change="再次更新", overrides={}, new_quotes=["再试"],
                                new_ai_notes=[], day="2026-10-25")
    assert path.read_bytes() == before
