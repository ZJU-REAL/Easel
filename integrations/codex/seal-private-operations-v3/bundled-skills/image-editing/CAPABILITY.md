---
name: image-editing
description: >-
  通用图像处理加工：改尺寸/缩放、裁剪、补边适配平台尺寸、格式转换（png/jpg/webp）、
  压缩到目标大小、加文字或图片水印、圆角、多图拼接、生成缩略图、读图片信息。
  基于 image_ops.py 确定性处理。
  使用时机：用户说"改尺寸"、"缩放图片"、"裁剪"、"压缩图片"、"加水印"、"转格式"、
  "圆角"、"拼图/多图联排"、"缩略图"、"适配小红书/朋友圈尺寸"、"把图 pad 成 1:1"。
  和 card-*（卡片类）的区别：card-* 是"HTML 设计→渲染出图"，
  image-editing 只加工已有图片，不负责视觉设计。
layer: produce
---

# 图像处理加工

> 对**已有图片**做确定性处理：缩放/裁剪/补边/转格式/压缩/水印/圆角/拼接/缩略图。
> 所有操作走 `skills/shared/scripts/image_ops.py`（纯 Pillow），不即兴写脚本。

## 输入

- 一张或多张已存在的图片文件路径（png/jpg/webp 等 Pillow 支持格式）
- 目标操作与参数（尺寸、比例、质量、水印文字、拼接方式等）

## 输出

- 处理后的图片文件（路径由用户指定或默认写入 `outputs/主题名/`）
- 每条命令回显 `✅ 路径 (宽x高, 大小KB)`；`info` 输出 json

## 边界（与 card-* 划清）

- card-quote / card-xiaohongshu / poster-hero / comparison-card = **设计并渲染新图**（HTML→截图）
- image-editing = **加工已有图片**，不做视觉设计，不生成内容，只做像素级处理
- 需要"从数据/文字生成图" → 用 chart/infographic/card-*；本 SKILL 只处理现成图片文件

## 执行步骤

1. 确认输入图片存在、明确目标操作与参数
2. 从**项目根目录**运行 `image_ops.py` 对应子命令（见下）
3. 需要平台尺寸时，查 `references/platform-sizes.md` 取推荐比例/像素
4. 回报输出路径与尺寸；多步操作可串联（如先 resize 再 compress）

## 命令速查

脚本路径统一为 `skills/shared/scripts/image_ops.py`，均支持 `-h` 查看参数。

```bash
# 缩放：按宽/高/百分比，--keep-ratio 在框内等比不拉伸
python skills/shared/scripts/image_ops.py resize -i in.jpg -o out.jpg --width 1080
python skills/shared/scripts/image_ops.py resize -i in.jpg -o out.jpg --percent 50
python skills/shared/scripts/image_ops.py resize -i in.jpg -o out.jpg --width 1080 --height 1440 --keep-ratio

# 裁剪：坐标裁 或 居中裁到指定尺寸
python skills/shared/scripts/image_ops.py crop -i in.jpg -o out.jpg --box 100,50,900,650
python skills/shared/scripts/image_ops.py crop -i in.jpg -o out.jpg --width 1080 --height 1080

# 补边到目标比例（社媒适配核心）：把任意图 pad 成 1:1 / 9:16 / 16:9
python skills/shared/scripts/image_ops.py pad -i in.jpg -o out.png --ratio 9:16 --background "#ffffff"
python skills/shared/scripts/image_ops.py pad -i in.jpg -o out.png --ratio 1:1 --background "20,20,30"

# 格式转换 png/jpg/webp
python skills/shared/scripts/image_ops.py convert -i in.png -o out.webp --format webp --quality 85

# 压缩：定质量 或 逼近目标文件大小上限（jpg/webp）
python skills/shared/scripts/image_ops.py compress -i in.jpg -o out.jpg --quality 80
python skills/shared/scripts/image_ops.py compress -i in.jpg -o out.jpg --max-kb 200

# 水印：文字（位置/透明度/字号/颜色，自动找系统中文字体）或图片（右下角等）
python skills/shared/scripts/image_ops.py watermark -i in.jpg -o out.png --text "@账号名" --position bottom-right --opacity 0.5 --size 40
python skills/shared/scripts/image_ops.py watermark -i in.jpg -o out.png --image logo.png --position bottom-right --scale 0.3 --opacity 0.8

# 圆角（输出透明 png）；--radius-percent 50 得圆形
python skills/shared/scripts/image_ops.py round -i in.jpg -o out.png --radius 60
python skills/shared/scripts/image_ops.py round -i avatar.jpg -o out.png --radius-percent 50

# 多图拼接：横向/纵向/网格 NxM（列x行），--cell-width/height 统一单元格
python skills/shared/scripts/image_ops.py collage -i a.jpg b.jpg c.jpg -o out.jpg --mode horizontal --gap 12
python skills/shared/scripts/image_ops.py collage -i 1.jpg 2.jpg 3.jpg 4.jpg -o out.jpg --grid 2x2 --gap 10 --cell-width 540 --cell-height 540

# 缩略图（最长边像素）
python skills/shared/scripts/image_ops.py thumbnail -i in.jpg -o thumb.jpg --size 256

# 读图片信息（json：尺寸/格式/比例/大小/透明通道）
python skills/shared/scripts/image_ops.py info -i in.jpg
```

## 领域知识：平台推荐尺寸

常用平台推荐见 `references/platform-sizes.md`。高频速记：

- 小红书竖版图文：**1080×1440**（3:4）；小红书视频/竖版海报：**1080×1920**（9:16）
- 朋友圈单图 / 通用方图：**1:1**（如 1080×1080）
- 横版金句/封面：**16:9**（如 1920×1080）；微信公众号头图 900×383
- 微博配图：**1:1 或 4:3**；抖音/视频号封面：**9:16（1080×1920）**

适配思路：优先 `pad`（补边不裁内容、不变形）保全画面；追求满版无边则 `crop` 居中裁到目标比例；
仅需缩小体积用 `resize`/`compress`。

## Profile 感知

- 有 Profile：水印文字默认用账号名/handle；输出比例默认贴合账号主平台（如小红书号默认 1080×1440）
- 无 Profile：按用户显式参数执行，比例默认保持原图，水印需用户给文字

## 依赖与错误处理

- 依赖：Pillow（已装，`python -c "import PIL"` 可用），纯标准库无其他第三方
- 脚本内建边界检查：文件不存在 / 裁剪框越界 / 非法比例或颜色 → 退出码 2 并打印 `ERROR:`
- 找不到系统中文字体时降级 PIL 默认字体并 `WARN`，可用 `--font` 指定
- 自检：`python skills/shared/scripts/image_ops.py --selftest`
