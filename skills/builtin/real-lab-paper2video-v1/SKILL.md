---
name: real-lab-paper2video-v1
description: 当用户需要论文视频、研究成果宣传片或修订成片时，制作或修订简洁优雅的论文讲解与宣传视频。将论文 PDF、arXiv 链接或素材包转为约三分钟的中文视频，使用完整论文原图、精准框选、内容动画、清晰轻快的配音配乐，并提供可编辑工程与成片检查；仅需图文时不使用本技能，通用论文解读用 paper-explainer。
layer: produce
---

# REAL Lab Paper2Video v1

制作一支主线清楚、证据直观、阅读轻松的研究视频。默认采用中文、约三分钟、16:9、1920×1080、恒定 30 fps，配中文字幕和轻快器乐。按用户指定的语言、时长、声音和风格调整这些默认值。

## Easel 接入

- 从项目根运行，Python 使用 `.venv/bin/python`。Easel 中统一经 `scripts/easel_video.py` 调用工具，它校验产物路径并复用 Python Playwright 自带的 Node 模块；原始工具随工程复制后仍可独立使用。
- 一个论文项目使用 `outputs/<论文简称>/`。可编辑工程放 `outputs/<论文简称>/assets/paper-video/`，事实表、素材、音轨、QA 和预览均在工程内；最终 `final.mp4`、`subtitles.srt`、`script.md`、`cover.png` 放主题根目录。
- 环境检查：`.venv/bin/python skills/builtin/real-lab-paper2video-v1/scripts/easel_video.py assets check`。PDF 依赖见 `requirements.txt`；Poppler 提供 `pdftotext` / `pdftoppm`，渲染还需 Node.js、Playwright、Chrome 与 FFmpeg。
- 配音与配乐可复用 [tts-voiceover](../tts-voiceover/SKILL.md)、[audio-mix](../audio-mix/SKILL.md)，沿用用户在 Easel 配置的声音服务；未配置时按对应技能的本地方案处理。此技能制作视频，不自动发布。

## 制作顺序

1. **建立论文事实与素材。** 读取指定版本 PDF，记录标题、作者、链接和文件哈希。将核心结论、实验条件、指标及局限整理成事实表。复用同版本素材包，或用[内置资产模块](references/paper-assets.md)取得完整图表。
2. **确定叙事与镜头。** 用“问题 → 核心想法 → 方法 → 实验证据 → 结论”串起全文，每页表达一个结论。为每页写出旁白、屏上短文案、配图、强调目标和动画节拍。按论文内容选择[页面版式](references/visual-system.md)。
3. **制作声音与时间轴。** 沿用已指定的人声，或生成清晰、明亮、自然的连续旁白。依据词边界或音频对齐结果确定字幕、页面和强调时段；配入低音量轻快器乐。具体参数见[讲稿与声音制作](references/production.md)。
4. **实现画面。** 根据素材与叙事选择开场：合适的 teaser 或代表性成果图可直接呈现亮点，也可用标题、关键问题或简洁示意引入，动画按解释需要添加。方法与实验用完整原图呈现证据。按论文内容、原图色彩和用户风格选择协调的配色，以清楚的明暗对比和少量强调色建立层级，全片保持一致。图像加白边，字幕占独立区域。对正在解释的具体模块或结果添加短暂单框提示。
5. **预览并渲染。** 使用确定性的 `render(t)` 和统一时间轴。先看开场、密集方法图、实验页及转场样片，再按整数帧导出整片。新工程使用内置模板，已有工程沿用现有技术栈；命令见[工程工具](references/tooling.md)。
6. **验收并交付。** 按[成片验收](references/quality.md)核对最终 MP4 的画面、框选、转场、字幕和音频。交付视频、SRT、讲稿/镜头表、封面、可编辑工程与简短检查记录。

## 画面执行要点

- **简洁：** 每页保持明确的视觉焦点和充足留白；主标题只出现一次，辅助文案补充解释或证据，元素与装饰服务于当前讲解。
- **原图：** 以整张 Figure/Table 为单位，contain 等比适配，保留子图、图例、标签和表格行列。
- **留白：** 图框内白边 22 px、外圆角 12 px；白边外缘与字幕线至少相距 32 px，以上尺寸以 1080p 为基准。
- **框选：** 用原图坐标定位具体目标，按口播时段出现；一框结束后再出现下一框。全景介绍以稳定整图承载信息。
- **转场：** 图像用约 0.64 秒的互补遮罩擦入；标题、正文和数字统一先淡出、后淡入。连续讲解同一 Pipeline 时保持图的位置与大小。
- **文字：** 主标题 54–64 px、正文 30–40 px、字幕约 40 px。侧栏概括关键点，底部承载字幕，出处放工程元数据或片尾。
- **声音：** 专业、轻松、明快；轻拨弦、键盘和轻打击配乐在人声期间保持低音量。

## 内容库与画像

- 有画像时读取 `profiles/<画像>/` 的受众、风格与平台偏好，用户本次要求优先；不把 REAL Lab 案例中的作者身份或成果归属套到其他论文。无画像仍按本技能默认值工作。
- 交付后用 `skills/shared/scripts/manifest.py meta` 登记 `kind=video`、`status=draft`、封面和真实成品相对路径；再用 `record --layer produce --skill real-lab-paper2video-v1` 记录步骤。项目 `.easel.json` 与工程内部时间轴/素材 manifest 分开。

## 修订已有视频

从最新源工程和成片开始，沿用已认可的版式、素材、配音与音乐。把新要求落实到具体镜头、图层和时间区间，重渲受影响片段及相邻转场，再从新 MP4 取预览。画面修订沿用音频时间轴；讲稿修订同步更新旁白、字幕、页面与框选时段。

## 内置资源

| 资源 | 用途 |
|---|---|
| `scripts/easel_video.py` | Easel 路径校验与工具统一入口 |
| `scripts/init_project.py` | 创建独立工程，复制模板及资产模块 |
| `scripts/paper_assets.py`、`vendor/paper2assets/` | 原图/PDF 提取、素材打包、二维码和 Logo |
| `assets/project-template/` | 浅色页面、字幕区、确定性动画与转场骨架 |
| `assets/project-template/motion-utils.js` | 白边/contain 坐标换算、单框时序、图文分层转场 |
| `scripts/render.cjs` | 静帧、片段和整片渲染 |
| `scripts/verify_video.py` | 帧数、时间戳、解码、响度和参考帧比较 |
