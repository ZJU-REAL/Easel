---
name: audio-mix
description: "音频混合 / 混音：把旁白口播 + 背景音乐 + 音效混成一轨，BGM 自动循环补足并可闪避（旁白说话时自动压低 BGM 保证人声清晰）。当用户说 混音、音频混合、旁白加背景音乐、配音加BGM、人声和音乐混一起、加音效、音频叠加、BGM 压低、闪避、ducking、把配音和bgm合起来 时使用。基于 shared/scripts/audio_mix.py。与 audio-editing concat 区别：concat 是前后顺序拼接，本 SKILL 是同时叠加混音；与 video-editing bgm 区别：那个给视频配乐，本 SKILL 输出纯音频。"
layer: produce
---

# 音频混合（旁白 + BGM + 音效）

> 把多条音频**同时叠加**混成一轨，核心能力是**闪避（ducking）**——旁白说话时自动压低
> 背景音乐，人声清晰、音乐不抢。全部走 `skills/shared/scripts/audio_mix.py`，
> **不要手拼 amix/sidechaincompress**。

> 前后顺序拼接（一段接一段）见 **audio-editing** `concat`；给视频配乐见 **video-editing** `bgm`；
> 降噪见 **audio-denoise**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 旁白 | 否 | 口播/配音主轨（给了则输出时长跟它走，并触发闪避） |
| BGM | 否 | 背景音乐（自动循环补足到旁白长度） |
| 音效 | 否 | 一个或多个音效，可指定各自出现时间点 |

（三者至少给一个。最典型："旁白 + BGM"。）

## 输出（`outputs/主题名/`）

- 混音后的单轨音频（mp3/wav/m4a，按输出后缀）
- 报告：轨数、时长、是否闪避

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/audio_mix.py`（`mix -h` 看参数）。

```bash
# 旁白 + BGM（默认自动闪避，BGM 循环补足到旁白长度）
python skills/shared/scripts/audio_mix.py mix \
  --voice narration.mp3 --bgm music.mp3 --bgm-volume 0.25 \
  -o outputs/主题名/final.mp3

# 关闭闪避（纯叠加）
python skills/shared/scripts/audio_mix.py mix --voice v.mp3 --bgm m.mp3 --no-duck -o out.mp3

# 旁白 + 定时音效（第 3.5s 一个叮，第 8s 一个 whoosh）
python skills/shared/scripts/audio_mix.py mix --voice v.mp3 \
  --sfx ding.wav --sfx-at 3.5 --sfx whoosh.wav --sfx-at 8 -o out.mp3
```

## 调参

- **人声被音乐盖住**：调低 `--bgm-volume`（默认 0.25）或确认闪避已开（默认开）。
- **闪避太猛/音乐一顿一顿**：`--no-duck` 后手动压低 `--bgm-volume`。
- **BGM 比旁白短**：默认自动循环；不想循环用 `--bgm-loop-off`。
- **音效太响/太轻**：`--sfx-volume`（默认 0.9）。

## 规则

1. 有旁白时输出时长 = 旁白长度，BGM 自动循环/裁切对齐并在末尾淡出。
2. 旁白 + BGM 默认开启闪避（人声优先）；不需要时显式 `--no-duck`。
3. `--sfx` 与 `--sfx-at` 数量一致（或不给 --sfx-at 全部默认 0s）。
4. 混音不做响度归一（保留相对音量）；需统一响度先用 audio-editing `normalize`。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

闪避用 ffmpeg `sidechaincompress`（以人声为控制信号压缩 BGM），是播客/口播视频保证人声清晰的
标准做法；多轨叠加用 `amix`。把 sidechain 接线与循环对齐封装成确定性脚本。
