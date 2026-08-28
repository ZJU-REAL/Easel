# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | multi-voice-dubbing |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研。核心引擎 `skills/shared/scripts/multivoice.py`：cast（选角）+ lines（逐行对白）→ 逐行按角色音色合成 → ffmpeg 拼多声线 voice.mp3 + 说话人字幕 voice.srt；情绪→韵律映射自带；纯标准库 + selftest |
| **参考项目** | edge-tts — https://github.com/rany2/edge-tts（逐行合成的免费多音色底座，经 `tts.py` 封装）；FFmpeg — https://ffmpeg.org（多段音轨拼接、时长探测、SRT 时序）；克隆音色经 `voice_clone.py`（DashScope/MiniMax/Fish Audio 等）。多声线编排逻辑本身无对应开源方案，为自研 |
| **内部复用** | tts.py（tts-voiceover 的 edge-tts 封装，逐行合成）、voice_clone.py（voice-clone 的克隆音色，可选）、ffmpeg（拼接/探测） |
| **被谁复用** | short-drama（对白配音，`scripts/dubbing.py` 薄层委派本引擎）、paper-explainer（双人问答口播）、可扩展到访谈/有声剧/auto-short-video 等任何多说话人场景 |
| **选角指南** | `skills/shared/references/voice-casting.md`（跨 SKILL 共享：音色→人物原型对照 + 同性别区分 + 旁白独立 + 情绪韵律 + cast/lines schema） |
| **刻意不做** | 严格对口型（lip-sync，生成式视频支持弱）；单音色整段口播（走 tts-voiceover）；克隆你本人音色（走 voice-clone） |
| **许可** | 随 Easel 项目许可；底层 edge-tts GPL-3.0 / FFmpeg LGPL-GPL |

> 整理时间: 2026-08-10
> 用途: 来源溯源与致谢
