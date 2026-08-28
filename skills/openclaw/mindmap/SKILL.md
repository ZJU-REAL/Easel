---
name: mindmap
description: "思维导图：把 Markdown 大纲（标题层级 + 列表）渲染成可交互思维导图 HTML，可选导出 PNG。适合知识结构、内容框架、SWOT、脑图梳理。当用户说 思维导图、脑图、mindmap、知识导图、大纲图、把要点做成脑图、内容结构图、SWOT图、树状图 时使用。基于 shared/scripts/mindmap.py（markmap 自包含 HTML + Chromium 渲染 PNG）。与 chart-visualization/infographic 区别：那些做数据图表/信息图，本 SKILL 专做层级大纲思维导图。"
layer: produce
---

# 思维导图（Markdown → 脑图）

> 把 Markdown 大纲渲染成可交互思维导图 HTML，可选导出 PNG。走 `skills/shared/scripts/mindmap.py`
> （markmap）。

> 数据图表见 chart-visualization；信息图/流程图见 infographic；本 SKILL 专做**层级大纲脑图**。

## 输入

Markdown 大纲（用标题 `#`/`##`/`###` 表示层级，`-` 列表表示叶子）：
```markdown
# 中心主题
## 分支一
- 要点 A
- 要点 B
## 分支二
- 要点 C
```

## 输出（`outputs/主题名/`）

- 思维导图 HTML（单文件；markmap JS 走 CDN，联网可交互展开/折叠，离线打开不可交互）
- 可选 PNG 图片（`--png`）

## 执行

脚本路径（相对项目根）：`skills/shared/scripts/mindmap.py`（`make -h`）。

```bash
# 先把内容整理成 Markdown 大纲（你来做），存为 outline.md，再：
python skills/shared/scripts/mindmap.py make -i outline.md \
  -o outputs/主题名/mm.html --png
```
`-i -` 可从 stdin 读；`--title` 自定义标题；`--bg` 背景色。

## 用法要点

1. **先把内容组织成清晰的 Markdown 大纲**（层级分明、每节点简短）——这是脑图质量的关键，
   由你（LLM）完成：从文章/主题提炼中心 → 分支 → 要点。
2. 层级建议 2-4 层，节点文字精炼（几个字），别把整句话塞进节点。
3. HTML 可交互（展开/折叠、缩放），适合分享或嵌入；PNG 适合直接发图。

## 前置（PNG）

PNG 渲染需 playwright + chromium + 外网（markmap JS 走 CDN）。仅要 HTML 则无额外依赖。

## 规则

1. 内容先成 Markdown 大纲再渲染，不要把无结构的长文直接丢进去。
2. 节点简洁；层级不宜过深（超过 4 层可读性差）。
3. 产物统一进 `outputs/主题名/`。

## 参考来源

markmap（Markdown → 交互式思维导图）是开源标准方案；本 SKILL 生成自包含 HTML（CDN 加载
markmap），并用 Chromium 无头渲染导出 PNG。
