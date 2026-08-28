---
name: skill-publish-analytics
description: >-
  分析发布日志数据，从发布时间、标签效果、内容类型、粉丝增长四个维度归因内容表现，输出可执行的优化建议。
  当用户说"发布数据分析""归因分析""什么时间发好""标签效果""内容表现分析""发布日志分析"时使用。
  和 skill-social-performance-review 的区别：本 SKILL 从发布日志做四维归因，review 做跨平台月度组合复盘。
layer: attribute
---

# 发布数据归因分析

> 读取 publish-log.json，从时间、标签、类型、增长四个维度分析内容表现，输出结构化归因报告。

## 数据层定位

本 SKILL 是归因链的**消费层**，只读底座、不新建存储、不回写：

| 数据 | 权威底座 | 维护方 | 本 SKILL 用途 |
|------|----------|--------|----------------|
| 发布事件 | `outputs/_analytics/publish-log.json` | skill-publish-log | 模式 A/B/C |
| 粉丝 / 时序快照 | `outputs/_analytics/snapshots/{profile}/{platform}/{date}.json` | skill-data-tracker | 模式 D 增长归因 |

**粉丝时序的权威来源是 `skill-data-tracker` 的快照底座。** 模式 D 读取的 `outputs/_analytics/follower-log.json` 由 `track.py export-followers` 确定性导出，不应手工维护。字段映射见 `references/follower-log-schema.md`。

## 输入

用户指定分析模式（可组合）：

- **模式 A — 最佳发布时间**：分析发布时段与互动数据的关系
- **模式 B — 标签效果分析**：评估标签对内容表现的影响
- **模式 C — 内容类型对比**：按内容类型对比各项指标
- **模式 D — 增长归因**：关联发布事件与粉丝增长

未指定模式时默认执行 A + B + C。模式 D 前先运行 `python3 skills/openclaw/skill-data-tracker/scripts/track.py export-followers`。

## 数据源

### publish-log.json 结构

```json
{
  "version": "1.0",
  "entries": [{
    "id": "唯一标识",
    "platform": "xiaohongshu|douyin|bilibili|weibo",
    "title": "标题",
    "url": "发布链接",
    "type": "图文|视频|直播|文章",
    "published_at": "ISO 8601 时间戳",
    "logged_at": "记录时间",
    "initial_metrics": {
      "views": null | number,
      "likes": null | number,
      "comments": null | number,
      "shares": null | number
    },
    "skill_source": "生成该内容的 SKILL",
    "profile": "账号画像名",
    "tags": ["标签列表"],
    "notes": "备注"
  }]
}
```

### 数据处理规则

- **null 指标**：排除出该指标的平均值计算，报告覆盖率百分比
- **样本量警告**：单桶 < 5 条时标注 `⚠ 样本不足`；全量 < 10 条时在报告头部警告结果可能不具统计意义
- **时区**：有 Profile 时使用 Profile 中的时区，无 Profile 时默认 Asia/Shanghai

## 执行步骤

四种分析模式的全部计算（时段分桶、标签聚合、类型对比、增长归因、样本量警告、
覆盖率）由 `scripts/analyze.py` 确定性完成。**不要用内联 Python 心算，直接调脚本。**
LLM 只负责选模式、按 Profile 过滤、解读 JSON、写关键发现/方法论/局限性。

1. 检查 Profile 上下文（`=== EASEL ACCOUNT PROFILE ===` 标记），有则取 profile 名。
2. 调用脚本（`--profile` 须放在子命令前；publish-log.json 不存在时脚本友好报错）：

```bash
python3 skills/openclaw/skill-publish-analytics/scripts/analyze.py all
python3 skills/openclaw/skill-publish-analytics/scripts/analyze.py --profile 画像名 time
python3 skills/openclaw/skill-publish-analytics/scripts/analyze.py --profile 画像名 tags
python3 skills/openclaw/skill-publish-analytics/scripts/analyze.py --profile 画像名 types
python3 skills/openclaw/skill-publish-analytics/scripts/analyze.py --profile 画像名 growth
```

3. 脚本输出结构化 JSON：`summary`（总数/日期范围/平台/各指标覆盖率/全量样本警告）+
   各模式结果。每个分析桶含 `count` 和 `warning`（单桶 <5 条标注样本不足）。
4. **解读输出**：按下方各模式说明和「输出格式」把 JSON 转成 Markdown 表格 →
   关键发现（3 条）→ 方法论 → 局限性。局限性须含"关联性不等于因果性"。

