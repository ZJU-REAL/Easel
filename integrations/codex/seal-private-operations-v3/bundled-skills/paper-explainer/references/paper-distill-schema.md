# asset library 提炼 Schema（论文 → 结构化中间产物）

> `paper_ingest.py skeleton` 生成空骨架，读解析出的 `parsed/content.*` 填满它。
> 这是**唯一真相源**：视频分镜和图文都从它生成，保证口径一致、不重复提炼。

## 字段与填写要求

| 字段 | 内容 | 要求 |
|------|------|------|
| `meta` | title / authors / venue / arxiv_id / url | 从原文抄，别改 |
| `one_liner` | 一句话讲清「这篇论文干了啥」 | 大白话，非专业读者也懂；≤40 字 |
| `hook` | 视频/图文开头钩子 | 制造好奇/反差/切身相关（见 explain-methodology） |
| `problem` | 要解决什么问题、为什么重要 | 落到「为什么该关心」 |
| `prior_gap` | 已有方法的不足 | 说清「以前不行在哪」，衬托本文贡献 |
| `contributions` | 核心贡献点 | **≤3 条**，每条一句话，是全篇最该传达的 |
| `method.idea` | 核心思路 | 一句话点破「关键的聪明点」 |
| `method.how` | 怎么做的 | 简述机制，能讲清但不堆公式 |
| `method.analogy` | **通俗类比** | 用日常事物类比方法（类比不能扭曲原意） |
| `key_figures[]` | 关键图表 | 挑 2–4 张最能说明问题/方法/结果的 |
| `key_figures[].path` | 图路径 | 引用 `parsed/figures/` 里的原图 |
| `key_figures[].plain` | 大白话解释这张图 | 看图能懂：横纵轴是啥、曲线说明啥 |
| `key_figures[].why_matters` | 这张图为何关键 | 它证明了什么 |
| `results` | 主要结果 | **带关键数字**（提升了多少、超过谁），别只说"效果好" |
| `limitations` | 局限 | 诚实列，别只报喜 |
| `takeaway` | 对观众意味着什么 | 落到读者/行业的 so-what |
| `terms[]` | 术语通俗表 | `{term, plain}`，把不得不用的术语各给一句人话 |

## 填写纪律

1. **忠于原文**：数字、结论、方法细节以原文为准；拿不准标 `[待核对]`，不臆造。
2. **贡献收敛**：论文常列一堆贡献，提炼时收敛到**最重要的 ≤3 条**——视频/图文讲不完那么多。
3. **图先行**：论文的核心方法图和主结果图通常是讲解主线，优先选进 key_figures。
4. **术语最小化**：能不用术语就不用；必须用的进 terms 给人话解释，正文里首次出现即解释。
5. **一次到位**：这份 JSON 填好后，视频和图文都不再回头读全文——所以要够全、够准。

## 下游怎么用

- **视频**：`hook`→开场；`problem/prior_gap`→背景；`contributions/method`→主体（配 key_figures 或重绘图）；`results`→高潮；`takeaway`→收尾。见 video-storyboard.md。
- **图文**：同结构展开成文，key_figures 作插图，terms 作名词解释。见 platform-adapt.md。
