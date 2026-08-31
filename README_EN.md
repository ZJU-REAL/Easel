<p align="left">
  <img src="assets/readme/logos/zhejiang_university_horizontal.png" width="106" align="middle" alt="Zhejiang University">
  &nbsp;&nbsp;&nbsp;
  <img src="assets/readme/logos/peking_university_horizontal_red.png" width="98" align="middle" alt="Peking University">
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/brand-dark.png">
    <img src="assets/readme/brand.png" width="640" alt="Easel">
  </picture>
  <br>
  <img src="assets/readme/logos/real_lab_horizontal_readme.png" width="74" alt="REAL Lab">&thinsp;&thinsp;<img src="assets/readme/logos/opendcai_lab_horizontal_readme.png" width="83" alt="OpenDCAI Lab">
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

<p align="center">
  Your personal, continuously evolving social media content assistant.<br>
  Start with an idea, then discover, plan, create, publish, and learn.
</p>

<p align="center">
  <a href="https://zju-real.github.io/Easel/"><img src="https://img.shields.io/badge/Easel-Project_Page-F05A3C?style=flat-square&logo=googlechrome&logoColor=white" alt="Easel Project Page"></a>
  <img src="https://img.shields.io/badge/OpenClaw-powered-111827?style=flat-square" alt="Powered by OpenClaw">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
  <a href="docs/skill-function-mapping.md"><img src="https://img.shields.io/badge/Skills-112-0F9D8A?style=flat-square" alt="112 Skills"></a>
  <a href="https://github.com/ZJU-REAL/Easel/stargazers"><img src="https://img.shields.io/github/stars/ZJU-REAL/Easel?style=flat-square&color=F6C344" alt="GitHub Stars"></a>
  <a href="https://github.com/ZJU-REAL/Easel/releases"><img src="https://img.shields.io/badge/release-v0.1.0_planned-0F9D8A?style=flat-square" alt="v0.1.0 planned"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-2EA44F?style=flat-square" alt="License: Apache 2.0"></a>
</p>

![Easel product poster](assets/readme/poster.png)

## 🎨 What Is Easel?

Easel is an open-source content workspace for social media creators. It connects an OpenClaw Agent, account profiles, content Skills, and real media tools, enabling the Agent to produce and archive content instead of merely explaining what to do, with direct or on-demand publishing when needed.

Think of Easel as a content partner that remembers your positioning, audience, voice, platform constraints, preferences, and past performance. It stays with you from trend discovery through publishing, then carries what it learns into the next creation cycle.

Easel follows five connected workflows: **Discover** relevant trends and opportunities, **Plan** topics, hooks, scripts, and schedules, **Produce** text, audio, and video, **Publish** checked and platform-ready content directly to the appropriate platforms, and **Attribute** performance insights back to the account profile.

#### 📌 Usage Notes and Research Vision

> - **Use the Web workspace for the complete experience:** it includes conversations, assets, accounts, profiles, a content library, and publishing management beyond the CLI entry points.
> - **Be cautious with automated Xiaohongshu publishing:** automation may trigger verification, reach restrictions, or account risk. Use preview and preflight checks, and prefer human-confirmed publishing.
> - **Research applied to real life:** Easel brings our research into real social media workflows. We will continue exploring social intelligence for AI in social media, including a deeper understanding of creators, audiences, and authentic interaction.

## ✨ Why Easel?

- **One Agent across the entire workflow:** discover trends, evaluate topics, plan calendars, generate copy and visuals, produce video, publish, and analyze results in one continuous flow.
- **Profile-driven creation:** each account has its own positioning, style, audience, platforms, preferences, boundaries, and long-term memory.
- **Executable Skills:** image, card, voice-over, subtitle, editing, short-drama, and publishing Skills include runnable tools and save deliverables to `outputs/`.
- **One source, many platforms:** adapt a single idea into Xiaohongshu cards, short video, a Zhihu article, or a short post while respecting platform conventions.
- **Project-based outputs:** source material, intermediate files, metadata, and final deliverables stay together for revision, retrying, and publishing.
- **A publishing and learning loop:** Easel supports login, adaptation, and publishing workflows for Xiaohongshu, Douyin, Kuaishou, Zhihu, Bilibili, and WeChat Channels, with performance data feeding back into account profiles.

## 🧭 Five-Layer Content Workflow

