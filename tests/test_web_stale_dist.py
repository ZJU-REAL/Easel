"""easel web 启动时的前端 dist 陈旧警告（_warn_stale_frontend）。

回归背景：服务托管的是 web/frontend/dist；源码改了不重建，浏览器一直跑旧
bundle，曾导致「登录成功仍显示未登录」。启动时检测 src/public/index.html
比 dist 新就警告，只提示不阻塞。
"""
import os
import types
import tempfile

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
        (frontend / "dist" / "index.html").write_text("<html>built</html>", encoding="utf-8")
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


def test_partial_dist_without_entry_uses_fallback(monkeypatch, tmp_path, capsys):
    frontend = _make_frontend(tmp_path, src_mtime=1_000_000_000, dist_mtime=2_000_000_000)
    (frontend / "dist" / "index.html").unlink()
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    cli._warn_stale_frontend()
    assert "回退版" in capsys.readouterr().err


def test_new_public_asset_does_not_hide_old_bundle(monkeypatch, tmp_path, capsys):
    frontend = _make_frontend(tmp_path, src_mtime=1_500_000_000, dist_mtime=1_000_000_000)
    asset = frontend / "dist" / "new-icon.svg"
    asset.write_text("<svg/>", encoding="utf-8")
    os.utime(asset, (2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    cli._warn_stale_frontend()
    assert "旧 bundle" in capsys.readouterr().err


@pytest.mark.parametrize("relative", ["web/static/dropdown.css", "web/frontend/vite.config.ts"])
def test_external_css_and_build_configuration_are_watched(monkeypatch, tmp_path, capsys, relative):
    _make_frontend(tmp_path, src_mtime=1_000_000_000, dist_mtime=1_500_000_000)
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("/* changed */", encoding="utf-8")
    os.utime(source, (2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    cli._warn_stale_frontend()
    assert "旧 bundle" in capsys.readouterr().err


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


# ---------- 浏览器登录态目录可写性守卫（_warn_unwritable_profiles_dir） ----------

def test_warns_when_profiles_dir_unwritable(tmp_path, capsys, monkeypatch):
    """登录态目录只读（如沙箱 EPERM）→ 明确警告；登录 runner 会在这里 mkdir 崩溃。"""
    ro = tmp_path / "ro-profiles"
    ro.mkdir()
    def denied(*args, **kwargs):
        raise PermissionError('denied')
    monkeypatch.setattr(tempfile, 'TemporaryFile', denied)
    cli._warn_unwritable_profiles_dir(ro)
    err = capsys.readouterr().err
    assert "不可写" in err and "easel web" in err


def test_silent_when_profiles_dir_writable(tmp_path, capsys):
    cli._warn_unwritable_profiles_dir(tmp_path / "profiles")
    assert capsys.readouterr().err == ""
    assert (tmp_path / "profiles").is_dir(), "可写时目录被创建（供后续登录 runner 使用）"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
