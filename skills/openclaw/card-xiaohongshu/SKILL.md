---
name: card-xiaohongshu
description: "把已有卡片文案渲染为 1080×1440 小红书竖版知识卡片组，并按 card-design 选择视觉风格。当用户说“渲染/制作小红书卡片、知识卡、滑动卡片组”时使用。整套笔记策划与文案用 xhs-note-creator；横版金句卡用 card-quote。"
layer: produce
---

# 小红书图文卡片

你是一名小红书视觉内容设计师。根据用户提供的内容，生成一组小红书风格的 HTML 知识卡片。

## ⚠️ 生成前必读设计系统（否则大概率做出廉价 AI 卡）

**写第一行 HTML 之前，先读 [card-design](../card-design/SKILL.md) 设计系统**，按它的五步来：
①**先让用户选风格**(card-design 有 9 种命名风格:瑞士极简/杂志编辑/新中式墨韵/奶油温柔/多巴胺Y2K/高奢黑金/手账贴纸/极客终端/植物清新——用户没选就列 3-4 个候选让 ta 挑或按内容推荐) ②锁定该风格 spec(字体/配色hex,禁自定义) ③字体层级(字越大越细) ④套骨架 ⑤渲染后跑 `card_audit.py` 硬门禁。

不读设计系统、凭"感觉"写，就会做出：深蓝科技渐变 + emoji 当图标 + 大片死空白的 PPT 味卡片（反面教材）。**卡片美不美第一取决于选对风格**，别所有内容都套同一种。

## 输出规范

- 输出 N 张连续卡片，每张 `width: 1080px; height: 1440px`，用 flex 纵向排列方便整体截图也方便单张截图
- N 由用户内容信息量决定：短内容 3-6 张起步，长内容更多（小红书平台单帖最多 18 图，通常 9 张以内最佳）
- 一张卡只承载一个核心观点

## 卡片结构

按 `card-design/references/card-recipes.md` 的骨架选型（封面/账本/管线/对比/矩阵/数据/金句/收尾）。典型一套：
1. **封面卡** — Display 大标题(细字重) + 一句钩子副标 + 顶 kicker + 底信息行（填到底，别中段空）
2. **正文卡** — 每张一个核心观点，用**账本行/管线/矩阵**等有信息量的骨架填满，不是一句话配大空白
3. **收尾卡** — 要点回顾(小账本) + 行动号召 + 水印

## 视觉风格（硬性，细节见 card-design）

- **配色**：从 `card-design/references/palettes.md` 选一套锁定的方案，**整套卡片全程用它**——知识/生活走杂志暖纸系(Ink/Kraft/Dune)，科技/工具走瑞士系(克莱因蓝)。**正文不用纯黑**。
- **禁**：深蓝/蓝紫科技渐变、渐变文字、玻璃拟态、emoji 当图标、居中一切、大标题用粗黑体、`flex:1` 顶出的底部死空白。（详见 `anti-ai-slop.md`）
- **填满**：内容覆盖 ≥75% 画高，任何无理由空白带 >15% 判失败。内容少就扩内容/换省高骨架/换 1:1，别留死空白。（详见 `layout-laws.md`）
- 图标用线性图标(Lucide 风格,stroke 1.5)或纯排版，不用 emoji。字号大、对比强、行距宽（手机可读，正文 ≥28px）。
- 每张卡片角落小水印（作者名 / 日期）。

## Profile 感知

- **有 Profile**：从 `style.md` 读品牌配色和风格偏好（但仍遵守 card-design 的高级感底线，别退回"柔和渐变"这类模糊描述），从 `identity.md` 读账号名用作水印
- **无 Profile**：按 card-design 默认——知识/科技类默认瑞士+克莱因蓝或杂志+Indigo Porcelain，生活/情感类默认杂志暖纸系，水印留空

## 与其他卡片 SKILL 的区别

三者都是"HTML 单图 → 截图"，仅画幅与场景不同，互不替代：

- **card-xiaohongshu（本 SKILL）** = 1080×1440 竖版小红书知识卡，可多张联排滑动浏览，一套干货拆成 3-9 张。**小红书的封面/首图**也用本 SKILL 的封面卡（一套卡的第 1 张）。
- **card-quote** = 16:9 横版金句/数据卡，单张 hero 观点或核心数字，配微博 / 知乎 / X / 公众号。
- **poster-hero** = 1080×1920 竖版**独立营销海报** / 朋友圈分享图，大标题 + 卖点 + 二维码，用于产品发布、活动宣传（不是笔记首图——笔记首图用本 SKILL 的封面卡）。

（三者生成前都应先读 card-design 设计系统。）

## 输出

生成完整的 HTML 文件，写入 `outputs/` 目录，再用共享脚本自动渲染成图（勿手动截图）：

```bash
# 多张卡片：每张 .card 元素单独出图，得 card_1.png card_2.png ...
python skills/shared/scripts/render_card.py \
  --html outputs/主题名/assets/cards.html \
  --out-dir outputs/主题名 --all ".card" --prefix card \
  --width 1080 --height 1440

# ⭐ 渲染后必做：死空白/密度硬门禁，全 PASS 才交付
python skills/openclaw/card-design/scripts/card_audit.py audit -f "outputs/主题名/card_*.png"
```

- 竖版 1080×1440；HTML 里每张卡片外层用统一 class（如 `.card`）便于 `--all` 批量导出。
- 脚本用 playwright+chromium，对 CDN/字体有界超时不卡死；首次需 `pip install playwright && playwright install chromium`。
- **card_audit 有 FAIL 的卡** → 按 `card-design/references/layout-laws.md` 的「欠填修正阶梯」补内容或换骨架，重渲到全 PASS。
