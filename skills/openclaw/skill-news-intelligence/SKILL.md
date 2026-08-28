---
name: skill-news-intelligence
description: >
  聚合中文行业媒体、垂类资讯和平台商业动态，按创作者赛道过滤，生成结构化情报简报与可执行选题。
  当用户说“行业资讯/深度情报、最近行业动态、每日简报、选题情报、财经/科技/AI 动态”时使用。
  本 SKILL 做日级深度资讯；分钟级实时热搜与快速二创选题用 skill-trending-topics。
layer: discover
---

# 资讯情报聚合

> 从中文行业媒体与垂类资讯源抓取深度内容，按创作者赛道过滤，
> 生成结构化中文情报简报，并给出可操作的选题方向。

## 与 skill-trending-topics 的分工

| | skill-trending-topics | skill-news-intelligence（本 SKILL）|
|---|---|---|
| 抓什么 | 微博/抖音/知乎/头条/B站**实时热搜榜** | 中文**行业媒体的深度文章 / 快讯** |
| 时效 | 分钟级，追热点 | 日级，看行业趋势 |
| 用途 | 蹭热点、快速二创选题 | 深度选题、行业观察、内容储备 |
| 输出 | 热搜排行 + 二创角度 | 情报简报 + 选题方向 |

**边界规则**：本 SKILL 不抓热搜榜（那是 trending-topics 的职责）。
若用户要的是"今天有什么热搜/热点"，路由到 skill-trending-topics。
本 SKILL 处理"行业里最近发生了什么、有什么值得深挖的选题"。

## 输入

用户 prompt 中提供以下信息（全部可选）：

- **赛道/领域**：自媒体运营 / 科技数码 / 商业财经 / AI / 时事话题（有 Profile 时自动提取）
- **关键词**：如 "AI"、"融资"、"新消费"（用于过滤标题）
- **深度**：快速浏览 / 深度分析（深度模式下载正文，默认快速）
- **数量**：每源 5-15 条（默认 10）

## 输出

```markdown
# 资讯情报简报
日期: {date} | 赛道: {track} | 信息源: {sources}

## 要闻速览
#### 1. [标题](url)
- **来源**: 源名（领域标签） | **时间**: 发布时间
- **摘要**: 一句话中文摘要
- **洞察**: 💡 背景 / 影响 / 与创作者的关系

## 选题方向
基于今日资讯，推荐 3-5 个可操作的选题：
1. {选题} — 切入角度 + 建议平台/形式
```

## 工作流

### Step 1 — 选择信息源

按赛道选择源组合（源 key 见下表，或 `--list-sources` 查看）：

| 赛道 | 推荐源 |
|------|--------|
| 自媒体/内容运营 | `woshipm,huxiu,aihot` |
| 科技数码 | `sspai,geekpark,infoq_cn,36kr` |
| 商业财经 | `wallstreetcn,huxiu,tmtpost,36kr` |
| AI | `aihot,infoq_cn` |
| 时事/话题素材 | `thepaper,tencent,huxiu` |

### Step 2 — 抓取数据

```bash
python3 skills/openclaw/skill-news-intelligence/scripts/fetch_news.py --source rss --limit 20 --keyword AI --no-save
```

参数：`--source` 源 key（逗号分隔，`all` 抓全部）；`--limit` 每源条数；
`--keyword` 关键词过滤（子串匹配，支持中文）；`--deep` 下载正文；`--no-save` 只输出 stdout。

### Step 3 — 生成简报

读取 JSON，按「输出」格式生成中文简报。规则：

1. **语言**：全部简体中文，保留知名英文专有名词
2. **反幻觉**：只使用 JSON 中的数据，不编造资讯；时间缺失标"未知时间"
3. **赛道过滤**：有 Profile/赛道时，优先与赛道相关的条目
4. **选题方向**：末尾基于资讯给出 3-5 个可操作选题（切入角度 + 建议平台/形式）
5. **smart_fill 标记**：标 `smart_fill` 的条目是关键词不足时的宽泛补充，注明"相关度较低"

### Step 4 — 保存产物

简报保存到 `outputs/资讯简报/news-briefing-{date}.md`。

## 每日简报模式

一键生成预设赛道简报：

```bash
python3 skills/openclaw/skill-news-intelligence/scripts/daily_briefing.py --profile 科技账号 --no-save
```

| Profile | 用途 | 包含源 |
|---------|------|--------|
| `creator` | 创作者情报日报 | 人人都是产品经理 + 虎嗅 + 36氪 + AIHOT |
| `tech_digital` | 科技数码日报 | 少数派 + 极客公园 + 36氪 + 钛媒体 + InfoQ |
| `business` | 商业财经日报 | 华尔街见闻 + 虎嗅 + 钛媒体 + 36氪 |
| `ai` | AI 资讯日报 | AIHOT + InfoQ |
| `topics` | 话题素材日报 | 澎湃 + 腾讯新闻 + 虎嗅 |

## 可用信息源

| Key | 名称 | 领域 |
|-----|------|------|
| `woshipm` | 人人都是产品经理 | 自媒体·运营·内容 |
| `huxiu` | 虎嗅 | 商业·科技·消费 |
| `tmtpost` | 钛媒体 | 科技·商业 |
| `geekpark` | 极客公园 | 科技·数码·消费 |
| `sspai` | 少数派 | 数码·效率·生活方式 |
| `infoq_cn` | InfoQ 中文 | 技术·开发 |
| `aihot` | AIHOT | AI 资讯（中文精选，日更）|
| `36kr` | 36氪 | 创投·科技·商业快讯 |
| `wallstreetcn` | 华尔街见闻 | 财经·宏观 |
| `tencent` | 腾讯新闻 | 综合时事（二创素材）|
| `thepaper` | 澎湃新闻 | 时事·社会（二创素材）|

## Profile 感知

- **有 Profile**：读取 `identity.md` 的赛道，自动选源与关键词；读取 `platforms.md` 匹配选题建议的平台形式
- **无 Profile**：用通用模式（`--source all` 或问用户关注的赛道）

## 源特殊处理

| 源 | 注意事项 |
|----|---------|
| AIHOT | 已是中文编辑稿，直接引用不再翻译；默认拉 24h |
| 澎湃 | 经 feedx 中转，默认拉 48h |
| InfoQ / 少数派 | RSS 可能只给标题/摘要，深度分析配 `--deep` |
| 36氪 / 华尔街见闻 / 腾讯 | 专用抓取器（非通用 RSS）|

任何源抓取失败都会返回空并跳过，不阻断整体简报（fail-open）。

## 依赖

- Python 3.8+
- `requests`、`beautifulsoup4`
