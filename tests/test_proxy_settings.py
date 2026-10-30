"""网络代理设置（EASEL_PROXY）契约测试。

覆盖：
1. GET/POST /api/settings/proxy：读写 .env、格式校验、清除、env 固定时只读；
2. _proxy_env 解析链：进程环境优先，其次 .env；
3. web_publisher._env_file_value：standalone CLI 场景的 .env 兜底读取。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"))
import web_publisher  # noqa: E402

import web.app as web  # noqa: E402


@pytest.fixture
def env_tmp(tmp_path, monkeypatch):
    """隔离 .env：指向临时文件，并清掉所有可能影响代理解析的环境变量。"""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(web, "ENV_FILE", env_file)
    for var in ("EASEL_PROXY", "TWITTER_X_PROXY", "YOUTUBE_PROXY",
                "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    return env_file


def test_get_proxy_default_none(env_tmp):
    from fastapi.testclient import TestClient
    client = TestClient(web.app, base_url="http://127.0.0.1:7860", headers={"Origin": "http://127.0.0.1:7860"})
    data = client.get("/api/settings/proxy").json()
    assert data == {"proxy": "", "source": "none"}


def test_save_then_get_proxy_roundtrip(env_tmp):
    from fastapi.testclient import TestClient
    client = TestClient(web.app, base_url="http://127.0.0.1:7860", headers={"Origin": "http://127.0.0.1:7860"})
    r = client.post("/api/settings/proxy", json={"proxy": "http://127.0.0.1:7890"})
    assert r.status_code == 200 and r.json()["proxy"] == "http://127.0.0.1:7890"
    assert "EASEL_PROXY=http://127.0.0.1:7890" in env_tmp.read_text(encoding="utf-8")
    data = client.get("/api/settings/proxy").json()
    assert data == {"proxy": "http://127.0.0.1:7890", "source": "envfile"}


def test_save_proxy_validates_format(env_tmp):
    from fastapi.testclient import TestClient
    client = TestClient(web.app, base_url="http://127.0.0.1:7860", headers={"Origin": "http://127.0.0.1:7860"})
    for bad in ("127.0.0.1:7890", "ftp://127.0.0.1", "http://user:pass@127.0.0.1:7890", "notaurl"):
        r = client.post("/api/settings/proxy", json={"proxy": bad})
        assert r.status_code == 400, f"{bad} 应被拒绝"
    for good in ("http://127.0.0.1:7890", "https://proxy.example:8443", "socks5://127.0.0.1:1080"):
        r = client.post("/api/settings/proxy", json={"proxy": good})
        assert r.status_code == 200, f"{good} 应被接受"


def test_clear_proxy_removes_env_line(env_tmp):
    from fastapi.testclient import TestClient
    client = TestClient(web.app, base_url="http://127.0.0.1:7860", headers={"Origin": "http://127.0.0.1:7860"})
    client.post("/api/settings/proxy", json={"proxy": "http://127.0.0.1:7890"})
    r = client.post("/api/settings/proxy", json={"proxy": ""})
    assert r.status_code == 200 and r.json()["proxy"] == ""
    assert "EASEL_PROXY" not in env_tmp.read_text(encoding="utf-8"), "清除应删除 .env 里的该行"


def test_env_var_pins_proxy_readonly(env_tmp, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("EASEL_PROXY", "http://127.0.0.1:1111")
    client = TestClient(web.app, base_url="http://127.0.0.1:7860", headers={"Origin": "http://127.0.0.1:7860"})
    assert client.get("/api/settings/proxy").json()["source"] == "env"
    r = client.post("/api/settings/proxy", json={"proxy": "http://127.0.0.1:7890"})
    assert r.status_code == 409, "启动环境固定时代理只读"


def test_proxy_env_resolution_order(env_tmp, monkeypatch):
    env_tmp.write_text("EASEL_PROXY=http://127.0.0.1:7890\n", encoding="utf-8")
    env = web._proxy_env()
    # .env 来源的代理显式回写，runner 子进程直接可见
    assert env["EASEL_PROXY"] == "http://127.0.0.1:7890"
    assert env["http_proxy"] == "http://127.0.0.1:7890"
    assert env["https_proxy"] == "http://127.0.0.1:7890"
    # 进程环境变量优先于 .env
    monkeypatch.setenv("EASEL_PROXY", "http://127.0.0.1:1111")
    assert web._proxy_env()["EASEL_PROXY"] == "http://127.0.0.1:1111"


def test_wp_env_file_value(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# 注释\nEASEL_PROXY="http://127.0.0.1:7890"\nOTHER=1\n', encoding="utf-8")
    assert web_publisher._env_file_value("EASEL_PROXY", env_file) == "http://127.0.0.1:7890"
    assert web_publisher._env_file_value("MISSING", env_file) == ""
    assert web_publisher._env_file_value("EASEL_PROXY", tmp_path / "nope.env") == ""


def test_wp_launch_kwargs_envfile_fallback(monkeypatch, tmp_path):
    """standalone CLI 场景：进程无代理变量时，_launch_kwargs 兜底读 .env。"""
    for var in ("EASEL_PROXY", "TWITTER_X_PROXY", "https_proxy", "HTTPS_PROXY",
                "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("EASEL_PROXY=http://127.0.0.1:7890\n", encoding="utf-8")
    real = web_publisher._env_file_value
    monkeypatch.setattr(web_publisher, "_env_file_value",
                        lambda key, env_file=env_file: real(key, env_file))
    kw = web_publisher._launch_kwargs(web_publisher.PLATFORMS["twitter-x"], "twitter-x")
    assert kw["proxy"]["server"] == "http://127.0.0.1:7890", ".env 里的代理应被兜底读取"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
