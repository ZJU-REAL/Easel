---
name: card-quote
description: "生成适合微博、知乎、公众号或 X/Twitter 分享的 16:9 横版金句卡和数据卡。当用户说“做金句卡、语录卡、数据卡、横版分享卡”时使用。小红书竖版知识卡用 card-xiaohongshu，竖版营销海报用 poster-hero。"
layer: produce
---

# 金句卡片

> HTML 单图渲染 → 截图分享。16:9 横版，一句 hero 金句 / 一组核心数据。

> ⚠️ **生成前先读 [card-design](../card-design/SKILL.md) 设计系统**（选立场/锁配色/字越大越细/禁 AI 廉价感）。金句卡尤其靠排版层级——避免渐变文字、粗黑大标题、居中一切。

## 骨架（二选一，按内容是"观点"还是"数字"）

先按 card-design 选风格锁配色，再套下面对应骨架。

### A. 金句卡（一句 hero 观点）

- 容器 `w-[1600px] h-[900px]`，暗色 / 亮色按内容情绪二选一。
- 中央一句 hero 金句（**字越大越细**，限 2-3 行，最戳的词用 1 个强调色）。
- 下方署名 / 出处（无个人 handle 时用来源或品牌名，不硬塞头像占位）。
- 左上角小标签（`Insight` / `观点` / `Quote`）；右下角品牌水印。
- 微妙纹理（grid / dot / 极淡 noise），禁玻璃拟态与渐变文字。

### B. 数据卡（一组核心数字）

- 同画幅，1 个主数字**超大字**（占视觉中心）+ 单位/说明小字在旁。
- 2-4 个副指标横向排开，每个「大数字 + 一行标签」，对齐到网格。
- 可加一句结论/来源脚注（`数据来源 · 截至 X`）建立可信度。
- 数字用等宽或 Inter Tight，避免用 emoji 当图标。

## 国内平台适配

- **微博**：横版直接配文；金句要短、能被单独转发；水印放品牌名。
- **知乎**：偏理性，数据卡 + 一句结论最合适；出处/来源要显。
- **公众号**：可作文中配图或封面延展；配色跟公众号主色。
- **X/Twitter（出海）**：可保留 handle 署名；其余同金句卡。

## 渲染出图（必做，勿手动截图）

生成 HTML 后，用共享渲染脚本自动出图（playwright + chromium，已配置走代理加载 CDN/字体）：

```bash
python skills/shared/scripts/render_card.py \
  --html outputs/主题名/assets/card.html \
  --out outputs/主题名/card.png \
  --full-page --width 1600 --height 900
```

- 16:9 横版用 `--width 1600 --height 900`。
- 脚本对外部 CDN/字体做有界超时（默认 20s 超时也继续），不会卡死；用环境代理加载 Tailwind/Google Fonts。
- 首次使用需 `pip install playwright && playwright install chromium`（见项目依赖说明）。

## 与其他卡片 SKILL 的区别

三者都是"HTML 单图 → 截图"，仅画幅与场景不同，互不替代：

- **card-quote（本 SKILL）** = 16:9 横版金句/数据卡，一句 hero 观点或一组核心数字，配微博 / 知乎 / X / 公众号。
- **card-xiaohongshu** = 1080×1440 竖版小红书知识卡（走 card-design 风格库），可多张联排滑动浏览。承载多观点、成套干货时用它。
- **poster-hero** = 1080×1920 竖版营销海报 / 朋友圈分享图，大标题 + 卖点 + 二维码，用于产品发布、活动宣传。
