---
name: chart-visualization
description: "将数据可视化为图表。当用户需要生成柱状图、折线图、饼图、散点图、雷达图、桑基图、思维导图、流程图等图表时调用此技能，通过 curl 工具调用 AntV API 生成图表图片。产出静态图片 URL（25+ 类型）；要本地渲染的信息图/GIF 动画图表用 infographic，要 CSV/JSON→整页报告用 data-report"
layer: produce
---

请根据用户输入的内容，将数据可视化为图表。

## 与其他图表 SKILL 的区别

三者都能"生成图表"，但机制与产物不同，按需求路由：

- **chart-visualization（本 SKILL）** = 调 AntV 远程 API（gpt-vis），产出**静态图片 URL**，25+ 图表类型，最快拿到单张图。要单张标准统计图、直接拿到图片链接时用它。
- **infographic** = 本地 JS 渲染，产出**信息图 / GIF 动画图表**（列表/流程/对比/层级模板 + 逐帧动画）。要可导出 SVG 的结构化信息图、或带入场动画的 GIF/MP4 时用它。
- **data-report** = 输入 CSV/Excel/JSON，产出**整页可视化报告**（KPI 卡 + 多图 + 数据洞察 + 表格）。要一份完整报告页而非单图时用它。

## 步骤
1. 分析用户数据和需求，选择最合适的图表类型
2. 构造符合规范的 JSON 请求体
3. 使用 curl 工具调用 API 生成图表图片
4. 将返回的图片 URL 以 Markdown 图片格式输出

## 图表选择指南

根据用户的数据特征和需求，选择最合适的图表类型：

- **时间序列**：用 `line`（趋势）或 `area`（累计趋势）；两个不同量纲用 `dual-axes`
- **比较类**：用 `bar`（横向分类对比）或 `column`（纵向分类对比）；频率分布用 `histogram`
- **占比类**：用 `pie`（比例构成）或 `treemap`（层级占比）
- **关系与流程**：用 `scatter`（相关性）、`sankey`（流向）或 `venn`（集合重叠）
- **层级与树形**：用 `organization-chart` 或 `mind-map`
- **专用类型**：
  - `radar`：多维度对比
  - `funnel`：流程阶段转化
  - `liquid`：百分比/进度
  - `word-cloud`：文本词频
  - `boxplot` / `violin`：统计分布
  - `network-graph`：复杂节点关系
  - `fishbone-diagram`：因果分析
  - `flow-diagram`：流程图
  - `spreadsheet`：结构化数据表或透视表

## API 接口

POST https://antv-studio.alipay.com/api/gpt-vis

> 该端点为 AntV/支付宝官方 gpt-vis 公共免费托管服务，无需 key；公共服务可能限流或调整，返回失败时重试或退回本地渲染（infographic 模式 A）。

请求体为 JSON，必须包含 `type` 和 `source: "chart-visualization-skills"` 字段。

示例：
```bash
curl -X POST https://antv-studio.alipay.com/api/gpt-vis \
  -H "Content-Type: application/json" \
  -d '{"type":"line","source":"chart-visualization-skills","data":[{"time":"2025-01","value":100}],"title":"示例图表"}'
```

返回示例：
```json
{"success":true,"resultObj":"https://..."}
```

将 `resultObj` 中的 URL 以 Markdown 图片格式输出：`![图表](URL)`

## 支持的图表类型

| 分类 | 图表类型 |
|------|---------|
| 比较类 | 条形图(bar)、柱状图(column)、瀑布图(waterfall)、双轴图(dual-axes) |
| 趋势类 | 面积图(area)、折线图(line)、散点图(scatter) |
| 分布类 | 箱线图(boxplot)、直方图(histogram)、小提琴图(violin)、漏斗图(funnel) |
| 占比类 | 饼图(pie)、水波图(liquid)、词云(word-cloud) |
| 层级类 | 组织架构图(organization-chart)、思维导图(mind-map)、矩形树图(treemap)、桑基图(sankey) |
| 关系类 | 关系图(network-graph)、韦恩图(venn) |
| 流程类 | 流程图(flow-diagram)、鱼骨图(fishbone-diagram) |
| 多维类 | 雷达图(radar) |
| 表格类 | 表格/透视表(spreadsheet) |

## 通用可选参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| theme | string | "default" | 主题："default" / "academy" / "dark" |
| width | number | 600 | 图表宽度 |
| height | number | 400 | 图表高度 |
| title | string | "" | 图表标题 |
| style.texture | string | "default" | 纹理："default" / "rough"（手绘风格） |

带坐标轴的图表还支持：axisXTitle、axisYTitle。

## 各图表 data 格式

- **area / line**: `{time: string, value: number, group?: string}[]`，可选 stack: boolean
- **bar**: `{category: string, value: number, group?: string}[]`，可选 group / stack (默认 stack: true)
- **column**: `{category: string, value: number, group?: string}[]`，可选 group (默认 true) / stack
- **scatter**: `{x: number, y: number, group?: string}[]`
- **pie**: `{category: string, value: number}[]`，可选 innerRadius: number (0-1)
- **radar**: `{name: string, value: number, group?: string}[]`
- **funnel**: `{category: string, value: number}[]`
- **waterfall**: `{category: string, value?: number, isTotal?: boolean, isIntermediateTotal?: boolean}[]`
- **dual-axes**: categories: string[], series: {type: "column"|"line", data: number[], axisYTitle?: string}[]
- **histogram**: `number[]`，可选 binNumber: number
- **boxplot / violin**: `{category: string, value: number, group?: string}[]`
- **liquid**: percent: number (0-1)，可选 shape: "circle"|"rect"|"pin"|"triangle"
- **word-cloud**: `{text: string, value: number}[]`
- **sankey**: `{source: string, target: string, value: number}[]`，可选 nodeAlign
- **treemap**: `{name: string, value: number, children?: ...}[]` (最深 3 层)
- **venn**: `{sets: string[], value: number, label?: string}[]`
- **network-graph / flow-diagram**: `{nodes: {name: string}[], edges: {source: string, target: string, name?: string}[]}`
- **fishbone-diagram / mind-map**: `{name: string, children?: ...}` (最深 3 层)
- **organization-chart**: `{name: string, description?: string, children?: ...}` (最深 3 层)，可选 orient: "horizontal"|"vertical"
- **spreadsheet**: `Record<string, string | number>[]`，可选 rows / columns / values（透视表字段）
