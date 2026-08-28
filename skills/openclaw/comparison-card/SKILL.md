---
name: comparison-card
description: >-
  对比图/一图流：生成 A vs B 参数对比图、优劣势对比表、产品参数一图流。
  用 HTML+CSS 渲染成可截图的视觉卡片，适合小红书/微博等平台分享。
  使用时机：用户说"做个对比图"、"A vs B"、"参数对比"、"优劣对比"、
  "一图流"、"对比表"、"哪个好"、"对比一下"。
  和 chart-visualization 的区别：chart 做数据图表（柱状图/折线图），comparison-card 做对比表/一图流。
  和 infographic 的区别：infographic 做多维信息图，comparison-card 专注 A vs B 对比。
layer: produce
---

# 对比图 / 一图流

> 生成 A vs B 可视化对比卡片，一张截图说清楚差异，适合社媒分享。

> ⚠️ **生成前先读 [card-design](../card-design/SKILL.md) 设计系统**（锁配色/字体层级/填满画幅/去 AI 廉价感）。对比图用「对比表」骨架（左右双栏、≥5 对比行、行高一致），避免渐变、emoji、底部死空白。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| `items` | 是 | 要对比的 2-4 个对象（名称） |
| `dimensions` | 否 | 对比维度列表（如价格、性能、功能等）；不指定则自动提取 |
| `data` | 否 | 结构化对比数据（JSON/表格）；不提供则由 SKILL 调研填充 |
| `layout` | 否 | 布局模式：`table`（默认）/ `versus` / `pros_cons` |
| `size` | 否 | 尺寸预设：`xiaohongshu`(1080x1440) / `weibo`(1080x1080) / `wechat`(1080x1920) / `auto` |
| `style` | 否 | 视觉风格：走 **card-design 风格库**（瑞士极简/杂志编辑/高奢黑金…），不指定则按内容品类/Profile 选一个立场 |
| `winner` | 否 | 是否标注胜出项：`true` / `false`（默认 `false`） |

### 布局模式说明

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| `table` | 经典参数对比表，行=维度，列=对象 | 多维度、多参数的产品对比 |
| `versus` | 左右对称 VS 布局，中间分割线 | 两个对象的直观对比 |
| `pros_cons` | 优劣势分栏，绿色优势/红色劣势 | 单一产品的优劣分析 |

## 输出

- 完整的 HTML 文件，可在浏览器打开并截图
- 卡片尺寸固定（px），截图即所见
- 写入 `outputs/` 目录

## 执行步骤

### Step 1 — 解析对比需求

1. 确认对比对象（2-4 个）
2. 确认对比维度：
   - 用户指定了 → 直接用
   - 用户没指定 → 根据对象类型自动推断常见对比维度（如手机：价格/屏幕/芯片/电池/摄像头）
3. 确认布局模式和尺寸

### Step 2 — 数据收集与整理

如果用户提供了完整数据：
- 直接结构化为对比矩阵

如果用户只给了对象名，没给数据：
- 用 WebSearch 查询各对象的关键参数
- 交叉验证数据准确性（至少 2 个来源）
- 标注数据来源

将数据整理为标准矩阵：
```json
{
  "items": ["A", "B"],
  "dimensions": [
    {"name": "价格", "values": ["¥2999", "¥3499"], "winner": "A"},
    {"name": "性能", "values": ["骁龙 8 Gen3", "A17 Pro"], "winner": "B"}
  ]
}
```

### Step 3 — 生成 HTML 卡片

1. 读取 `references/comparison-template.html` 作为基础模板
2. 根据 `layout` 模式选择布局结构
3. 填充数据到模板
4. **应用 card-design 选定风格的配色/字体**（锁 spec，全表一致；不自造配色）
5. 设置卡片尺寸（`size` 参数）
6. 如果 `winner` 为 true，用视觉标记（高亮/皇冠图标）标注胜出项

### Step 4 — 视觉优化

- 确保文字不溢出单元格
- 数值类数据右对齐，文本类左对齐
- 胜出项用 card-design 选定风格的**强调色**高亮，劣势项用中性灰（不写死某个绿）
- 底部加数据来源说明和日期
- 遵守 card-design 铁律：禁蓝紫科技渐变、禁 emoji 当图标、填满不留死空白

### Step 5 — 写入文件

将 HTML 写入 `outputs/` 目录，文件名格式：`{A}_vs_{B}_对比_{日期}.html`

### Step 6 — 渲染出图（勿手动截图）

用共享脚本自动渲染成图：

```bash
python skills/shared/scripts/render_card.py \
  --html outputs/主题名/assets/A_vs_B_对比.html \
  --out outputs/主题名/A_vs_B_对比.png \
  --full-page --width 1080 --height 1440
```

尺寸按 Profile 匹配的平台预设调整（默认小红书 1080×1440）。脚本用 playwright+chromium，对 CDN/字体有界超时不卡死；首次需 `pip install playwright && playwright install chromium`。

## Profile 感知

- **有 Profile**：从 `style.md` 读取品牌配色，替换模板默认色；从 `identity.md` 读取账号名作为水印；从 `platforms.md` 读取主力平台，自动匹配尺寸
- **无 Profile**：使用默认清新风格配色，无水印，默认小红书尺寸（1080x1440）

> 自研溯源与参考项目见同目录 `EASEL-META.md`。
