---
name: skill-data-tracker
description: >
  社媒数据记录与趋势分析。三种模式：(A) 记录快照 — 记录当日粉丝数、互动量等指标快照；
  (B) 增长趋势 — 分析粉丝增长率、增速变化、里程碑预测；(C) 内容生命周期 — 追踪单条内容
  从发布到衰减的数据变化，判断速爆型/稳增型/长尾型。当用户说"记录数据"、"今天粉丝数"、
  "增长趋势"、"粉丝增长"、"内容生命周期"、"这条笔记数据变化"、"数据快照"时触发。
layer: attribute
---

# 社媒数据记录与趋势分析

> 记录社媒指标快照、分析粉丝增长趋势、追踪内容生命周期，用时间序列数据驱动运营决策。

## 数据层定位

本 SKILL 是归因链的**粉丝 / 时序快照底座**，唯一权威存储粉丝数、互动量、内容生命周期的时间序列快照（`outputs/_analytics/snapshots/{profile}/{platform}/{date}.json`）。

- **只存时序快照，不存发布事件** — 每次发布的元信息（标题 / 链接 / 类型 / 来源 SKILL）由 `skill-publish-log` 维护（`outputs/_analytics/publish-log.json`）。本底座不重复记录发布事件，避免同一事实两处存储。
- **消费方（读，不回写）** — `skill-publish-analytics` 模式 D（增长归因）与 `skill-social-performance-review`（环比 / 粉丝趋势）以本快照为**粉丝时序的权威来源**。

| 底座 | 存什么 | 谁维护 |
|------|--------|--------|
| `outputs/_analytics/snapshots/{profile}/{platform}/{date}.json` | 粉丝 / 互动时序快照（本 SKILL） | skill-data-tracker |
| `outputs/_analytics/publish-log.json` | 发布事件 | skill-publish-log |

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| mode | 是 | record / growth / lifecycle |
| platform | Mode A: 是 | 平台名（小红书/抖音/微博/B站/公众号等） |
| followers | Mode A: 是 | 当前粉丝数 |
| total_likes | Mode A: 否 | 总获赞数 |
| total_posts | Mode A: 否 | 总笔记/视频数 |
| post_snapshots | Mode A: 否 | 近期帖子的逐条数据（用于生命周期追踪） |
| post_title | Mode C: 是 | 要追踪的帖子标题或标识 |
| time_range | Mode B: 否 | 分析窗口（默认近 30 天） |

## 输出

### Mode A — 记录快照

```markdown
# 数据快照记录
- 日期: {date} | 平台: {platform} | Profile: {profile_name}

## 账号指标
| 指标 | 当前值 | 上次记录 | 变化 |
|------|--------|---------|------|

## 帖子快照（如有）
| 标题 | 发布日期 | 点赞 | 收藏 | 评论 | 转发 |

快照已保存至: outputs/_analytics/snapshots/{profile}/{platform}/{date}.json
```

### Mode B — 增长趋势

```markdown
# 增长趋势分析
- 平台: {platform} | 区间: {start} → {end} | 数据点: {count}

## 粉丝增长趋势
| 日期 | 粉丝数 | 日增长 | 日增长率 |

## 关键指标
- 日均/周均增长 | 趋势方向: 加速/稳定/减速
- 最高/最低单日增长
- 里程碑预测: 照此速度，{X} 天后破 {milestone} 粉
- 趋势洞察: {增长加速/减速原因分析与建议}
```

### Mode C — 内容生命周期

```markdown
# 内容生命周期分析
- 帖子: {post_title} | 发布: {published_at} | 平台: {platform}

## 生命周期数据
| 天数 | 日期 | 点赞 | 收藏 | 评论 | 转发 | 日增量 |
（Day 0 / 1 / 3 / 7 / 14 / 30 各行）

## 分类与洞察
- 类型: 速爆型/稳增型/长尾型 | 峰值日: Day {peak} | 半衰期: {days} 天
- 判定依据与后续策略启示
```

## 数据存储

快照文件路径：`outputs/_analytics/snapshots/{profile}/{platform}/{date}.json`

