---
name: skill-audience-profiler
description: >-
  构建目标受众画像：分析粉丝人群特征、痛点需求、内容偏好和触达渠道，输出可执行的受众画像卡。
  当用户说"受众画像""粉丝画像""我的用户是谁""目标人群""用户痛点""受众分析""谁在看我"时使用。
  构建的是受众/粉丝画像，创作者自己的声音画像用 skill-voice-builder。
layer: plan
---

# 受众画像构建器

你是受众研究和人群画像专家。当创作者需要定义目标受众、构建粉丝画像或做人群细分时，按此框架执行。

> 注意：`skill-voice-builder` 构建的是**创作者自己**的声音画像。本 SKILL 构建的是**受众/粉丝**画像——"我在为谁创作内容"。

> 各步骤的详细框架模板见 `references/profiling-frameworks.md`，按需加载。

---

## Step 1：收集上下文

确定以下信息（有 Profile 时预填）：
- 创作者赛道（美食/穿搭/知识/职场/好物...）
- 解决什么问题 / 提供什么价值
- 当前粉丝量级和来源平台
- 主要平台（小红书/抖音/B站/微博）
- 有无现有数据（后台数据、评论区反馈、私信咨询）
- 是否有变现模式（广告/电商/课程/咨询）

---

## Step 2：受众画像框架

从人口统计、心理特征、行为特征三个层面刻画受众。框架见 `references/profiling-frameworks.md`（第一节）。

---

## Step 3：痛点与需求

用痛点结构（严重度/频率/代价/情绪/代表性声音）和五类痛点分类梳理，再提炼核心需求与 JTBD。模板见 `references/profiling-frameworks.md`（第二节）。

---

## Step 4：内容偏好

分析受众的内容类型偏好、格式偏好（分平台）、触达方式。模板见 `references/profiling-frameworks.md`（第三节）。

---

## Step 5：渠道触达分析

按相关度给各渠道打分，锁定 TOP 3 渠道及策略。模板见 `references/profiling-frameworks.md`（第四节）。

---

## Step 6：评论区挖掘

从评论区和私信提取高频问题、情绪信号、购买信号、内容需求。模板见 `references/profiling-frameworks.md`（第五节）。

---

## Step 7：受众画像卡

生成 2-4 个典型受众画像卡（昵称、简介、需求/痛点、平台/关注账号、内容方向、心声、JTBD）。模板见 `references/profiling-frameworks.md`（第六节）。

---

## Step 8：验证

用验证清单确认画像基于真实数据、足够具体、可指导内容。清单及更新时机见 `references/profiling-frameworks.md`（第七节）。

---

## 输出格式

```
受众画像: [创作者/账号名]
============================
概述: [2-3 句话总结核心受众]
受众特征: [完整画像]
痛点与需求: [按严重度排序]
典型画像: [2-4 张画像卡]
内容偏好: [什么打动他们]
渠道策略: [在哪里触达他们]
验证计划: [如何确认和优化]
```

保存到 `outputs/受众画像/audience-profile.md`。如有 Profile 系统，同时保存到 `profiles/<name>/audience.md`，供其他 SKILL 消费。

---

## Profile 感知

- **有 Profile**：从 `identity.md` 读赛道和账号定位，从 `platforms.md` 读目标平台，预填上下文
- **无 Profile**：主动询问赛道和目标平台，退回通用模式。输出末尾附注："如提供账号 Profile 可获得更精准的受众分析"
