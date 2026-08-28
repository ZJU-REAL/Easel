# 复盘报告模板

> Phase 6 输出的报告结构模板。主 SKILL.md 引用此文件。

---

## 报告文件

保存路径：`outputs/reviews/[客户名]-social-review-[月份]-[年份].md`

---

## 报告结构

```markdown
# 社媒复盘 — [年 月]
**复盘对象：** [客户/账号名]
**覆盖平台：** [平台列表]
**数据来源：** [CSV 导出 / 截图 / 手动录入 — 如实标注]

---

## 本月概览
[3-4 句概括。当月的核心故事是什么？]

| 指标 | 本月 | 环比上月 |
|---|---|---|
| 总触达/曝光 | | |
| 平均互动率 | | |
| 发布条数 | | |
| 粉丝变化 | | |

---

## 表现好的
[Top 3 帖子 + 指标 + 用通俗语言解释为什么有效]

## 表现差的
[Bottom 帖子 + 诚实诊断 + 教训]

## 内容拆解
[支柱和格式表现摘要 — 保持可读性，不堆数字]

## 核心洞察
[2-4 条要点 — 解释当月表现的核心模式]

## 下月建议
[3-5 条具体的、按影响力排序的建议]

每条建议格式：
**[建议标题]**
What: [具体变更]
Why: [数据支撑]
How: [在排期或文案中如何落地]

---
*Review prepared using [Month] data. Next review: [Next month].*
```

---

## 上下文文件更新

### 更新 `context/best-performers.md`

追加本月 Top 3 帖子（按保存或互动率），每条包含：
- 帖子主题
- 格式（单图/轮播/Reels）
- 文案首句
- 关键指标（触达、互动率、保存数）

此文件为 `social-content` / `copywriting` 提供参考 — 保持更新可提升文案质量。

### 追加 `context/review-history.md`

追加一行月度摘要：
```
[Month Year] | Reach: [x] | Avg ER: [x%] | Followers: [+/- x] | Top pillar: [pillar] | Top format: [format] | Score: [x/10]
```

此文件构建跨月趋势日志。

---

## 交接提示

报告完成后输出：

```
复盘已保存到 outputs/reviews/[文件名].md

基于本次复盘的下一步操作：
- 运行 /content-calendar 制定下月排期 — 使用上述支柱和格式调整建议
- 如需永久调整内容支柱，更新 brand-style.md
- best-performers.md 已更新本月 Top 3 帖子
```
