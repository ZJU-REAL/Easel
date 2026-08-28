"""Data-tracker storage and follower export contracts."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "skills/openclaw/skill-data-tracker/scripts/track.py"


def load_module():
    spec = importlib.util.spec_from_file_location("easel_data_tracker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_snapshots_merge_legacy_and_current_by_platform(tmp_path, monkeypatch):
    track = load_module()
    monkeypatch.setattr(track, "SNAP_ROOT", tmp_path / "_analytics" / "snapshots")
    monkeypatch.setattr(track, "LEGACY_SNAP_ROOT", tmp_path / "analytics" / "snapshots")

    legacy = track.LEGACY_SNAP_ROOT / "demo"
    current = track.SNAP_ROOT / "demo" / "xiaohongshu"
    legacy.mkdir(parents=True)
    current.mkdir(parents=True)
    (legacy / "2026-01-01.json").write_text(json.dumps({
        "date": "2026-01-01", "profile": "demo", "platform": "xiaohongshu",
        "account_metrics": {"followers": 10},
    }), encoding="utf-8")
    (current / "2026-01-01.json").write_text(json.dumps({
        "date": "2026-01-01", "profile": "demo", "platform": "xiaohongshu",
        "account_metrics": {"followers": 12},
    }), encoding="utf-8")
    douyin = track.SNAP_ROOT / "demo" / "douyin"
    douyin.mkdir(parents=True)
    (douyin / "2026-01-01.json").write_text(json.dumps({
        "date": "2026-01-01", "profile": "demo", "platform": "douyin",
        "account_metrics": {"followers": 20},
    }), encoding="utf-8")

    rows = track.load_snapshots("demo")
    assert [(row["platform"], row["account_metrics"]["followers"]) for row in rows] == [
        ("douyin", 20), ("xiaohongshu", 12),
    ]


def test_export_followers_builds_analysis_view(tmp_path, monkeypatch):
    track = load_module()
    snapshot_root = tmp_path / "_analytics" / "snapshots"
    monkeypatch.setattr(track, "SNAP_ROOT", snapshot_root)
    monkeypatch.setattr(track, "LEGACY_SNAP_ROOT", tmp_path / "analytics" / "snapshots")
    for platform, followers in (("xiaohongshu", 12), ("douyin", 20)):
        directory = snapshot_root / "demo" / platform
        directory.mkdir(parents=True)
        (directory / "2026-01-01.json").write_text(json.dumps({
            "date": "2026-01-01", "profile": "demo", "platform": platform,
            "account_metrics": {"followers": followers, "total_posts": 3},
        }), encoding="utf-8")

    output = tmp_path / "follower-log.json"
    track.cmd_export_followers(argparse.Namespace(
        profile=None, platform=None, output=str(output),
    ))
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == "1.0"
    assert {(row["platform"], row["followers"]) for row in payload["snapshots"]} == {
        ("douyin", 20), ("xiaohongshu", 12),
    }
