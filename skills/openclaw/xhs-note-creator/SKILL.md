---
name: xhs-note-creator
description: >
  小红书内容总入口：生成标题、正文、caption、hashtags，以及 3-9 张图文卡片或短视频分镜，覆盖素材分析、卖点评估、去 AI 味和质检。
  当用户说“写/做小红书笔记、小红书图文/种草/文案、出一套卡片、小红书视频”时使用。
  整套笔记用本 SKILL；仅渲染卡片用 card-xiaohongshu；其他平台的通用文案用 social-content。
layer: produce
---

# 小红书笔记创作

把一个主题 + 可选素材，生成**图文卡片组**或**短视频分镜脚本**，按规范输出到 `outputs/`。

## 核心理念

小红书读者看的不是长文，是**卡片组**或**短视频**。长文原稿只是中间产物。

- **图文帖**：3-9 张 3:4 竖版卡片（cover + content × N + ending），每张 ≤80 字
- **视频帖**：15-90 秒竖屏视频分镜 + 封面卡

### 爆款 5 大原则

1. **真实素材优先**：截图、对比图 > 纯 AI 生图
2. **聚焦核心卖点**：用公式判断优先级（稀缺性 × 实用性 × 可感知）
3. **高级感视觉（走 card-design，别做糙卡）**：卡片视觉**统一走 [card-design](../card-design/SKILL.md) 设计系统**（选风格锁 spec、字大字细、填满画幅、禁大 emoji 廉价感）。文案要口语化、真实感，但**视觉不能糙**——想要「素人 / 手账」质感就选 card-design 的**手账贴纸 / 奶油温柔**风格（仍是高质量 HTML 渲染，不是糙 t2i 大 emoji）。
4. **痛点导向**："能解决什么问题" > 堆砌功能列表
5. **快速迭代**：V1(60 分) → 用户反馈 → V2(70 分)

详细方法论：`references/xiaohongshu-viral-methodology.md`

## 工作流

按顺序执行，**不要跳步**。

### Step 0 — Intake（必问，一次问完）

1. **主题 / 目标读者 / 核心观点**
2. **输出形态**：图文 or 视频？（默认图文）
3. **素材**：有无现成文字/图片/视频？
4. **风格**：视觉风格走 **card-design 风格库**（9 种：瑞士极简/杂志编辑/新中式墨韵/奶油温柔/多巴胺 Y2K/高奢黑金/手账贴纸/极客终端/植物清新）——在 Step 5A 出卡时由 card-xiaohongshu 引导选定，这里先不锁死。
5. **卡片数量 / 视频时长**：图文默认 5-7 张；视频默认 30-60 秒

### Step 0.5 — 卖点/亮点分析（推广/分享/测评类必做）

1. 列出所有功能/特性/亮点
2. 让用户对每个点打分：
   - 稀缺性（1-5）：别人有吗？
   - 实用性（1-5）：解决多大问题？
   - 可感知（1-5）：用户能直接看到吗？
3. 得分 = 稀缺性 × 实用性 × 可感知
4. 选 Top 1-2 作为核心卖点

### Step 1 — 素材清点（有素材才做）

如果用户提供了素材，先用脚本生成清单：

```bash
python3 skills/openclaw/xhs-note-creator/scripts/analyze_material.py <path>... \
  --out <work-dir>/reference/materials.json \
  --frames-dir <work-dir>/reference/frames
```

素材价值排序：对比图 > 功能演示 > 数据图表 > 品牌素材

### Step 2 — 采集外部参考（观点类/资讯类必做）

按 `references/reference-search.md` 执行，核心数据 ≥2 个来源交叉验证。

### Step 3 — 写长文原稿（2000-4000 字）

从 H2 开始（不写 H1），写完**先给用户确认**再继续。

### Step 4 — 去 AI 化（强制）

去 AI 感规则统一走 text-polisher 权威源，不在本 SKILL 维护副本：

- 中文规则（含小红书素人感/闺蜜语气/emoji 节奏特化）→ `../text-polisher/references/zh-ai-markers.md`
- 通用填充短语 → `../text-polisher/references/phrases-to-remove.md`
- 公式化结构 → `../text-polisher/references/structures-to-avoid.md`

按其五层原则完整扫描重写，质量评分满分 50。

### Step 5 — 分发：图文 or 视频

#### 5A. 图文帖：拆成 3-9 张卡片

- cover（第 1 张）+ content（中间）+ ending（最后 1 张）
- 每张 ≤80 字
- 一张卡只讲一个论点
- 全套配色/字体/风格保持一致（由 card-design 选中的那一套贯穿整组）

