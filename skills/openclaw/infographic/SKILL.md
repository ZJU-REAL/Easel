---
name: infographic
description: "将数据或文字内容转化为可视化信息图，支持静态（AntV）和动画 GIF 两种模式。当用户需要制作信息图、数据可视化、流程图、对比图、动画图表、GIF 图表、思维导图、SWOT 分析图时调用。本地渲染信息图/GIF 动画；要单张静态图片 URL 用 chart-visualization，要 CSV/JSON→整页报告用 data-report"
layer: produce
---

# 信息图制作

> 将数据或文字内容转化为可视化信息图，支持静态 AntV 信息图和动画 GIF 两种输出模式

## 与其他图表 SKILL 的区别

都能"生成图表"，但机制与产物不同，按需求路由：

- **infographic（本 SKILL）** = 本地渲染。两种产物：静态**信息图**（AntV DSL，列表/流程/对比/层级 HTML→SVG）+ **GIF 动画图表**（matplotlib 逐帧→GIF）。
- **chart-visualization** = 调 AntV 远程 API，产出**单张静态图片 URL**（25+ 类型），最快拿到单图。
- **data-report** = 输入 CSV/Excel/JSON，产出**整页可视化报告**（KPI 卡 + 多图 + 洞察 + 表格）。

**两模式边界**：要**静态矢量信息图**（可导出 SVG、模板丰富）→ 模式 A；要**会动的 GIF**（发社媒/朋友圈的动图，如条形竞赛、数字滚动、进度动画、折线生长）→ 模式 B。

## 输入

用户提供的文字内容、数据、或主题描述。可以是结构化数据（CSV/JSON）、自然语言描述、或简单的数字罗列。

## 输出

- 静态模式：`outputs/主题名/infographic.html`（浏览器打开，可导出 SVG）
- 动画模式：`outputs/主题名/chart.gif`（`scripts/gif_chart.py` 直接产出可发社媒的 GIF）

## 执行步骤

### 第一步：确认输出模式

询问用户选择输出格式：

1. **静态信息图**（AntV Infographic）— 列表、流程、对比、层级、关系图等 50+ 模板，矢量渲染，可导出 SVG
2. **动画 GIF**（`scripts/gif_chart.py`）— 条形竞赛 / 数字滚动 / 进度 / 折线生长 4 类爆款动画，直接产出 GIF

如用户需求明确（如"做个条形竞赛动图"或"做个流程图"），直接选择对应模式，无需确认。

### 第二步：分析内容与选择图表

分析用户输入，提取关键信息结构（标题、描述、数据项等）。选择合适的模板/图表类型。

**关键：必须尊重用户输入的语言。用户用中文输入，所有文本必须是中文。**

### 第三步：渲染

- **模式 A（静态 AntV）** → 读 `references/antv-templates.md`：DSL 语法规则、模板选择指南、可用模板列表、HTML 渲染模板。生成 HTML 保存到 `outputs/`，告知路径。

- **模式 B（动画 GIF）** → 调 `scripts/gif_chart.py <子命令>`，无需手写动画代码。子命令按图型：

  | 子命令 | 用途 | 数据 JSON 结构 |
  |--------|------|----------------|
  | `bar-race` | 条形竞赛（排名随时间变化，数据可视化爆款） | `{"title","times":[...],"series":{"名称":[数值×时间]}}` |
  | `count-up` | 数字滚动增长（KPI 从 0 涨到目标） | `{"title","items":[{"label","value","suffix"}]}` 或 `{"label","value"}` |
  | `progress` | 进度动画（`--style ring`/`bar`） | `{"label","value","max","color"}` |
  | `line-grow` | 折线逐步生长 | `{"title","x":[...],"series":{"名称":[数值]}}` |

  通用参数：`--output x.gif`、`--data f.json`（`-` 读 stdin，省略用内置示例）、`--title`、`--width`（默认 900）、`--height`、`--fps`（默认 20）、`--duration`（秒，默认 4）。

  典型调用（先写数据到临时 JSON，再调脚本）：
  ```bash
  python skills/openclaw/infographic/scripts/gif_chart.py bar-race --data data.json \
    --output outputs/城市增长/柱状竞速.gif --width 900 --duration 5
  ```
  脚本自动设置中文字体、Agg 后端、自适应调色板控体积。自检：`python skills/openclaw/infographic/scripts/gif_chart.py --selftest`。

## 目录结构

```
infographic/
├── SKILL.md                    本文件（执行流程 + references 指针）
├── scripts/
│   └── gif_chart.py            模式 B：动画 GIF 运行时（matplotlib+Pillow，4 子命令）
└── references/
    ├── antv-templates.md       模式 A：静态 AntV 信息图完整规范
    └── gif-charts.md           模式 B：图表选择/数据格式参考
```
