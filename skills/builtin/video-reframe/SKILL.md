---
name: video-reframe
description: "智能转换视频画幅，支持 9:16/16:9/1:1、模糊背景填充、焦点裁切和人脸居中裁切。当用户说“横竖版互转、改成 9:16、转竖屏、去黑边、适配平台尺寸、人脸居中裁”时使用。通用简单裁切用 video-editing；逐段动态人脸跟随切片用 clipify。"
layer: produce
---

# 视频画幅智能转换（竖横互转）

> 把视频转到目标宽高比，三种策略可选。全部走 `skills/shared/scripts/reframe.py`，
> **不要手拼 crop/overlay 滤镜**——脚本已算好裁切尺寸、焦点边界、偶数对齐、音轨保留。

| 模式 | 效果 | 适用 |
|------|------|------|
| `blur`（默认） | 原画完整居中 + 放大模糊的自身作背景，**无黑边** | 横转竖最常用，画面不丢内容 |
| `crop` | 按焦点位置裁到目标比例，**无黑边但裁边缘** | 主体明确、想铺满屏幕 |
| `smart` | cv2 检测人脸 → 以人脸中位位置为焦点裁切 | 口播/人物视频横转竖 |

> 需要逐镜头动态追踪人脸做 pan 见 **clipify**；只想加黑边/居中裁见 **video-editing** `aspect`。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 视频文件 | 是 | 要转换的视频（没给就问） |
| 目标比例 | 是 | `9:16` / `16:9` / `1:1` / `4:5` / `3:4` / `4:3` / `21:9` |
| 模式 | 否 | `blur`（默认）/ `crop` / `smart` |
| 焦点 | 否 | crop 模式下主体不在中间时用 `--focus-x`（0 左 1 右） |

## 输出（`outputs/主题名/`）

- 转换后视频（`*-<比例>.mp4`）
- 报告：源→目标尺寸、比例、所用策略、人脸焦点（smart 时）

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/reframe.py`（`reframe -h` 看参数）。

```bash
# 横版转竖版，模糊背景填充（最稳，画面不丢）
python skills/shared/scripts/reframe.py reframe -i <视频> \
  -o outputs/主题名/<名>-9x16.mp4 --ratio 9:16 --mode blur

# 焦点裁切，主体偏右时把焦点拉到 0.65
python skills/shared/scripts/reframe.py reframe -i <视频> \
  -o outputs/主题名/<名>-9x16.mp4 --ratio 9:16 --mode crop --focus-x 0.65

# 人脸感知裁切（口播/人物视频）
python skills/shared/scripts/reframe.py reframe -i <视频> \
  -o outputs/主题名/<名>-9x16.mp4 --ratio 9:16 --mode smart
```
`--size WxH` 可强制最终分辨率（默认按比例与源分辨率推算，如 1280x720 → 720x1280）。

## Profile 感知

- 有 Profile：默认目标比例按 `platforms.md` 主平台（抖音/小红书竖版 9:16，B站横版 16:9，
  朋友圈/ins 方形 1:1）；口播/人物类账号默认 `smart` 模式。
- 无 Profile：默认 `blur` 模式 + 询问目标平台/比例。

## 规则

1. 拿不准选哪种：横转竖优先 `blur`（不丢画面）；主体明确且想铺满用 `crop`；人物口播用 `smart`。
2. `smart` 未检出人脸时自动退化为居中裁切，并在报告里说明。
3. 音轨自动保留（copy），不重编码音频。
4. 输出分辨率强制偶数对齐（H.264 要求），无需手动处理。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

模糊背景填充（blurred bars）是竖屏适配的主流做法；人脸感知裁切参考 AI-Youtube-Shorts-Generator
思路，用 OpenCV Haar 级联检测人脸中位位置定焦点。把裁切几何与边界钳制封装成确定性脚本。
