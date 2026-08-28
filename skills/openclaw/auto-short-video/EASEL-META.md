# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | auto-short-video |
| **所属层** | produce（编排型） |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研（`scripts/assemble.py` + 编排流程） |
| **参考项目** | 沉淀自 AIDC-AI/Pixelle-Video（主题→文案→配图→配音→BGM→合成 的全自动短视频引擎）、harry0703/MoneyPrinterTurbo、LuoGen-AI/LuoGen-agent（数字人口播全流程编排）；合成用 FFmpeg |
| **依赖** | 系统 ffmpeg/ffprobe；上游各环节 SKILL（video-script / ai-image-gen / ai-video-gen / tts-voiceover / auto-subtitle / ai-music / image-editing） |
| **许可** | 待核实（参考项目 Apache-2.0/GPL-3.0，本实现为自研编排 + 自研合成脚本） |

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢

## 说明

Easel 从"制作零件箱"升级为"一键出片机"的关键编排 SKILL。核心自研资产是 `scripts/assemble.py`（确定性合成器：图片 Ken Burns、补边画幅、拼接、配音+BGM 混音、烧录字幕，纯 ffmpeg，selftest 实测出片）。编排层把各制作 SKILL 串成流水线，零件可缺则降级。上游生成环节（生图/生视频/生乐/TTS）依赖用户自备 API key。
