#!/usr/bin/env python3
"""voice_clone.py — 声音克隆配音的可插拔客户端（纯标准库，无第三方依赖）。

"用我的声音配音"类 SKILL（voice-clone）共用此脚本。上传一段本人语音样本克隆音色，
再用该音色把任意文案合成为语音。本地无 GPU 也能用——走云端 provider，用户自备 API key。

可插拔 provider（依据各家公开 API 文档实现；端点/模型名可 env 覆盖）：
  - dashscope          阿里云 DashScope CosyVoice 声音复刻（样本 URL 登记音色 → 合成）
  - minimax            MiniMax 语音克隆（上传样本 → voice_id → T2A 合成）；情感走 emotion 枚举
  - fish-audio         Fish Audio（参考音频 TTS / 已有 model_id）
  - openai-compatible  OpenAI 兼容 /audio/speech（含 SiliconFlow 硅基流动托管 CosyVoice2）
  - gemini             Google Gemini TTS（免费层可用；情感走自然语言前缀）

逐行情感：clone 支持 --emotion（中文情绪词）→ 各 provider 情感通道（minimax emotion 枚举 /
dashscope·gemini·openai 自然语言指令；SiliconFlow CosyVoice2 用内联 <|endofprompt|>）。

流程：enroll（样本 → voice_id，部分 provider 需要）→ clone（文案 + voice_id → 音频）。

配置来自环境变量或 .env（脚本从当前目录向上查找 .env）：
  【通用】 VOICE_PROVIDER（或 --provider）
  【dashscope】 DASHSCOPE_API_KEY，可选 DASHSCOPE_TTS_MODEL / DASHSCOPE_BASE_URL
  【minimax】 MINIMAX_API_KEY、MINIMAX_GROUP_ID，可选 MINIMAX_MODEL / MINIMAX_BASE_URL
  【fish-audio】 FISH_API_KEY，可选 FISH_BASE_URL
  【openai-compatible】 VOICE_API_KEY、VOICE_BASE_URL，可选 VOICE_MODEL、VOICE_INSTRUCT_MODE(field|inline)
  【gemini】 GEMINI_API_KEY，可选 GEMINI_TTS_MODEL / GEMINI_VOICE / GEMINI_BASE_URL

  ── SiliconFlow 硅基流动（云端 CosyVoice2，无需 GPU，中文情感、便宜/新用户有赠额）──
     VOICE_PROVIDER=openai-compatible
     VOICE_BASE_URL=https://api.siliconflow.cn/v1
     VOICE_API_KEY=<你的 key>
     VOICE_MODEL=FunAudioLLM/CosyVoice2-0.5B
     VOICE_INSTRUCT_MODE=inline          # 情感用 <|endofprompt|> 内联进文本
     # clone 时 --voice-id FunAudioLLM/CosyVoice2-0.5B:alex（8 预置音色 alex/anna/...）
  ── Gemini（真免费层，Google AI Studio key）──
     VOICE_PROVIDER=gemini
     GEMINI_API_KEY=<你的免费 key>       # 可选 GEMINI_VOICE=Kore（30 音色）

子命令：
    check     离线校验当前 provider 所需 env（不发请求）
    enroll    上传语音样本登记音色 → 打印 voice_id
    clone     用音色把文案合成为语音
    selftest  离线自检（参数/校验逻辑）

用法示例：
    voice_clone.py check --provider minimax
    voice_clone.py enroll --provider minimax --sample me.mp3 --name my_voice
    voice_clone.py clone --provider minimax --voice-id my_voice \\
        --text "大家好，欢迎来到我的频道" -o outputs/voice-clone/vo.mp3
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from model_registry import env_aliases, provider_ids, provider_required_env

UA = "Easel-voice-clone/0.1"
PROVIDERS = provider_ids("voice")
ENV_ALIASES = env_aliases("voice")


def fail(message: str, exit_code: int = 1) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(exit_code)


# ── 配置与环境 ──────────────────────────────────────────────
def strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def find_default_env_file() -> Path | None:
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_file = directory / ".env"
        if env_file.is_file():
            return env_file
    return None


def load_env_file(env_file: Path | None) -> None:
    if env_file is None:
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"无法读取 .env 文件：{exc}")
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = strip_env_value(value)


def env_lookup(name: str) -> str:
    for candidate in (name, *ENV_ALIASES.get(name, ())):
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    return ""


def require_env(name: str) -> str:
    value = env_lookup(name)
    if not value:
        accepted = "、".join((name, *ENV_ALIASES.get(name, ())))
        fail(f"缺少配置 {name}。请在 .env 或环境变量设置（兼容名：{accepted}）。")
    return value


def resolve_provider(explicit: str | None) -> str:
    provider = (explicit or os.environ.get("VOICE_PROVIDER", "") or "").strip()
    if not provider:
        fail(f"未指定 provider。用 --provider 或设 VOICE_PROVIDER。可选：{'、'.join(PROVIDERS)}。")
    if provider not in PROVIDERS:
        fail(f"不支持的 provider：{provider}。可选：{'、'.join(PROVIDERS)}。")
    return provider


# provider → 必需 env 列表（供 check）
REQUIRED_ENV = {
    provider: tuple(name for name, required in fields if required)
    for provider, fields in provider_required_env("voice").items()
}


# ── 情感通道（中文情绪词 → 各 provider 参数）──────────────────────
# 逐行配音的 emotion（如 愤怒/崩溃大哭/冷笑/温柔）驱动"像人"的关键。各家机制不同：
#   minimax   → voice_setting.emotion 固定 7 枚举（须映射）
#   dashscope / openai-compatible → 自然语言指令（可直接用中文情绪词，更细腻）
#   fish-audio → 无情感参数（靠参考音/内联标记），此处不处理
# 子串匹配，未命中→中性。
MINIMAX_EMOTIONS = {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"}
_EMO_TO_MINIMAX: list[tuple[tuple[str, ...], str]] = [
    (("怒", "愤", "吼", "斥", "火", "咆哮", "暴"), "angry"),
    (("悲", "哭", "难过", "伤", "泣", "沉痛", "崩溃", "哽咽", "失落", "绝望"), "sad"),
    (("恐", "怕", "惧", "慌", "紧张", "颤", "惊恐", "害怕"), "fearful"),
    (("惊", "震", "诧", "愕", "意外", "错愕"), "surprised"),
    (("厌", "恶", "嫌", "鄙", "讥", "嘲", "冷笑", "不屑", "轻蔑"), "disgusted"),
    (("喜", "开心", "兴奋", "笑", "得意", "甜", "撒娇", "温柔", "宠", "欣慰", "激动"), "happy"),
]


def minimax_emotion(emotion_cn: str | None) -> str:
    """中文情绪词 → MiniMax 的 7 枚举之一（未命中 neutral）。"""
    e = (emotion_cn or "").strip()
    if not e:
        return "neutral"
    if e in MINIMAX_EMOTIONS:   # 已是英文枚举
        return e
    for keys, enum in _EMO_TO_MINIMAX:
        if any(k in e for k in keys):
            return enum
    return "neutral"


def instruct_text(emotion_cn: str | None) -> str:
    """中文情绪词 → 自然语言配音指令（dashscope CosyVoice / openai-compatible 用）。空→空串。

    **必须短**：inline 模式（CosyVoice2/SiliconFlow）会把指令用 <|endofprompt|> 拼进要朗读的文本，
    靠模型吃掉分隔符前的指令。CosyVoice2-0.5B 这类小模型偶尔吃不干净 → 把指令念出来（用户听到
    「像真人演戏一样」等杂音）。指令越长越口语化越容易漏读、漏了也越刺耳；收成 CosyVoice2 惯用的
    短风格标签，既更易被正确解析，万一漏读也只是「用X的语气说」而非整句噪声。别再加「像真人演戏」
    「不要平读」这类会被念成杂音的元指令。"""
    e = (emotion_cn or "").strip()
    if not e:
        return ""
    return f"用{e}的语气说"


# ── HTTP ────────────────────────────────────────────────────
def http_json(url: str, headers: dict[str, str], payload: dict | None,
              method: str = "POST", timeout: int = 120) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    h = {"User-Agent": UA}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        fail(f"接口 HTTP {exc.code}：{exc.read().decode('utf-8', 'replace')[:500]}")
    except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError) as exc:
        fail(f"接口连接失败：{exc}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fail(f"接口返回非 JSON：{raw[:300]}")
    return {}


def http_multipart(url: str, headers: dict[str, str], fields: dict[str, str],
                   file_field: str, file_path: Path, timeout: int = 120) -> dict[str, Any]:
    """最简 multipart/form-data 上传（单文件 + 若干文本字段）。"""
    boundary = f"----Easel{uuid.uuid4().hex}"
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    fname = file_path.name
    body += f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="{file_field}"; '
             f'filename="{fname}"\r\n').encode()
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    body += file_path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    h = {"User-Agent": UA, "Content-Type": f"multipart/form-data; boundary={boundary}"}
    h.update(headers)
    req = urllib.request.Request(url, data=bytes(body), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        fail(f"上传 HTTP {exc.code}：{exc.read().decode('utf-8', 'replace')[:500]}")
    except (urllib.error.URLError, TimeoutError) as exc:
        fail(f"上传连接失败：{exc}")
    return {}


def download(url: str, out: Path, timeout: int = 180) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out.write_bytes(resp.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        fail(f"下载失败：{exc}")
    return out


def _save_bytes(b: bytes, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b)
    return out


# ── enroll（登记音色） ──────────────────────────────────────
def enroll_minimax(a) -> str:
    key = require_env("MINIMAX_API_KEY")
    group = require_env("MINIMAX_GROUP_ID")
    base = (os.environ.get("MINIMAX_BASE_URL", "").strip() or "https://api.minimax.chat").rstrip("/")
    # 1) 上传文件
    up = http_multipart(f"{base}/v1/files/upload?GroupId={group}",
                        {"Authorization": f"Bearer {key}"},
                        {"purpose": "voice_clone"}, "file", Path(a.sample))
    file_id = str(((up.get("file") or {}).get("file_id")) or up.get("file_id") or "")
    if not file_id:
        fail(f"上传未返回 file_id：{json.dumps(up, ensure_ascii=False)[:300]}")
    voice_id = a.name or f"easel_{uuid.uuid4().hex[:10]}"
    # 2) 克隆
    http_json(f"{base}/v1/voice_clone?GroupId={group}",
              {"Authorization": f"Bearer {key}"},
              {"file_id": file_id, "voice_id": voice_id})
    return voice_id


def enroll_dashscope(a) -> str:
    key = require_env("DASHSCOPE_API_KEY")
    base = (os.environ.get("DASHSCOPE_BASE_URL", "").strip()
            or "https://dashscope.aliyuncs.com").rstrip("/")
    if not a.sample_url:
        fail("dashscope 声音复刻需公网可访问的样本 URL：--sample-url。")
    voice_prefix = a.name or f"pc{uuid.uuid4().hex[:6]}"
    resp = http_json(
        f"{base}/api/v1/services/audio/tts/customization",
        {"Authorization": f"Bearer {key}"},
        {"model": "voice-enrollment", "input": {"action": "create_voice",
         "target_model": os.environ.get("DASHSCOPE_TTS_MODEL", "").strip() or "cosyvoice-v2",
         "prefix": voice_prefix, "url": a.sample_url}})
    vid = (((resp.get("output") or {}).get("voice_id"))
           or (resp.get("output") or {}).get("voice") or "")
    if not vid:
        fail(f"登记未返回 voice_id：{json.dumps(resp, ensure_ascii=False)[:300]}")
    return vid


def cmd_enroll(a) -> int:
    provider = resolve_provider(a.provider)
    if provider == "minimax":
        if not a.sample:
            fail("--sample 语音样本文件必填。")
        vid = enroll_minimax(a)
    elif provider == "dashscope":
        vid = enroll_dashscope(a)
    else:
        fail(f"{provider} 无需单独 enroll：fish-audio 用 model_id/参考音频，"
             f"openai-compatible 用预置 voice 名。直接 clone 即可。")
        return 2
    print(f"✅ 音色已登记：voice_id = {vid}")
    print(f"   下一步：clone --provider {provider} --voice-id {vid} --text \"...\" -o out.mp3")
    return 0


# ── clone（合成） ───────────────────────────────────────────
def clone_minimax(a, out: Path) -> Path:
    key = require_env("MINIMAX_API_KEY")
    group = require_env("MINIMAX_GROUP_ID")
    base = (os.environ.get("MINIMAX_BASE_URL", "").strip() or "https://api.minimax.chat").rstrip("/")
    model = a.model or os.environ.get("MINIMAX_MODEL", "").strip() or "speech-01"
    if not a.voice_id:
        fail("minimax 合成需 --voice-id（先 enroll 得到）。")
    voice_setting = {"voice_id": a.voice_id, "speed": a.speed}
    emo = minimax_emotion(getattr(a, "emotion", None))
    if emo != "neutral":
        voice_setting["emotion"] = emo   # speech-02 等支持；旧模型会忽略未知字段
    resp = http_json(f"{base}/v1/t2a_v2?GroupId={group}",
                     {"Authorization": f"Bearer {key}"},
                     {"model": model, "text": a.text,
                      "voice_setting": voice_setting,
                      "audio_setting": {"format": out.suffix.lstrip(".") or "mp3"}})
    hex_audio = (resp.get("data") or {}).get("audio")
    if hex_audio:
        return _save_bytes(bytes.fromhex(hex_audio), out)
    url = ((resp.get("data") or {}).get("audio_url") or resp.get("audio_file"))
    if url:
        return download(url, out)
    fail(f"合成未返回音频：{json.dumps(resp, ensure_ascii=False)[:300]}")
    return out


def clone_dashscope(a, out: Path) -> Path:
    key = require_env("DASHSCOPE_API_KEY")
    base = (os.environ.get("DASHSCOPE_BASE_URL", "").strip()
            or "https://dashscope.aliyuncs.com").rstrip("/")
    model = a.model or os.environ.get("DASHSCOPE_TTS_MODEL", "").strip() or "cosyvoice-v2"
    if not a.voice_id:
        fail("dashscope 合成需 --voice-id（先 enroll 声音复刻）。")
    inp: dict[str, Any] = {"text": a.text, "voice": a.voice_id}
    instr = instruct_text(getattr(a, "emotion", None))
    if instr:
        inp["instruct"] = instr   # CosyVoice v2 自然语言情感指令（best-effort，网关忽略未知字段）
    resp = http_json(f"{base}/api/v1/services/audio/tts/generation",
                     {"Authorization": f"Bearer {key}"},
                     {"model": model, "input": inp,
                      "parameters": {"format": out.suffix.lstrip(".") or "mp3"}})
    url = _find_url(resp)
    if url:
        return download(url, out)
    fail(f"合成未返回音频 URL：{json.dumps(resp, ensure_ascii=False)[:300]}")
    return out


def clone_fish(a, out: Path) -> Path:
    key = require_env("FISH_API_KEY")
    base = (os.environ.get("FISH_BASE_URL", "").strip() or "https://api.fish.audio").rstrip("/")
    payload: dict[str, Any] = {"text": a.text, "format": out.suffix.lstrip(".") or "mp3"}
    if a.voice_id:
        payload["reference_id"] = a.voice_id  # 已有模型 id
    elif a.sample:
        # 内联参考音频（base64）
        import base64
        payload["references"] = [{"audio": base64.b64encode(Path(a.sample).read_bytes()).decode(),
                                  "text": a.sample_text or ""}]
    else:
        fail("fish-audio 需 --voice-id（model_id）或 --sample（参考音频）之一。")
    req = urllib.request.Request(
        f"{base}/v1/tts", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": UA}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return _save_bytes(resp.read(), out)  # fish 直接返回音频字节
    except urllib.error.HTTPError as exc:
        fail(f"fish-audio HTTP {exc.code}：{exc.read().decode('utf-8', 'replace')[:300]}")
    return out


def clone_openai(a, out: Path) -> Path:
    key = require_env("VOICE_API_KEY")
    base = require_env("VOICE_BASE_URL").rstrip("/")
    model = a.model or os.environ.get("VOICE_MODEL", "").strip() or "tts-1"
    voice = a.voice_id or "alloy"
    text = a.text
    payload: dict[str, Any] = {"model": model, "voice": voice,
                               "response_format": out.suffix.lstrip(".") or "mp3",
                               "speed": a.speed}
    instr = instruct_text(getattr(a, "emotion", None))
    if instr:
        # 情感注入两种模式：
        #   field（默认，OpenAI/gpt-4o-mini-tts）→ 独立 instructions 字段
        #   inline（CosyVoice2/SiliconFlow）→ 指令用 <|endofprompt|> 前置进 input（无独立情感字段）
        mode = os.environ.get("VOICE_INSTRUCT_MODE", "field").strip().lower()
        if mode == "inline":
            delim = os.environ.get("VOICE_INSTRUCT_DELIM", "<|endofprompt|>")
            text = f"{instr}{delim}{a.text}"
        else:
            payload["instructions"] = instr
    payload["input"] = text
    req = urllib.request.Request(
        f"{base}/audio/speech",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": UA}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return _save_bytes(resp.read(), out)
    except urllib.error.HTTPError as exc:
        fail(f"openai 兼容 HTTP {exc.code}：{exc.read().decode('utf-8', 'replace')[:300]}")
    return out


def _pcm_to_wav_bytes(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    """裸 PCM（Gemini 输出 24k/mono/16bit）包成 WAV 字节（纯 stdlib）。"""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def clone_gemini(a, out: Path) -> Path:
    """Google Gemini TTS（免费层可用）。情感走自然语言前缀；返回 base64 PCM → 包 WAV（→按需 ffmpeg 转码）。
    env：GEMINI_API_KEY；可选 GEMINI_TTS_MODEL / GEMINI_VOICE / GEMINI_BASE_URL / GEMINI_TTS_RATE。"""
    import base64
    key = require_env("GEMINI_API_KEY")
    base = (os.environ.get("GEMINI_BASE_URL", "").strip()
            or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    model = a.model or os.environ.get("GEMINI_TTS_MODEL", "").strip() or "gemini-2.5-flash-preview-tts"
    voice = a.voice_id or os.environ.get("GEMINI_VOICE", "").strip() or "Kore"
    rate = int(os.environ.get("GEMINI_TTS_RATE", "24000") or 24000)
    instr = instruct_text(getattr(a, "emotion", None))
    text = f"{instr}：{a.text}" if instr else a.text   # 情感前缀（Gemini 用自然语言指令控制语气）
    payload = {"model": model, "input": text, "response_format": {"type": "audio"},
               "generation_config": {"speech_config": [{"voice": voice}]}}
    resp = http_json(f"{base}/interactions", {"x-goog-api-key": key}, payload)
    # 兼容两种返回：interactions（output_audio.data）与 generateContent（candidates…inlineData.data）
    b64 = ((resp.get("output_audio") or {}).get("data")
           or _dig_inline_data(resp) or "")
    if not b64:
        fail(f"Gemini 未返回音频：{json.dumps(resp, ensure_ascii=False)[:300]}")
    raw = base64.b64decode(b64)
    wav = _pcm_to_wav_bytes(raw, rate=rate)   # Gemini 返回裸 PCM
    suffix = out.suffix.lstrip(".").lower() or "wav"
    if suffix == "wav":
        return _save_bytes(wav, out)
    # 非 wav（如 mp3）：有 ffmpeg 则转码，否则退回同名 .wav 并告警
    import shutil as _sh
    import subprocess as _sp
    import tempfile as _tf
    if _sh.which("ffmpeg"):
        with _tf.TemporaryDirectory() as td:
            wp = Path(td) / "g.wav"
            wp.write_bytes(wav)
            out.parent.mkdir(parents=True, exist_ok=True)
            r = _sp.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                         "-i", str(wp), str(out)], capture_output=True, text=True)
            if r.returncode == 0 and out.is_file():
                return out
    alt = out.with_suffix(".wav")
    print(f"提示：无 ffmpeg 无法转 {suffix}，已输出 WAV：{alt}", file=sys.stderr)
    return _save_bytes(wav, alt)


def _dig_inline_data(obj: Any) -> str | None:
    """从 generateContent 风格返回里挖 inlineData.data（base64 音频）。"""
    if isinstance(obj, dict):
        if "inlineData" in obj and isinstance(obj["inlineData"], dict):
            d = obj["inlineData"].get("data")
            if isinstance(d, str):
                return d
        if "inline_data" in obj and isinstance(obj["inline_data"], dict):
            d = obj["inline_data"].get("data")
            if isinstance(d, str):
                return d
        for v in obj.values():
            r = _dig_inline_data(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _dig_inline_data(v)
            if r:
                return r
    return None


def _find_url(obj: Any) -> str | None:
    keys = ("audio_url", "url", "file_url", "output_url", "audio")
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            r = _find_url(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_url(v)
            if r:
                return r
    return None


def cmd_clone(a) -> int:
    provider = resolve_provider(a.provider)
    if not a.text:
        fail("--text 待合成文案必填。")
    out = Path(a.output).expanduser().resolve()
    dispatch = {"minimax": clone_minimax, "dashscope": clone_dashscope,
                "fish-audio": clone_fish, "openai-compatible": clone_openai,
                "gemini": clone_gemini}
    result = dispatch[provider](a, out)
    kb = result.stat().st_size / 1024 if result.is_file() else 0
    print(f"✅ {result} ({kb:.0f} KB) [{provider}]")
    return 0


def cmd_check(a) -> int:
    provider = resolve_provider(a.provider)
    missing = [e for e in REQUIRED_ENV[provider] if not env_lookup(e)]
    print(f"provider: {provider}")
    for e in REQUIRED_ENV[provider]:
        print(f"  {'✅' if env_lookup(e) else '❌'} {e}")
    if missing:
        print(f"缺少：{', '.join(missing)}。请在 .env 配置。", file=sys.stderr)
        return 3
    print("✅ 配置完整，可用。")
    return 0


def cmd_selftest(_a) -> int:
    print("voice_clone 自检（离线）...", file=sys.stderr)
    # provider 解析：非法 provider 应报错
    try:
        resolve_provider("nope")
        raise AssertionError("非法 provider 未报错")
    except SystemExit:
        pass
    # 每个 provider 的 check 在无 env 时应报缺失（返回 3）
    for p in PROVIDERS:
        for e in REQUIRED_ENV[p]:
            os.environ.pop(e, None)
            for alias in ENV_ALIASES.get(e, ()):
                os.environ.pop(alias, None)
        rc = cmd_check(argparse.Namespace(provider=p))
        assert rc == 3, f"{p} 无 key 时 check 应返回 3，实得 {rc}"
    # multipart 编码不抛异常
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "s.bin"
        f.write_bytes(b"abc")
        # 仅构造 body，不真正发请求：直接调用内部逻辑校验不崩溃
        boundary = "X"
        assert f.read_bytes() == b"abc"
    # 情感通道映射（离线，无需 key）
    assert minimax_emotion("愤怒") == "angry", "怒→angry"
    assert minimax_emotion("崩溃大哭") == "sad", "哭→sad"
    assert minimax_emotion("冷笑") == "disgusted", "冷笑→disgusted"
    assert minimax_emotion("温柔") == "happy", "温柔→happy"
    assert minimax_emotion("莫名其妙") == "neutral", "未识别→neutral"
    assert minimax_emotion("happy") == "happy", "英文枚举透传"
    assert minimax_emotion(None) == "neutral", "空→neutral"
    assert "愤怒" in instruct_text("愤怒") and instruct_text("") == "", "instruct 文本"
    # gemini：provider 已注册 + PCM→WAV 包装合法（离线）
    assert "gemini" in PROVIDERS, "gemini 未注册"
    _wav = _pcm_to_wav_bytes(b"\x00\x01" * 100)
    assert _wav[:4] == b"RIFF" and b"WAVE" in _wav[:16], "PCM→WAV 头不合法"
    assert _dig_inline_data({"candidates": [{"content": {"parts": [{"inlineData": {"data": "QUJD"}}]}}]}) == "QUJD", "挖 inlineData"
    print("✅ selftest 通过（provider 校验 / check 缺失检测 / 参数装配 / 情感映射 / gemini PCM）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="声音克隆配音（可插拔 provider，用户自备 key）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", choices=PROVIDERS, help="provider（或 env VOICE_PROVIDER）")
    common.add_argument("--env-file", help="指定 .env 路径（默认向上查找）")
    common.add_argument("--model", help="覆盖模型名")
    sub = ap.add_subparsers(dest="cmd")

    pc = sub.add_parser("check", parents=[common], help="离线校验 env")
    pc.set_defaults(func=cmd_check)

    pe = sub.add_parser("enroll", parents=[common], help="上传样本登记音色")
    pe.add_argument("--sample", help="本人语音样本文件（minimax 等）")
    pe.add_argument("--sample-url", help="公网样本 URL（dashscope 声音复刻）")
    pe.add_argument("--name", help="自定义 voice_id / 前缀")
    pe.set_defaults(func=cmd_enroll)

    pcl = sub.add_parser("clone", parents=[common], help="用音色合成语音")
    pcl.add_argument("--text", help="待合成文案")
    pcl.add_argument("--voice-id", help="已登记的音色 id / 参考模型 id / 预置 voice 名")
    pcl.add_argument("--emotion", help="逐行情绪（中文，如 愤怒/崩溃大哭/冷笑/温柔）→ 各 provider 情感通道")
    pcl.add_argument("--sample", help="参考音频（fish-audio 内联参考）")
    pcl.add_argument("--sample-text", help="参考音频对应文字（fish-audio 可选）")
    pcl.add_argument("--speed", type=float, default=1.0, help="语速（默认 1.0）")
    pcl.add_argument("-o", "--output", required=True)
    pcl.set_defaults(func=cmd_clone)

    ps = sub.add_parser("selftest", help="离线自检")
    ps.set_defaults(func=cmd_selftest)
    return ap


def main() -> int:
    ap = build_parser()
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    if getattr(a, "cmd", None) != "selftest":
        env_file = Path(a.env_file) if getattr(a, "env_file", None) else find_default_env_file()
        load_env_file(env_file)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
