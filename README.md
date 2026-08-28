<p align="center">
  <img src="assets/readme/brand.png" width="680" alt="Easel">
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README_EN.md">English</a>
</p>

<p align="center">
  你的私人、持续进化的社媒内容助手<br>
  从一个想法开始，完成发现、策划、创作、发布与复盘。
</p>

<p align="center">
  <img src="https://img.shields.io/badge/OpenClaw-powered-111827?style=flat-square" alt="Powered by OpenClaw">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <a href="docs/skill-function-mapping.md"><img src="https://img.shields.io/badge/Skills-112-0F9D8A?style=flat-square" alt="112 Skills"></a>
  <a href="https://zju-real.github.io/Easel/"><img src="https://img.shields.io/badge/Project-Page-F28C6F?style=flat-square&logo=googlechrome&logoColor=white" alt="Project Page"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-2EA44F?style=flat-square" alt="License: Apache 2.0"></a>
</p>

<!-- 仓库公开并确定最终 GitHub 地址后，可在这里增加 Stars / Release 徽章。 -->

![Easel 产品宣传海报](assets/readme/poster.png)

## 🎨 Easel 是什么

Easel 是一个面向社交媒体创作者的开源内容工作台。它把 OpenClaw Agent、账号画像、内容技能和真实的媒体工具接在一起，让 Agent 不只回答“应该怎么做”，而是直接把内容做出来并归档。

你可以把它理解成一个会记住你的内容搭档：它了解账号定位、受众、风格、平台限制和历史表现，从热点发现一直陪你做到发布，再把结果带回下一次创作。

> - **推荐使用 Web 前端**：前端提供完整的会话、素材、账号、画像、内容库和发布管理能力，体验和功能比单独使用 CLI 更全面。
> - **谨慎自动发布到小红书**：小红书平台可能检测自动化操作，存在验证、限流或账号风控风险；建议使用预览与发布前检查，并由用户确认后手动发布，其他平台正常。
> - **从研究走向真实生活**：Easel 是我们将研究成果应用到真实社媒创作场景的一次实践。后续我们会继续研究 AI 在社媒场景中的社交智能，让 Agent 更好地理解创作者、受众与真实互动。

## ✨ 为什么是 Easel

- **一个 Agent 贯穿完整链路**：发现热点、评估选题、规划日历、生成文案与视觉、制作视频、发布和归因在同一个工作流中完成。
- **画像驱动，而不是一次性生成**：每个账号有独立的定位、风格、受众、平台、偏好和记忆，输出会越来越贴合真实账号。
- **技能是真执行，不是功能清单**：图片、卡片、配音、字幕、剪辑、短剧和发布技能都配有可运行脚本，成品写入 `outputs/`。
- **一份素材，多种平台形态**：同一主题可以改写成小红书卡片、短视频、知乎长文或短帖，并遵循不同平台的格式和字数要求。
- **项目化保存产物**：内容、素材、中间文件和元数据按项目归档，后续修改、重试和发布不会散落在聊天记录里。
- **真实发布与复盘闭环**：目前支持小红书、抖音、快手、知乎、B 站、微信视频号六个平台的登录、适配和发布，并可回收账号数据。

## 🧭 五层内容工作流

1. **发现**：聚合热榜、行业新闻、竞品动态和用户讨论，筛选真正适合账号的机会。
2. **策划**：把机会变成选题、标题、脚本和内容矩阵，写入内容日历。
3. **创作**：生成文案、卡片、海报、信息图、音频、视频、短剧和论文解读等可发布素材。
4. **发布**：按平台适配标题、正文、画幅和媒体要求，执行发布前检查并发送到已登录账号。
5. **归因**：读取播放、互动、评论和内容表现，把有效结构和偏好沉淀回账号画像。

## 🧰 已经落地的能力

| 能力层 | 已实现功能 |
|---|---|
| **发现** | 全网热搜聚合、垂类趋势研究、内容缺口分析、节日与事件日历、平台算法动态、竞品分析、行业资讯、跨平台差异、RSS 聚合、UGC 发现 |
| **策划** | 账号定位分析、受众画像、人设与声音构建、账号诊断、选题矩阵、选题评分、热点结合、系列内容规划、标题与 Hook、文章大纲、分镜脚本、内容日历、跨平台复用、直播策划、营销活动与商单方案 |
| **文字与视觉** | 社媒文案、短视频与中长视频脚本、小红书笔记、长文、小说、去 AI 感改写、风格迁移、论文解读、金句卡、小红书知识卡、海报、信息图、数据图表、思维导图、对比图、电商详情图、Meme、AI 生图、图片增强、去背景与批处理 |
| **音频与视频** | 文字转语音、多角色配音、声音克隆、AI 音乐、降噪、混音、语音转文字、音频可视化、AI 视频、AI 短剧、字幕与翻译、视频剪辑、长视频切片、直播高光、横竖版转换、片头片尾、相册视频、音乐卡点、绿幕换背景、视频转图文与章节目录 |
| **发布与归因** | 发布质量门禁、敏感与版权风险检查、平台搜索优化、发布 Checklist、多平台格式适配；小红书、抖音、快手、知乎、B 站、微信视频号登录与发布；内容日历回写、账号数据、评论洞察、内容复盘、ROI 与画像记忆 |

