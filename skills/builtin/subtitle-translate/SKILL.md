---
name: subtitle-translate
description: "字幕翻译 / 双语字幕：把已有字幕（SRT/VTT/ASS）翻译成目标语言，生成双语（原文+译文）或纯译文字幕，并可软挂载 / 硬烧录进视频。当用户说 字幕翻译、翻译字幕、双语字幕、中英字幕、给视频加翻译、SRT 翻译、字幕本地化、把字幕翻成中文/英文、字幕转双语 时使用。翻译由 LLM 完成，时间轴/格式/烧录由 shared/scripts/subtitle_ops.py 确定性处理。与 auto-subtitle 区别：auto-subtitle 是语音识别生成字幕，本 SKILL 是把已有字幕翻译成双语。"
layer: produce
---

# 字幕翻译 / 双语字幕

> 把已有字幕翻译成目标语言，产出**双语**（原文+译文）或**纯译文**字幕，可选烧录进视频。
> 翻译交给 LLM（你自己），确定性部分（解析/合并/格式/时间轴/烧录）全交给
> `skills/shared/scripts/subtitle_ops.py`。**不要手拼 ffmpeg，也不要手改时间轴。**

> 只做"已有字幕 → 翻译/双语/烧录"。语音识别生成字幕见 **auto-subtitle**；
> 通用视频剪辑见 **video-editing**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 字幕文件 | 是 | `.srt` / `.vtt` / `.ass` 路径（没给就问） |
| 目标语言 | 是 | 译成什么语言（如中文 / English / 日本語） |
| 输出形态 | 否 | `双语`（默认）/ `纯译文` |
| 原译顺序 | 否 | 双语时原文在上（默认）或译文在上 |
| 视频文件 | 否 | 给了则可烧录；软挂载（可开关）或硬烧录（烧进画面） |

## 输出（`outputs/主题名/`）

- 双语 / 纯译文字幕文件（`.srt` 或 `.ass`）
- 若烧录：带字幕的视频（`*-sub.mp4`）
- 报告：条数、目标语言、形态、输出路径

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/subtitle_ops.py`（每个子命令支持 `-h`）。

### 1. 提取待译文本
```bash
python skills/shared/scripts/subtitle_ops.py extract -i <字幕> -o /tmp/st_lines.txt
```
每条字幕一行、行号与顺序固定。**记住总行数 N。**

### 2. 逐行翻译（你来做）
读 `/tmp/st_lines.txt`，逐行翻译成目标语言，写入 `/tmp/st_trans.txt`：
- **行数必须严格等于 N，顺序一一对应，不增删空行、不合并、不拆行**（脚本会校验，不一致直接报错）。
- 一行内如原文有多句，整合成一行译文，不要拆成多行。
- 语气/术语按内容领域走；口语内容译得自然口语，书面内容译得书面。
- 空行原文对应空行译文（保持占位）。

### 3. 合并成双语 / 纯译文字幕
```bash
# 双语 SRT（原文在上，译文在下）
python skills/shared/scripts/subtitle_ops.py merge -i <字幕> --trans /tmp/st_trans.txt \
  -o outputs/主题名/<名>-bilingual.srt

# 双语 ASS（原文白色较大 / 译文黄色略小，样式更佳，推荐用于硬烧录）
python skills/shared/scripts/subtitle_ops.py merge -i <字幕> --trans /tmp/st_trans.txt \
  -o outputs/主题名/<名>-bilingual.ass --format ass

# 纯译文（不保留原文）
python skills/shared/scripts/subtitle_ops.py merge -i <字幕> --trans /tmp/st_trans.txt \
  -o outputs/主题名/<名>-<lang>.srt --trans-only
```
`--order trans-top` 可让译文在上。

### 4.（可选）烧录进视频
```bash
# 硬烧录（烧进画面，推荐用 .ass 保留双语样式）
python skills/shared/scripts/subtitle_ops.py burn -i <视频> \
  --sub outputs/主题名/<名>-bilingual.ass \
  -o outputs/主题名/<名>-sub.mp4

# 软挂载（可在播放器开关，不改画面；mp4→mov_text，mkv→srt）
python skills/shared/scripts/subtitle_ops.py burn -i <视频> \
  --sub outputs/主题名/<名>-bilingual.srt \
  -o outputs/主题名/<名>-sub.mp4 --soft
```

## 其它子命令

- `parse -i <字幕> [-o out.json]` — 解析成 JSON（含时间轴），供程序化处理或核对。
- `build --json <cues.json> -o <字幕>` — 从 JSON（cue 带 `text` 与可选 `trans`）构建，适合批量/整段翻译回填。
- `convert -i a.srt -o b.vtt` — 格式互转（srt ↔ vtt ↔ ass）。

## 规则

1. 翻译走 extract → 逐行译 → merge 三步，**严守行数一致**，绝不让脚本回退到"猜行对应"。
2. 时间轴、字幕条数、格式一律由脚本产出，禁止手改时间戳。
3. 硬烧录中文优先用 `.ass`（内置 Noto Sans CJK 样式）；若用 srt 硬烧录且中文变方块，`burn` 加 `--font-dir` 指向含 CJK 字体的目录。
4. 双语默认原文在上、译文在下（`--order` 可调）；纯译文用 `--trans-only`。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

字幕翻译工具形态参考开源项目：rockbenben/subtitle-translator（批量双语、译文上下对齐）、
bonigarcia/dualsub（双语合并）、innovationmech/video-translate（软/硬字幕嵌入）。
本 SKILL 把"翻译"交给 LLM，只把易错的解析/时间轴/合并/烧录做成确定性脚本。
