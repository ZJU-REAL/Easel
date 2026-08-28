---
name: roi-calculator
description: >-
  计算内容营销 ROI：根据投放数据算出 CTR/CPC/CPM/ROAS 等指标，对比行业基准，支持单活动分析与多活动横向比较。
  当用户说"算ROI""投放效果""CTR/CPC/CPM/ROAS""投产比""广告效果""投放数据分析""活动ROI"时使用。
layer: attribute
---

# 内容投放 ROI 计算器

> 根据用户提供的投放数据，计算标准营销效果指标，对比行业基准，输出结构化分析报告。

## 输入

用户提供以下字段的任意子集（缺失字段跳过其依赖指标）：

| 字段 | 代号 | 单位 | 必要性 |
|------|------|------|--------|
| 投放费用 | ad_spend | CNY | 核心（为 0 或缺失时切换有机模式） |
| 曝光量 | impressions | 次 | 可选 |
| 点击量 | clicks | 次 | 可选 |
| 互动量 | engagements | 次（赞+评+转） | 可选 |
| 转化数 | conversions | 次 | 可选 |
| 客单价 | avg_order_value | CNY | 可选 |
| 内容制作成本 | production_cost | CNY | 可选，默认不计 |

**两种模式：**

- **Mode A — 单活动分析**：一组输入数据，输出完整指标卡片
- **Mode B — 多活动对比**：多组数据（表格或逐条），按 ROI 降序排列，横向对比

## 输出

### 指标计算（公式表）

以下指标仅在分母数据存在且非零时计算，否则标注"数据不足，已跳过"：

| 指标 | 公式 | 依赖字段 |
|------|------|----------|
| CTR（点击率） | clicks / impressions | impressions, clicks |
| CPC（单次点击成本） | ad_spend / clicks | ad_spend, clicks |
| CPM（千次曝光成本） | (ad_spend / impressions) * 1000 | ad_spend, impressions |
| CPE（单次互动成本） | ad_spend / engagements | ad_spend, engagements |
| 转化率 | conversions / clicks | conversions, clicks |
| CPA（单次转化成本） | ad_spend / conversions | ad_spend, conversions |
| 营收 | conversions * avg_order_value | conversions, avg_order_value |
| ROAS（广告支出回报率） | revenue / ad_spend | revenue, ad_spend |
| 总成本 | ad_spend + production_cost | ad_spend（production_cost 缺失按 0） |
| 利润 | revenue - total_cost | revenue, total_cost |
| ROI | (revenue - total_cost) / total_cost | revenue, total_cost |

### 输出格式

**Mode A — 单活动分析：**

```
## 投放效果报告

### 基础数据
（用户提供的原始字段）

### 计算指标
| 指标 | 值 | 公式 | 基准对比 |
|------|----|------|----------|
| CTR  | x% | clicks/impressions | ▲ 高于行业均值 |
| ...  |    |      |          |

### 基准对比图例
▲ 高于行业均值（表现良好）
▼ 低于行业均值（需关注）
≈ 接近行业均值（正常水平）
⚠ 显著偏离（超出基准 2 倍或低于 50%）

### 诊断
- 表现突出：（列出高于基准的指标及优势分析）
- 待优化：（列出低于基准的指标及具体改进方向）
- 综合评价：（一句话总结本次投放效果）
```

**Mode B — 多活动对比：**

```
## 多活动横向对比（按 ROI 降序）

| 活动 | 花费 | 营收 | ROI | ROAS | CTR | CPC | 综合评价 |
|------|------|------|-----|------|-----|-----|----------|
| ...  |      |      |     |      |     |     |          |

### 最优/最差活动分析
（对比 ROI 最高与最低活动的关键指标差异，找出差距来源）

### 预算分配建议
（基于各活动效率，建议预算向高 ROI 活动倾斜的比例）

### 优化建议
（针对低效活动的具体改进方向）
```

## 执行步骤

> **确定性计算交给脚本，LLM 只做解读。** 上表各项指标（含营收/利润派生，有机模式另算互动率）、
> 有机模式切换、字段校验、Mode B 按 ROI 降序排序，全部由
> [`scripts/calc.py`](scripts/calc.py) 完成（复用 `skills/shared/scripts/social_stats.py`
> 的 `safe_div`，除零/缺字段一律返回 `null`，不心算、不猜数）。

