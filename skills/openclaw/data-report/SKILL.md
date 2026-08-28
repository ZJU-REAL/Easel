---
name: data-report
description: "把 CSV、Excel 或 JSON 数据生成包含 KPI、图表和洞察的完整可视化报告页。当用户说“数据报告、CSV/Excel 转报告、做 KPI 看板、生成可视化报告页”时使用。单张图表用 chart-visualization；信息图或 GIF 动画图表用 infographic。"
layer: produce
---

# 数据可视化报告

你是一名数据可视化专家。把用户提供的 CSV/Excel/JSON 数据，转成一份自包含的
HTML 可视化报告（KPI 卡片 + 图表 + 数据洞察 + 数据表）。

数据读取、聚合、出图、HTML 组装都由 `scripts/report.py` 确定性完成，
你只负责"写洞察文字"这一需要理解的环节，不要手算聚合、手拼图表。

## 与其他图表 SKILL 的区别

三者都能"生成图表"，但机制与产物不同，按需求路由：

- **data-report（本 SKILL）** = 输入 CSV/Excel/JSON，产出**整页可视化报告**（KPI 卡 + 多图 + 洞察 + 表格）。要一份完整报告页时用它。
- **chart-visualization** = 调 AntV 远程 API，产出**单张静态图片 URL**（25+ 类型）。只要一张标准统计图、直接拿图片链接时用它。
- **infographic** = 本地 JS 渲染，产出**信息图 / GIF 动画图表**。要结构化信息图或带动画的 GIF/MP4 时用它。

## 输入

- 数据文件：`.csv` / `.json` / `.xlsx`（Excel 需环境有 openpyxl，缺失时脚本会提示）
- 可选：报告标题、想突出的 KPI 列名

## 输出

- 一个自包含 HTML 报告文件（图表以 base64 内嵌，可离线打开），写入 `outputs/`
- 可选：把 HTML 渲染成一张长图用于社媒分享

## 执行步骤

### 1. 读数据概览（供你写洞察）

```bash
python skills/openclaw/data-report/scripts/report.py analyze <数据文件>
```

返回 JSON：行列数、每列类型与缺失、数值列的 min/max/mean/median/sum/std、
每个类别列的 Top 5。**据此判断数据讲了什么**，为第 3 步准备洞察文字。

### 2. 生成报告 HTML

```bash
python skills/openclaw/data-report/scripts/report.py report <数据文件> \
  -o outputs/主题名/report.html \
  --title "报告标题" \
  --kpi 列名1 列名2         # 可选，不给则自动挑数值列
```

脚本自动：算 KPI（数值列汇总）、自动选型出 2-4 张图（时间序列→折线、
类别→柱状、占比→饼图）、拼成含 KPI 卡 + 内嵌图 + 数据表的整页 HTML。
matplotlib 用 Agg 后端并已配好中文字体，不会乱码。

### 3. 补写洞察文字（可选但推荐）

基于第 1 步的概览，在生成的 HTML 里补 3-5 条洞察（emoji 开头、像产品周报：
趋势、异常、对比、行动建议）。用 Edit 在报告的洞察区插入即可——数据都是
真实的，**不要捏造数字**，只做解读。

### 4. 渲染成长图分享（可选）

```bash
python skills/shared/scripts/render_card.py \
  --html outputs/主题名/report.html \
  --out outputs/主题名/report.png \
  --full-page --width 1080
```

## Profile 感知

- **有 Profile**：从 `style.md` 读品牌主色，用 Edit 改 HTML 里 `--main` 变量统一配色。
- **无 Profile**：用脚本默认专业配色。

## 要点

- **必须用脚本解析真实数据**，KPI 与图表由脚本从数据算出，不要手写数值。
- 洞察是你唯一"创作"的部分，其余都走脚本保证确定性。
- 无数值列时脚本仍出数据表（会打印 WARN），报告依然可用。
