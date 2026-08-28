---
name: slideshow-video
description: "图片相册 → 视频：把一组图片做成带 Ken Burns 缓慢缩放、图间转场、背景音乐和逐图字幕的视频，自动适配平台画幅（竖版/方形/横版）。当用户说 图片转视频、图片做成视频、相册视频、照片视频、一组图生成视频、图片轮播视频、幻灯片视频、把这几张图做成短视频、图集成片、卡点图片视频 时使用。基于 shared/scripts/slideshow.py 确定性 ffmpeg 封装。与 auto-short-video 区别：auto-short-video 从一句话主题自动生成配图/配音成片，本 SKILL 用用户已有的图片直接拼成视频。"
layer: produce
---

# 图片相册 → 视频

> 把一组图片拼成一条视频：Ken Burns 缓慢缩放 + 图间转场 + 背景音乐 + 逐图字幕，
> 自动适配目标画幅。全部走 `skills/shared/scripts/slideshow.py`，**不要手拼
> zoompan / xfade**——脚本已处理帧数换算、转场偏移、音画时长对齐。

> 只做"已有图片 → 视频"。从主题自动生成配图/配音的完整流水线见 **auto-short-video**；
> 已有视频的剪辑见 **video-editing**；单张封面/海报见 **poster-hero**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 图片 | 是 | 一组图片路径（按顺序），或一个图片目录（按文件名排序） |
| 画幅 | 是 | 用户或上游任务未明确横版/竖版/方形（或具体分辨率）时，制作前必须追问并等确认；不得按平台、Profile 或默认值静默推断，已明确则不重复问 |
| 每图时长 | 否 | 默认每张 3 秒 |
| 转场 | 否 | 默认淡入淡出 `fade`；`none` 为硬切 |
| BGM | 否 | 背景音乐文件（自动循环/裁到片长/尾部淡出） |
| 逐图字幕 | 否 | 每张图配一句字幕 |

## 输出（`outputs/主题名/`）

- 成片视频（`*.mp4`）
- 报告：图片数、总时长、画幅、转场方式、是否带 BGM

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/slideshow.py`（`build -h` 看全部参数）。

### 基本用法
```bash
python skills/shared/scripts/slideshow.py build \
  -i 1.jpg 2.jpg 3.jpg -o outputs/主题名/show.mp4 \
  --size 1080x1920 --per 3 --transition fade
```

### 带 BGM + 逐图字幕
```bash
python skills/shared/scripts/slideshow.py build --images-dir ./photos \
  -o outputs/主题名/show.mp4 \
  --bgm ./music.mp3 --bgm-volume 0.7 \
  --captions "开场一句|第二张说明|第三张说明"
```
字幕也可用 `--captions-file <文件>`（每行对应一张图）。

### 常用变体
- **静止画面（不缩放）**：`--no-kenburns`，配 `--fit pad`（补边）或 `--fit crop`（裁满）。
- **换转场**：`--transition` 可选 `fade/fadeblack/fadewhite/wipeleft/wiperight/slideup/slidedown/circleopen/dissolve/none`。
- **平台画幅**：小红书/抖音竖版 `1080x1920`，朋友圈/ins 方形 `1080x1080`，B站/横版 `1920x1080`。

## Profile 感知

- 有 Profile：`platforms.md` 只用于给出画幅建议，仍须用户确认；字幕语气贴合 `style.md`；
  BGM 风格建议贴合账号调性（欢快/治愈/燃）。
- 无 Profile：先确认横版/竖版/方形；转场默认 fade + Ken Burns。

## 规则

1. 图片顺序 = 视频顺序；用 `--images-dir` 时按文件名排序，必要时先重命名。
2. 转场时长自动限制在每图时长内（不超过 `--per`）。
3. BGM 自动循环补足并裁到成片长度、尾部淡出；无 BGM 时补静音轨方便上传。
4. 逐图字幕数量可少于图片数（多出的图不加字幕），不要求一一对应。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

Ken Burns（缓慢缩放位移）+ 交叉转场 + BGM 是相册/图集视频的标准做法（MoneyPrinterTurbo
等短视频工具同款思路）；本 SKILL 复用 auto-short-video 合成器的 zoompan 方案，把帧数换算与
xfade 偏移计算封装成确定性脚本，避免手写滤镜链出错。
