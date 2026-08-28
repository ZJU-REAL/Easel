# 论文解读 Slide 设计系统

> 适用于论文解读视频中的 16:9 / 9:16 页面。复用 `card-design` 的核心原则：先选设计立场、
> 锁定字体与颜色、一页一观点、渲染后硬审计；但不照搬小红书 3:4 卡片的字号和密度。

## 1. 先锁设计立场

稳定的是页面骨架、信息预算、渲染和审计，不是风格名单。用户可以要求任意风格；先把其拆成可观察的
氛围、配色、线条、纹理、字体、构图与视觉素材，再锁定整套设计立场；不逐页换主题。

`style` 是用户的原始风格意图，不是枚举。`base_style` 才是稳定渲染基底：

| base_style | 初始视觉 | 可作为哪类迁移的起点 |
|---|---|---|
| `editorial` | 暖纸、衬线、细线、论文图优先 | 默认；知识、社科、论文深度解读 |
| `swiss` | 白底、无衬线、12 栏、单一克莱因蓝 | AI、工程、数据、产品论文 |
| `noir` | 近黑、暖白、少量金色、细衬线 | 影视、游戏、视觉生成等题材 |
| `chinese-ink` | 宣纸色、墨色、印章红 | 中文人文、历史、传统文化 |
| `cream` | 低饱和奶油色、柔和大圆角 | 生活科普、心理、教育 |
| `dopamine` | 高饱和对比、粗线、硬阴影 | 快节奏、年轻化、强钩子 |
| `journal` | 手账纸感、网格、轻微错落 | 学习笔记、方法整理 |
| `terminal` | 深色终端、等宽字、绿色信号 | 编程、开源、系统论文 |
| `botanical` | 植物系绿、米白、细腻纸感 | 生物、环境、健康 |
| `cute-anime` | 明亮粉蓝、圆润边框、星点纹理 | 可爱动漫、轻科普、人物向解读 |
| `detective-comic` | 蓝红高对比、网点、粗边硬阴影 | 侦探漫画、揭秘、推理式叙事 |

这些只是初始基底，不是对用户风格的分类。不得说“只支持表中风格”，不得为每个 IP、画风或形容词新增一个预设，
也不得把用户意图简化成“换配色”。例如暗夜英雄、美式超级英雄、日式侦探动漫都是合法的 `style`；
它们可以共用某个 `base_style`，但通过不同的 treatment、token、参考图和素材得到不同结果。

`treatment` 控制跨风格的形式语法：`clean`（克制）、`soft`（圆润柔和）、`comic`（粗线、网点、硬阴影）、
`technical`（终端/工程）、`handmade`（手账错落）。这些也是可组合的渲染语法，不是用户风格名。

每次迁移都重新做设计判断，不套固定映射：

1. 保留用户原话作为 `style`，结合 Profile/参考图提取可观察特征。
2. 选一个只负责底色与字体起点的 `base_style`，不将其当成最终风格。
3. 用 `treatment` 确定线条、边框、阴影和构图语法，用 `theme` 精确锁定 token。
4. 需要角色、建筑、道具、动作线或特定插画笔触时，放入 `figure`/重绘素材，不指望 CSS token 代替内容素材。
5. 渲染 contact sheet 与参考图对照；只换了颜色、氛围或构图不像都必须返工。

### 默认也要有设计

用户没指定风格时，`editorial` 是设计立场，不是“米白底 + 两段字”。至少要锁定一套可识别的纸张纹理、
编辑网格、章节编号、图片框法与强调色规则。渲染器会提供受控 `motif`（`auto/none/index/brackets/rings/crosshair`）
作为辅助视觉锚点；它不能代替与论文内容有关的素材。

写 slide-plan 前先做一次视觉素材盘点：

- 从 `parsed/figures/` 挑 2–4 张真正支撑结论的论文图，必要时裁关键局部。
- 方法或结果难读时，用 infographic/chart-visualization 重绘，不把原图缩成邮票。
- 封面、问题和结论页缺少论文图时，可添加与概念直接相关的线稿、符号图形、局部截图或字体图形；不用随机机器人、灯泡和 blob。
- 一套 6 页以上的成片，原则上至少 1/3 页面有内容型视觉素材（原图/裁切/重绘/相关插图）；其余页面也要靠网格、层级和 motif 形成完整构图。
- 素材是证据或风格语汇，不是填空。加了素材却分散中心观点，宁可删掉。

