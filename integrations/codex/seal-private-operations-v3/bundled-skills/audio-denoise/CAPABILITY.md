---
name: audio-denoise
description: >-
  音频降噪：去除录音中的背景噪声、电流声、风噪、嗡嗡声，基于 ffmpeg 滤镜链（afftdn/highpass/lowpass）。
  当用户说"降噪""去噪""去杂音""消除背景噪声""电流声""风噪""录音有杂音""音频降噪"时使用。
  和 audio-editing 的区别：audio-editing 做剪辑/转码/音量等通用音频操作（内置 denoise 兜底），本 SKILL 专做降噪调参。
layer: produce
---

# 音频降噪

清理录音中的背景噪声。降噪专项 SKILL——通过共享脚本 `skills/shared/scripts/audio_ops.py denoise` 封装 ffmpeg 降噪滤镜，提供三级方案（从基础滤波到 RNN 神经网络），参数确定、可复现，不现场手拼命令。

> 通用音频操作（裁剪/转码/音量/提取/拼接/淡入淡出/变速）见 **audio-editing**。本 SKILL 专注降噪。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| input_file | 是 | 音频或视频文件路径 |
| tier | 否 | `1` / `2` / `3`（默认 `2`） |
| output_file | 否 | 默认 `outputs/主题名/{filename}-clean.{ext}` |
| mix | 否 | 降噪强度 0.0-1.0（默认 0.8，仅 tier3 RNNoise） |
| preserve_original | 否 | 保留原始文件（默认 true） |

支持格式：wav, mp3, flac, aac, m4a, mp4, mkv, mov。

## 输出

- 降噪后的音频文件（放入 `outputs/主题名/`）
- 处理报告：原始文件信息、所用 tier 与滤镜链、输出文件信息、大小对比

## 三级降噪方案（对应脚本 `--tier`）

脚本按 tier 自动选滤镜链并打印实际执行的 ffmpeg 命令。

### Tier 1 — 基础降噪（ffmpeg 内置滤波）

切除低频隆隆声、高频嘶嘶声 + FFT 降噪，纯 ffmpeg 无外部依赖。
滤镜：`highpass=f=80,lowpass=f=8000,afftdn=nr=12:nf=-40:tn=1`
适用：轻度噪声、无需模型的快速处理。

### Tier 2 — 加强降噪（更强 FFT + 非局部均值）

更激进的 FFT 降噪叠加 anlmdn，仍纯 ffmpeg。
滤镜：`highpass=f=70,afftdn=nr=24:nf=-30:tn=1,anlmdn=s=0.0005`
适用：中度噪声、稳态背景噪声（空调/风扇/底噪）。**默认档**。

### Tier 3 — RNN 神经网络降噪（arnndn + 后处理）

RNNoise 针对人声优化 + 高通预处理 + 动态压缩 + 响度归一化。
滤镜：`highpass=f=60,arnndn=m=<model>:mix=<mix>,acompressor=...,loudnorm=...`
适用：人声录音、播客、访谈、复杂噪声环境。
**需要 RNNoise 模型 `sh.rnnn`；缺失时脚本自动降级 Tier2 并打印下载提示。**

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/audio_ops.py`。

### 1. 探测输入文件

```bash
python skills/shared/scripts/audio_ops.py info input_file
```

脚本自身检查 ffmpeg/ffprobe，缺失时给安装提示。向用户展示时长/码率/声道，判断音频还是视频。

### 2. 准备 RNN 模型（仅 Tier3）

检查脚本旁 `skills/shared/scripts/models/sh.rnnn` 是否存在。不存在则下载：

```bash
mkdir -p skills/shared/scripts/models
curl -L https://github.com/GregorR/rnnoise-models/raw/master/somnolent-hogwash-2018-09-01/sh.rnnn \
  -o skills/shared/scripts/models/sh.rnnn
```

不下载也可——脚本会自动降级 Tier2。也可用 `--model <path>` 指定其它模型。

### 3. 执行降噪

```bash
# 默认 Tier2
python skills/shared/scripts/audio_ops.py denoise input.wav -o outputs/主题名/input-clean.wav --tier 2
# Tier3（RNNoise，人声）
python skills/shared/scripts/audio_ops.py denoise input.wav -o outputs/主题名/input-clean.wav --tier 3 --mix 0.8
```

- 脚本会打印实际运行的 ffmpeg 命令（透明执行）。
- **视频输入自动 `-c:v copy`**：只处理音轨，视频轨原样保留。

### 4. 验证输出 + 报告

脚本处理完自动打印输出文件的时长/码率/声道/采样率。如需完整对比：

```bash
python skills/shared/scripts/audio_ops.py info outputs/主题名/input-clean.wav
```

报告内容：原始 vs 输出（格式/时长/大小/采样率）、所用 tier 与滤镜链、大小变化。

## 规则

1. **绝不删除原始文件** — 即使用户未指定 `preserve_original`。
2. **先探测再处理** — 始终先 `info` 展示文件信息。
3. **视频输入只动音频** — 脚本自动 `-c:v copy`。
4. **透明执行** — 脚本打印实际 ffmpeg 命令。
5. **降噪过度时** — 建议降低 tier 或 `--mix`（如 0.8→0.5）。
6. **无 Profile 依赖** — 音频处理不需要账号画像。

## 自研参考

- FFmpeg afftdn/arnndn/anlmdn 滤镜文档
- [xiph/rnnoise](https://github.com/xiph/rnnoise) — RNN 噪声抑制
- [GregorR/rnnoise-models](https://github.com/GregorR/rnnoise-models) — 预训练模型
- [timsainb/noisereduce](https://github.com/timsainb/noisereduce) — Python 频谱门控（备选方案）
