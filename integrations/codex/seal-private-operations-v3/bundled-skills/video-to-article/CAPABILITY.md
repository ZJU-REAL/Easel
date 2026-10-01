---
name: video-to-article
description: "把口播、讲座、直播或 Vlog 转录并改写成小红书笔记、公众号文章或知乎内容，同时抽帧配图。当用户说“视频转图文/文章/笔记、视频扒文案、口播转文章、视频内容复用”时使用。只生成字幕文件用 auto-subtitle；翻译已有字幕用 subtitle-translate。"
layer: produce
---

# 视频转图文（视频 → 笔记/文章）

> 把视频复用成图文内容：转录 → 结构化成篇 → 抽帧配图。转录与抽帧走确定性脚本
> （`asr.py` / `video_ops.py`），**结构化成文由你（LLM）完成**——这是本 SKILL 的核心价值。

> 只出字幕文件见 **auto-subtitle**；翻译字幕见 **subtitle-translate**；
> 出成套小红书卡片见 **xhs-note-creator**；纯文案润色见 **text-polisher**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 视频文件 | 是 | 口播/讲座/直播/Vlog（没给就问） |
| 目标形态 | 否 | 小红书笔记（默认）/ 公众号文章 / 知乎回答 / 通用图文 |
| 配图数量 | 否 | 从视频抽几张配图（默认 3-6，按内容节点） |

## 输出（`outputs/主题名/`）

- `article.md` — 成篇图文（标题 + 正文 + 小标题/要点 + 金句 + 话题标签）
- `assets/frame-*.jpg` — 抽取的配图
- `assets/transcript.txt` / `assets/transcript.json` — 转录原文与时间轴（备查）

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/asr.py`、`skills/shared/scripts/video_ops.py`。

### 1. 语音转录（带时间轴）
```bash
python skills/shared/scripts/asr.py transcribe -i input.mp4 --format json \
  -o outputs/主题名/assets/transcript.json
python skills/shared/scripts/asr.py transcribe -i input.mp4 --format txt \
  -o outputs/主题名/assets/transcript.txt
```
（首次跑 ASR 需外网代理下模型，见 auto-subtitle 前置说明。）

### 2. 结构化成图文（你来做）
读转录，按目标形态改写成图文，**不是照抄口语**：
- **提炼结构**：口语流水账 → 清晰的标题 + 3-6 个小标题/要点段落。
- **去口水**：删"然后、就是、那个"等口头禅，书面化但保留个人风格。
- **抓金句**：把视频里最有价值的观点提成金句/加粗句。
- **按形态适配**：小红书（emoji、短段、闺蜜语气、话题标签）/ 公众号（成文、有起承转合）/
  知乎（专业、有逻辑链）。字数与排版参考 `post-formatter` / `social-content` 规范。
- 写入 `article.md`，并在文中标注"【配图1：xx画面 @ 02:15】"指明每张配图对应的视频时间点。

### 3. 抽取配图
按第 2 步标注的时间点，逐个抽帧：
```bash
python skills/shared/scripts/video_ops.py frame -i input.mp4 \
  -o outputs/主题名/assets/frame-01.jpg --time 00:02:15 --width 1080
```
挑画面清晰、有信息量的时间点（避免糊帧/转场帧）。

### 4.（可选）成套卡片
需要做成小红书卡片组时，把 `article.md` 交给 **xhs-note-creator** 或 **card-xiaohongshu**。

## Profile 感知

- 有 Profile：目标形态默认按 `platforms.md` 主平台；语气/称呼/emoji 尺度贴合 `style.md`；
  话题标签贴合账号垂类；合规底线遵守 `preferences.md`。
- 无 Profile：默认小红书笔记形态 + 中性口语风，末尾提示可提供 Profile 定制语气。

## 规则

1. 是**改写**不是**照搬转录**——口语要书面化、结构化，去口水词。
2. 配图从视频真实画面抽取，时间点由内容决定，避免糊帧。
3. 不编造视频里没有的信息；转录不清处标注"[听不清]"而非臆测。
4. 保留说话人的核心观点与个人风格，别改成千篇一律的 AI 腔（可再过 text-polisher）。
5. 最终 `article.md` 放 `outputs/主题名/`，转录和抽帧等中间件放 `outputs/主题名/assets/`。

## 参考来源

视频→图文是创作者复用内容的高频需求（一鱼多吃）。转录用 faster-whisper（asr.py），配图用
ffmpeg 抽帧（video_ops.py frame），成文结构化交给 LLM——把确定性 IO 与创意改写分层。
