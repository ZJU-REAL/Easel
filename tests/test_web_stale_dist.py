"""easel web 启动时的前端 dist 陈旧警告（_warn_stale_frontend）。

回归背景：服务托管的是 web/frontend/dist；源码改了不重建，浏览器一直跑旧
bundle，曾导致「登录成功仍显示未登录」。启动时检测 src/public/index.html
比 dist 新就警告，只提示不阻塞。
"""
import os
import types

import pytest

from easel import cli


def _make_frontend(root, src_mtime=None, dist_mtime=None, with_dist=True):
    frontend = root / "web" / "frontend"
    (frontend / "src").mkdir(parents=True)
    (frontend / "src" / "main.ts").write_text("// src", encoding="utf-8")
    (frontend / "index.html").write_text("<html></html>", encoding="utf-8")
    if with_dist:
        assets = frontend / "dist" / "assets"
        assets.mkdir(parents=True)
        (assets / "index.js").write_text("// bundle", encoding="utf-8")
    if src_mtime is not None:
        for f in (frontend / "src").rglob("*"):
            os.utime(f, (src_mtime, src_mtime))
        os.utime(frontend / "index.html", (src_mtime, src_mtime))
    if with_dist and dist_mtime is not None:
        for f in (frontend / "dist").rglob("*"):
            os.utime(f, (dist_mtime, dist_mtime))
    return frontend


def test_warns_when_dist_missing(monkeypatch, tmp_path, capsys):
    _make_frontend(tmp_path, with_dist=False)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    cli._warn_stale_frontend()
    assert "npm run build" in capsys.readouterr().err


def test_warns_when_src_newer_than_dist(monkeypatch, tmp_path, capsys):
    _make_frontend(tmp_path, src_mtime=2_000_000_000, dist_mtime=1_000_000_000)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    cli._warn_stale_frontend()
    err = capsys.readouterr().err
    assert "旧 bundle" in err and "npm run build" in err


def test_silent_when_dist_fresh(monkeypatch, tmp_path, capsys):
    _make_frontend(tmp_path, src_mtime=1_000_000_000, dist_mtime=2_000_000_000)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    cli._warn_stale_frontend()
    assert capsys.readouterr().err == ""


def test_cmd_web_still_starts_with_stale_dist(monkeypatch, tmp_path):
    """警告不阻塞启动：dist 陈旧时 cmd_web 仍照常起子进程并透传返回码。"""
    _make_frontend(tmp_path, src_mtime=2_000_000_000, dist_mtime=1_000_000_000)
    (tmp_path / "web").mkdir(exist_ok=True)
    (tmp_path / "web" / "app.py").write_text("# app", encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    class _Fake:
        @staticmethod
        def run(*args, **kwargs):
            return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "subprocess", _Fake)
    assert cli.cmd_web(types.SimpleNamespace(port=7860)) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
