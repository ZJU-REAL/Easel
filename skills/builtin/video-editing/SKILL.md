---
name: video-editing
description: >-
  用自然语言指令剪辑视频：裁剪、拼接、变速、跳切去静音、文字覆盖、横竖比转换、抽帧封面、转 GIF、压缩、加 BGM/水印，基于 ffmpeg。
  当用户说"剪视频""裁剪视频""拼接视频""视频变速""去静音""视频加文字""视频转GIF""压缩视频""加BGM/水印"时使用。
  本 SKILL 做单条视频的通用剪辑；智能画幅转换用 video-reframe，长视频切片用 clipify/video-highlights，从 0 生成用 ai-video-gen。
layer: produce
---

# 视频剪辑

用自然语言指令做通用视频处理。所有操作都调用共享脚本
`skills/shared/scripts/video_ops.py`（subprocess 封装 ffmpeg/ffprobe），
**不要现场手拼 ffmpeg 命令**——脚本已处理音画同步、字体路径、编码默认值、
错误捕获等易错点。

> 从项目根目录运行。脚本相对路径：`skills/shared/scripts/video_ops.py`。
> 每个子命令都支持 `-h` 查看参数。

## 输入

- 视频文件路径 + 操作描述（用户没给路径就问）
- 可选：目标平台/比例/时间段等参数

## 输出

处理后的视频/图片，存到 `outputs/主题名/`。脚本会打印 `✅ <路径> (大小)`。

## 与 clipify 的边界

- **clipify** = 长视频智能切片 + 人脸追踪 pan + 逐字字幕烧录的**特化流程**。
  需要"从长视频找精彩片段做成竖版短视频带字幕"时用它。
- **video-editing（本 SKILL）** = 通用剪辑处理。单点操作或自由组合时用它。
  不做人脸追踪、不做字幕烧录（那是 clipify）。

## 子命令速查

先 `python skills/shared/scripts/video_ops.py info -i <视频>` 看清源信息，再操作。

| 子命令 | 用途 | 关键参数 |
|--------|------|----------|
| `cut` | 按起止时间裁剪 | `--start --end`/`--duration`，`--reencode` 精确裁 |
| `concat` | 多段拼接 | `--mode demuxer`(同参数无损)/`filter`(异参数统一) |
| `speed` | 变速（音画同步） | `--factor 2.0` |
| `silence-cut` | 检测静音并去除（跳切） | `--noise -30 --min-silence 0.5 --pad 0.05`（别名 `mute-cut`） |
| `text` | 文字覆盖 | `--text --position --fontsize --color --start --end --box` |
| `aspect` | 横竖比转换 | `--ratio 9:16 --mode pad`(补边)/`crop`(裁切) |
| `frame` | 抽帧做封面 | `--time 00:00:03 --width` |
| `gif` | 转 GIF | `--start --end --fps 12 --width 480` |
| `compress` | 压缩 | `--crf 26` 或 `--bitrate 2M`，`--scale` 降分辨率 |
| `bgm` | 加背景音乐混音 | `--music --voice-volume 1.0 --music-volume 0.3` |
| `watermark` | 加图片水印 | `--logo --position --width --opacity` |
| `info` | 时长/分辨率/帧率/码率(json) | `-i` |

`text` / `watermark` 位置七选一：`center top bottom top-left top-right
bottom-left bottom-right`。中文字体自动探测（wqy-microhei / Noto CJK），
也可 `--font` 显式指定。

## 常用示例

```bash
V=skills/shared/scripts/video_ops.py

# 裁剪 00:02:00–00:15:00
python $V cut -i in.mp4 -o out.mp4 --start 00:02:00 --end 00:15:00

# 横版转竖版（社媒竖版转制刚需）：补边不裁 or 裁切填满
python $V aspect -i in.mp4 -o vertical.mp4 --ratio 9:16 --mode pad
python $V aspect -i in.mp4 -o vertical.mp4 --ratio 9:16 --mode crop

# 去静音 + 1.25 倍速（先跳切再变速）
python $V silence-cut -i in.mp4 -o t.mp4
python $V speed -i t.mp4 -o out.mp4 --factor 1.25

# 第 3 秒抽帧做封面
python $V frame -i in.mp4 -o cover.jpg --time 00:00:03 --width 1080

# 2–6 秒转 GIF
python $V gif -i in.mp4 -o clip.gif --start 2 --end 6 --fps 12 --width 480

# 60 秒处叠 5 秒"关注我"字幕（底部带框）
python $V text -i in.mp4 -o out.mp4 --text "关注我" --position bottom --box --start 60 --end 65

# 加 BGM（原声 1.0 / BGM 0.3）、加右下角水印、压缩
python $V bgm -i in.mp4 -o out.mp4 --music bgm.mp3 --music-volume 0.3
python $V watermark -i in.mp4 -o out.mp4 --logo logo.png --position bottom-right --width 120
python $V compress -i in.mp4 -o small.mp4 --crf 26 --scale 720
```

## 组合操作

链式：每步产物作下一步输入。典型顺序 `cut → silence-cut → speed → text →
aspect → compress`。竖版转制放最后（在最终画布上叠字幕更可控）。

## 平台规范（简表）

| 平台 | 比例 | 时长 | 备注 |
|------|------|------|------|
| 抖音/视频号/Reels | 9:16 | ≤60s 黄金，前 3s 定成败 | 1080×1920 |
| 小红书视频 | 9:16 / 3:4 | ≤60s | 竖版优先 |
| B站/YouTube 横版 | 16:9 | 数分钟起 | 1920×1080 |
| Instagram Feed | 4:5 / 1:1 | 短 | 4:5 占屏更大 |

更详细规范按需查 `references/`（如有）。

## 环境要求

- **ffmpeg + ffprobe** — ✅ 已安装（脚本启动即检查，缺则报错退出）
- **字幕烧录/逐字字幕** — 走 clipify（需 whisper）；本 SKILL 只做 `text` 覆盖

## Agent 指令

1. **先 `info`** 看源比例/时长/有无音轨，再决定操作
2. **每个操作调对应子命令**，别手写 ffmpeg；不确定参数用 `<子命令> -h`
3. **多操作链式**执行，中间产物可留 `.drafts/`
4. **产物输出到** `outputs/主题名/`，最后告知路径与时长
