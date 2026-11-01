"""「改了 skill 到底生效没有」这条链路的契约测试。

背景：doctor 原本只查「agent workspace 里有没有 skills/」，漏掉了内容过期这一种失效——
仓库里改了 skill 但没重新同步，agent 读到的仍是旧快照，而 doctor 照样报绿。
本文件盯住 easel/skills_sync.py 的新鲜度判断与链接修复。

运行：pytest tests/test_skills_sync.py -q
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import easel.skills_sync as ss  # noqa: E402


@pytest.fixture()
def fake_workspace(tmp_path, monkeypatch):
    """造一个假的 agent workspace：src（仓库技能）与 dst（workspace 副本）各一份。"""
    src = tmp_path / "repo" / "skills" / "builtin"
    dst = tmp_path / "ws" / "skills"
    src.mkdir(parents=True)
    dst.mkdir(parents=True)
    (src / "demo").mkdir()
    (dst / "demo").mkdir()
    (src / "demo" / "SKILL.md").write_text("v1", encoding="utf-8")
    (dst / "demo" / "SKILL.md").write_text("v1", encoding="utf-8")

    monkeypatch.setattr(ss, "PROJECT_ROOT", tmp_path / "repo")
    monkeypatch.setattr(ss, "agent_workspace", lambda: tmp_path / "ws")
    return tmp_path


def _age(path: Path, seconds: float) -> None:
    """把文件的 mtime 往回拨（模拟「源比目标新」）。"""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_fresh_copy_is_reported_synced(fake_workspace):
    """源与目标一样新 → 已同步。"""
    ok, detail = ss.skills_sync_state()

    assert ok is True, detail
    assert "已是最新" in detail


def test_missing_workspace_skills_is_reported_unsynced(fake_workspace):
    """workspace 里没有 skills/ → 未同步（agent 读不到任何技能）。"""
    shutil.rmtree(fake_workspace / "ws" / "skills")

    ok, detail = ss.skills_sync_state()

    assert ok is False
    assert "为空或不存在" in detail


def test_edited_source_is_detected_as_stale(fake_workspace):
    """改了仓库里的 skill 但没同步 → 必须判为未同步（doctor 不能照样报绿）。"""
    src_file = fake_workspace / "repo" / "skills" / "builtin" / "demo" / "SKILL.md"
    dst_file = fake_workspace / "ws" / "skills" / "demo" / "SKILL.md"
    _age(dst_file, 60)   # 目标比源旧 → 目标落后
    assert ss.skills_sync_state()[0] is False

    # 把目标同步到与源同样新 → 恢复已同步
    shutil.copyfile(src_file, dst_file)
    assert ss.skills_sync_state()[0] is True

    # 再次改动源（目标保持旧）→ 必须判为未同步
    _age(dst_file, 60)
    src_file.write_text("v2 已改", encoding="utf-8")

    ok, detail = ss.skills_sync_state()

    assert ok is False, "改了 skill 却判成已同步——这正是 issue #19 同类的静默失效"
    assert "没同步" in detail


def test_latest_mtime_ignores_missing_root(tmp_path):
    """不存在的目录 → 0，不抛异常。"""
    assert ss._latest_mtime(tmp_path / "nope") == 0.0


def test_latest_mtime_finds_nested_newest(tmp_path):
    """深层文件也要算进去（skill 的 references/ 改动不更新顶层目录 mtime）。"""
    root = tmp_path / "skills" / "demo" / "references"
    root.mkdir(parents=True)
    deep = root / "notes.md"
    deep.write_text("x", encoding="utf-8")

    assert ss._latest_mtime(tmp_path / "skills") == deep.stat().st_mtime


@pytest.mark.skipif(os.name != "nt", reason="Windows 目录联接专有")
def test_ensure_workspace_links_replaces_stale_copy(fake_workspace, monkeypatch, tmp_path):
    """Windows 上 ln -s 会退化成复制；副本必须被换成真联接，否则 agent 读的是旧快照。"""
    ws = fake_workspace / "ws"
    profiles = ws / "easel-profiles"
    profiles.mkdir()
    (profiles / "stale.md").write_text("旧快照", encoding="utf-8")
    source = fake_workspace / "repo" / "profiles"
    source.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ss, "PROJECT_ROOT", fake_workspace / "repo")

    problems = ss.ensure_workspace_links()

    assert not problems, problems
    # 副本目录已被真联接取代：写进去的能从项目侧看到
    (profiles / "fresh.md").write_text("新内容", encoding="utf-8")
    assert (source / "fresh.md").read_text(encoding="utf-8") == "新内容"
