---
name: remove-bg
description: "图片去背景 / 抠图 / 换背景：用 AI 语义分割把主体从背景抠出，输出透明 PNG，或直接换成纯色（电商白底）/ 新场景背景。无需绿幕。当用户说 去背景、抠图、抠图换背景、去掉背景、透明背景、白底图、换背景、抠人像、抠产品、扣图、KO图、商品白底 时使用。基于 shared/scripts/remove_bg.py（rembg u2net）。与 green-screen 区别：green-screen 处理绿幕视频，本 SKILL 处理任意图片；与 ecom-details-image 区别：那个出电商视觉方案，本 SKILL 只做抠图。"
layer: produce
---

# 图片去背景 / 抠图换背景

> 用 rembg（AI 语义分割）把主体抠出，输出透明 PNG 或换新背景。无需绿幕。全部走
> `skills/shared/scripts/remove_bg.py`。

> 绿幕**视频**抠像见 **green-screen**；电商视觉方案见 **ecom-details-image**；
> 常规缩放/裁切/水印见 **image-editing**。

## 前置

首次运行自动下载模型（~4-170MB，视模型而定），需外网代理（脚本读 `EASEL_PROXY`/`http(s)_proxy`，未设则直连）。先自检：
```bash
python skills/shared/scripts/remove_bg.py check
```

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 图片 | 是 | 要抠图的图片（没给就问） |
| 输出背景 | 否 | 透明（默认）/ 纯色 / 换图片背景 |
| 模型 | 否 | 通用 / 人像 / 精细，见下表 |

## 输出（`outputs/主题名/`）

- 抠好的图片（透明用 `.png`）
- 报告：所用模型、背景形态

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/remove_bg.py`（`remove -h` 看参数）。

```bash
# 透明背景（务必输出 .png）
python skills/shared/scripts/remove_bg.py remove -i product.jpg \
  -o outputs/主题名/cutout.png

# 电商白底主图
python skills/shared/scripts/remove_bg.py remove -i product.jpg \
  -o outputs/主题名/white.jpg --bg-color white

# 换新场景背景
python skills/shared/scripts/remove_bg.py remove -i person.jpg \
  -o outputs/主题名/scene.png --bg-image scene.jpg

# 人像 + 毛发边缘细腻
python skills/shared/scripts/remove_bg.py remove -i portrait.jpg \
  -o outputs/主题名/cut.png --model u2net_human_seg --alpha-matting
```

## 模型选择

| 模型 | 适用 |
|------|------|
| `u2net`（默认） | 通用主体 |
| `u2netp` | 轻量快速（质量略低） |
| `u2net_human_seg` | 人像专用 |
| `isnet-general-use` | 更精细的通用分割 |
| `silueta` | 体积小的通用模型 |

抠不干净/边缘毛糙时：换更精细的模型，或加 `--alpha-matting`（慢但边缘更好，适合头发/毛绒）。

## 规则

1. 要透明背景**必须输出 .png**（jpg 不支持透明，脚本会自动改白底并提示）。
2. 电商主图用 `--bg-color white`；换场景用 `--bg-image`（自动等比覆盖裁切）。
3. 人像优先 `u2net_human_seg`，商品/通用用 `u2net`。
4. 抠图质量取决于主体与背景对比度；复杂/低对比图无法保证完美。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

去背景用 rembg（u2net 系列显著性目标检测/分割模型）+ onnxruntime CPU 推理，是无 GPU 抠图的
主流方案。换背景合成用 Pillow alpha_composite。把模型加载、代理注入、背景合成封装成确定性脚本。
