---
name: video-highlights
description: "长视频 / 直播录像高光切片：从一条长视频里找出高光片段，切成多条独立短视频，可选转竖版 9:16 + 加字幕。找点两种方式——音频能量峰值（情绪高涨/欢呼/大声处）或转录后由内容判断挑金句段。当用户说 直播切片、高光切片、长视频切短、录像剪精华、切片、高光时刻、把直播剪成短视频、提取精彩片段、长视频找亮点 时使用。基于 shared/scripts/highlight_cut.py（librosa 能量分析）。与 clipify 区别：clipify 专做英文口播找笑点+动态人脸pan，本 SKILL 更通用（中文/直播皆可）、静态转竖版更稳。"
layer: produce
---

# 长视频 / 直播录像高光切片

> 从长视频里找高光段 → 切成多条短视频（可转竖版 + 加字幕）。切片执行走
> `skills/shared/scripts/highlight_cut.py`，**不要手拼裁切命令**——脚本已处理精确裁切、
> 前后留白、批量输出、转竖版、清单生成。

> 英文口播找笑点 + 逐段动态人脸 pan 见 **clipify**；只转画幅见 **video-reframe**；
> 字幕翻译见 **subtitle-translate**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 长视频 | 是 | 直播录像 / 长视频（没给就问） |
| 找点方式 | 否 | `能量`（默认，情绪高涨处）/ `内容`（转录后按金句/爆点挑） |
| 片段数 | 否 | 切几条（默认 5） |
| 每段时长 | 否 | 每条大约多长（默认 20s） |
| 转竖版 | 否 | 是否转 9:16 发抖音/小红书 |

## 输出（`outputs/主题名/`）

- 多条切片（`highlight_01.mp4` …）+ 清单 `highlights.json`

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/highlight_cut.py`（`energy -h` / `cut -h`）。

### 方式 A：音频能量找点（快，适合有欢呼/情绪起伏的直播）
```bash
# 1) 找候选段
python skills/shared/scripts/highlight_cut.py energy -i <长视频> \
  --top 5 --clip-len 20 -o /tmp/hl_cand.json
# 2) 切片（可同时转竖版）
python skills/shared/scripts/highlight_cut.py cut -i <长视频> \
  --segments /tmp/hl_cand.json -o outputs/video-highlights \
  --reframe 9:16 --reframe-mode blur
```

### 方式 B：内容找点（准，适合口播/知识/带货，挑金句爆点）
1. 先转录（复用 auto-subtitle 的 `asr.py`，带时间轴）：
   ```bash
   python skills/shared/scripts/asr.py transcribe -i <长视频> --format json -o /tmp/hl.json
   ```
2. **你**读转录，挑出 3-5 个最有价值/最抓人的片段（完整语义段，别切半句），
   写成切片清单 `/tmp/hl_segs.json`：
   ```json
   {"segments": [{"start": 73.2, "end": 95.0, "label": "金句：xxx"}, ...]}
   ```
3. 切片：
   ```bash
   python skills/shared/scripts/highlight_cut.py cut -i <长视频> \
     --segments /tmp/hl_segs.json -o outputs/video-highlights --reframe 9:16
   ```

`--pad 0.3` 每段前后留白避免切太紧；不转竖版就去掉 `--reframe`。

## Profile 感知

- 有 Profile：转竖版比例按 `platforms.md` 主平台；找点侧重贴合账号定位（带货看爆点、
  知识看金句、娱乐看情绪高潮）；切片时长贴合平台（抖音 15-30s，视频号 30-60s）。
- 无 Profile：默认能量找点 top5、每段 20s，询问是否转竖版。

## 规则

1. 内容找点务必切**完整语义段**，不要从半句话切进/切出。
2. 能量找点适合有明显情绪起伏的素材；平淡口播优先用内容找点（方式 B）。
3. 切片默认前后各留 0.3s 白，避免开头/结尾被切掉。
4. 转竖版口播类建议 `--reframe-mode smart`（人脸居中），其它用 `blur`（不丢画面）。
5. 产物统一进 `outputs/主题名/`，附 `highlights.json` 清单。

## 参考来源

音频能量选段用 librosa RMS 峰值（贪心去重保证峰间隔）；内容选段沿用 opus-clip 式"转录→挑金句"
思路但交给 LLM 判断。切片/转竖版复用确定性脚本，保证时间轴与画幅不出错。
