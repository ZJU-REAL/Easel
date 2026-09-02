# 动画 GIF 图表参考（模式 B）

> 模式 B 的运行时是 `scripts/gif_chart.py`（matplotlib + Pillow，纯 Python，无浏览器）。
> 本文件说明 4 个子命令的适用场景与数据格式。自检：`python skills/openclaw/infographic/scripts/gif_chart.py --selftest`。

## 子命令选择

| 子命令 | 动画效果 | 适用场景 |
|--------|----------|----------|
| `bar-race` | 条形竞赛（排名随时间变化） | 多主体随时间的排名/规模变化（各平台粉丝增长、销量榜） |
| `count-up` | 数字滚动增长（0 → 目标） | KPI 数字冲击（累计用户、日活、好评率） |
| `progress` | 进度动画（环形 ring / 条形 bar） | 单一完成度 / 达成率 / 占比 |
| `line-grow` | 折线逐步生长 | 趋势随时间生长（增长曲线、对比走势） |

## 通用参数

所有子命令共用：`-o/--output`（指定 `outputs/<具体主题>/<子命令>.gif`）、`--data`（JSON 路径，`-` 读 stdin，省略用内置示例）、`--title`、`--width`（默认 900）、`--height`、`--fps`（默认 20）、`--duration`（默认 4 秒）。脚本自动设置中文字体、Agg 后端、自适应调色板控体积。

## 数据格式（JSON）

### bar-race
```json
{
  "title": "各平台粉丝增长",
  "times": ["1月", "2月", "3月", "4月"],
  "series": {
    "小红书": [10, 25, 40, 62],
    "抖音":   [15, 30, 38, 55],
    "B站":    [8,  14, 22, 30]
  }
}
```
额外参数：`--top-n`（每帧显示前 N 名，默认 10）。

### count-up
```json
{
  "title": "核心数据",
  "items": [
    {"label": "累计用户", "value": 1280000, "suffix": ""},
    {"label": "日活跃",   "value": 356000,  "suffix": ""},
    {"label": "好评率",   "value": 98,      "suffix": "%"}
  ]
}
```
每项支持 `prefix`/`suffix`（如 `¥`、`%`）。也可传单条 `{"label","value","prefix","suffix"}`。

### progress
```json
{"label": "项目完成度", "value": 76, "max": 100, "color": "#FF6B6B"}
```
额外参数：`--style ring`（环形，默认）或 `--style bar`（条形）。

### line-grow
```json
{
  "title": "增长趋势",
  "x": ["Q1", "Q2", "Q3", "Q4"],
  "series": {
    "营收": [120, 180, 240, 320],
    "利润": [30,  55,  90,  150]
  }
}
```

## 命令示例

```bash
# 条形竞赛，前 8 名，6 秒
python skills/openclaw/infographic/scripts/gif_chart.py bar-race --data data.json --title "平台粉丝榜" --top-n 8 --duration 6 -o outputs/主题名/chart.gif

# KPI 数字滚动（stdin 传数据）
echo '{"items":[{"label":"累计GMV","value":8600000,"prefix":"¥"}]}' | python skills/openclaw/infographic/scripts/gif_chart.py count-up --data -

# 环形进度
python skills/openclaw/infographic/scripts/gif_chart.py progress --data prog.json --style ring
```

## 规则

1. 数据键名严格按上表（`times`/`series`/`items`/`x`/`value`/`max`），键名错误会回退内置示例或报错。
2. GIF 体积：帧数 = fps × duration，社媒发布建议 fps 15-20、duration 3-6 秒，避免过大。
3. 尊重用户输入语言：标题/标签用中文即全中文输出。
4. 需要静态信息图（非动画）走模式 A（`references/antv-templates.md`，AntV CDN 渲染）。
