# follower-log.json Schema

> 模式 D（增长归因）所需的粉丝快照数据格式。

## 数据来源：派生自 data-tracker 快照底座

粉丝时序的**权威底座是 `skill-data-tracker`** 的快照（`outputs/_analytics/snapshots/{profile}/{platform}/{date}.json`）。运行 `track.py export-followers` 生成本派生视图，用于 `analyze.py` 模式 D；请勿手工另起粉丝台账。

字段映射（快照 → 本文件的每个 `snapshots[]` 元素）：

| data-tracker 快照 | follower-log.json |
|-------------------|-------------------|
| 快照文件名 `{date}` | `recorded_at` |
| `account_metrics.followers` | `followers` |
| `account_metrics.total_posts` | `total_posts` |
| `platform` | `platform` |
| `profile` | `profile` |

## 文件位置

`outputs/_analytics/follower-log.json`

```bash
python3 skills/openclaw/skill-data-tracker/scripts/track.py export-followers
```

## 结构

```json
{
  "version": "1.0",
  "snapshots": [
    {
      "profile": "账号画像名（与 publish-log 中的 profile 字段对应）",
      "platform": "xiaohongshu|douyin|bilibili|weibo",
      "recorded_at": "ISO 8601 时间戳（记录时间）",
      "followers": 12345,
      "following": 100,
      "total_posts": 50,
      "notes": "可选备注（如活动期间、投放期间）"
    }
  ]
}
```

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| profile | string | 是 | 账号画像名，用于关联 publish-log 中的条目 |
| platform | string | 是 | 平台标识，枚举值同 publish-log |
| recorded_at | string | 是 | ISO 8601 格式的记录时间 |
| followers | integer | 是 | 粉丝数 |
| following | integer | 否 | 关注数 |
| total_posts | integer | 否 | 累计发布数 |
| notes | string | 否 | 备注信息 |

## 采集建议

- **频率**：每日至少一次，最好在固定时间采集（如每日 23:00）
- **关键时点**：发布新内容前后各采集一次，以便计算单条内容的粉丝影响
- **数据来源**：从 `skill-data-tracker` 已积累的快照按上表字段映射导出；快照本身由 data-tracker 的 `record` 模式采集

## 归因计算方式

模式 D 通过以下方式关联发布事件与粉丝变化：

1. 找到发布时间 `published_at` 前最近的粉丝快照作为基准
2. 找到发布后 24h / 48h / 7d 内最近的粉丝快照
3. 粉丝增量 = 后续快照的 followers - 基准快照的 followers
4. 若时间窗口内无快照数据，该窗口标注为 `N/A`