### 可迁移主题 token

`theme` 只接受受控 token，不接受原始 CSS；这样既能迁移风格，又不破坏溢出检查和稳定渲染：

```json
{
  "style": "雨夜都市超级英雄漫画",
  "base_style": "noir",
  "treatment": "comic",
  "theme": {
    "bg": "#10131a",
    "ink": "#f4f1e8",
    "accent": "#f2c94c",
    "accent2": "#3973d6",
    "font": "sans",
    "radius": 4,
    "heading_weight": 900,
    "texture": "halftone"
  }
}
```

可覆写颜色 `bg/ink/muted/accent/accent2/line/surface/panel`，字体类型 `sans/serif/mono/rounded`，
圆角 `0–32`，字重 `100–900`，纹理 `none/paper/grid/halftone/sparkle`。参考图里的角色、插画或论文图仍作为
`figure` 素材处理；主题 token 只负责把其它页面的视觉语言统一起来。完整示例见
`slide-plan.style-transfer.example.json`；它是迁移机制的测试样例，不是推荐所有论文使用该画风。

颜色不是“填得进 JSON 就算可用”。渲染器会在合并 `base_style + theme` 后检查 `ink/muted` 与
`bg/surface/panel` 的正文对比度（至少 4.5:1）；明亮 accent 仍可保留作边框、阴影和图形，但用在小字或
彩色圆点内时会自动切换到可读的语义前景色。不要为了过门槛固定某套颜色，应从参考风格中重新选择同色相但
更合适的明度，或调整承载文字的 surface/panel。

## 2. 先做 slide-plan，再渲染

`slide-plan.json` 是页面唯一输入；渲染器不负责重新理解论文：

```json
{
  "version": 1,
  "title": "论文简称",
  "style": "editorial",
  "base_style": "editorial",
  "treatment": "clean",
  "size": "1920x1080",
  "source": "Paper title · arXiv:xxxx.xxxxx",
  "slides": [
    {
      "type": "cover",
      "kicker": "PAPER EXPLAINED · 01",
      "title": "模型会翻译，为什么还是不会说人话？",
      "claim": "这篇论文把文化有效性纳入机器翻译评测",
      "figure": {"path": "assets/figure-1.png", "caption": "Figure 1", "fit": "contain"},
      "narration": "……"
    },
    {
      "type": "evidence",
      "kicker": "EVIDENCE · 06",
      "title": "老指标漏掉了什么？",
      "claim": "字面正确，不等于文化语气传达有效",
      "figure": {"path": "assets/figure-6.png", "caption": "Figure 6 · 论文原图", "fit": "contain"},
      "points": ["BLEU 只看句面相似", "Eff. 检查梗和语气是否传达"],
      "source": "Paper §4.2 / Figure 6",
      "narration": "……"
    }
  ]
}
```

相对图片路径先按 plan 所在目录解析，再按项目根解析。`narration` 只给配音，不显示在页面。

## 3. 页面类型

只从以下骨架选，不临场发明布局：

| type | 用途 | 必需内容 |
|---|---|---|
| `cover` | 钩子封面 | title + claim，可选 figure |
| `statement` | 问题、转折、局限、结论 | title + claim，可选 points |
| `evidence` | 论文关键图/表 | title + claim + figure，可选 points |
| `process` | 方法流程 | title + steps（2–4 步） |
| `metrics` | 实验主结果 | title + metrics（1–3 个）+ claim |
| `comparison` | 新旧方法/两种路线 | title + columns（恰好 2 列） |
| `takeaway` | 收尾 | title + claim + points（2–4 条） |

连续最多两页使用同一种 `type`；结构相近的页面要通过 evidence / statement / metrics 切换节奏。

## 4. 信息充分度与预算（硬门）

- 一页只讲一个 `claim`，是只有一个中心结论，不是整页只能放一句话。暂停或静音时，读者仍应能从
  claim + 解释/证据/数字口径中理解“结论是什么、为什么”。口播可以更丰富，但不能把 narration 整段搬上屏。