1. **解析输入** — 从用户 prompt 中提取数据字段，识别 Mode A（单组数据）或 Mode B（多组数据）
2. **调用脚本算指标** —
   - Mode A（单活动）：
     ```bash
     python3 skills/openclaw/roi-calculator/scripts/calc.py single --name "活动名" \
       --ad-spend 5000 --impressions 100000 --clicks 3000 \
       --engagements 8000 --conversions 150 --avg-order-value 200 \
       --production-cost 1000
     ```
   - Mode B（多活动，按 ROI 降序）：把各活动整理成 JSON 数组文件后
     ```bash
     python3 skills/openclaw/roi-calculator/scripts/calc.py multi --file campaigns.json
     ```
   脚本自动：11 指标逐项计算（分母为 0/缺失返回 `null` 并视为"数据不足"）、
   营收→ROAS/利润/ROI 派生、`ad_spend` 为 0/缺失时切有机模式（跳过成本类指标）、
   字段校验（负值 / 曝光<点击 / 转化>点击 写入 `warnings`）、Mode B 按 `roi_pct` 降序排序并标 `roi_rank`。
3. **加载基准** — 读取 [benchmarks.md](references/benchmarks.md) 获取行业基准数据
4. **确定对比基准** —
   - 有 Profile：读取 `platforms.md` 确定主平台，选对应平台基准
   - 无 Profile：使用跨平台均值
5. **基准对比（LLM 解读）** — 把脚本输出的每个指标与基准比较，标注 ▲ 高于 / ▼ 低于 / ≈ 持平 / ⚠ 显著偏离
6. **生成诊断（LLM 解读）** — 汇总表现突出项和待优化项，给出可操作的改进建议；转达脚本 `warnings`
7. **Mode B 追加（LLM 解读）** — 基于脚本已排好的 ROI 排名，标注最优/最差，分析差异原因，给出预算分配建议

## 有机内容模式

当 ad_spend 为 0 或缺失时，自动切换：

- 跳过所有成本类指标（CPC/CPM/CPE/CPA/ROAS/ROI/利润）
- 仅计算：CTR（若有 impressions + clicks）、互动率（engagements / impressions）
- 报告标题标注"有机内容效果分析"
- 基准对比使用自然流量基准（通常高于付费流量）

## Profile 感知

**有 Profile 时：**
- 读取 `platforms.md` 获取主投放平台，选用平台专属基准区间
- 读取 `audience.md` 了解受众特征，为转化率判断提供上下文
- 对比结论使用平台维度的精确基准

**无 Profile 时：**
- 使用跨平台综合均值作为基准
- 在报告末尾附注："提供账号 Profile（含平台信息）可获得平台专属基准对比"

## 规则

1. **不捏造输入** — 所有指标仅从用户提供的数据计算，缺失字段跳过依赖指标
2. **公式透明** — 每个指标旁标注计算公式，用户可验证
3. **基准对比** — 与行业基准比较，明确标注高于/低于/持平
4. **缺失容忍** — 缺字段不假设数值，跳过并说明"因缺少 X 数据无法计算"
5. **有机切换** — ad_spend 为 0 或缺失时自动切换有机模式，不报错

## 自研笔记

**基准数据来源（定期更新 references/benchmarks.md）：**
- Google Ads / Meta Ads 官方行业基准报告
- 巨量引擎 / 千川 投放效果白皮书
- 新榜 / 飞瓜 / 蝉妈妈 行业报告
- 各平台创作者中心公开数据

**迭代方向：**
- 增加时间序列对比（周环比、月同比）
- 支持自定义基准（用户提供历史均值作为对比基线）
- 接入真实 API 数据源（巨量引擎 / 小红书聚光 / 微信广告）
- 漏斗可视化输出（impressions → clicks → conversions 漏斗图）
- 归因模型支持（首次触达 / 末次触达 / 线性归因）
- 与 content-postmortem SKILL 联动，投放数据反哺内容策略

**基准数据维护规则：**
- 每季度对照最新行业报告校准 benchmarks.md 中的数值区间
- 标注数据采集时间，过期超过 6 个月的基准加 ⚠ 提示
- 鼓励用户提供自身历史数据，逐步建立账号级内部基准
