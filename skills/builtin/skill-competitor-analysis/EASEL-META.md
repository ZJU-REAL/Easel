# EASEL-META — skill-competitor-analysis

本文件记录 SKILL 的移植血缘与致谢，不参与运行。

## references 移植血缘（诚实标注）

本 SKILL 的 references 早期移植自一套**西方 SEO / SaaS 竞品情报**工具，与"中文社媒账号拆解"场景错配。2026-07-22 已清洗重写。

| 现文件 | 原始来源（西方 SEO 工具血缘） | 清洗后定位 |
|--------|------------------------------|-----------|
| `data-collection.md` | 原 `api-integrations.md`：SemRush / SerpAPI / ScrapingBee，`database=us`、Google/Meta Ads、DA/DR 域名情报 | 中文社媒账号公开数据采集 + 各平台反爬降级方案（改用 web_search 公开信息，不承诺后台精确数据） |
| `viral-patterns.md` | 原 `traffic-analysis.md`：SimilarWeb/Ahrefs 流量来源真实性校验、品牌词 vs 非品牌自然搜索、LLM 引用流量 | 爆款特征识别 + 更新频率 + 涨粉节奏（用公开可观测量推断） |
| `analysis-templates.md` | 原含 SEO 档案（DA/DR/外链）、付费广告档案（Google/Meta/LinkedIn Ads）、G2/Capterra 评分、B2B 定价矩阵 | 中文社媒账号画像卡 / 选题分布 / 爆款拆解卡 / 竞争矩阵 / 内容层 SWOT |

## 本次参考的 GitHub 开源库（致谢）

清洗时参考了以下中文社媒数据采集 / 竞品分析开源项目的能力边界与数据字段设计，用于确定"能采到什么、采不到什么、如何降级"。仅作方法论参考，本 SKILL 不依赖也不集成这些代码。

| 项目 | 地址 | 参考用途 |
|------|------|---------|
| NanmiCoder/MediaCrawler | https://github.com/NanmiCoder/MediaCrawler | 多平台（小红书/抖音/B站/微博/知乎）笔记与评论采集的字段与反爬现状，界定公开可采数据范围 |
| cv-cat/Spider_XHS | https://github.com/cv-cat/Spider_XHS | 小红书竞品分析报表场景（点赞/收藏/评论拉取做爆款规律分析）的维度设计 |
| cwjcw/xhs_douyin_content | https://github.com/cwjcw/xhs_douyin_content | 创作者中心核心数据（播放/完播/粉丝增量）说明——据此确认这些属外部不可得，降级时如实标注"无公开数据" |
| ReaJason/xhs | https://github.com/ReaJason/xhs | 小红书笔记公开字段（点赞/收藏/正文），佐证画像卡可填字段 |

## 合规说明

上述项目均声明"仅供学习研究"。本 SKILL 采集路径仅使用 `web_fetch` / `web_search` 抓取平台公开信息，不做逆向、不高频请求、不承诺获取需登录态的后台数据。