1. **Discover:** aggregate trending topics, industry news, competitors, and user conversations to identify relevant opportunities.
2. **Plan:** turn opportunities into topics, titles, scripts, content series, and calendar entries.
3. **Produce:** create copy, cards, posters, infographics, audio, video, short dramas, and paper explainers.
4. **Publish:** adapt titles, copy, aspect ratios, and media for each platform, run preflight checks, and publish through logged-in accounts.
5. **Attribute:** collect views, engagement, comments, and content performance, then preserve useful patterns in the account profile.

## 🧰 Implemented Capabilities

| Layer | Capabilities |
|---|---|
| **Discover** | Cross-platform trends, vertical research, content-gap analysis, event calendars, algorithm updates, competitor research, industry news, platform differences, RSS aggregation, and UGC discovery |
| **Plan** | Positioning, audience profiles, persona and voice, account diagnosis, content matrices, topic scoring, trend adaptation, series planning, hooks, outlines, storyboards, calendars, repurposing, livestreams, campaigns, and collaborations |
| **Text & Visual** | Social copy, video scripts, Xiaohongshu notes, long-form articles, novels, natural rewriting, style transfer, paper explainers, quote cards, knowledge cards, posters, infographics, charts, mind maps, comparison cards, product images, memes, AI images, enhancement, background removal, and batch processing |
| **Audio & Video** | Text-to-speech, multi-role dubbing, voice cloning, AI music, denoising, mixing, transcription, audio visualization, AI video, short drama, subtitles, translation, editing, clipping, highlights, format conversion, intros/outros, slideshows, beat sync, green screen, and video-to-article conversion |
| **Publish & Attribute** | Quality gates, risk checks, search optimization, publishing checklists, platform adaptation, six-platform publishing workflows, calendar logging, account analytics, comment insights, postmortems, ROI, and profile memory |

## 🖥️ Workspace Examples

These are four representative examples, not the complete feature set. Explore the Skill library in the Web workspace or the [capability map](docs/skill-function-mapping.md) for more.

<table>
  <tr>
    <td width="50%" valign="top"><strong>🧬 Account Profiles</strong><br><sub>Build reusable account context from identity, social links, goals, preferences, and boundaries.</sub><br><br><img src="assets/readme/features/profile.png" width="100%" alt="Easel account profile"></td>
    <td width="50%" valign="top"><strong>🔥 Trend Radar</strong><br><sub>Aggregate real-time trends across major platforms and identify topics relevant to the current account.</sub><br><br><img src="assets/readme/features/discover.png" width="100%" alt="Easel trend radar"></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><strong>📅 Content Calendar</strong><br><sub>Manage ideas, drafts, scheduled posts, published work, platform events, and daily plans.</sub><br><br><img src="assets/readme/features/calendar.png" width="100%" alt="Easel content calendar"></td>
    <td width="50%" valign="top"><strong>📣 Publishing Center</strong><br><sub>Generate platform-specific versions from one master asset, preview them, run checks, and publish.</sub><br><br><img src="assets/readme/features/publish.png" width="100%" alt="Easel publishing center"></td>
  </tr>
</table>

## 🖼️ Real Outputs

The following examples were produced by real Easel workflows. README media lives under `assets/readme/`; the project page uses lightweight six-second previews under `web/static/showcase/`.

### 📚 Paper Explainers and Knowledge Cards

<p align="center">
  <img src="assets/readme/showcase/spatialevo-cards-strip.jpg" width="49%" alt="SpatialEvo explainer cards">
  <img src="assets/readme/showcase/spatialladder-cards-strip.jpg" width="49%" alt="SpatialLadder explainer cards">
</p>
<p align="center">
  <img src="assets/readme/showcase/culture-mt-cards-strip.jpg" width="49%" alt="CULTURE-MT research cards">
  <img src="assets/readme/showcase/knowu-cards-strip.jpg" width="49%" alt="KnowU-Bench explainer cards">
</p>

### 📖 Novels and Stories

<p align="center">
  <img src="assets/readme/showcase/novel-xiuxian.png" width="24%" alt="Comedy cultivation story">
  <img src="assets/readme/showcase/novel-horror.png" width="24%" alt="Horror short story">
  <img src="assets/readme/showcase/novel-romance.png" width="24%" alt="Romantic comedy">
  <img src="assets/readme/showcase/novel-seventh.png" width="24%" alt="Suspense story">
</p>

### 🌿 Lifestyle and Meme Content

