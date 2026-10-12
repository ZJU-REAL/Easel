# 模式 A：静态信息图（AntV Infographic）

使用 AntV Infographic DSL 渲染，适合列表、流程、对比、层级、关系图等结构化内容。矢量渲染，可导出 SVG。

## DSL 语法规则

- 第一行必须是 `infographic <template-name>`
- 使用 `data` / `theme` 块，块内两空格缩进
- 键值对使用"key 空格 value"；数组使用 `-` 前缀
- icon 使用 icon 关键字（如 `star fill`）
- `data` 应包含 title/desc + 模板特定的主数据字段（只用一个，不要混用）：
  - `list-*` -> `lists` | `sequence-*` -> `sequences`（可选 `order asc|desc`）
  - `compare-*` -> `compares`（支持 `children` 分组）| `compare-binary-*` 必须恰好两个根节点
  - `hierarchy-structure` -> `items` | `hierarchy-*` -> 单个 `root`（树形，通过 `children` 嵌套）
  - `relation-*` -> `nodes` + `relations`（边标签：`A -label-> B` 或 `A -->|label| B`）
  - `chart-*` -> `values` | 兜底用 `items`
- `theme` 自定义主题：
  - 暗色：`theme dark`
  - 调色板：`palette` 下列颜色值
  - 手绘风格：`stylize rough` + `font-family 851tegakizatsu`
  - 图案填充：`stylize pattern`
  - 渐变：`stylize linear-gradient` / `radial-gradient`
- 不要输出 JSON、Markdown 或解释性文本

## 语法示例

列表模板：

```plain
infographic list-grid-ribbon-card
data
  title 中国六大茶类
  desc 按发酵程度分类
  lists
    - label 绿茶
      desc 不发酵，清汤绿叶
      icon leaf
    - label 红茶
      desc 全发酵，红汤红叶
      icon fire
theme
  palette #2d5016 #c4a35a #d4483b
```

关系模板：

```plain
infographic relation-dagre-flow-tb-simple-circle-node
data
  nodes
    - id A
      label 节点 A
    - id B
      label 节点 B
  relations
    A - 审批 -> B
```

对比模板（SWOT）：

```plain
infographic compare-swot
data
  compares
    - label 优势
      children
        - label 品牌强
        - label 用户忠诚
    - label 劣势
      children
        - label 成本高
```

序列模板（流程步骤）：

```plain
infographic sequence-timeline-simple
data
  title 产品发展路线
  sequences
    - label 2023 Q1
      desc 立项启动
    - label 2023 Q2
      desc 内测上线
    - label 2023 Q4
      desc 正式发布
  order asc
```

层级模板（组织结构）：

```plain
infographic hierarchy-tree-tech-style-badge-card
data
  root
    label 总部
    children
      - label 技术部
        children
          - label 前端组
          - label 后端组
      - label 产品部
```

手绘风格示例（stylize rough）：

```plain
infographic list-row-horizontal-icon-arrow
theme
  stylize rough
  base
    text
      font-family 851tegakizatsu
data
  title 每日习惯
  lists
    - label 早起
      icon sun
    - label 运动
      icon running
```

## 模板选择指南

| 场景 | 推荐模板 |
|------|----------|
| 严格序列（流程/步骤） | `sequence-*`（timeline / stairs / roadmap / zigzag / circular / pyramid） |
| 观点罗列 | `list-row-*` / `list-column-*` / `list-grid-*` |
| 二元对比 | `compare-binary-*` |
| SWOT 分析 | `compare-swot` |
| 象限分析 | `compare-quadrant-*` |
| 层级结构 | `hierarchy-tree-*` / `hierarchy-structure` |
| 思维导图 | `hierarchy-mindmap-*` |
| 数据图表 | `chart-*`（bar / column / line / pie / wordcloud） |
| 关系展示 | `relation-*` |

## 可用模板列表

`chart-*`: bar-plain-text, column-simple, line-plain-text, pie-compact-card, pie-donut-pill-badge, pie-donut-plain-text, pie-plain-text, wordcloud

`compare-*`: binary-horizontal-badge-card-arrow, binary-horizontal-simple-fold, binary-horizontal-underline-text-vs, hierarchy-left-right-circle-node-pill-badge, quadrant-quarter-circular, quadrant-quarter-simple-card, swot

`hierarchy-*`: mindmap-branch-gradient-capsule-item, mindmap-level-gradient-compact-card, structure, tree-curved-line-rounded-rect-node, tree-tech-style-badge-card, tree-tech-style-capsule-item

`list-*`: column-done-list, column-simple-vertical-arrow, column-vertical-icon-arrow, grid-badge-card, grid-candy-card-lite, grid-ribbon-card, row-horizontal-icon-arrow, sector-plain-text, zigzag-down-compact-card, zigzag-down-simple, zigzag-up-compact-card, zigzag-up-simple

`relation-*`: dagre-flow-tb-animated-badge-card, dagre-flow-tb-animated-simple-circle-node, dagre-flow-tb-badge-card, dagre-flow-tb-simple-circle-node

`sequence-*`: ascending-stairs-3d-underline-text, ascending-steps, circular-simple, color-snake-steps-horizontal-icon-line, cylinders-3d-simple, filter-mesh-simple, funnel-simple, horizontal-zigzag-underline-text, mountain-underline-text, pyramid-simple, roadmap-vertical-plain-text, roadmap-vertical-simple, snake-steps-compact-card, snake-steps-simple, snake-steps-underline-text, stairs-front-compact-card, stairs-front-pill-badge, timeline-rounded-rect-node, timeline-simple, zigzag-pucks-3d-simple, zigzag-steps-underline-text

## HTML 渲染模板

```html
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{标题} - Infographic</title></head>
<body>
<div id="container" style="width:100%;height:100%"></div>
<script src="https://unpkg.com/@antv/infographic@latest/dist/infographic.min.js"></script>
<script>
  const infographic = new AntVInfographic.Infographic({
    container: '#container', width: '100%', height: '100%',
  });
  document.fonts?.ready.then(() => {
    infographic.render(`{syntax}`);
  }).catch(() => {
    infographic.render(`{syntax}`);
  });
</script>
</body></html>
```

必须包含：charset utf-8、AntV 脚本引入、container div、响应式宽高 100%。
SVG 导出：`const svgDataUrl = await infographic.toDataURL({ type: 'svg' });`
