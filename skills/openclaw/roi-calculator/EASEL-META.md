# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | roi-calculator |
| **所属层** | attribute |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研 |
| **参考项目** | 无开源代码库参考；正文「自研笔记」列出基准数据来源：Google Ads / Meta Ads 官方行业基准报告、巨量引擎 / 千川投放效果白皮书、新榜 / 飞瓜 / 蝉妈妈行业报告、各平台创作者中心公开数据（数据源，非代码来源） |
| **许可** | 随 Easel 项目许可（基准数据引自各平台公开报告，版权归原发布方） |

## 确定性脚本

| 脚本 | 用途 | 依赖 |
|------|------|------|
| `scripts/calc.py` | 11 个营销指标（CTR/CPC/CPM/CPE/转化率/CPA/营收/ROAS/总成本/利润/ROI）确定性计算 + Mode B 多活动按 ROI 降序排序 + 有机模式切换 + 字段校验 | 复用 `skills/shared/scripts/social_stats.py`（`safe_div` / `mean` / `engagement_rate` / `clean` / `sample_warning`），纯标准库 |

> 2026-07-23 新增：把原 SKILL.md 中"逐项计算 / 派生指标 / 按 ROI 排序"的 LLM 心算改为调 `calc.py` 得确定性结果，LLM 只做基准对比与诊断解读。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