```json
{
  "date": "2026-07-22",
  "platform": "xiaohongshu",
  "profile": "科技数码达人",
  "account_metrics": {
    "followers": 5200,
    "total_likes": 42000,
    "total_posts": 89
  },
  "post_snapshots": [
    {
      "post_id": "用户提供或自动编号",
      "title": "帖子标题",
      "published_at": "2026-07-20",
      "likes": 350,
      "collects": 120,
      "comments": 28,
      "shares": 15
    }
  ]
}
```

## 执行步骤

快照读写、增长率/移动平均/里程碑外推、生命周期分类全部由 `scripts/track.py`
确定性完成。LLM 负责补全参数（从 Profile/用户输入）、解读脚本 JSON、写增长建议。
**不要手动算增长率、不要心算移动平均、不要手改快照 JSON。**

### Mode A — 记录快照

1. 从 Profile（`identity.md` 取 profile 名、`platforms.md` 取平台）或用户输入采集指标；缺失字段询问一次。
2. 调用脚本（一天一快照，同日覆盖；自动计算与上次快照的 delta）：

```bash
python3 skills/openclaw/skill-data-tracker/scripts/track.py snapshot --profile "科技数码达人" --platform xiaohongshu \
  --followers 5200 --total-likes 42000 --total-posts 89 [--date 2026-07-22] \
  [--posts 帖子逐条数据.json]   # --posts 为数组，含 post_id/title/published_at/likes/collects/comments/shares
```

3. 展示脚本返回的 `snapshot` + `delta_vs_last` + 保存路径。

### Mode B — 增长趋势

```bash
python3 skills/openclaw/skill-data-tracker/scripts/track.py trend --profile "科技数码达人" --metric followers \
  [--platform xiaohongshu] [--since 2026-07-01] [--until 2026-07-31]
```

脚本返回：逐点日增长/日增长率、7 日移动平均、`trend_direction`（加速/稳定/减速）、
`milestone` + `milestone_eta_days`（≤30 天，超出返回 null）、`warning`（<3 点样本不足）。
LLM 据此写趋势洞察与受众相关建议（有 Profile 时读 `audience.md`）。

### Mode C — 内容生命周期

```bash
python3 skills/openclaw/skill-data-tracker/scripts/track.py lifecycle --profile "科技数码达人" \
  --platform xiaohongshu --post-title "露营装备" --metric likes
```

脚本跨快照重建帖子时间序列，返回逐日增量、`peak_day`、`half_life_days`、
`lifecycle_type`（速爆型/稳增型/长尾型/数据不足）。LLM 据类型写后续内容策略。

### 导出增长归因视图

记录快照后生成 `skill-publish-analytics` 模式 D 所需的派生视图；不要手工维护另一份粉丝台账：

```bash
python3 skills/openclaw/skill-data-tracker/scripts/track.py export-followers
```

默认汇总全部画像和平台到 `outputs/_analytics/follower-log.json`；可用 `--profile` 或 `--platform` 过滤。

## Profile 感知

**有 Profile 时：**
- 读取 `identity.md` 获取 profile 名称，用作快照目录名
- 读取 `platforms.md` 自动填充 platform 参数，支持多平台同时记录
- 读取 `audience.md` 在增长分析中给出受众相关的增长建议
- 快照目录按 profile/platform 隔离：`outputs/_analytics/snapshots/{profile_name}/{platform}/`

**无 Profile 时：**
- 要求用户显式提供 platform 参数
- 快照目录使用 "default"：`outputs/_analytics/snapshots/default/{platform}/`
- 增长分析不做受众关联判断
- 附注"提供 Profile 可自动关联平台和账号信息"

## 规则

1. **不修改不删除** — 已有快照文件只读不改，同一天同一平台的重复记录是唯一允许的覆盖情况
2. **一天一快照** — 同一平台每天最多一个快照，当天重复记录会覆盖当天数据
3. **最少 3 个数据点** — 增长率计算至少需要 3 个数据点，不足时输出警告而非空洞的趋势判断
4. **预测不超 30 天** — 里程碑预测基于近期趋势外推，不超过 30 天，避免误导
5. **数据来源透明** — 所有指标来自用户输入或快照文件，不编造数据，不假设未提供的指标

> 自研溯源与参考项目见同目录 `EASEL-META.md`。