## 模式 A — 最佳发布时间

**步骤：**
1. 解析 `published_at` 提取小时和星期几
2. 将时段分为 6 个桶：早晨(6-9) / 上午(9-12) / 午间(12-14) / 下午(14-18) / 晚间(18-22) / 深夜(22-6)
3. 交叉 initial_metrics 计算每个桶的平均互动量（views、likes、comments、shares）
4. 按平台分别统计

**输出：**
- 热力图表格（星期 × 时段），单元格为平均互动综合分
- 推荐 Top 3 发布时段（含具体星期和时间段）
- 各平台分别的最佳时段

**互动综合分计算：**
`engagement_score = views × 0.1 + likes × 1.0 + comments × 2.0 + shares × 3.0`

## 模式 B — 标签效果分析

**步骤：**
1. 提取每条记录的 `tags[]`，统计各标签使用频次
2. 对每个标签计算其关联条目的平均 views、likes、comments、shares
3. 构建标签共现矩阵：标签 A 与标签 B 同时出现的次数
4. 识别高效标签（平均互动高于全局均值）和低效标签

**输出：**
- 标签效果排名表：标签 / 使用次数 / 平均浏览 / 平均点赞 / 平均评论 / 平均转发
- Top 5 与 Bottom 5 标签对比
- 标签共现矩阵（仅展示共现 >= 2 次的组合）

## 模式 C — 内容类型对比

**步骤：**
1. 按 `type` 字段分组（图文 / 视频 / 直播 / 文章）
2. 计算每类的发布数量、平均 views、likes、comments、shares
3. 交叉平台与类型生成二维表

**输出：**
- 类型对比表：类型 / 数量 / 平均浏览 / 平均点赞 / 平均评论 / 平均转发
- 每个指标标注 "winner"（最高值类型）
- 平台 × 类型 交叉表

## 模式 D — 增长归因

**前置条件：** `outputs/_analytics/follower-log.json`（从 `skill-data-tracker` 快照底座导出的派生视图，schema 与字段映射见 `references/follower-log-schema.md`）

**步骤：**
1. 读取 follower-log.json，若不存在则输出提示并跳过本模式
2. 将每条发布事件与发布后 24h / 48h / 7d 的粉丝变化关联
3. 计算每条发布的粉丝增量（发布后快照 - 发布前最近快照）
4. 按粉丝影响力排名

**输出：**
- 发布事件粉丝影响排名表：标题 / 平台 / 发布时间 / 24h增量 / 48h增量 / 7d增量
- 高增长条目的共性分析（类型、标签、时段）
- 若 follower-log.json 不存在，输出：
  > "模式 D 需要粉丝数据。请在 outputs/_analytics/follower-log.json 中记录粉丝快照数据，schema 见 skill-publish-analytics/references/follower-log-schema.md"

## 输出格式

每个模式的输出均包含以下部分：

```markdown
## 数据摘要
- 总条目数 / 日期范围 / 涉及平台
- 各指标覆盖率（非 null 比例）

## 分析结果
（模式对应的表格和图表）

## 关键发现
1. （最重要的可执行洞察）
2. （第二重要）
3. （第三重要）

## 方法论
- 互动综合分计算公式
- 聚合方式（均值 / 中位数）
- 时段划分标准

## 局限性
- 样本量说明
- null 数据覆盖率
- "关联性不等于因果性 — 时段/标签分析反映相关关系，不能直接推导因果"
```

## Profile 感知

- **有 Profile**：
  - 按 `profile` 字段过滤，只分析当前账号的数据
  - 使用 Profile 中的 platform 和 timezone 字段
  - 输出标注 "当前分析范围：{profile_name} @ {platform}"
- **无 Profile**：
  - 分析全部条目，按平台分组展示
  - 报告附注："提供 Profile 可按账号过滤数据并使用平台特定时区"

## 规则

1. **不捏造数据** — 所有数字必须来自 publish-log.json，不得推测或补全
2. **报告样本量** — 每个分析桶必须标注条目数
3. **关联非因果** — 时段和标签分析中必须注明"关联性不等于因果性"
4. **样本不足警告** — 全量 < 10 条时在报告头部加粗警告
5. **计算透明** — 展示每个指标的计算公式和聚合方式

## 自研备注

参考产品：Metricool analytics、Iconosquare insights、SocialBee performance reports、Later analytics。
本 SKILL 侧重中文社媒平台（小红书、抖音、B站、微博）的发布节奏与互动规律分析。