## 🖥️ 工作台功能示例

下面只展示 Easel 工作台中的四个代表性功能，并不是完整功能清单。更多发现、策划、创作、发布和归因能力，
可以在工作台的技能库或[能力地图](docs/skill-function-mapping.md)中查看。

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>🧬 账号画像</strong><br>
      <sub>通过基础信息、社媒链接、运营意图和偏好红线建立账号上下文；一份画像可以跨多个平台和会话持续使用。</sub><br><br>
      <img src="assets/readme/features/profile.png" width="100%" alt="Easel 账号画像配置">
    </td>
    <td width="50%" valign="top">
      <strong>🔥 热点雷达</strong><br>
      <sub>聚合微博、抖音、知乎、B 站、百度和头条等平台热榜，帮助 Agent 从实时趋势中筛选适合当前账号的选题。</sub><br><br>
      <img src="assets/readme/features/discover.png" width="100%" alt="Easel 多平台热点雷达">
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <strong>📅 内容日历</strong><br>
      <sub>统一管理选题、草稿、待发、已发和平台活动，结合节日节点规划内容，并记录每一天的发布安排。</sub><br><br>
      <img src="assets/readme/features/calendar.png" width="100%" alt="Easel 内容日历">
    </td>
    <td width="50%" valign="top">
      <strong>📣 发布中心</strong><br>
      <sub>从一份母版内容生成多平台版本，集中完成格式适配、媒体附件、发布前检查、预览和真实发布。</sub><br><br>
      <img src="assets/readme/features/publish.png" width="100%" alt="Easel 多平台发布中心">
    </td>
  </tr>
</table>

## 🖼️ 真实产物

这些文件来自 Easel 的实际工作流，主页中也有同一批案例的分类展示。
README 的品牌图、海报、案例图片和视频统一保存在 `assets/readme/`；产品主页使用独立的
`web/static/showcase/` 素材，其中视频保持为 6 秒轻量预览。

### 📚 论文解读与知识卡片

<p align="center">
  <img src="assets/readme/showcase/spatialevo-cards-strip.jpg" width="49%" alt="SpatialEvo 论文解读卡片">
  <img src="assets/readme/showcase/spatialladder-cards-strip.jpg" width="49%" alt="SpatialLadder 论文解读卡片">
</p>
<p align="center"><sub>SpatialEvo · 论文解读　/　SpatialLadder · VLM 视觉叙事</sub></p>

<p align="center">
  <img src="assets/readme/showcase/culture-mt-cards-strip.jpg" width="49%" alt="CULTURE-MT 研究卡片">
  <img src="assets/readme/showcase/knowu-cards-strip.jpg" width="49%" alt="KnowU-Bench 论文解读卡片">
</p>
<p align="center"><sub>CULTURE-MT · 文化翻译　/　KnowU-Bench · 侦探漫画</sub></p>

<p align="center">
  <img src="assets/readme/showcase/agentg2-cards-strip.jpg" width="49%" alt="AGENT G2 论文解读卡片">
  <img src="assets/readme/showcase/pause-cards-strip.jpg" width="49%" alt="Pause or Fabricate 论文解读卡片">
</p>
<p align="center"><sub>AGENT G2 · 暗夜英雄　/　Pause or Fabricate · 角色化科普</sub></p>

### 📖 小说与故事

<p align="center">
  <img src="assets/readme/showcase/novel-xiuxian.png" width="24%" alt="外门弟子整顿修仙界">
  <img src="assets/readme/showcase/novel-horror.png" width="24%" alt="中元节那晚">
  <img src="assets/readme/showcase/novel-romance.png" width="24%" alt="我和相亲对象互演正常人">
  <img src="assets/readme/showcase/novel-seventh.png" width="24%" alt="第七格">
</p>
<p align="center"><sub>搞笑修仙　/　恐怖短篇　/　爱情喜剧　/　悬疑故事</sub></p>