<p align="center">
  <img src="assets/readme/showcase/life-color-cards-strip.jpg" width="49%" alt="Colorful lifestyle cards">
  <img src="assets/readme/showcase/life-mountain-cards-strip.jpg" width="49%" alt="Nature cards">
</p>
<p align="center">
  <img src="assets/readme/showcase/life-chengdu-cards-strip.jpg" width="49%" alt="Chengdu lifestyle cards">
  <img src="assets/readme/showcase/jokes-cards-strip-wide.jpg" width="49%" alt="Meme cards">
</p>

### 🎬 Finished Videos

For faster browsing, each cover opens a lightweight preview of up to one minute. Use the links beneath each row for the full videos.

<p align="center">
  <a href="assets/readme/videos/preview/spatialladder-explainer.mp4"><img src="assets/readme/videos/thumbnails/spatialladder-explainer.jpg" width="49%" alt="Play SpatialLadder preview"></a>
  <a href="assets/readme/videos/preview/culture-mt-explainer.mp4"><img src="assets/readme/videos/thumbnails/culture-mt-explainer.jpg" width="49%" alt="Play CULTURE-MT preview"></a>
</p>
<p align="center"><sub>Full videos: <a href="assets/readme/videos/full/spatialladder-explainer.mp4">SpatialLadder</a> · <a href="assets/readme/videos/full/culture-mt-explainer.mp4">CULTURE-MT</a></sub></p>

<p align="center">
  <a href="assets/readme/videos/preview/ordinary-person.mp4"><img src="assets/readme/videos/thumbnails/ordinary-person.jpg" width="24%" alt="Play Ordinary Person preview"></a>
  <a href="assets/readme/videos/preview/hanako-change.mp4"><img src="assets/readme/videos/thumbnails/hanako-change.jpg" width="24%" alt="Play Hanako preview"></a>
  <a href="assets/readme/videos/preview/cyber-cultivation.mp4"><img src="assets/readme/videos/thumbnails/cyber-cultivation.jpg" width="24%" alt="Play cyber cultivation preview"></a>
  <a href="assets/readme/videos/preview/cyber-turtle.mp4"><img src="assets/readme/videos/thumbnails/cyber-turtle.jpg" width="24%" alt="Play cyber turtle preview"></a>
</p>
<p align="center"><sub>Full videos: <a href="assets/readme/videos/full/ordinary-person.mp4">Ordinary Person</a> · <a href="assets/readme/videos/full/hanako-change.mp4">Hanako's Change</a> · <a href="assets/readme/videos/full/cyber-cultivation.mp4">Cyber Cultivation</a> · <a href="assets/readme/videos/full/cyber-turtle.mp4">Cyber Turtle Mukbang</a></sub></p>

<p align="center">
  <a href="assets/readme/videos/preview/jilong-news.mp4"><img src="assets/readme/videos/thumbnails/jilong-news.jpg" width="32%" alt="Play Jilong news preview"></a>
  <a href="assets/readme/videos/preview/daomu-book.mp4"><img src="assets/readme/videos/thumbnails/daomu-book.jpg" width="32%" alt="Play Daomu Biji preview"></a>
  <a href="assets/readme/videos/preview/zju-intro.mp4"><img src="assets/readme/videos/thumbnails/zju-intro.jpg" width="32%" alt="Play Zhejiang University preview"></a>
</p>
<p align="center"><sub>Full videos: <a href="assets/readme/videos/full/jilong-news.mp4">Jilong Landslide News</a> · <a href="assets/readme/videos/full/daomu-book.mp4">Daomu Biji Introduction</a> · <a href="assets/readme/videos/full/zju-intro.mp4">Zhejiang University</a></sub></p>

## 🚀 Quick Start

Requirements: Linux or macOS, Python 3.10+, Git, and Node.js 22.19+. On Linux x86_64, the setup script can install Node.js when it is missing. On macOS, install Node.js first using Homebrew or the official installer.

```bash
git clone git@github.com:ZJU-REAL/Easel.git
cd Easel
cp .env.example .env
vim .env

bash setup.sh
easel web
# Or: easel chat
```

Open `http://localhost:7860` for the Web workspace. Run `easel doctor` to check the environment and `easel ping` to verify the gateway and Agent connection.

For image, audio/video, or browser publishing capabilities, install the optional dependencies:

```bash
pip install -e ".[media]"
playwright install chromium
# FFmpeg is also required on the system.
```

## ⚙️ Configuration

