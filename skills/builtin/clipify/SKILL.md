---
name: clipify
description: >-
  从长视频中自动提取精彩片段，切成独立短视频，支持 16:9→9:16 竖版转制和逐字字幕烧录。
  当用户说"视频切片""提取精彩片段""长视频切短""切成短视频""高光剪辑""逐字字幕""转竖版短视频"时使用。
  和 video-highlights 的区别：clipify 专做英文口播找笑点+动态人脸 pan；video-highlights 更通用（中文/直播皆可），静态转竖版更稳。
layer: produce
---

# Clipify

Find the funniest moments in a video, cut them as standalone clips, optionally reformat 16:9 → 9:16 (face-pan or split-screen), and burn opus-style word-by-word captions.

## Inputs

- A video file path (the user will provide it; otherwise ask)
- Optional: requested format (9:16, 16:9, 1:1) — if not given, ask after candidates are picked
- Optional: subtitle style preference — if not given, ask before captioning

## Tooling (use only the fastest path)

- **Whisper:** `whisper --model tiny.en --word_timestamps True --output_format json` (≈10× faster than `small.en`; quality fine for English). For non-English: `--model base` (drop `--language`).
- **ffmpeg:** hardware decode is optional and platform-specific — use `-hwaccel auto`, or omit it (macOS: `videotoolbox`; Linux: `vaapi`/`cuda`/none). Add `-preset ultrafast` for renders. Use `-c:v libx264 -crf 20` for the final master.
- **Numpy** for audio alignment (FFT cross-correlation). No scipy/cv2 needed.
- **Scripts:** `<skill-dir>/scripts/` (where `<skill-dir>` is the directory containing this SKILL.md — typically `~/.claude/skills/clipify/`)
  - `analyze.py` — speaker timeline from two ROI motion files
  - `build_pan.py` — ffmpeg crop x-expression with hard cuts
  - `build_ass.py` — opus-style ASS captions from whisper JSON
  - `audio_align.py` — find offset of a sub-clip in a longer source

Working dir: `/tmp/clipify/` (mkdir at start, leave artifacts for debugging).

---

## Workflow

### Step 1 — Find the funniest parts

```bash
mkdir -p /tmp/clipify
ffmpeg -y -i "$VIDEO" -vn -ac 1 -ar 16000 /tmp/clipify/audio.wav
whisper /tmp/clipify/audio.wav --model tiny.en --word_timestamps True --output_format json --output_dir /tmp/clipify --language en
```

Read the resulting JSON (or `.txt`) and pick 3–5 candidate clips. Funny signals to scan for:

- **Punchlines and reactions:** words like "what", "wait", "no way", laughter, "haha", swearing
- **Reversal moments:** setup question → unexpected answer
- **Awkward pauses:** Whisper segment with long gap, or filler ("uh", "um")
- **Self-roast / quotable one-liners:** short declarative sentences that stand alone
- **Audio peaks:** detect via `ffmpeg -af volumedetect` or look for rapid back-and-forth (alternating short Whisper segments)

For each candidate, propose: `[start, end, why-it's-funny, suggested title]`. Aim for 10–25s clips. Show the list and let the user confirm/pick.

### Step 2 — Trim each chosen clip

```bash
ffmpeg -y -ss "$START" -t "$DURATION" -i "$VIDEO" -c copy /tmp/clipify/clip_$N.mp4
```

(Use `-c copy` for instant trim. Re-encode only if cuts must be frame-accurate.)

### Step 3 — Decide the output format

Ask the user (skip if they already specified): "9:16 (TikTok / Reels), 16:9 (YouTube), or 1:1 (Insta feed)?"

### Step 4 — If 16:9 → 9:16: pan-between-faces vs split-screen

Detect source aspect with `ffprobe`. If source is 16:9 and target is 9:16, ask:

> "Two options: **(a) hard-cut pan** that follows whoever is speaking (single face on screen at a time), or **(b) split-screen** stack with both faces visible. Which do you want?"

Skip the question if there's only one face (single-talker clip). For single-talker, just center-crop.

#### Step 4a — Pan-between-faces (recommended for fast-cut talking-head dialogue)

1. **Locate the two face ROIs.** Sample one frame: `ffmpeg -ss <middle> -i <clip> -frames:v 1 /tmp/clipify/probe.jpg`. Read it. Eyeball each face's mouth+chin area as `x,y,w,h` in the source's pixel space. (No cv2 needed — camera is static within a clip; one frame is enough.) Verify by drawing boxes:

   ```bash
   ffmpeg -i probe.jpg -vf "drawbox=x=$LX:y=$LY:w=$LW:h=$LH:color=cyan@0.9:t=4,drawbox=x=$RX:y=$RY:w=$RW:h=$RH:color=magenta@0.9:t=4" verify.jpg
   ```

   Iterate **at most twice**. Boxes should cover mouth + chin and avoid hands/mics. Don't over-tune — frame differencing is forgiving.

