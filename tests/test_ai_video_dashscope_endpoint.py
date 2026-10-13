"""DashScope 视频合成迁移到 video-generation 统一端点的离线测试。

不发起真实网络请求：mock http_request / _poll / download_video / _put_audio /
_image_to_data_or_url，只验证端点拼装与参数构造。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))
import ai_video  # noqa: E402

VIDEO_GEN_PATH = "/services/aigc/video-generation/video-synthesis"


@pytest.fixture()
def dashscope_run(monkeypatch, tmp_path):
    captured: dict = {}

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.delenv("DASHSCOPE_T2V_PATH", raising=False)
    monkeypatch.delenv("DASHSCOPE_I2V_PATH", raising=False)

    def fake_http(url, headers, method="GET", payload=None):
        captured["endpoint"] = url
        captured["payload"] = payload
        return {"output": {"task_id": "t1"}}

    monkeypatch.setattr(ai_video, "http_request", fake_http)
    monkeypatch.setattr(ai_video, "_poll",
                        lambda *a, **k: {"output": {"video_url": "https://example/v.mp4"}})
    monkeypatch.setattr(ai_video, "download_video", lambda url, out: out)
    monkeypatch.setattr(ai_video, "_put_audio", lambda *a, **k: None)
    monkeypatch.setattr(ai_video, "_image_to_data_or_url", lambda p: "data:image/png;base64,x")

    def run(**kw):
        image = kw.pop("image", None)
        values = dict(model=None, prompt="测试", ratio="9:16", duration=None,
                      output=str(tmp_path / "o.mp4"), poll_interval=1, timeout=1)
        values.update(kw)
        ai_video.generate_dashscope(SimpleNamespace(**values), image)
        return captured

    return run


def test_t2v_uses_video_generation_endpoint(dashscope_run):
    captured = dashscope_run()
    assert captured["endpoint"].endswith(VIDEO_GEN_PATH)
    assert "text2video" not in captured["endpoint"]
    assert captured["payload"]["input"]["prompt"] == "测试"
    assert "img_url" not in captured["payload"]["input"]


def test_i2v_uses_video_generation_endpoint(dashscope_run):
    captured = dashscope_run(image="/fake/first-frame.png")
    assert captured["endpoint"].endswith(VIDEO_GEN_PATH)
    assert "image2video" not in captured["endpoint"]
    assert captured["payload"]["input"]["img_url"].startswith("data:image")


@pytest.mark.parametrize("ratio,pixels", [
    ("9:16", "720*1280"),
    ("16:9", "1280*720"),
    ("1:1", "960*960"),
])
def test_size_sent_as_pixels(dashscope_run, ratio, pixels):
    captured = dashscope_run(ratio=ratio)
    assert captured["payload"]["parameters"]["size"] == pixels


def test_unknown_ratio_falls_back_to_asterisk(dashscope_run):
    captured = dashscope_run(ratio="3:4")
    assert captured["payload"]["parameters"]["size"] == "3*4"


def test_t2v_path_env_override(dashscope_run, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_T2V_PATH", "/custom/t2v")
    captured = dashscope_run()
    assert captured["endpoint"].endswith("/custom/t2v")


def test_i2v_path_env_override(dashscope_run, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_I2V_PATH", "/custom/i2v")
    captured = dashscope_run(image="/fake/f.png")
    assert captured["endpoint"].endswith("/custom/i2v")


def test_default_model_unchanged():
    # 模型默认值的调整不属于本修复范围，保持向后兼容
    assert ai_video.DEFAULT_DASHSCOPE_MODEL == "wan2.1-t2v-turbo"