- title ≤ 28 字符；claim ≤ 72 字符。
- points 2–5 条时，每条 8–48 字符，写成可独立理解的解释，不用“更快 / 更强 / 效果好”式标签。
- steps 2–4 个，每步 title ≤ 16、body ≤ 52 字符。
- metrics 1–3 个；value ≤ 14、label ≤ 20、note 需说明数字口径或意义且 ≤ 40 字符，不能重复 label。
- comparison 两列，每列 body 用完整依据解释差异且 ≤ 90 字符，不能只写一句口号。
- 放不下就拆页或删字，绝不缩成小字。

默认 `density` 为 `balanced`：statement/takeaway 无图时至少 2 条支持信息，evidence 至少 2 条读图线索，
process 的每一步要说清动作或因果，metrics/comparison 要能脱离口播独立读懂。只有当一张图本身就是主要信息、
放大阅读比加文字更重要时，才在该页显式设 `"density": "visual"`；visual 页必须有 figure。这个开关表达的是
信息载体，不绑定题材或画风，也不能用来掩盖没有提炼出内容。

## 5. 论文图的处理

- `evidence` 页面里论文图必须是主角，默认占页面内容区 55%–65%，不能缩成邮票。
- 原图信息太密时先裁关键区域或重绘，不把整页 PDF 截图直接塞入。
- 一页只解释图中的一个结论；claim 先说结论，caption 再标 Figure/Table 和来源。
- 图中文字在最终视频分辨率下看不清时，必须重绘或加局部放大页。
- 禁止拉伸图片；`fit` 只用 `contain` 或 `cover`。

## 6. 16:9 / 9:16 排版底线

- 16:9：标题 ≥ 56px，正文 ≥ 30px，caption/source ≥ 20px。
- 9:16：标题 ≥ 58px，正文 ≥ 32px，caption/source ≥ 22px。
- 标题左对齐；除 cover/noir 明确需要外，不居中一切。
- 英文按单词换行，禁止把 `Translation` 断成 `Tr / anslation`。
- 一套只用 1 个强调色；颜色承担语义，不用彩色左边框装饰每个块。
- 禁止靠无关 blob、圆圈、机器人、emoji 填空；空白必须是有网格依据的呼吸。

### 对齐与容器律（硬门）

- 先定主网格再放元素：标题、主内容、底部来源共用页边距，不用肉眼凑坐标。
- 同一卡片内的编号、小标题、正文必须共用一条左边线；文字不得漂在它所解释的元素外。
- process/metrics/comparison 组内元素等高，顶边和底边对齐；不因某一列字少就变成高低错落。
- 子元素不得超出卡片/图框/主内容区边界，也不得与兄弟元素重叠；阴影可越界，实体和文字不行。
- 结构页的主内容横向至少跨主区 62%、纵向至少 38%；内容少就换紧凑骨架或加有意义的图，不把小卡片悬在大片空白中。
- 留白用来分组和强调，不是“剩下的地方”。某一边持续空出超过画面 1/3 却没有图、motif 或叙事作用，视为死空白。

## 7. 生成与硬审计

```bash
python skills/openclaw/paper-explainer/scripts/render_slides.py validate \
  --plan outputs/<项目>/assets/slide-plan.json

python skills/openclaw/paper-explainer/scripts/render_slides.py render \
  --plan outputs/<项目>/assets/slide-plan.json \
  --out-dir outputs/<项目>/assets/slides

python skills/openclaw/paper-explainer/scripts/render_slides.py audit \
  --plan outputs/<项目>/assets/slide-plan.json \
  --slides-dir outputs/<项目>/assets/slides \
  --contact-sheet outputs/<项目>/assets/slides-contact-sheet.jpg
```

`render` 会在截图前检查 DOM 溢出、父容器越界、元素重叠、组内顶/底边对齐、卡内文字左边对齐与结构页内容跨度；
`audit` 检查数量、尺寸、空白图、计划预算，并生成 contact sheet。
任何非 0 退出都必须改 plan 后重渲。最后当前 Agent 还要肉眼查看 contact sheet，检查论文图是否可读、
视觉节奏是否重复、强调点是否正确；只过脚本不等于视觉合格。
