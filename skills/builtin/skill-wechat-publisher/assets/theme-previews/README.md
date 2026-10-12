# 主题预览

同一篇示例文章([`sample.md`](sample.md))用 **15 套主题**渲染成静态 HTML。打开 [`index.html`](index.html),即可在手机宽度 frame 里并排对比、按分类筛选、一键复制 `--theme` 命令。

## 15 套主题

`academic-paper` · `business-navy` · `elegant-ink` · `girly-pink` · `ink-wash` · `magazine-grid` · `minimal-bw` · `minimal-mono` · `mint-fresh` · `news-bold` · `refined-blue` · `sage-premium` · `sunset-coral` · `warm-editorial` · `warm-orange`

主题定义在 [`../themes/*.json`](../themes/),与同名 `<theme>.html` 一一对应。默认主题:`refined-blue`(main 账号)、`minimal-mono`(tech 账号)。

## 文件

| 文件 | 说明 |
|---|---|
| `index.html` | 15 套主题并排总览(手机 frame + 分类筛选 + CLI 提示) |
| `<theme>.html` × 15 | 每套主题的单页渲染,被 `index.html` 以 `<iframe>` 引用 |
| `sample.md` | 示例文章源(h1~h3 / 列表 / 引用 / 代码块 / 表格 / 7 种行内高亮 / 分节符) |
| `screenshots/*.webp` | 主仓库 README 用的静态截图(总览 + 4 套代表主题) |

## 改了主题后重新生成

```bash
cd wechat-publisher
for theme in academic-paper business-navy elegant-ink girly-pink ink-wash \
             magazine-grid minimal-bw minimal-mono mint-fresh news-bold \
             refined-blue sage-premium sunset-coral warm-editorial warm-orange; do
  python3 scripts/html_converter.py assets/theme-previews/sample.md \
    --theme "$theme" -o "assets/theme-previews/${theme}.html"
done
bash scripts/sync_pages.sh   # 同步到 docs/(GitHub Pages 发布目录)
```

文件名需与 `--theme` 值一致;截图有变化时重截 `screenshots/*.webp`。
