# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | paper-explainer |
| **所属层** | produce |
| **来源类型** | 自研（借鉴多个开源方案的方法论） |
| **参考项目** | [QuZhan51496/paper2anything](https://github.com/QuZhan51496/paper2anything)（skills-based 内容生成流程，思路可借鉴：parse_pdf 用 MinerU + 提炼方法论/设计规范/QA 清单全外置 references + 一份解析扇出 slides/poster/html/xhs/wechat 多形态）；[showlab/Paper2Video](https://github.com/showlab/Paper2Video)（Slides→Subtitles→Speech 流水线、按内容块切段、字幕先行再 TTS）；[Paper2Poster/Paper2Poster](https://github.com/Paper2Poster/Paper2Poster)（Parser 把论文蒸馏成结构化 asset library 中间产物）；[Azzedde/paper_to_podcast](https://github.com/Azzedde/paper_to_podcast)（多角色对话/双人问答口播）；[OpenDCAI/Paper2Any](https://github.com/OpenDCAI/Paper2Any)（同一份解析扇出多形态） |
| **借鉴方式** | 仅借鉴方法论与产物结构（MinerU 解析 + 结构化 asset library + 多形态扇出 + 双人问答），未引入其代码。确定性解析/取原文自研 `scripts/paper_ingest.py`（标准库 + 可选 pdfplumber/PyMuPDF/MinerU） |
| **内部复用** | card-design（视觉立场/排版/去 AI 味）、video-script（分镜/留存结构）、chart-visualization/infographic（重绘方法图/结果图）、tts-voiceover / multi-voice-dubbing（口播）、auto-subtitle（字幕）、auto-short-video（成片）、doc-convert（图文排版/长图）、skill-channels-upload/skill-zhihu-publisher/skill-wechat-publisher（发布） |
| **依赖** | pdfplumber（PDF 文本兜底，必需）；可选 PyMuPDF(fitz) 抽图、MINERU_API_TOKEN（公式/图表结构化解析，用户自备）；联网走 http(s)_proxy / EASEL_PROXY |
| **刻意不做** | 数字人讲座录屏（Paper2Video 的 Hallo2 需 48G GPU，太重）、依赖 LaTeX 源（从 PDF 入覆盖面更广） |
| **许可** | 随 Easel 项目许可 |

> 整理时间: 2026-08-04
> 用途: 来源溯源与致谢