The minimum configuration is a usable LLM in the project-root `.env` file:

```bash
ANTHROPIC_API_KEY=your_api_key
CLAUDE_MODEL=anthropic/claude-sonnet-4-6
```

`.env.example` also documents optional video, music, voice, and Anthropic-compatible provider settings. Configure only the capabilities you use. Missing media-provider credentials do not prevent chat, planning, or text creation.

| Capability | Configuration | Additional dependency |
|---|---|---|
| AI video | `VIDEO_PROVIDER` plus the provider key, URL, and model | A supported video service |
| AI music | `MUSIC_PROVIDER` plus provider settings | A supported music service |
| Cloud voice | `VOICE_PROVIDER` plus provider settings | A supported voice service |
| Local media processing | No model is required for supported local tools | Media extras and FFmpeg |
| Browser publishing | Log in from the Web workspace's Accounts page | Playwright Chromium and valid platform accounts |

Never commit `.env`, cookies, or platform login state. Real publishing can be affected by verification, permissions, platform risk controls, and UI changes; use previews and checks for the first attempt.

## 🧩 Using Easel

| Command | Purpose |
|---|---|
| `easel web [--port 7860]` | Start the Web workspace |
| `easel chat` | Start a multi-turn terminal conversation and select an account profile |
| `easel skill <name> -i "..." [-p <profile>]` | Run a Skill directly; input may also be a file path |
| `easel doctor` | Check Python, Node.js, OpenClaw, and essential configuration |
| `easel ping` | Check the gateway and Agent connection |
| `easel gateway start\|stop\|restart\|status\|logs` | Manage the OpenClaw gateway |

```bash
easel skill quality-gate -i "Review this social media post"
easel skill social-content -i "Write a post introducing spatial intelligence"
easel skill quality-gate -i "Review this draft" -p MyCreatorProfile
```

## 🧬 Account Profiles

Each profile is stored under `profiles/<name>/` and contains six dimensions: identity, style, audience, platforms, preferences and boundaries, and long-term memory.

```bash
cp -r profiles/_template "profiles/MyCreatorProfile"
```

Profiles can also be created and edited from the Web workspace.

## 🏗️ Project Structure

```text
Easel/
├── easel/                    Python CLI
├── web/                      FastAPI backend and React workspace
├── skills/openclaw/          Discover, plan, produce, publish, and attribution Skills
├── skills/shared/            Shared scripts and references
├── assets/                   Brand, README media, and imported assets
├── profiles/                 Account profiles
├── outputs/                  Content projects and final deliverables
├── openclaw/                 Isolated profile, workspace, and sync scripts
└── docs/                     Specifications, capability map, and architecture docs
```

Easel uses an isolated `easel` OpenClaw profile and does not overwrite an existing OpenClaw setup. The Web workspace defaults to port `7860`; the gateway defaults to `18789`.

## 📑 Documentation

- [Capability map](docs/skill-function-mapping.md)
- [SKILL interface specification](docs/SKILL-SPEC.md)
- [Prompt and architecture layers](docs/prompt-stack.md)
- [Full acknowledgments](docs/ACKNOWLEDGMENTS.md)

## 🙏 Acknowledgments

Easel's Skill system and workflows benefit from many excellent open-source projects, tools, and content methodologies. We thank their original authors and contributors. See the [full acknowledgments](docs/ACKNOWLEDGMENTS.md) for projects, usage, and license information.

### 🤝 Contributors

<table>
  <tr>
    <td align="center" width="84"><a href="https://github.com/lidingm"><img src="https://github.com/lidingm.png?size=96" width="72" height="72" alt="lidingm"><br><strong>lidingm</strong></a></td>
    <td align="center" width="84"><a href="https://github.com/qywMichelle"><img src="https://github.com/qywMichelle.png?size=96" width="72" height="72" alt="qywMichelle"><br><strong>qywMichelle</strong></a></td>
    <td align="center" width="84"><a href="https://github.com/wulinjuan"><img src="https://github.com/wulinjuan.png?size=96" width="72" height="72" alt="wulinjuan"><br><strong>wulinjuan</strong></a></td>
    <td align="center" width="84"><a href="https://github.com/arctanxarc"><img src="https://github.com/arctanxarc.png?size=96" width="72" height="72" alt="arctanxarc"><br><strong>arctanxarc</strong></a></td>
  </tr>
</table>

## ⚖️ License

[Apache 2.0](LICENSE)
