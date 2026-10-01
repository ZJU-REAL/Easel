---
name: tts-voiceover
description: "文字转语音配音：把文案/脚本合成为 AI 语音口播、旁白、朗读音频。**配了 VOICE_PROVIDER 默认走闭源云 TTS（CosyVoice2 等，有情感、像真人），edge 仅无 key 时兜底**（edge 偏机械/AI 味）；同步输出分句 SRT 字幕、mp3/wav/m4a。合成后可与 BGM 混音或加到视频作旁白。当用户说“配音”“文字转语音”“TTS”“AI 配音”“口播语音”“旁白”“朗读”“把这段文字读出来”“生成语音”“语音合成”时使用。"
layer: produce
---

# 文字转语音配音（TTS Voiceover）

> **配置检查路径铁律**：先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认当前目录有 `.env` 和 `skills/shared/scripts/`。云 TTS 配置只能用项目根的 `model_registry.py configured --group voice --env-file .env` 和 `voice_clone.py check ... --env-file .env` 判断；不得在 workspace 跑 `./shared/scripts/...`，也不得用 `env` / `printenv` 推断 Key/URL 缺失。

把文案 / 脚本合成为 AI 语音（口播、旁白、朗读）。共享脚本 `skills/shared/scripts/tts.py speak`：
**默认闭源优先**——配了 `.env` 的 `VOICE_PROVIDER`(+ VOICE_API_KEY) 就走闭源云 TTS（voice_clone，
按句合成+拼接+分句 SRT，有情感、像真人），**没 key 才退 edge**（AI 味、生硬，仅兜底）。
`--engine closed/edge` 可强制；闭源音色用 `--voice` 传 voice-id（如 `FunAudioLLM/CosyVoice2-0.5B:alex`），
旁白默认 alex，可用 `VOICE_NARRATOR_VOICE_ID` 覆盖。合成后语音可交 `audio_ops.py`/`video_ops.py` 混音或加到视频。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| text / file | 是 | 待配音的文本，或文本文件路径（长文本推荐 --file） |
| voice | 否 | 音色，默认 `zh-CN-XiaoxiaoNeural`（晓晓） |
| rate/volume/pitch | 否 | 语速 / 音量 / 音调微调 |
| output | 否 | 默认 `outputs/主题名/{name}.mp3` |

## 输出

- 配音音频文件（mp3，可选 wav/m4a），放入 `outputs/主题名/`
- 可选同步输出 SRT 字幕（`--subtitle`），供视频烧字幕用
- 打印实际执行的 edge-tts 命令 + 输出文件时长/大小/音色

## 前置：外网代理

edge-tts 调微软在线服务，**必须能访问外网**。内网环境先设代理：

```bash
export https_proxy=http://<代理host>:<端口> http_proxy=http://<代理host>:<端口>
```

脚本会自动读环境变量代理并透传给 edge-tts（也可用 `--proxy` 覆盖）。

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/tts.py`。每个子命令支持 `-h`。

### 0. 挑音色（可选）

```bash
python skills/shared/scripts/tts.py voices          # 常用中文音色 + 简介
python skills/shared/scripts/tts.py voices --all    # 拉全量 zh- 音色（需外网）
```

### 1. 合成配音 speak

```bash
# 最简：一句话 → mp3
python skills/shared/scripts/tts.py speak --text "欢迎来到本期内容" \
  -o outputs/主题名/intro.mp3

# 长文本从文件读 + 换音色 + 加速 10%
python skills/shared/scripts/tts.py speak --file script.txt \
  -o outputs/主题名/narration.mp3 --voice zh-CN-YunxiNeural --rate +10%

# 同步出 SRT 字幕（视频烧字幕用）
python skills/shared/scripts/tts.py speak --file script.txt \
  -o outputs/主题名/vo.mp3 --subtitle outputs/主题名/vo.srt

# 输出 wav（需 ffmpeg，便于后续无损处理）
python skills/shared/scripts/tts.py speak --text "……" \
  -o outputs/主题名/vo.wav --format wav
```

参数：`--rate +10%`（语速）、`--volume +20%`（音量）、`--pitch +2Hz`（音调）。

### 2. 后处理（可选，复用已有共享脚本）

配音出来后按需接下游脚本，无需在本 SKILL 重造能力：

```bash
# ① 配音 + BGM 混音（原声 1.0 / BGM 0.3）→ 用 audio_ops concat / video_ops bgm
python skills/shared/scripts/video_ops.py bgm -i vo.mp3 -o vo_bgm.mp3 \
  --music bgm.mp3 --voice-volume 1.0 --music-volume 0.3

# ② 配音音量归一化到社媒响度（-14 LUFS）
python skills/shared/scripts/audio_ops.py normalize vo.mp3 -o vo_norm.mp3

# ③ 把配音作为旁白加到视频
python skills/shared/scripts/video_ops.py bgm -i clip.mp4 -o clip_vo.mp4 \
  --music vo.mp3 --voice-volume 0.4 --music-volume 1.0
```

## 常用中文音色

| 音色 | 特点 |
|------|------|
| `zh-CN-XiaoxiaoNeural` | 晓晓 · 女声，温暖亲和，通用首选（默认） |
| `zh-CN-XiaoyiNeural` | 晓伊 · 女声，活泼年轻，口播/种草 |
| `zh-CN-YunxiNeural` | 云希 · 男声，清朗自然，旁白/解说 |
| `zh-CN-YunyangNeural` | 云扬 · 男声，专业沉稳，新闻/播报 |
| `zh-CN-YunjianNeural` | 云健 · 男声，浑厚有力，激情内容 |

粤语用 `zh-HK-HiuMaanNeural`（曉曼），台式用 `zh-TW-HsiaoChenNeural`（曉臻）。

## 规则

1. **绝不覆盖原始素材** — 只写新文件到 `outputs/主题名/`。
2. **长文本走 --file** — 避免命令行过长 / 换行转义问题。
3. **先设代理** — edge-tts 需外网，网络失败脚本会给明确提示。
4. **不重造能力** — 混音/归一化/加视频旁白复用 audio_ops.py / video_ops.py。
5. **无 Profile 也能用** — 无画像时用默认音色晓晓。

## Profile 感知

有 Profile 时可读取账号偏好音色 / 语速 / 平台调性（如口播偏活泼晓伊、
知识类偏沉稳云扬）作为默认参数；无 Profile 退到通用默认（晓晓、正常语速）。