2. **Extract per-frame motion energy in each ROI:**

   ```bash
   ffmpeg -y -i clip.mp4 -filter_complex "
   [0:v]split=2[a][b];
   [a]crop=$LW:$LH:$LX:$LY,format=gray,tblend=all_mode=difference,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=/tmp/clipify/L.txt[la];
   [b]crop=$RW:$RH:$RX:$RY,format=gray,tblend=all_mode=difference,signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=/tmp/clipify/R.txt[ra]
   " -map "[la]" -f null - -map "[ra]" -f null -
   ```

3. **Build speaker timeline** (min dwell 1.0s — short interjections merge into the prior speaker):

   ```bash
   python3 <skill-dir>/scripts/analyze.py /tmp/clipify/L.txt /tmp/clipify/R.txt 1.0 > /tmp/clipify/segments.json
   ```

4. **Pick pan x-coordinates** for a 9:16 vertical strip from the source. With source W=1920 and target W=1080, crop strip width = 608.
   - LEFT_X = `face_left_center_x - 304` (clamp ≥ 0)
   - RIGHT_X = `face_right_center_x - 304` (clamp ≤ source_W - 608)

5. **Generate the hard-cut x expression and render:**

   ```bash
   EXPR=$(python3 <skill-dir>/scripts/build_pan.py /tmp/clipify/segments.json $LEFT_X $RIGHT_X)
   ffmpeg -y -i clip.mp4 -filter_complex \
     "[0:v]crop=608:1080:x='$EXPR':y=0,scale=1080:1920:flags=lanczos[v]" \
     -map "[v]" -map 0:a -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p \
     -c:a aac -b:a 192k /tmp/clipify/clip_panned.mp4
   ```

   Source 1920×1080 assumed; for 4K source either downscale first or double all coordinates.

#### Step 4b — Split-screen (both faces always visible)

Two stacked tiles, 1080×960 each. The active speaker's tile is on top — overlay flips at speaker changes.

```
[0:v]split=2[a0][a1];
[a0]crop=Wcrop:Hcrop:LX_tile:LY_tile,scale=1080:960,split=2[lt0][lt1];
[a1]crop=Wcrop:Hcrop:RX_tile:RY_tile,scale=1080:960,split=2[rt0][rt1];
[lt0][rt0]vstack[layoutL];
[rt1][lt1]vstack[layoutR];
[layoutL][layoutR]overlay=0:0:enable='<RIGHT_SPEAKER_ENABLE>'[v]
```

Build `<RIGHT_SPEAKER_ENABLE>` from `segments.json` as `between(t,a,b)+between(t,a,b)+...` over the right-speaker segments. Tile crops should target ~720×640 around each face (1.125:1 to match 1080×960).

### Step 5 — Add subtitles

Ask once (only if user hasn't already specified a style):

> "Three subtitle styles: **opus** (big bold white, yellow active-word highlight), **karaoke** (4-word chunks, green highlight), **minimal** (clean Helvetica, no highlight). Or paste an example you like."

If they paste a reference image/example: match the font, size, weight, color, position, and animation as closely as possible — write a custom ASS by hand or extend `build_ass.py`.

Else use the preset:

```bash
# Re-run whisper on the trimmed clip for accurate timestamps relative to clip start
whisper /tmp/clipify/clip_panned.mp4 --model tiny.en --word_timestamps True --output_format json --output_dir /tmp/clipify --language en
python3 <skill-dir>/scripts/build_ass.py /tmp/clipify/clip_panned.json /tmp/clipify/captions.ass opus
```

Burn captions:

```bash
ffmpeg -y -i /tmp/clipify/clip_panned.mp4 -vf "subtitles=/tmp/clipify/captions.ass" \
  -c:v libx264 -preset fast -crf 20 -c:a copy "$OUTPUT.mp4"
```

### Step 6 — Deliver

- Save each output to `<source_dir>/clipify_out/` (mkdir if missing)
- Print one line per clip: name, duration, what was funny, output path
- Print the first output path (or open it — Linux `xdg-open <path>`, macOS `open <path>`) so the user can check it
- Offer to iterate (different style, different ROI, swap to split-screen, retime captions)

---

## Pitfalls (lessons from prior runs — don't repeat)

- **Don't over-tune ROIs.** Two iterations max. Motion-diff is forgiving — wider ROIs covering mouth+chin work fine even if not perfectly mouth-centered.
- **Watch out for scene cuts inside a clip.** Run `ffmpeg -filter:v "select='gt(scene,0.3)',showinfo" -f null -` to count cuts. If a 16:9→9:16 clip has many cuts, the fixed face ROIs only work for the dominant scene; warn the user, and offer to either pick a single-take clip or accept off-center framing during cuts.
- **Source resolution matters.** If source is 4K, either downscale to 1920×1080 first (faster, fine for 9:16 output) or multiply all ROI/pan coordinates by 2.
- **Burned-in subtitles in source.** Some "raw" clips still have subtitles. If so, find the no-subs master via audio cross-correlation (`audio_align.py`) and trim from there.
- **Don't run whisper on the full feature-length source if a short clip suffices.** Whisper the trimmed clip after Step 2; only whisper the full source in Step 1 if you need a transcript to find funny moments.
- **State the plan in one line, then act.** Don't narrate every iteration.
