# Easel SKILL 元数据

## 移植来源（诚实标注）

本 SKILL 由一个**通用极客/科技新闻聚合工具移植改造**而来，原始工具面向个人开发者，
聚合 40+ 中英文信息源（含大量西方开发者/科技源与国际新闻）。Easel 将其
**方向重构为"服务中文社媒创作者的行业资讯情报"**：保留 RSS/API 抓取内核，
裁掉西方开发者源与无关 profile，换成对中文创作者有价值的行业媒体与垂类资讯源。

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-news-intelligence |
| **所属层** | discover |
| **原始工具（回溯）** | cclank/news-aggregator-skill |
| **原始地址** | https://github.com/cclank/news-aggregator-skill |
| **原始定位** | 全网新闻聚合 skill，多源 + Playwright 绕过 Cloudflare + 场景化早报（综合/财经/科技/吃瓜/AI 深度）|
| **回溯依据** | 原 SKILL/脚本的 profile 命名（general/finance/tech/social/ai_daily）、源清单（HN/GitHub/PH/微博/华尔街见闻）、Playwright 反爬逻辑与 cclank 仓库描述高度一致 |
| **Easel 改造** | 裁剪西方开发者源（HN/arXiv/BBC/Guardian/Paul Graham/Lex Fridman/Lobsters/Dev.to 等）；删 Windows cp936 处理、OPML 订阅、播客/专栏聚合；换成中文行业媒体源；profile 改为 creator/tech_digital/business/ai/topics；明确与 skill-trending-topics 分工（不抓热搜）|
| **保留内核** | `rss_parser.py`（通用 RSS/Atom 解析）、`fetch_news.py` 抓取/关键词过滤/深度正文/smart-fill 框架、36氪/华尔街见闻/腾讯专用抓取器 |
| **SKILL.md 行数** | 150 |

## 本次参考的 GitHub 库（致谢）

重构信息源清单与"创作者选题情报"方向时参考了以下开源项目：

| 项目 | 地址 | 用途 |
|------|------|------|
| cclank/news-aggregator-skill | https://github.com/cclank/news-aggregator-skill | 原始工具（本 SKILL 移植来源），场景化早报与多源聚合思路 |
| RSS-Renaissance/awesome-newsCN-feeds | https://github.com/RSS-Renaissance/awesome-newsCN-feeds | 优质中文新闻媒体 RSS 清单（澎湃等 feedx 源） |
| weekend-project-space/top-rss-list | https://github.com/weekend-project-space/top-rss-list | 订阅人数最多的中文优质 RSS 源，用于筛选行业媒体源 |
| xiangyugongzuoliu/awesome-rss-feeds | https://github.com/xiangyugongzuoliu/awesome-rss-feeds | 全网 RSS 订阅源汇总，feedparser + OPML 选题情报库思路 |
| SuYxh/ai-news-aggregator | https://github.com/SuYxh/ai-news-aggregator | 80+ AI/科技资讯源聚合、RSS 导入与智能过滤参考 |
| jwenjian/reading-list | https://github.com/jwenjian/reading-list | 社区驱动中文高质量科技/内容聚合，选题情报形态参考 |

> 收录时间: 2026-07-22
> 说明: 移植来源为尽力回溯，若原始作者另有其人，以实际上游为准。参考库仅用于方向与源清单借鉴，未直接复制代码。
