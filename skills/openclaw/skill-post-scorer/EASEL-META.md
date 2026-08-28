# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-post-scorer |
| **所属层** | attribute |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研（frontmatter 无 references/self_developed，正文无自研说明） |
| **参考项目** | 无 |
| **许可** | 待核实 |

## 确定性脚本

| 脚本 | 用途 | 依赖 |
|------|------|------|
| `scripts/score.py` | 历史帖子互动分（`点赞 + 评论×3`）确定性计算 + 筛 Top N%（默认 10%）+ 分布统计 | 复用 `../../shared/scripts/social_stats.py`（`engagement_score` 带自定义权重 / `mean` / `median` / `sample_warning`），纯标准库 |

## 本地化清理

- 2026-07-23：将西方平台/工具残留改为国内可行方案 —— `LinkedIn` 示例改为知乎/微博等国内平台；`fallback-benchmarks.md` 的「Charlie Hills LinkedIn 基准」改为国内长文平台头部创作者基准；删除 `Apify`（西方爬虫），改为各平台创作者中心/后台导出 CSV/Excel 或整理 JSON。
- 互动分与 Top 10% 从 LLM 心算改为调 `score.py`，LLM 只做 Top 帖子特征提炼与草稿五维评分。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
