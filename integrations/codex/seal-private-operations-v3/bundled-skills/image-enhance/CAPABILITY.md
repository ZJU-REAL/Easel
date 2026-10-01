---
name: image-enhance
description: "图片增强 / 放大 / 变清晰：高质量放大（Lanczos 2x/4x）+ 去噪 + 锐化 + 自动对比度/饱和度，改善偏糊、偏暗、噪点多的图片。当用户说 图片放大、图片变清晰、提高清晰度、图片增强、去噪点、锐化、图片太糊了、放大到高清、提升画质、优化图片、图片调亮调色 时使用。基于 shared/scripts/img_enhance.py（Pillow+OpenCV）。注意：这是传统增强非 AI 超分，凭空生成细节请用 ai-image-gen 图生图。与 image-editing 区别：那个做缩放/裁切/水印等常规操作，本 SKILL 专做画质提升。"
layer: produce
---

# 图片增强 / 放大

> 高质量放大 + 去噪 + 锐化 + 调色，改善偏糊/偏暗/有噪点的图片。走
> `skills/shared/scripts/img_enhance.py`。

> ⚠️ **传统确定性增强，不是 AI 超分**——能改善轻中度模糊/噪点，但无法凭空造细节。
> 要 AI 超分/重绘用 **ai-image-gen**（图生图）。常规缩放/裁切/压缩/水印见 **image-editing**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 图片 | 是 | 要增强的图片（没给就问） |
| 放大倍数 | 否 | 默认 2 倍；1 表示只增强不放大 |
| 增强项 | 否 | 一键 `--auto`，或分别指定去噪/锐化/对比/饱和 |

## 输出（`outputs/主题名/`）

- 增强后的图片
- 报告：原尺寸→新尺寸、执行了哪些增强

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/img_enhance.py`（`enhance -h` 看参数）。

```bash
# 一键增强 + 2 倍放大（最常用）
python skills/shared/scripts/img_enhance.py enhance -i blurry.jpg \
  -o outputs/主题名/out.jpg --scale 2 --auto

# 噪点多的照片：去噪 + 4 倍 + 强锐化
python skills/shared/scripts/img_enhance.py enhance -i photo.jpg \
  -o outputs/主题名/out.png --scale 4 --denoise --sharpen 1.5

# 只调色不放大（偏暗/发灰的图）
python skills/shared/scripts/img_enhance.py enhance -i img.jpg \
  -o outputs/主题名/out.jpg --scale 1 --auto
```

## 调参

- **还是糊**：本工具无法造细节，改用 ai-image-gen 图生图超分。
- **锐化过头有噪点/白边**：降低 `--sharpen`（默认 auto=1.0）。
- **颜色过饱和**：`--saturation 1.0` 关闭增色，或调低。
- **噪点被放大**：加 `--denoise`（放大前先去噪）。

## 规则

1. 先设定预期：这是"改善"不是"重绘"，糊得厉害的图别承诺变高清。
2. 有噪点务必 `--denoise`（放大前执行，避免噪点被放大）。
3. 放大统一用 Lanczos 高质量重采样；倍数别盲目开 4x（文件暴涨且无新细节）。
4. 产物统一进 `outputs/主题名/`。

## 参考来源

Lanczos 重采样 + UnsharpMask 锐化 + OpenCV fastNlMeans 去噪 + 自动对比度，是无 GPU 的传统
画质提升组合。真正的超分辨率（Real-ESRGAN 等）需 GPU/模型，此处以 ai-image-gen 图生图替代。