### 🌿 生活分享与梗内容

<p align="center">
  <img src="assets/readme/showcase/life-color-cards-strip.jpg" width="49%" alt="丰富多彩的生活">
  <img src="assets/readme/showcase/life-mountain-cards-strip.jpg" width="49%" alt="大山大水">
</p>
<p align="center"><sub>生活方式　/　自然记录</sub></p>

<p align="center">
  <img src="assets/readme/showcase/life-chengdu-cards-strip.jpg" width="49%" alt="成都乡土生活">
  <img src="assets/readme/showcase/jokes-cards-strip-wide.jpg" width="49%" alt="开学趣事梗卡">
</p>
<p align="center"><sub>城市生活　/　梗内容</sub></p>

### 🎬 视频成片

为便于快速浏览，这里使用可点击的视频封面。点击封面查看最长 1 分钟的轻量预览，点击封面下方的标题
查看完整成片。

**论文解读视频**

<p align="center">
  <a href="assets/readme/videos/preview/spatialladder-explainer.mp4"><img src="assets/readme/videos/thumbnails/spatialladder-explainer.jpg" width="49%" alt="播放 SpatialLadder 论文解读预览"></a>
  <a href="assets/readme/videos/preview/culture-mt-explainer.mp4"><img src="assets/readme/videos/thumbnails/culture-mt-explainer.jpg" width="49%" alt="播放 CULTURE-MT 论文解读预览"></a>
</p>
<p align="center"><sub>▶ 点击封面播放预览 · 查看完整视频：<a href="assets/readme/videos/full/spatialladder-explainer.mp4">SpatialLadder</a>　/　<a href="assets/readme/videos/full/culture-mt-explainer.mp4">CULTURE-MT</a></sub></p>

**口播、连续剧与 AI 角色短视频**

<p align="center">
  <a href="assets/readme/videos/preview/ordinary-person.mp4"><img src="assets/readme/videos/thumbnails/ordinary-person.jpg" width="24%" alt="播放普通人口播剧预览"></a>
  <a href="assets/readme/videos/preview/hanako-change.mp4"><img src="assets/readme/videos/thumbnails/hanako-change.jpg" width="24%" alt="播放花子的转变预览"></a>
  <a href="assets/readme/videos/preview/cyber-cultivation.mp4"><img src="assets/readme/videos/thumbnails/cyber-cultivation.jpg" width="24%" alt="播放赛博修仙预览"></a>
  <a href="assets/readme/videos/preview/cyber-turtle.mp4"><img src="assets/readme/videos/thumbnails/cyber-turtle.jpg" width="24%" alt="播放赛博吃播甲鱼预览"></a>
</p>
<p align="center"><sub>▶ 点击封面播放预览 · 查看完整视频：<a href="assets/readme/videos/full/ordinary-person.mp4">普通人</a>　/　<a href="assets/readme/videos/full/hanako-change.mp4">花子的转变</a>　/　<a href="assets/readme/videos/full/cyber-cultivation.mp4">赛博修仙</a>　/　<a href="assets/readme/videos/full/cyber-turtle.mp4">赛博吃播甲鱼</a></sub></p>

**氛围影像与横版内容**

<p align="center">
  <a href="assets/readme/videos/preview/jilong-news.mp4"><img src="assets/readme/videos/thumbnails/jilong-news.jpg" width="32%" alt="播放西藏吉隆泥石流预览"></a>
  <a href="assets/readme/videos/preview/daomu-book.mp4"><img src="assets/readme/videos/thumbnails/daomu-book.jpg" width="32%" alt="播放盗墓笔记小说介绍预览"></a>
  <a href="assets/readme/videos/preview/zju-intro.mp4"><img src="assets/readme/videos/thumbnails/zju-intro.jpg" width="32%" alt="播放浙江大学介绍预览"></a>
</p>
<p align="center"><sub>▶ 点击封面播放预览 · 查看完整视频：<a href="assets/readme/videos/full/jilong-news.mp4">西藏吉隆泥石流</a>　/　<a href="assets/readme/videos/full/daomu-book.mp4">盗墓笔记小说介绍</a>　/　<a href="assets/readme/videos/full/zju-intro.mp4">浙江大学</a></sub></p>

## 🚀 快速开始

环境要求：Linux 或 macOS、Python 3.10 及以上、`git`。还需要 Node.js 22.19 及以上；Linux x86_64
缺少 Node.js 时安装脚本会自动处理，macOS 建议先通过 Homebrew 或 Node.js 官网安装。

```bash
git clone git@github.com:ZJU-REAL/Easel.git
cd Easel
cp .env.example .env
vim .env

bash setup.sh
easel web
# 或：easel chat
```

