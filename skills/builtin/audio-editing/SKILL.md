---
name: audio-editing
description: "通用音频处理：音频剪辑/裁剪、格式转码（mp3/wav/m4a/aac）、音量归一化、从视频提取音轨、多段拼接、淡入淡出、变速（保音高）。当用户说“剪音频”“裁一段”“转成 mp3”“调音量/响度”“提取音轨/扒音频”“拼接音频”“淡入淡出”“加速/减速音频”“变速不变调”时使用。与 audio-denoise 的区别：audio-denoise 专做降噪，audio-editing 做除降噪外的通用音频操作（也内置 denoise 作为兜底）。"
layer: produce
---

# 通用音频处理

除降噪外的通用音频操作：裁剪、转码、音量归一化、提取音轨、拼接、淡入淡出、变速。全部通过共享脚本 `skills/shared/scripts/audio_ops.py` 封装 ffmpeg，参数确定、可复现，不现场手拼命令。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| input_file | 是 | 音频或视频文件路径 |
| operation | 是 | trim / convert / normalize / extract / concat / fade / speed / denoise / info |
| output_file | 否 | 默认 `outputs/主题名/{name}-{op}.{ext}` |

支持格式：wav / mp3 / m4a / aac / flac，视频容器 mp4 / mkv / mov（提取音轨）。

## 输出

- 处理后的音频文件（放入 `outputs/主题名/`）
- 每次操作打印实际执行的 ffmpeg 命令 + 输出文件的时长/码率/声道/采样率

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/audio_ops.py`。每个子命令都支持 `-h`。

### 0. 环境检查 + 探测

```bash
python skills/shared/scripts/audio_ops.py info input.mp3
```

脚本自身会检查 ffmpeg/ffprobe，缺失时给安装提示。先 `info` 展示文件时长/码率/声道再动手。

### 1. 裁剪 trim

```bash
# 起止时间
python skills/shared/scripts/audio_ops.py trim in.mp3 -o outputs/主题名/clip.mp3 --start 00:00:05 --end 00:00:20
# 起点 + 时长
python skills/shared/scripts/audio_ops.py trim in.mp3 -o clip.mp3 --start 5 --duration 15
```

### 2. 转码 convert

```bash
python skills/shared/scripts/audio_ops.py convert in.wav -o out.mp3 --bitrate 192k
python skills/shared/scripts/audio_ops.py convert in.m4a -o out.wav --sample-rate 44100 --channels 2
```

输出格式由扩展名决定（mp3/wav/m4a/aac）。

### 3. 音量归一化 normalize

```bash
python skills/shared/scripts/audio_ops.py normalize in.mp3 -o out.mp3
```

默认 loudnorm 到 -14 LUFS / -1.5 dBTP（社媒/播客通用响度）。可用 `--i --tp --lra` 覆盖。

### 4. 提取音轨 extract

```bash
python skills/shared/scripts/audio_ops.py extract video.mp4 -o audio.m4a
python skills/shared/scripts/audio_ops.py extract video.mp4 -o audio.aac --copy   # 不重编码，最快
```

### 5. 拼接 concat

```bash
python skills/shared/scripts/audio_ops.py concat a.mp3 b.mp3 c.mp3 -o all.mp3
```

按参数顺序拼接，重编码方式兼容不同采样率/容器。

### 6. 淡入淡出 fade

```bash
python skills/shared/scripts/audio_ops.py fade in.mp3 -o out.mp3 --fade-in 2 --fade-out 3
```

`--fade-out` 自动定位到结尾前 N 秒。

### 7. 变速 speed（保持音高）

```bash
python skills/shared/scripts/audio_ops.py speed in.mp3 -o out.mp3 --factor 1.5   # 1.5 倍速
python skills/shared/scripts/audio_ops.py speed in.mp3 -o out.mp3 --factor 0.8   # 放慢
```

基于 atempo 保音高，超 0.5-2.0 范围自动级联。

### 8. 降噪 denoise（兜底，专项请用 audio-denoise）

```bash
python skills/shared/scripts/audio_ops.py denoise in.wav -o out.wav --tier 2
```

## 与 audio-denoise 的边界

- **audio-denoise**：降噪专项 SKILL，负责选级、模型下载、降噪报告等完整流程——需要认真降噪时用它。
- **audio-editing**：通用音频处理。`denoise` 子命令仅作为顺手兜底，两者调用同一个 `audio_ops.py denoise`，能力一致，定位不同。

## 规则

1. **绝不删除原始文件** — 只写新文件到 `outputs/主题名/`。
2. **先 info 再处理** — 展示文件信息，避免误操作。
3. **视频输入只动音频** — denoise 对视频自动 `-c:v copy`；纯抽音用 extract。
4. **透明执行** — 脚本会打印实际 ffmpeg 命令。
5. **无 Profile 也能用** — 音频处理不依赖账号画像。

## Profile 感知

有 Profile 时可据平台偏好选默认参数（如短视频响度、目标码率）；无 Profile 退到通用默认（-14 LUFS、192k）。
