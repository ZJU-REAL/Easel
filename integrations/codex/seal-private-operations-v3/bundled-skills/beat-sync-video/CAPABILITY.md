---
name: beat-sync-video
description: "音乐卡点视频 / 踩点视频：检测背景音乐的节拍，让图片或片段在节拍点上切换，配推进/白闪特效，做出燃系'卡点'短视频。当用户说 卡点视频、踩点视频、音乐卡点、节奏卡点、按音乐切换、鼓点视频、踩节奏、beat 卡点、图片卡点、卡点混剪 时使用。基于 shared/scripts/beatsync.py（librosa 节拍检测）。与 slideshow-video 区别：slideshow 每图固定时长、柔和转场，本 SKILL 切换点由音乐节拍决定、硬切踩点带特效。"
layer: produce
---

# 音乐卡点视频（踩点混剪）

> 用 librosa 检测背景音乐节拍，让画面在节拍上硬切换，配节拍特效，做"踩点"燃系短视频。
> 全部走 `skills/shared/scripts/beatsync.py`，**不要手数节拍、手拼滤镜**——脚本已做
> 节拍检测、区间切分、素材循环、音画对齐。

> 每图固定时长的柔和相册见 **slideshow-video**；主题→AI 配图配音成片见 **auto-short-video**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 背景音乐 | 是 | 决定卡点的音乐文件（节奏越强效果越好；没给就问） |
| 素材 | 是 | 一组图片和/或短片段（按顺序，循环使用），或一个目录 |
| 画幅 | 是 | 用户或上游任务未明确横版/竖版（或具体分辨率）时，制作前必须追问并等确认；不得按平台、Profile 或默认值静默推断，已明确则不重复问 |
| 切换频率 | 否 | 每几拍切一次（默认每 2 拍） |
| 特效 | 否 | `zoom` 推进（默认）/ `flash` 白闪 / `none` |

## 输出（`outputs/主题名/`）

- 卡点成片（`*.mp4`）
- 报告：卡点段数、总时长、检测到的 BPM、特效

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/beatsync.py`（`build -h` / `beats -h`）。

### 1.（可选）先看节拍
```bash
python skills/shared/scripts/beatsync.py beats --music <音乐>
# 打印 tempo(BPM) 与节拍时间点，用于判断 --every 该设多少
```

### 2. 生成卡点视频
```bash
python skills/shared/scripts/beatsync.py build \
  -i 1.jpg 2.jpg 3.jpg 4.jpg --music <音乐> \
  -o outputs/主题名/show.mp4 \
  --size 1080x1920 --every 2 --effect zoom
```
- 素材 = 图片或短片段，**数量可少于卡点段数**（自动循环复用）。
- `--every 1` 每拍都切（快闪，素材要多）；`--every 4` 每小节切一次（舒缓）。
- `--effect flash` 段首白闪更"燃"；`--effect none` 干净硬切。
- `--max-duration 15` 限制成片长度（如做 15s 抖音）。
- 也可 `--images-dir <目录>` 批量喂素材（按文件名排序）。

## Profile 感知

- 有 Profile：`platforms.md` 只用于给出画幅建议，仍须用户确认；卡点风格（快闪/舒缓）与特效贴合账号调性
  （潮流/运动账号偏快闪 flash，生活/治愈账号偏 zoom 舒缓）。
- 无 Profile：先确认横版/竖版；默认每 2 拍、zoom 特效。

## 规则

1. 音乐节奏越明确卡点越准；无明显节拍时脚本自动退化为等间隔切换并在报告说明。
2. 卡点用**硬切**（不加转场），否则会糊掉节拍感——这是刻意设计。
3. 素材不足自动循环；素材充足时建议 `--every 1~2` 让每段都换新画面。
4. 成片默认跟音乐等长，用 `--max-duration` 卡平台时长。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

节拍检测用 librosa `beat_track`（onset 强度 + 动态规划求拍点），画面在拍点硬切是卡点混剪的
标准做法。把节拍→区间→逐段渲染→音画对齐封装成确定性脚本，避免手数拍子对不齐。
