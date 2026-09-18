---
name: green-screen
description: "绿幕抠像 / 换背景 / 合成：把绿幕（或蓝幕/指定色）拍摄的前景人物抠出来，合成到新背景——图片、视频、纯色或前景自身模糊。当用户说 绿幕、抠像、抠图换背景、去绿幕、chromakey、绿幕合成、换背景、蓝幕、把绿幕背景换掉、人物抠出来、绿布 时使用。基于 shared/scripts/chromakey.py（ffmpeg chromakey + despill）。与 video-reframe 区别：reframe 只改画幅不换背景；与 ai-image-gen 区别：那个生成新图，本 SKILL 处理已拍的绿幕素材。"
layer: produce
---

# 绿幕抠像 / 换背景合成

> 把绿幕前景抠出来合成到新背景。全部走 `skills/shared/scripts/chromakey.py`，
> **不要手拼 chromakey/overlay 滤镜**——脚本已处理抠像、溢色抑制(despill)、边缘融合、
> 背景缩放、音轨保留。

> 只改画幅见 **video-reframe**；从零 AI 生成画面见 **ai-video-gen**；通用剪辑见 **video-editing**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 前景视频 | 是 | 绿幕/蓝幕拍摄的素材（没给就问） |
| 背景 | 是 | 四选一：图片 / 视频 / 纯色 / 前景自身模糊 |
| 幕布色 | 否 | 默认绿 `0x00ff00`；蓝幕用 `0x0000ff` |

## 输出（`outputs/主题名/`）

- 合成后视频（`*-composited.mp4`）
- 报告：分辨率、抠掉的颜色、所用背景

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/chromakey.py`（`key -h` 看参数）。

```bash
# 合成到图片背景
python skills/shared/scripts/chromakey.py key -i <绿幕视频> \
  --bg <背景图> -o outputs/主题名/<名>-composited.mp4

# 合成到视频背景（背景自动循环补足）
python skills/shared/scripts/chromakey.py key -i <绿幕视频> \
  --bg <背景视频> -o outputs/主题名/<名>.mp4

# 合成到纯色背景
python skills/shared/scripts/chromakey.py key -i <绿幕视频> \
  --bg-color white -o outputs/主题名/<名>.mp4

# 背景=前景自身放大模糊（虚化景深感）
python skills/shared/scripts/chromakey.py key -i <绿幕视频> \
  --bg-blur -o outputs/主题名/<名>.mp4
```

## 调参（抠不干净时）

- **绿边残留 / 抠不净**：调大 `--similarity`（默认 0.30，可到 0.4）。
- **主体边缘被吃 / 镂空**：调小 `--similarity`，或加大 `--blend`（默认 0.10）柔化边缘。
- **主体泛绿（溢色）**：脚本已自动 `despill`；仍明显时说明幕布打光不匀，属素材问题。
- **蓝幕**：`--color 0x0000ff`。

## 规则

1. 幕布色默认绿；蓝幕/其它色用 `--color` 指定。
2. 背景四选一（`--bg` / `--bg-color` / `--bg-blur`），互斥。
3. 背景自动缩放裁切到前景画幅、视频背景自动循环补足到前景时长。
4. 前景音轨自动保留。
5. 抠像质量取决于素材（幕布纯净度、打光均匀度）；脚本尽力，但拍摄差无法救回。
6. 产物统一进 `outputs/主题名/`。

## 参考来源

绿幕抠像用 ffmpeg `chromakey`（按颜色距离生成 alpha）+ `despill`（抑制主体边缘溢色）+
`overlay` 合成，是标准无 GPU 抠像方案。把颜色阈值、边缘融合、背景适配封装成确定性脚本。