**卡片视觉一律走 card-design 高质量管线，别用糙 t2i / 大 emoji 素人卡。** 按有无真实照片分两条渲染路径（策略写入 `meta.json`，枚举与 `references/meta-schema.md` 一致）：

| 策略 | 适用 | 渲染路径 |
|------|------|----------|
| `html_card` | 纯文字卡 / 概念卡 / 数据卡（**默认、最常用**） | **走 [card-xiaohongshu](../card-xiaohongshu/SKILL.md)**：读 [card-design](../card-design/SKILL.md) 选风格锁 spec → 写 HTML → `render_card.py` 出图 → `card_audit.py` 硬门禁 |
| `text_on_photo` | 有真实照片 + 钩子文字（真实素材最佳） | Pillow `scripts/text_on_image.py`（小红书真实素材路径，保留） |
| `collage` | 有 2-4 张互补照片 | Pillow `scripts/collage_3x4.py` |

> 纯文字/概念/数据卡**不再走用户自备 t2i**——统一由 card-xiaohongshu 渲染，保证视觉质量；只有「真实照片卡」才走 Pillow 路径。

#### 5B. 视频帖：写分镜脚本

- 6-12 个分镜，每镜 2-8 秒
- 每镜含：narration（≤30 字）、on_screen_text（≤15 字）、visual、material_ref
- 出一张 cover 卡作为封面

### Step 6 — caption + hashtags + 标题

**标题**：从公共源 `skills/shared/references/hook-title-formulas.md` 选标题公式（痛点+方案 / 提问式 / 发现式 / 热点词 / 身份共鸣等），产 2-3 个备选。

**caption**：100-300 字，hook 开头 → 关键信息 → CTA，闺蜜语气 + 少量 emoji（点缀节奏，不当图标）

**hashtags**：5-8 个，4 核心（热点词 + 核心功能 + 差异化 + 目标人群）+ 4 辅助（场景 + 品类）

### Step 7 — 落盘

```
outputs/主题名/{YYYY-MM-DD}/{短标题}_{时间戳}/
├── {完整标题}.md        # 长文原稿
├── meta.json            # 元数据（卡片/分镜/caption/hashtags）
├── images/              # 最终卡图 / 封面
└── reference/           # materials.json / 搜索结果
```

目录名走脚本标准化：`python3 skills/openclaw/xhs-note-creator/scripts/normalize_slug.py "标题" --with-ts`

### Step 8 — 校验（强制，两道门）

**① 文本/结构门**（标题/caption/hashtag/卡片字数与结构）：

```bash
python3 skills/openclaw/xhs-note-creator/scripts/validate_meta.py outputs/主题名/meta.json
```

**② 视觉门**（仅 `html_card` 路径，渲染后跑；死空白/密度硬门禁）：

```bash
python skills/openclaw/card-design/scripts/card_audit.py audit -f "outputs/主题名/card_*.png"
```

任一非 0 退出 → 修改后重跑，直到通过。不交付未校验的产物。

## 不要做的事

- 不写 H1；标题只放 `meta.json.title`
- 不在正文末尾写参考来源
- 不在 `.md` 里留 `【插入图片】` 占位符
- 不跳过 Step 4（去 AI 化）和 Step 8（validate）
- 不手算目录名，一律走 `normalize_slug.py`

## Profile 感知

- **有 Profile**：读取赛道、目标受众、内容风格，对齐笔记语气和标签策略
- **无 Profile**：询问基本信息后以通用种草风格输出

## 工具依赖

- Python 3.8+、Pillow（必需，真实照片卡路径）
- playwright + chromium（`html_card` 路径渲染卡片，走 card-xiaohongshu；首次 `pip install playwright && playwright install chromium`）

## 参考资料

- **卡片视觉** → [card-design](../card-design/SKILL.md)（设计系统/风格库，出图前必读）+ [card-xiaohongshu](../card-xiaohongshu/SKILL.md)（HTML→截图渲染管线）
- `references/xiaohongshu-viral-methodology.md` — 文案/卖点/标题/情绪方法论（视觉部分已交 card-design）
- 去 AI 化 → `../text-polisher/references/zh-ai-markers.md`（权威源，含小红书特化）
- 钩子/标题公式 → `skills/shared/references/hook-title-formulas.md`（公共源）
- `references/material-intake.md` — 素材处理流程
- `references/image-sourcing.md` — 图片来源处理
- `references/meta-schema.md` — 元数据字段定义
- `references/output-spec.md` — 输出目录规范
