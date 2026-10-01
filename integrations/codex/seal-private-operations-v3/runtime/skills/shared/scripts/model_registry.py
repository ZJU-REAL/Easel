"""Shared media-model provider metadata for scripts and the Web configuration UI."""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any
from pathlib import Path


def _key(env: str, label: str, *, required: bool = True, secret: bool = True,
         aliases: tuple[str, ...] = (), choices: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "env": env,
        "label": label,
        "required": required,
        "secret": secret,
        "aliases": aliases,
        "choices": choices,
    }


MODEL_GROUPS: dict[str, dict[str, Any]] = {
    "image": {
        "label": "AI 生图",
        "settings": [],
        "providers": [{
            "id": "openai",
            "name": "OpenAI 兼容 / apimart / 小红书 MaaS",
            "keys": [
                _key("IMG_API_KEY", "API Key", aliases=("OPENAI_API_KEY", "API_KEY")),
                _key("IMG_BASE_URL", "API 根地址", secret=False,
                     aliases=("OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL")),
                _key("IMG_MODEL", "模型", required=False, secret=False),
                _key("IMG_API_KEY_HEADER", "鉴权头名", required=False, secret=False),
                _key("IMG_API_VERSION", "api-version", required=False, secret=False),
                _key("IMG_NO_PROXY", "内网直连（填 1）", required=False, secret=False),
            ],
        }],
    },
    "video": {
        "label": "AI 视频生成",
        "settings": [
            _key("VIDEO_PROVIDER", "默认视频 provider", required=False, secret=False,
                 choices=("dashscope", "ark", "kling", "openai-compatible", "xhs-maas", "agnes")),
            _key("VIDEO_CAPABILITIES_JSON", "模型能力覆盖 JSON", required=False, secret=False),
        ],
        "providers": [
            {
                "id": "dashscope", "name": "阿里通义万相 Wan", "keys": [
                    _key("DASHSCOPE_API_KEY", "DashScope API Key",
                         aliases=("DASHSCOPE_KEY", "ALIYUN_API_KEY")),
                    _key("DASHSCOPE_VIDEO_MODEL", "视频模型", required=False, secret=False,
                         aliases=("DASHSCOPE_MODEL",)),
                    _key("DASHSCOPE_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "ark", "name": "火山引擎 Seedance", "keys": [
                    _key("ARK_API_KEY", "Ark API Key",
                         aliases=("VOLCENGINE_API_KEY", "VOLC_ARK_API_KEY")),
                    _key("ARK_MODEL", "视频模型", required=False, secret=False),
                    _key("ARK_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "kling", "name": "快手可灵", "keys": [
                    _key("KLING_ACCESS_KEY", "Access Key"),
                    _key("KLING_SECRET_KEY", "Secret Key"),
                    _key("KLING_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "openai-compatible", "name": "OpenAI 兼容 /videos", "keys": [
                    _key("VIDEO_API_KEY", "API Key", aliases=("OPENAI_API_KEY", "API_KEY")),
                    _key("VIDEO_BASE_URL", "API 根地址", secret=False,
                         aliases=("OPENAI_BASE_URL", "BASE_URL")),
                    _key("VIDEO_MODEL", "视频模型", required=False, secret=False,
                         aliases=("VIDEO_MODEL_NAME",)),
                ],
            },
            {
                "id": "xhs-maas", "name": "小红书 MaaS（happyhorse）", "keys": [
                    _key("XHS_MAAS_API_KEY", "MaaS api-key"),
                    _key("XHS_MAAS_VIDEO_BASE", "视频端点根地址", required=False, secret=False),
                    _key("XHS_MAAS_T2V_MODEL", "文生视频模型", required=False, secret=False),
                    _key("XHS_MAAS_I2V_MODEL", "图生视频模型", required=False, secret=False),
                    _key("XHS_MAAS_RESOLUTION", "分辨率", required=False, secret=False),
                ],
            },
            {
                "id": "agnes", "name": "Agnes Video", "keys": [
                    _key("AGNES_API_KEY", "Agnes API Key"),
                    _key("AGNES_BASE_URL", "创建端点根地址", required=False, secret=False),
                    _key("AGNES_POLL_BASE", "轮询端点", required=False, secret=False),
                    _key("AGNES_MODEL", "视频模型", required=False, secret=False),
                    _key("AGNES_SIZE", "分辨率", required=False, secret=False),
                ],
            },
        ],
    },
    "music": {
        "label": "AI 音乐 / BGM",
        "settings": [
            _key("MUSIC_PROVIDER", "默认音乐 provider", required=False, secret=False,
                 choices=("dashscope", "suno-compatible")),
        ],
        "providers": [
            {
                "id": "dashscope", "name": "阿里 DashScope", "keys": [
                    _key("DASHSCOPE_API_KEY", "DashScope API Key",
                         aliases=("DASHSCOPE_KEY", "ALIYUN_API_KEY")),
                    _key("DASHSCOPE_MUSIC_MODEL", "音乐模型", required=False, secret=False,
                         aliases=("DASHSCOPE_MODEL",)),
                    _key("DASHSCOPE_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "suno-compatible", "name": "Suno 类第三方 API", "keys": [
                    _key("MUSIC_API_KEY", "API Key", aliases=("SUNO_API_KEY", "API_KEY")),
                    _key("MUSIC_BASE_URL", "API 根地址", secret=False,
                         aliases=("SUNO_BASE_URL", "BASE_URL")),
                    _key("MUSIC_MODEL", "音乐模型", required=False, secret=False),
                ],
            },
        ],
    },
    "voice": {
        "label": "云端语音 / 声音克隆",
        "settings": [
            _key("VOICE_PROVIDER", "默认语音 provider", required=False, secret=False,
                 choices=("dashscope", "minimax", "fish-audio", "openai-compatible", "gemini")),
            _key("VOICE_NARRATOR_VOICE_ID", "默认旁白 voice-id", required=False, secret=False),
        ],
        "providers": [
            {
                "id": "dashscope", "name": "阿里 CosyVoice", "keys": [
                    _key("DASHSCOPE_API_KEY", "DashScope API Key",
                         aliases=("DASHSCOPE_KEY", "ALIYUN_API_KEY")),
                    _key("DASHSCOPE_TTS_MODEL", "TTS 模型", required=False, secret=False),
                    _key("DASHSCOPE_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "minimax", "name": "MiniMax", "keys": [
                    _key("MINIMAX_API_KEY", "API Key"),
                    _key("MINIMAX_GROUP_ID", "Group ID", secret=False),
                    _key("MINIMAX_MODEL", "TTS 模型", required=False, secret=False),
                    _key("MINIMAX_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "fish-audio", "name": "Fish Audio", "keys": [
                    _key("FISH_API_KEY", "API Key"),
                    _key("FISH_BASE_URL", "根地址", required=False, secret=False),
                ],
            },
            {
                "id": "openai-compatible", "name": "OpenAI 兼容 /audio/speech", "keys": [
                    _key("VOICE_API_KEY", "API Key", aliases=("OPENAI_API_KEY", "API_KEY")),
                    _key("VOICE_BASE_URL", "API 根地址", secret=False,
                         aliases=("OPENAI_BASE_URL", "BASE_URL")),
                    _key("VOICE_MODEL", "TTS 模型", required=False, secret=False),
                    _key("VOICE_INSTRUCT_MODE", "情感指令模式", required=False, secret=False,
                         choices=("field", "inline")),
                    _key("VOICE_INSTRUCT_DELIM", "内联指令分隔符", required=False, secret=False),
                ],
            },
            {
                "id": "gemini", "name": "Google Gemini TTS", "keys": [
                    _key("GEMINI_API_KEY", "Gemini API Key",
                         aliases=("GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY")),
                    _key("GEMINI_TTS_MODEL", "TTS 模型", required=False, secret=False),
                    _key("GEMINI_VOICE", "预置音色", required=False, secret=False),
                    _key("GEMINI_BASE_URL", "根地址", required=False, secret=False),
                    _key("GEMINI_TTS_RATE", "采样率", required=False, secret=False),
                ],
            },
        ],
    },
}


def model_group(name: str) -> dict[str, Any]:
    return MODEL_GROUPS[name]


def provider_ids(group: str) -> tuple[str, ...]:
    return tuple(provider["id"] for provider in MODEL_GROUPS[group]["providers"])


def provider_required_env(group: str) -> dict[str, tuple[tuple[str, bool], ...]]:
    return {
        provider["id"]: tuple((key["env"], bool(key["required"])) for key in provider["keys"])
        for provider in MODEL_GROUPS[group]["providers"]
    }


def env_aliases(group: str) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {}
    spec = MODEL_GROUPS[group]
    for key in [*spec.get("settings", []),
                *(key for provider in spec["providers"] for key in provider["keys"])]:
        if key.get("aliases"):
            aliases[key["env"]] = tuple(key["aliases"])
    return aliases


_PLACEHOLDER_RE = re.compile(r"replace_me|your[-_]?api[-_]?key|xxx|^\.{3}$|^<.*>$", re.I)


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """Read KEY=value without evaluating shell syntax; process env takes precedence."""
    if path is None:
        for directory in (Path.cwd(), *Path.cwd().parents):
            candidate = directory / ".env"
            if candidate.is_file():
                path = candidate
                break
    values: dict[str, str] = {}
    if path and path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def _configured_value(key: dict[str, Any], env: dict[str, str]) -> str:
    for name in (key["env"], *key.get("aliases", ())):
        value = str(env.get(name, "")).strip()
        if value and not _PLACEHOLDER_RE.search(value):
            return value
    return ""


def configured_providers(group: str, env: dict[str, str]) -> list[dict[str, Any]]:
    """Return usable providers and non-secret model names without exposing credentials."""
    configured = []
    for provider in MODEL_GROUPS[group]["providers"]:
        required = [key for key in provider["keys"] if key["required"]]
        if not all(_configured_value(key, env) for key in required):
            continue
        models = {
            key["env"]: _configured_value(key, env)
            for key in provider["keys"]
            if not key["secret"] and "MODEL" in key["env"] and _configured_value(key, env)
        }
        configured.append({"id": provider["id"], "name": provider["name"], "models": models})
    return configured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查询已配置的媒体模型 provider（不输出密钥）")
    sub = parser.add_subparsers(dest="command", required=True)
    configured = sub.add_parser("configured", help="列出必填凭证已齐全的 provider")
    configured.add_argument("--group", required=True, choices=tuple(MODEL_GROUPS))
    configured.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    providers = configured_providers(args.group, read_env_file(args.env_file))
    print(json.dumps({"group": args.group, "count": len(providers), "configured": providers},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
