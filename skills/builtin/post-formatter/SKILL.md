---
name: post-formatter
description: >
  用 PAS、AIDA、BAB、STAR、SLAY 等经典框架将主题结构化为社媒帖子。
  200-250 字、20 行以内、移动端友好排版。适用于公众号、知乎、微博、LinkedIn 等长文帖子。
  当用户说"用 PAS 写"、"AIDA 框架"、"结构化帖子"、"套框架写"时使用。
  和 social-content 的区别：post-formatter 严格套用营销框架，social-content 偏自由写作。
layer: produce
---

# 帖子框架化

> 用 PAS / AIDA / BAB / STAR / SLAY 五大经典框架，把一个主题结构化成中文社媒长文帖子。
> 只负责"套框架 + 排版"，不做自由创作（那是 social-content 的活）。

## 输入

从用户 prompt 中提取以下信息，缺哪个就现场问：

| 字段 | 说明 | 缺省处理 |
|------|------|----------|
| 主题 | 一句话主题，或一段素材/笔记/数据 | 必需，缺则询问 |
| 框架 | PAS / AIDA / BAB / STAR / SLAY 之一 | 缺则按内容目的自动选 |
| 平台 | 小红书 / 抖音 / B站 / 微博 / 公众号 / 知乎 | 缺则按通用中文社媒 |
| 补充 | 事实、数据、调性、目标读者 | 可空 |

若主题和框架都缺，用一轮 AskUserQuestion 一次问齐主题与框架，再补一句
"还有什么要我知道的？数据、调性或写给谁看"。信息足够时直接开写，不啰嗦。

## 输出

一条可直接发布的中文帖子，放在代码块里，无前言无后记。结构：

- 首行钩子
- 第二行反转/对比
- 主体（按所选框架分阶段）
- 收尾 + 一句中文互动引导

## 执行步骤

1. **定框架**：用户指定就用指定的；没指定就按 `skills/shared/references/copy-frameworks.md`
   的"框架选择规则"，按内容目的挑一个。选定后只用一个，不混用。
2. **拆主题**：框架各阶段的定义见 `skills/shared/references/copy-frameworks.md`，各阶段占几行见
   `references/frameworks.md`（行数分配）；把主题和素材拆进各阶段。
3. **写正文**：严格套用 `references/formatting.md` 的中文排版规则——
   200-250 字、≤20 行、行间空行、短句、去破折号、去 AI 感。
4. **配 CTA**：结尾用中文社媒式引导（关注 / 收藏 / 评论区聊聊），一句即可，
   贴合内容目的，不用 "Repost if" 这类英文表达。
5. **自检**：按 `references/formatting.md` 末尾的自检清单逐条过（钩子、翻译腔、
   列表、结尾）。**字数、行数用脚本取确定性结果，不靠肉眼数**：
   - 字数：`python3 skills/shared/scripts/wordcount.py check --target 225 --tolerance 0.12`
     （stdin 传入正文），退出码 0 = 落在 200-250 区间；非 0 时脚本会给出「还需增/删 X 字」，据此调整后重跑。
   - 行数：把正文交给 `wc -l` 数一遍，确认 ≤20 行。
   超限就改到脚本判定通过为止。
6. **输出**：只给最终帖子，放代码块，不加解释。

## 与 social-content 的边界

- **post-formatter（本 SKILL）**：严格套一个营销框架，产出结构固定的单条帖子。
  用户明确要"用 PAS 写""套 AIDA""结构化帖子"时用。
- **social-content**：自由创作，多平台原生格式、钩子/标签/互动策略齐活，不绑框架。
- 简言之：要框架、要结构 → 本 SKILL；要自由发挥、要全套物料 → social-content。

## Profile 感知

- 有 Profile：把账号的调性、常用句式、目标读者、禁用词吃进去，让框架输出
  贴合该账号人设；平台默认取 Profile 主平台。
- 无 Profile：退到通用中文社媒模式，按 `references/formatting.md` 的默认规则写。

## 硬规则

- 只返回成品帖子，不加元评论。
- 字数、行数用脚本校验：字数走 `skills/shared/scripts/wordcount.py check`（social_count 口径），行数用 `wc -l`，以脚本结果为准，超限即改。
- 全程不用破折号（em dash）。
- 列表要么恰好三项，要么不列，不凑数。
- 领域知识（框架说明、排版规则）都在 references/，本文件只讲流程。
