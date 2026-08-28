---
name: skill-content-calendar-log
description: >
  统一内容日历底座。记录每次发布（发布页/对话页均自动落库）、用户排期、平台活动/节日/特殊日期到
  一个时间线，并供 Agent 规划前读回。当用户说"内容日历""日历里有什么""接下来发什么""这周发了啥"
  "把这个活动记到日历""最近的发布节奏""哪个平台该更新了"时触发。是发布时间线的权威底座，
  与 skill-publish-log（指标底座）互补：本底座管"何时发什么/该做什么"，publish-log 管"每条数据表现"。
layer: attribute
---

# 统一内容日历底座

> 记录发布 + 排期 + 平台活动到一条时间线，供规划读回。产物即 Web「内容日历」页所见。

## 数据层定位

唯一权威存储 `outputs/_schedule.json`（与 Web 日历页 `/api/schedule` **同一文件**）。每条：

| 字段 | 说明 |
|------|------|
| `kind` | `content`（内容/发布）\| `event`（平台活动/节日/特殊日期） |
| `status` | content 专属：`idea`/`draft`/`scheduled`/`published` |
| `platform` `title` `date` `time` `note` `url` | 通用 |
| `source` | `manual`/`publish-page`/`chat`/`scheduler`（来源可溯） |
| `event_type` `end_date` | event 专属 |

- **发布自动落库，无需手动**：发布页与对话页最终都调 publisher 脚本（`xhs_publish`/`douyin_publish`/`web_publisher`/`bili_upload`），脚本在 `--exec` 成功时自动记一条 `published`（并同步转发 `skill-publish-log`）。别再手动补记，避免重复。
- **与 publish-log 分工**：本底座管时间线（何时发什么、待发排期、平台节点、该补内容提醒）；`skill-publish-log` 管每条发布的指标（阅读/点赞/复盘）。record-publish 一次调用同时写两库，不漂移。

## 触发场景

- **读回规划**（最常用）：规划选题/排期前先看日历——各平台发布节奏、断更缺口、待发排期、临近可蹭的平台活动。
- **记平台活动**：把节日/电商大促/平台活动落到对应日期（常配合 `skill-event-calendar` 查出节点再批量导入）。
- **手动排期/补记**：用户口头说的排期或线下已发的内容。

## 命令

```bash
# 读回规划摘要（Agent 规划前必读）：各平台节奏/断更缺口 + 待发排期 + 临近节点 + 建议
python skills/shared/scripts/calendar_ops.py context --days 14 --gap 5

# 未来 N 天的排期 + 活动（--kind 可只看 content 或 event）
python skills/shared/scripts/calendar_ops.py upcoming --days 14 [--kind event]

# 一键铺某年固定节日（阳历固定日 + 阴历经 lunar.py 换算 + 母亲节/感恩节等"第N个周几"；幂等可反复跑）
python skills/shared/scripts/calendar_ops.py seed-holidays --year 2026

# 记录一条平台活动/节日/特殊日期
python skills/shared/scripts/calendar_ops.py add-event --title "双11" --date 2026-11-11 \
  --event-type 电商 [--end-date 2026-11-12] [--platform 抖音] [--note 备注]

# 从 skill-event-calendar 的 JSON 批量导入活动（同名同日幂等去重；stdin 或 --file）
python skills/shared/scripts/calendar_ops.py import-events --file events.json

# 过滤查询
python skills/shared/scripts/calendar_ops.py list [--kind content] [--platform 小红书] \
  [--since 2026-08-01] [--until 2026-08-31]

# 手动补记一条已发布（仅当发布未经 publisher 脚本、需人工补录时用）
python skills/shared/scripts/calendar_ops.py record-publish --platform 小红书 --title "标题" \
  --type 图文 [--url ...] [--tags "AI,教程"] [--note ...] [--source manual]
```

`context` 输出的 `suggestions`（断更提醒 / 临近节点无排期）应原样转达用户，作为"接下来做什么"的依据。

## 与其他 SKILL 的分工

| SKILL | 关系 |
|-------|------|
| `skill-content-calendar`（plan） | 生成月度排期表；排前先读本底座 `context`，排后把计划写回（`add-event`/或前端排期） |
| `skill-event-calendar`（discover） | 查未来节日/节点；查到后可 `import-events` 落库到日历 |
| `skill-publish-log`（attribute） | 指标底座；发布记录已由脚本自动同步，无需重复调用 |

## Profile 感知

- 有 Profile：`platform` 可从 `platforms.md` 主平台推断；`context` 的断更提醒结合账号主平台更有意义。
- 无 Profile：覆盖全部记录，不做账号过滤。

> 自研溯源与参考见同目录 `EASEL-META.md`。
