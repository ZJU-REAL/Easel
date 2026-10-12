---
name: auto-subtitle
description: "自动字幕 / 语音转字幕：把音频或视频里的语音识别成字幕文件（SRT/ASS/TXT/JSON），可选把字幕烧录进视频。当用户说自动字幕、语音转字幕、视频加字幕、上字幕、转录、听写、字幕文件、生成字幕、烧字幕时使用。"
layer: produce
---

# 自动字幕（语音转字幕）

把音频/视频里的人声识别成字幕。基于共享脚本 `skills/shared/scripts/asr.py`（faster-whisper 封装），
参数确定、可复现，做中文友好断句。可选把字幕烧录进视频（复用 `skills/shared/scripts/video_ops.py` / ffmpeg subtitles 滤镜）。

> 只做"语音 → 字幕文件 (+ 可选烧录)"。通用视频剪辑见 **video-editing**；纯降噪见 **audio-denoise**；长视频智能切片+烧字幕见 **clipify**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| input_file | 是 | 音频或视频文件路径（视频自动提取音轨） |
| format | 否 | `srt`（默认）/ `ass` / `txt` / `json` |
| language | 否 | `auto`（默认）或 `zh`/`en` 等 ISO 639-1 码 |
| model | 否 | `tiny`/`base`（默认）/`small`/`medium`/`large-v3`，越大越准越慢 |
| burn | 否 | 是否把字幕烧录进视频（需视频输入） |

支持：mp3/wav/m4a/aac/flac 等音频；mp4/mkv/mov/webm 等视频。

## 输出

- 字幕文件放入 `outputs/主题名/`（SRT/ASS/TXT/JSON）
- 若烧录：带硬字幕的视频（`*-sub.mp4`）
- 报告：识别语言、字幕条数、所用模型、输出路径

## 前置

- 首次运行会从 HuggingFace 下模型，**需外网代理**。脚本读取 `EASEL_PROXY` 或 `http(s)_proxy` 环境变量作代理；
  都未设则直连。也可先 `export https_proxy=... http_proxy=...` 指定。
- CPU 环境用默认 `--device cpu --compute-type int8` 即可。

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/asr.py`、`skills/shared/scripts/video_ops.py`。

### 1. 生成字幕文件

```bash
# 视频 → SRT（自动提取音轨 + 自动检测语言）
python skills/shared/scripts/asr.py transcribe \
  -i input.mp4 -o outputs/主题名/input.srt --language zh

# 视频 → ASS（带样式，**字号/边距按视频横竖屏自适应**）：视频输入自动探测宽高
python skills/shared/scripts/asr.py transcribe \
  -i input.mp4 -o outputs/主题名/input.ass --format ass --model small
# 纯音频 → ASS：无法探测尺寸，默认竖屏 1080x1920；横屏加 --res 1920x1080
python skills/shared/scripts/asr.py transcribe \
  -i voice.mp3 -o outputs/主题名/voice.ass --format ass --res 1920x1080
```

- **ASS 样式按目标视频宽高自适应**：字号按**短边**(min(w,h)*0.05，竖/横屏都≈合适、不再横屏过大)，
  底边距按高、左右边距按宽，`PlayRes`=真实宽高。视频输入自动探测；纯音频用 `--res 宽x高` 指定。
  **要带样式的硬字幕优先烧这份 ASS**（下节），比裸 SRT + 手填 force_style 更省心、且自适应。
- 中文默认每行 ~18 字，超长自动断行/拆条；`--max-line-chars` 可调。
- 不给 `-o` 时按输入文件名建项目目录，例如 `talk.mp4` 输出到 `outputs/talk/talk.srt`；已有项目应显式 `-o outputs/主题名/<文件名>.<format>`。
- 查看可用模型/语言：`python skills/shared/scripts/asr.py info`。

### 2.（可选）把字幕烧录进视频

用户要"硬字幕/烧进视频"时，用 ffmpeg 的 `subtitles`（SRT）或 `ass`（ASS）滤镜：

```bash
# 烧 SRT（可定制样式）
ffmpeg -y -i input.mp4 \
  -vf "subtitles=outputs/主题名/input.srt:force_style='FontName=Noto Sans CJK SC,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2'" \
  -c:a copy outputs/主题名/input-sub.mp4

# 烧 ASS（样式已在 ass 文件里，保真）
ffmpeg -y -i input.mp4 \
  -vf "ass=outputs/主题名/input.ass" \
  -c:a copy outputs/主题名/input-sub.mp4
```

- 路径含特殊字符时，把 `subtitles=` 的值用单引号包裹并转义冒号。
- 需要软字幕（可关闭）而非烧录：`ffmpeg -i in.mp4 -i sub.srt -c copy -c:s mov_text out.mp4`。

### 3. 产物与报告

- 字幕文件、烧录视频均写入 `outputs/主题名/`。
- 向用户报告：识别语言、字幕条数、模型、文件路径；提示可换 `--model`/`--max-line-chars` 重跑。

## 规则

1. **视频先提取音轨** — 脚本自动用 ffmpeg 提取 16kHz 单声道 wav，不改原视频。
2. **中文友好断句** — 按标点/长度断行，避免一行过长。
3. **绝不删原文件** — 只产出新文件到 `outputs/`。
4. **模型选择** — 求快用 `base`，求准用 `small`/`medium`；CPU 用 int8。
5. **烧录需视频输入** — 纯音频无法烧录，只出字幕文件。
6. **无 Profile 依赖** — 转录不需要账号画像。

## 自研参考

- [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 加速的 Whisper 推理
- [openai/whisper](https://github.com/openai/whisper) — 原始 Whisper 模型与 ASR 方法
- FFmpeg `subtitles` / `ass` 滤镜（字幕烧录）
