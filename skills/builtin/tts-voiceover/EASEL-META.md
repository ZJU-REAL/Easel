# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | tts-voiceover |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研；封装共享脚本 `skills/shared/scripts/tts.py`，通过 subprocess 调 edge-tts + ffmpeg |
| **参考项目** | edge-tts — https://github.com/rany2/edge-tts（微软 Edge 在线 TTS 的 Python 封装，提供音色列表 / rate / volume / pitch / SRT 字幕）；FFmpeg — https://ffmpeg.org（wav/m4a 转码、时长探测） |
| **许可** | 待核实（edge-tts: GPL-3.0；FFmpeg: LGPL/GPL；TTS 服务为微软 Edge 在线接口） |

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