启动 Web 工作台后访问 `http://localhost:7860`。安装完成后可以运行 `easel doctor` 检查环境，
运行 `easel ping` 检查 gateway 和 Agent 连通性。

需要图片、音视频或浏览器发布能力时，安装可选依赖：

```bash
pip install -e ".[media]"
playwright install chromium
# 系统还需要 ffmpeg
```

## ⚙️ 配置说明

最小配置只需要在项目根目录 `.env` 中提供一个可用的 LLM：

```bash
ANTHROPIC_API_KEY=你的_API_Key
CLAUDE_MODEL=anthropic/claude-sonnet-4-6
```

`.env.example` 还列出了视频、音乐、语音等可选模型配置。只需要配置实际使用的能力，也可以在 Web
工作台的“技能库”中填写；没有配置的媒体 Skill 不会影响聊天、策划和文本创作。常见可选项包括：

| 能力 | 配置入口 | 额外依赖 |
|---|---|---|
| AI 视频 | `VIDEO_PROVIDER` 及对应服务的 Key、URL、模型 | 相应视频生成服务 |
| AI 音乐 | `MUSIC_PROVIDER` 及对应服务配置 | 相应音乐生成服务 |
| 云端配音 | `VOICE_PROVIDER` 及对应服务配置 | 相应语音生成服务 |
| 图片与音视频处理 | 无额外模型时也可使用本地工具 | `pip install -e ".[media]"`、FFmpeg |
| 浏览器发布 | 在 Web“账号”页面登录目标平台 | Playwright Chromium、有效平台账号 |

## 🧩 使用 Easel

常用入口：

| 命令 | 作用 |
|---|---|
| `easel web [--port 7860]` | 启动 Web 工作台 |
| `easel chat` | 在终端开启多轮对话并选择账号画像 |
| `easel skill <name> -i "..." [-p <画像>]` | 直接运行指定 Skill；输入也可以是文件路径 |
| `easel doctor` | 检查 Python、Node.js、OpenClaw 和关键配置 |
| `easel ping` | 检查 gateway 与 Agent 连通性 |
| `easel gateway start\|stop\|restart\|status\|logs` | 管理 OpenClaw gateway |

所有技能都通过 Easel 的 Agent 执行。Agent 会读取对应 `SKILL.md`，调用脚本和工具，并把产物保存到 `outputs/`。

```bash
easel skill quality-gate -i "帮我检查这条小红书文案"
easel skill social-content -i "写一条介绍空间智能的微博"
easel skill quality-gate -i "这是一段待发布文案" -p 科技数码达人
```

Web 工作台提供同样的能力，并额外管理会话、素材、账号、画像、内容库和发布状态。拖入对话框的素材会作为结构化附件传给 Agent，用户消息只显示实际输入的文字。

## 🧬 账号画像

一个画像对应 `profiles/<名字>/` 目录，包含六个维度：定位、风格、受众、平台、偏好与红线、长期记忆。

```bash
cp -r profiles/_template "profiles/我的账号"
```

在 Web 的“画像”页面可以直接创建和编辑；同一画像可以跨多个已登录平台使用。

## 🏗️ 项目结构

```text
Easel/
├── easel/                    Python CLI：chat / web / skill / doctor / ping
├── web/                      FastAPI 后端与 React 工作台
├── skills/openclaw/          发现、策划、制作、发布、归因技能
├── skills/shared/            跨技能脚本与参考资料
├── assets/                   品牌、README 媒体与用户导入素材
├── profiles/                 账号画像（每个画像一个目录）
├── outputs/                  内容项目与最终产物
├── openclaw/                 隔离 profile、workspace 与同步脚本
└── docs/                     能力规范、能力地图与架构文档
```

Easel 使用独立的 `easel` OpenClaw profile，不会覆盖你本机已有的 OpenClaw 配置。Web 默认运行在 `7860`，gateway 默认运行在 `18789`。

## 📑 文档

- [能力地图](docs/skill-function-mapping.md)
- [SKILL 接口规范](docs/SKILL-SPEC.md)
- [提示词与架构分层](docs/prompt-stack.md)
- [完整致谢](docs/ACKNOWLEDGMENTS.md)

## 🙏 致谢

Easel 的技能体系和工作流受益于许多优秀的开源项目、工具与内容方法论。感谢所有原作者和社区贡献者；
具体项目、用途和许可信息请查看[完整致谢](docs/ACKNOWLEDGMENTS.md)。

## ⚖️ 许可证

[Apache 2.0](LICENSE)
