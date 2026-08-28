# EASEL-META — skill-content-gap-analysis

本文件记录 SKILL 的移植血缘与致谢，不参与运行。

## references 移植血缘（诚实标注）

本 SKILL 主体（热搜 + 搜索联想词 + 评论区蓝海挖掘）已是中文社媒语境，但 references 早期移植自**西方 SEO 关键词差距（keyword gap）分析**工具，2026-07-22 已清洗重写。

| 现文件 | 原始来源（西方 SEO 工具血缘） | 清洗后定位 |
|--------|------------------------------|-----------|
| `demand-signals.md` | 原 `api-usage.md`：SemRush `domain_organic` API，`database=us`，关键词差距 = 竞品排名词集合 − 用户排名词集合，过滤条件为月搜索量 > 100、KD < 60 | 需求信号来自平台搜索联想 / 热搜 / 评论区未满足需求；热搜采集统一引用 `../../shared/hotlist-apis.md`，不复制 API 端点 |
| `scoring-model.md` | 原用"搜索量潜力 / 业务匹配度 / 排名难度(KD) / 用户旅程缺口 / 主题集群"等 SEO 话术，季节性需查 Google Trends | 社媒语境评分模型：需求度 / 竞争度 / 账号匹配度 / 制作成本 / 时效价值，逐平台评分，交叉验证防伪蓝海 |

## 本次参考的 GitHub 开源库（致谢）

清洗时参考了以下中文社媒选题挖掘 / 评论区需求分析开源项目，用于确定"需求信号从哪来、怎么读"。仅作方法论参考，本 SKILL 不依赖也不集成这些代码。

| 项目 | 地址 | 参考用途 |
|------|------|---------|
| NanmiCoder/MediaCrawler | https://github.com/NanmiCoder/MediaCrawler | 多平台按关键词采集笔记+评论、评论词云生成——佐证"搜索联想词 + 评论区"作为需求信号源的可行性 |
| 54514382/xhs_search_comment_tool | https://github.com/54514382/xhs_search_comment_tool | 小红书评论区批量采集与字段设计（点赞数/级别/内容），支撑"评论区未满足需求"的信号读法 |
| cv-cat/Spider_XHS | https://github.com/cv-cat/Spider_XHS | 小红书关键词搜索 + 舆情监控场景，佐证平台内搜索联想作为长尾需求入口 |

## 合规说明

上述项目均声明"仅供学习研究"。本 SKILL 采集路径仅使用 `web_fetch` / `web_search` 抓取平台公开信息与热搜公益 API，不做逆向、不高频请求。
