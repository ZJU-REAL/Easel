"""Regression tests for the confirmed bug-fix round.

每个用例对应一个已确认（可复现/可推理验证）并已修复的 bug。命名即 bug 描述。
覆盖：
- web/app.py   ：job 事件回放跳过坏行；登出终止仍在跑的登录进程；schedule 锁单例
- doctor/ping  ：healthz 回环探针绕过继承的 http_proxy
- video_ops    ：cut 的 start+end 换算成 -t(end-start)；_tsec 解析
- intro_outro  ：card 的 logo 恒为输入 1（--bg-image 不再多 +1）
- content_guard：私网 IP 正则不再吞 3 段版本号（macOS 10.15.7）
- image_ops    ：compress 低 quality + --max-kb 不再 TypeError
- gemini 适配器：非流式 finishReason 映射与流式一致
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

import web.app as web

SHARED = Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── web/app.py：_read_job_events 单行损坏不应丢弃整个事件流 ───────────
def test_read_job_events_skips_torn_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path / "sessions")
    jobs = tmp_path / "sessions" / "jobs"
    jobs.mkdir(parents=True)
    path = web._job_event_file("turn-1")
    lines = [
        json.dumps({"id": 1, "event": "activity", "data": "收到"}),
        json.dumps({"id": 2, "event": "token", "data": "你好"}),   # torn line below
        '{"id": 3, "event": "tok',
        json.dumps({"id": 4, "event": "done", "data": None}),
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    events = web._read_job_events("turn-1")
    assert [e["id"] for e in events] == [1, 2, 4]
    assert [e["id"] for e in web._read_job_events("turn-1", after=2)] == [4]


# ── web/app.py：api_logout 应终止仍在跑的登录进程（防 success 标记写回） ──
class _FakeLoginProc:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None            # 永远“还在跑”

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def test_logout_terminates_inflight_login_runner(tmp_path, monkeypatch):
    platform = "kuaishou"
    monkeypatch.setattr(web, "LOGIN_RUNNERS", {
        platform: {"name": "快手", "backend": "web", "wp": "kuaishou", "profile": "KuaishouProfile"}})
    monkeypatch.setattr(web, "BROWSER_PROFILES", tmp_path / "profiles")
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path / "_login")
    (tmp_path / "profiles" / "KuaishouProfile").mkdir(parents=True, exist_ok=True)
    fake = _FakeLoginProc()
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {platform: fake})
    result = asyncio.run(web.api_logout(platform))
    assert result["ok"] is True
    assert fake.terminated is True, "登出必须停掉仍在跑的登录进程，否则它会把 success 标记写回"
    assert platform not in web.LOGIN_PROCESSES


# ── web/app.py：_schedule.json 读-改-写必须有共享锁 ─────────────────────
def test_schedule_lock_is_a_shared_singleton():
    lock = web._schedule_lock()
    assert callable(getattr(lock, "acquire", None)) and callable(getattr(lock, "release", None))
    assert web._schedule_lock() is lock, "发布回流与增删改端点必须共用同一把锁"


# ── doctor：healthz 回环探针不得走继承的 http_proxy ─────────────────────
def test_gateway_healthz_bypasses_inherited_proxy(monkeypatch):
    from easel.commands import doctor

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        monkeypatch.setattr(doctor, "healthz_url",
                             lambda: f"http://127.0.0.1:{port}/healthz")
        # 黑洞代理：若探针继承系统代理，会连到 10.255.255.1:9 并超时 → 误报 FAIL
        monkeypatch.setenv("http_proxy", "http://10.255.255.1:9")
        monkeypatch.setenv("HTTP_PROXY", "http://10.255.255.1:9")
        monkeypatch.setenv("https_proxy", "http://10.255.255.1:9")
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("NO_PROXY", raising=False)
        assert doctor._gateway_healthy() is True
    finally:
        server.shutdown()
        server.server_close()


# ── video_ops：cut 的 --start+--end 必须产出 [start,end) 片段 ────────────
def test_video_cut_start_end_duration_math(tmp_path, monkeypatch):
    video_ops = _load("video_ops_fix", SHARED / "video_ops.py")
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    captured: list[list[str]] = []
    monkeypatch.setattr(video_ops, "_run", lambda cmd, **kw: captured.append(cmd))

    def run_cut(**kw):
        args = SimpleNamespace(
            input=str(src), output=str(tmp_path / kw.pop("out")),
            start=kw.pop("start", None), end=kw.pop("end", None),
            duration=kw.pop("duration", None), reencode=False, crf=23, preset="medium")
        assert not kw, kw
        return video_ops.cmd_cut(args)

    # 2s→6s：输入侧 -ss 归零时间戳后，输出侧时长必须是 end-start=4s
    run_cut(out="o1.mp4", start="00:00:02", end="00:00:06")
    cmd = captured[-1]
    assert cmd[0:2] == ["ffmpeg", "-y"]
    assert cmd[2:4] == ["-ss", "00:00:02"], "输入侧 -ss 保留（快速关键帧定位）"
    assert "-to" not in cmd, "--start+--end 不能用输出侧 -to（从新零点起算会得到 [2s,8s)）"
    i = cmd.index("-t")
    assert abs(float(cmd[i + 1]) - 4.0) < 0.01, cmd

    # 只有 --end：无 -ss，-to 从原始 0 点起算 → 正确
    run_cut(out="o2.mp4", end="6")
    assert "-to" in captured[-1] and "-ss" not in captured[-1]

    # start>end：报错退出而不是产出空片段
    with pytest.raises(SystemExit):
        run_cut(out="o3.mp4", start="10", end="2")


def test_video_tsec_parses_ffmpeg_time_forms():
    video_ops = _load("video_ops_tsec", SHARED / "video_ops.py")
    t = video_ops._tsec
    assert t("90") == 90.0
    assert t("90.5") == 90.5
    assert t("00:01:30") == 90.0
    assert t("1:30") == 90.0
    assert t("1:2:3.5") == 3723.5
    for bad in ("", "1:2:3:4", "abc", "-5", "1:30:"):
        with pytest.raises(ValueError):
            t(bad)


# ── intro_outro：card 的 logo 恒为输入 1（--bg-image 不再 +1） ──────────
def test_card_logo_is_always_input_one(tmp_path, monkeypatch):
    intro = _load("intro_outro_fix", SHARED / "intro_outro.py")
    bg = tmp_path / "bg.png"; bg.write_bytes(b"x")
    logo = tmp_path / "logo.png"; logo.write_bytes(b"x")
    out = tmp_path / "card.mp4"
    captured: list[list[str]] = []
    monkeypatch.setattr(intro, "_check_ffmpeg", lambda: None)
    monkeypatch.setattr(intro, "_find_font", lambda explicit=None: "/tmp/font.ttf")
    monkeypatch.setattr(intro, "_run", lambda cmd: captured.append(cmd))
    argv = ["intro_outro.py", "card", "-o", str(out),
            "--bg-image", str(bg), "--logo", str(logo),
            "--title", "测试", "--duration", "2"]
    monkeypatch.setattr(sys, "argv", argv)
    intro.main()
    cmd = captured[-1]
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:v]scale=" in graph, "logo 必须引用输入 1：背景恒占一个 -i（见 _audio_idx 注释）"
    assert "[2:v]" not in graph, "带 --bg-image 时旧代码错指 [2:v]（anullsrc 音频输入）→ filtergraph 必挂"
    # 输入布局：0=bg，1=logo，2=anullsrc；音频 map 仍指最后一个输入
    assert cmd[cmd.index("-map") + 1] == "[vout]"
    assert cmd[cmd.index("-map") + 3] == "2:a", "anullsrc 是输入 2，音频 map 应为 2:a"


# ── content_guard：私网 IP 正则不吞 3 段版本号 ──────────────────────────
def test_content_guard_private_ip_regex(tmp_path, monkeypatch):
    guard = _load("content_guard_fix", SHARED / "content_guard.py")
    monkeypatch.chdir(tmp_path)          # 无 .env → 字面值通道为空

    def cats(text):
        return [f.category for f in guard.scan(text)]

    # 真私网 IP（4 段）必须命中 BLOCK 级 proxy-ip
    assert "proxy-ip" in cats("内网机器 10.1.2.3:8080 走代理")
    assert "proxy-ip" in cats("路由器后台 192.168.1.1 默认密码")
    assert "proxy-ip" in cats("手机热点网段 172.20.10.1")
    # 3 段版本号形态（旧正则 {2,3} 会误拦发布）
    assert "proxy-ip" not in cats("升级到 macOS 10.15.7 后再试")
    assert "proxy-ip" not in cats("版本 10.3.2 修复了问题")
    assert "proxy-ip" not in cats("10.15.7")


# ── image_ops：compress 低 quality + --max-kb 不再 TypeError ────────────
def test_image_compress_low_quality_with_max_kb(tmp_path):
    from PIL import Image
    image_ops = _load("image_ops_fix", SHARED / "image_ops.py")
    src = tmp_path / "big.jpg"
    Image.new("RGB", (256, 256),
              tuple(200 - i % 64 for i in range(3))).save(src, quality=95)
    out = tmp_path / "small.jpg"

    def run(quality, max_kb):
        args = SimpleNamespace(input=str(src), output=str(out),
                               quality=quality, max_kb=max_kb)
        return image_ops.cmd_compress(args)

    # quality=5：旧代码 range(5,9,-5) 为空 → best=None → len(None) 崩
    assert run(quality=5, max_kb=10240) == 0
    assert out.is_file() and out.stat().st_size > 0
    # 永远压不到目标的兜底路径也不崩，仍产出文件 + WARN
    assert run(quality=5, max_kb=1) == 0
    assert out.is_file() and out.stat().st_size > 0


# ── gemini_maas_adapter：非流式 finishReason 与流式一致 ────────────────
def test_gemini_adapter_non_streaming_finish_reason():
    adapter = _load("gemini_adapter_fix", SCRIPTS / "gemini_maas_adapter.py")
    base = {"usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2,
                              "thoughtsTokenCount": 0, "totalTokenCount": 3}}

    def finish_for(candidate_extra):
        data = dict(base)
        data["candidates"] = [dict({"content": {"parts": [{"text": "hi"}]}},
                                   **candidate_extra)]
        return adapter.gemini_to_openai(data, "gemini-pro")["choices"][0]["finish_reason"]

    assert finish_for({"finishReason": "MAX_TOKENS"}) == "length"
    assert finish_for({"finishReason": "SAFETY"}) == "content_filter"
    assert finish_for({"finishReason": "STOP"}) == "stop"
    assert finish_for({}) == "stop"
    # 工具调用优先于 STOP：客户端要继续 tool loop
    data = dict(base)
    data["candidates"] = [{"finishReason": "STOP", "content": {"parts": [
        {"functionCall": {"name": "f", "args": {}}}]}}]
    assert adapter.gemini_to_openai(data, "m")["choices"][0]["finish_reason"] == "tool_calls"
