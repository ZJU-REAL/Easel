---
name: doc-convert
description: "把 Markdown 文稿排版并转换为 HTML、可打印 PDF 或长图 PNG。当用户说“Markdown/MD 转 HTML/PDF/图片、文章导出长图、MD 排版/渲染”时使用。仅处理 Markdown；DOCX/PPT 不在范围内，层级大纲转脑图用 mindmap。"
layer: produce
---

# Markdown 格式转换 / 排版

> 把 Markdown 排版成 HTML / PDF / 长图 PNG。走 `skills/shared/scripts/doc_convert.py`
> （python-markdown 排版 + Chromium 打印/截图）。

> 思维导图见 mindmap；公众号专属排版见 skill-wechat-publisher；卡片/海报见 card-*/poster-hero。

## 输入 / 输出

- 输入：Markdown 文件（支持标题、列表、表格、代码块、引用、图片等）。
- 输出（`outputs/主题名/`）：按后缀 `.html` / `.pdf` / `.png`（长图）。

## 执行

脚本路径（相对项目根）：`skills/shared/scripts/doc_convert.py`（`convert -h`）。

```bash
# 转干净 HTML（可读排版 + CJK 字体）
python skills/shared/scripts/doc_convert.py convert -i article.md -o outputs/主题名/a.html

# 转 PDF（A4 可打印，适合存档/发送）
python skills/shared/scripts/doc_convert.py convert -i article.md -o outputs/主题名/a.pdf

# 转长图 PNG（适合发不支持 MD 的平台/朋友圈存档）
python skills/shared/scripts/doc_convert.py convert -i article.md -o outputs/主题名/a.png --width 800
```

## 前置

- MD→HTML：需 `pip install markdown`。
- MD→PDF/PNG：需 playwright + chromium（`playwright install chromium`）。

## 规则

1. 长图宽度 `--width` 按平台调（朋友圈/小红书 ~750-1080）；正文宽度 `--page-width` 控制 HTML/PDF 版心。
2. 图片用相对/绝对可访问路径，渲染时要能加载到。
3. 需要 DOCX/PPT/富交互排版时本 SKILL 不覆盖（提示用 pandoc 或对应平台工具）。
4. 产物统一进 `outputs/主题名/`。

## 参考来源

python-markdown（含 extra/tables/fenced_code/toc 扩展）做 MD→HTML，Chromium 无头
`page.pdf()`/`screenshot(full_page)` 出 PDF/长图，替代 pandoc 完成最常用的 MD 排版分发需求。
