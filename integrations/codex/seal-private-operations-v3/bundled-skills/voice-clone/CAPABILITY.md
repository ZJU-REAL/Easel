---
name: voice-clone
description: "上传本人语音样本克隆专属音色，再用它合成口播、旁白或带货语音。当用户说“声音克隆、克隆/复刻我的声音、用我的声音配音、定制专属音色”时使用，需要用户自备云端 provider 凭证。使用公共现成音色时改用 tts-voiceover。"
layer: produce
---

# 声音克隆配音

> 用本人语音样本克隆音色，再合成任意文案。走云端 provider（用户自备 key），本地无需 GPU。
> 全部走 `skills/shared/scripts/voice_clone.py`。

> 不想克隆、用现成公共音色见 **tts-voiceover**（edge-tts，免费无需 key）；
> AI 生成音乐/BGM 见 **ai-music**；合成后与 BGM 混音见 **audio-mix**。

## 前置：配置 API key

> **配置检查路径铁律**：先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认当前目录有 `.env` 和 `skills/shared/scripts/`，再运行注册表、`check`、`enroll` 或 `clone`。不得改用 workspace 的 `./shared/scripts/...`，也不得以 `env` / `printenv` 没显示变量为由判断 `VOICE_BASE_URL`/Key 缺失。`check` 支持时显式传 `--env-file .env`。

选 provider 并在 `.env` 填 key，再 `check` 离线校验：
```bash
python skills/shared/scripts/voice_clone.py check --provider minimax --env-file .env
```

| provider | 服务 | .env 需配 |
|----------|------|----------|
| `dashscope` | 阿里 CosyVoice 声音复刻 | `DASHSCOPE_API_KEY`（可选 `DASHSCOPE_TTS_MODEL`/`DASHSCOPE_BASE_URL`） |
| `minimax` | MiniMax 语音克隆 | `MINIMAX_API_KEY`、`MINIMAX_GROUP_ID`（可选 `MINIMAX_MODEL`） |
| `fish-audio` | Fish Audio | `FISH_API_KEY`（可选 `FISH_BASE_URL`） |
| `openai-compatible` | OpenAI 兼容 /audio/speech | `VOICE_API_KEY`、`VOICE_BASE_URL`（预置 voice，非零样本克隆） |
| `gemini` | Google Gemini TTS | `GEMINI_API_KEY`（可选 `GEMINI_TTS_MODEL`/`GEMINI_VOICE`/`GEMINI_BASE_URL`） |

> ⚠️ 各 provider 依公开 API 文档实现，端点/模型名可用 env 覆盖以适配实际参数。

执行前先跑 `model_registry.py configured --group voice --env-file .env`。只有一个可用时显式选择；多个可用且用户没点名时，列出 provider/模型询问本次使用哪个，不按 `VOICE_PROVIDER` 擅自选择。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 语音样本 | 克隆时必填 | 本人清晰无噪的语音（一般 10s-1min，具体看 provider 要求） |
| 文案 | 合成时必填 | 要用克隆音色说出来的文字 |

## 输出（`outputs/主题名/`）

- 合成的语音音频（mp3/wav）

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/voice_clone.py`（各子命令支持 `-h`）。

### 1. 登记音色（enroll，得到 voice_id）
```bash
# minimax：上传样本文件
python skills/shared/scripts/voice_clone.py enroll --provider minimax \
  --sample me.mp3 --name my_voice
# dashscope：用公网可访问的样本 URL
python skills/shared/scripts/voice_clone.py enroll --provider dashscope \
  --sample-url https://.../me.wav --name myv
```
（fish-audio 用已有 model_id 或内联参考音频，openai-compatible 用预置 voice 名，无需 enroll。）

### 2. 合成（clone）
```bash
python skills/shared/scripts/voice_clone.py clone --provider minimax \
  --voice-id my_voice --text "大家好，欢迎来到我的频道" --speed 1.0 \
  -o outputs/主题名/vo.mp3
```
fish-audio 也可直接给参考音频：`--sample ref.mp3 --sample-text "参考音频的文字"`。

## 合规红线（必须遵守）

1. **只能克隆你有权使用的声音**（本人，或已获明确授权的人）。
2. **不得克隆他人/名人声音用于误导、诈骗、冒充、伪造**。
3. 合成内容不得用于虚假信息或侵权用途。
   —— 越线不做，并向用户说明。

## 规则

1. 样本质量决定克隆效果：清晰、无背景噪、语气自然、时长足够。
2. 先 `check` 确认 key，再 enroll，再 clone。
3. 合成语音可接 **audio-mix** 加 BGM、接 **auto-subtitle** 出字幕、接视频。
4. 产物统一进 `outputs/主题名/`。

## 参考来源

主流声音克隆云服务：阿里 CosyVoice（声音复刻）、MiniMax（语音克隆 + T2A）、Fish Audio、
OpenAI 兼容 TTS。本地零样本克隆（GPT-SoVITS/CosyVoice 本地）需 GPU，故走云端 provider。
