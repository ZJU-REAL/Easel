---
name: skill-publish-log
description: >
  发布记录管理。当用户提到"记一下刚发的"、"发布记录"、"这个月发了多少"、"发布历史"、
  "记录一下"、"发布日志"、"上次发了什么"时触发。支持记录每次发布的内容信息（平台、标题、
  链接、时间、初始数据），并提供查询和统计功能，方便后续复盘。
layer: attribute
---

# 发布记录管理

> 记录、查询、统计每次社媒内容发布的信息，作为复盘和归因的数据底座。

## 数据层定位

本 SKILL 是归因链的**发布事件底座**，唯一权威存储 `outputs/_analytics/publish-log.json`（每次发布的平台 / 标题 / 链接 / 时间 / 初始数据 / 标签 / 来源 SKILL）。

- **只存发布事件，不存粉丝时序** — 粉丝数、互动量的时间序列快照由 `skill-data-tracker` 维护（`outputs/_analytics/snapshots/`）。本底座不重复记录粉丝时序，避免同一事实两处存储。
- **消费方（读，不回写）** — `skill-publish-analytics`（时段 / 标签 / 类型 / 增长归因）与 `skill-social-performance-review`（月度复盘）读取本底座做归因。

| 底座 | 存什么 | 谁维护 |
|------|--------|--------|
| `outputs/_analytics/publish-log.json` | 发布事件（本 SKILL） | skill-publish-log |
| `outputs/_analytics/snapshots/{profile}/{platform}/{date}.json` | 粉丝 / 互动时序快照 | skill-data-tracker |

## 输入

用户 prompt 中提供以下信息之一：

### 记录模式（写入）
- **必填**：平台、标题（或内容摘要）
- **可选**：链接、发布时间（默认当前时间）、内容类型（图文/视频/直播）、初始数据（阅读/点赞/评论/转发）、关联 SKILL（由哪个 SKILL 产出）、备注

### 查询模式（读取）
- 按时间范围查询："这个月发了什么""最近一周"
- 按平台筛选："小红书上发了哪些"
- 按关键词搜索："关于 AI 的发布记录"
- 查看最近一条："上次发了什么"

### 统计模式（汇总）
- 按时间统计："这个月发了多少条"
- 按平台统计："各平台发布数量"
- 数据汇总："总互动量排行"

## 输出

### 记录模式

确认写入成功，返回记录摘要：

```
已记录发布：
- 平台：小红书
- 标题：《5 个被低估的 AI 工具》
- 时间：2026-07-22 14:30
- 链接：https://...
- 记录编号：#042
```

### 查询模式

返回匹配的记录列表（表格形式）：

```markdown
| # | 日期 | 平台 | 标题 | 链接 | 类型 |
|---|------|------|------|------|------|
| 042 | 07-22 | 小红书 | 5 个被低估的 AI 工具 | [链接] | 图文 |
| 041 | 07-20 | 抖音 | AI 剪辑实操 | [链接] | 视频 |
```

### 统计模式

返回结构化的统计信息：

```markdown
## 本月发布统计（2026-07）

- 总发布数：12 条
- 按平台：小红书 5 | 抖音 4 | B站 2 | 微博 1
- 按类型：图文 7 | 视频 4 | 直播 1
- 总互动量：点赞 2,340 | 评论 189 | 转发 67
```

## 存储格式

数据存储在 `outputs/_analytics/publish-log.json`，结构如下：

```json
{
  "version": "1.0",
  "entries": [
    {
      "id": 42,
      "platform": "小红书",
      "title": "5 个被低估的 AI 工具",
      "url": "https://...",
      "type": "图文",
      "published_at": "2026-07-22T14:30:00+08:00",
      "logged_at": "2026-07-22T14:35:00+08:00",
      "initial_metrics": {
        "views": null,
        "likes": null,
        "comments": null,
        "shares": null
      },
      "skill_source": "skill-card-xiaohongshu",
      "profile": "my-xhs-account",
      "tags": ["AI", "工具推荐"],
      "notes": ""
    }
  ]
}
```

**字段说明：**
- `id`：自增编号
- `platform`：发布平台
- `title`：内容标题或摘要
- `url`：发布链接（可为空）
- `type`：内容类型（图文/视频/直播/文章）
- `published_at`：实际发布时间
- `logged_at`：记录写入时间
- `initial_metrics`：发布时的初始数据（可部分为空）
- `skill_source`：产出该内容的 SKILL（可为空）
- `profile`：关联的账号 Profile（可为空）
- `tags`：内容标签
- `notes`：备注

## 执行步骤

读写、id 自增、过滤、聚合全部由 `scripts/log.py` 确定性完成（原子写、除零安全）。
LLM 只负责解析用户意图 → 组织参数 → 解读脚本返回的 JSON → 生成用户可读输出。
**不要手动改 JSON、不要心算统计。**

1. **判断操作模式**：根据用户 prompt 识别是记录、查询还是统计
2. **信息不足时追问**：记录模式下至少需要平台和标题，缺少时提示补充
3. **调用脚本**（数据文件不存在时脚本自动初始化空结构）：

```bash
# 记录（id 自增，原子写回 outputs/_analytics/publish-log.json）
python3 skills/openclaw/skill-publish-log/scripts/log.py record --platform 小红书 --title "标题" \
  --type 图文 --url "https://..." --views 1000 --likes 120 \
  --comments 30 --shares 10 --tags "AI,工具推荐" [--published-at ISO时间] \
  [--skill-source skill-xxx] [--profile 画像名] [--notes 备注]

# 查询（按平台/时间/关键词/画像过滤，--latest 取最近一条）
python3 skills/openclaw/skill-publish-log/scripts/log.py query --platform 小红书 --since 2026-07-01 \
  [--until 2026-07-31] [--keyword AI] [--profile 画像名] [--latest] [--limit N]

# 统计（按 platform/type/month 聚合数量 + 互动总量 + 平均综合分）
python3 skills/openclaw/skill-publish-log/scripts/log.py stat --by platform --since 2026-07-01
```

4. **解读结果**：把 JSON 转成 SKILL.md「输出」节的表格/摘要格式呈现给用户；
   脚本返回的 `warning` 字段（样本不足）如非空须原样传达。

## Profile 感知

### 有 Profile 时

- 读取 `platforms.md` 自动填充 `platform` 字段（从主平台推断）
- 读取 `identity.md` 获取账号名称，自动关联 `profile` 字段
- 统计时可按 Profile（账号）维度汇总
- 查询时默认只显示当前 Profile 的记录

### 无 Profile 时

- `platform` 必须由用户明确指定
- `profile` 字段留空
- 统计和查询覆盖所有记录，不做账号过滤
- 附注："如提供账号 Profile，可自动关联平台并按账号分组统计"

> 自研溯源与参考项目见同目录 `EASEL-META.md`。
