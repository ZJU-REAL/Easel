---
name: novel-writer
description: >
  长篇小说/网文连载创作：从世界观、人设和三级大纲写到逐章正文，并用文件化状态维护伏笔、前情和跨章一致性。
  当用户说“写小说/网文/盐选故事、连载、续写下一章、小说大纲、人物设定、世界观、黄金三章”时使用。
  通用文章用 article-outline/social-content；单段改风格或润色用 style-transfer/text-polisher。
layer: produce
---

# AI 小说 / 网文连载创作

> 一句灵感 → 世界观/人设 → 三级大纲 → 逐章正文。核心是**长篇一致性**：
> 用「**文件即真相 + 按需加载**」——AI 不靠上下文记忆，每写一章只加载相关切片，
> 状态全落文件、可 diff、可续写。确定性 IO（搭骨架/进度/机械查 AI 味）走
> `scripts/novel_ops.py`，**创意（设定/大纲/正文）由你 LLM 完成**。

> 只做单段风格改写见 **style-transfer**；只做润色去 AI 感见 **text-polisher**；
> 只做通用文章见 **social-content**；发知乎见 **skill-zhihu-publisher**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 灵感/题材 | 是 | 一句话创意，或已有设定（没给就问） |
| 平台 | 否 | 知乎盐选 / 番茄 / 起点 / 小红书图文（默认按 Profile 或问） |
| 书名 | 否 | 缺省由题材拟定，用作产物目录名 |
| 本次动作 | 否 | 立项 / 出大纲 / 写第 N 章 / 续写 / 改图文（默认按对话判断） |

## 产物结构（`outputs/书名/`）

```
bible/    world.md characters.md voice.md canon.md   ← 硬事实（写每章必读）
outline/  overview.md volumes.md chapters.md          ← 三级大纲
state/    summary.md character-state.md plot-arcs.md progress.json/md  ← 连载状态
chapters/ 001.md 002.md ...                            ← 章节正文
```

脚本路径（相对项目根）：`skills/openclaw/novel-writer/scripts/novel_ops.py`。
字数校验复用：`skills/shared/scripts/wordcount.py`。

## 执行步骤（按对话选对应子流程，不必每次全跑）

### A. 立项（首次）

1. **搭骨架**：`python skills/openclaw/novel-writer/scripts/novel_ops.py scaffold --book "<书名>"`
   （生成 bible/outline/state/chapters 模板，已存在的文件不覆盖）。
2. **定世界观 + 人设 + 文风**：读 `references/web-novel-methodology.md` 与 `references/platform-specs.md`，
   据题材写满 `bible/world.md`（力量体系/规则/硬约束）、`bible/characters.md`（主角+关键配角：身份/外貌/性格/目标/关系）、
   `bible/voice.md`（视角/时态/句式节奏/用词偏好 + 本书禁用词表）。设定要**可执行**（能约束后续正文），不写空话。

### B. 大纲（三级）

3. **overview → volumes → chapters**：写 `outline/overview.md`（一句话卖点+核心冲突+主线+结局向）、
   `outline/volumes.md`（分卷 arc：每卷目标/转折/卷末高潮）、`outline/chapters.md`（章节目录表：标题+一句话钩子+涉及伏笔）。
   大纲底座可参考 `skill-article-outline`，但必须扩成网文三级结构 + 伏笔埋点表（登记进 `bible/canon.md`）。

### C. 黄金三章（前 3 章单独强化）

4. 按 `references/web-novel-methodology.md` 的黄金三章模板，把前三章的**开局钩子、爽点、代入感、追读悬念**拉满
   （第 1 章 3 秒内给冲突/金手指信号；每章末留强钩子）。这三章决定留存，值得单独打磨。

### D. 写单章（连载主循环）

5. **只加载相关切片**（不塞全书）：读 `bible/`（全部，是硬约束）+ `outline/chapters.md` 里本章那行 +
   `state/summary.md`（前情提要）+ `state/character-state.md` 里相关角色。
6. **（可选）先出场景卡**：复杂章节按 `references/scene-card-schema.md` 先列场景卡（角色/地点/冲突/story value 涨落/情绪/出口）再写正文。
7. **写正文**到 `chapters/<三位数>.md`：遵守 `bible/voice.md` 文风、章末强钩子。
8. **字数门禁**：把正文喂
   `python3 skills/shared/scripts/wordcount.py check --target <平台目标字数> --tolerance 0.15 -f chapters/<NNN>.md`
   （知乎盐选/番茄单章常 2000–4000，见 platform-specs），不达标按提示增删。
9. **去 AI 味**：先跑 `python skills/openclaw/novel-writer/scripts/novel_ops.py slopcheck -f chapters/<NNN>.md`
   机械扫（AI 味词/过度连接词/重复句首），命中处改写；再整章过一遍 **text-polisher**（去 AI 感模式）。

### E. sync（定稿后维护状态，防跨章崩坏）

10. 更新 `state/` 与 `bible/canon.md`：
    - 用 **text-condenser**（摘要模式）把「已发生剧情」滚动压缩进 `state/summary.md`（下一章加载它，不是全文）。
    - 更新 `state/character-state.md`（角色位置/处境/关系变化）、`state/plot-arcs.md`（各线进度）、`bible/canon.md`（新事件/时间线/伏笔状态：埋下→回收）。
    - 登记进度：`novel_ops.py record --book "<书名>" --chapter N --title "<标题>" --words <字数> --status done --when <今天日期>`
      （日期从对话上下文取，脚本不自取时间以保确定性）。
11. **一致性自查**：对照 `bible/canon.md` 扫本章有无与既定事实/时间线/人设冲突；发现则改正文或补设定（见 `references/consistency-rules.md`）。

### F.（可选）next 剧情推演

12. 卡剧情时，生成 2–3 个后续章纲**分支**（不同走向/爽点/反转），列优劣供用户选，选定再写。

### G.（可选）改小红书图文连载

13. 把某章交给 **card-xiaohongshu** 或 **xhs-note-creator**，拆成 3–9 张竖版卡片连载（每卡一个情绪节点，末卡留钩子）。

## Profile 感知

- **有 Profile**：`platforms.md` 定平台与单章字数/更新频率；`style.md` 融进 `bible/voice.md` 文风；
  `identity.md`/`audience.md` 定题材调性与目标读者；`preferences.md` 红线（题材/敏感内容）过滤。
- **无 Profile**：先问平台与题材偏好；默认第三人称、单章 ~3000 字、章末强钩子的通用网文风。

## 规则

1. **文件即真相**：设定/状态以 `bible/` `state/` 文件为准，不靠对话记忆；冲突时以 canon 为准。
2. **按需加载**：写每章只读相关切片，避免全书塞上下文导致漂移/超长。
3. **一致性优先**：人设/世界观/伏笔跨章不崩是网文命脉，宁可慢也不崩。
4. **去 AI 味**：机械 slopcheck + text-polisher 双保险；文风统一靠 `bible/voice.md`。
5. **不覆盖已写内容**：scaffold 幂等、record upsert；正文/设定改动用增量编辑，别整篇重写抹掉用户改动。
6. **不编造设定**：拿不准的世界观细节先问或先在 bible 补定义，再写正文。

## 参考来源

见 `EASEL-META.md`。方法论沉淀自 autonovel（模板体系/双免疫去 slop）、马良 MaliangAINovalWriter
（三级大纲/黄金三章/剧情推演）、AI_NovelGenerator（定稿更新状态+一致性校验）、GOAT-Storytelling-Agent
（场景卡分解替代长上下文）——均为「文件即真相 + 按需加载」思路，最适合纯文件工具的 Easel。
