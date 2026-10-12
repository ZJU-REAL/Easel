# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-content-postmortem |
| **所属层** | attribute |
| **来源类型** | 自研（参考开源项目与方法论） |
| **原始来源** | Easel 自研 |
| **参考项目** | 1) pyviralcontent（GitHub bhaskatripathi/pyviralcontent，https://github.com/bhaskatripathi/pyviralcontent）— 多维度内容传播力评分（Keener 多准则决策分析）；2) Predicting-Virality-of-Social-Media-Content（GitHub Ashish-Nanda，仓库地址 待核实）— 基于随机森林的特征重要性排序；3) GitHub topics: viral-content / social-media-analysis / social-media-analytics — "Hook 分析 + 结构拆解 + 平台适配"通用分析框架 |
| **许可** | 待核实 |

## 确定性脚本

| 脚本 | 用途 | 依赖 |
|------|------|------|
| `scripts/aggregate.py` | 模式 B（≥5 条规律提炼）的聚合统计：阈值划分 top20%、爆款组 vs 普通组分组对比、两维交叉、标签共现 | 复用 `../../shared/scripts/social_stats.py`（`engagement_score` / `group_aggregate` / `cooccurrence` / `pct_change` / `median` / `sample_warning`），纯标准库 |

> 2026-07-23 新增：模式 B 的阈值划分/分组对比/多维交叉从 LLM 心算改为调 `aggregate.py`，LLM 只做规律提炼与公式总结。模式 A（单条定性拆解）不变。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
