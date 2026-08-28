---
name: auto-short-video
description: "一句话主题 → 成品短视频：自动串联 文案→配图/AI视频→配音→字幕→BGM→合成，把 Easel 制作层零件编排成一条'一键出片'流水线。**单条视频、口播/资讯向，画面默认逐句配图 + Ken Burns 缓动，需要动态时才逐段图生视频**。当用户说 一键生成视频、自动做短视频、主题生成视频、帮我做条视频、口播视频一条龙、自动出片、短视频一键生成 时使用。**有剧情/角色/对白/反转/多集的短剧改用 short-drama（每镜强制图生视频、不用静态图冒充）；只写脚本用 video-script；只生成单个片段用 ai-video-gen。**"
layer: produce
---

# 一键短视频（端到端编排）

> 输入一个主题，自动产出一条短视频。本 SKILL 是**编排层**：把已有制作零件串成流水线——
> 文案(video-script) → 逐句配图(ai-image-gen)或片段(ai-video-gen) → 配音(tts-voiceover) →
> 字幕(auto-subtitle) → BGM(ai-music) → **合成(scripts/assemble.py)**。
> 沉淀自 Pixelle-Video / MoneyPrinterTurbo 的自动短视频引擎思路。

## 输入

- 主题 / 文案（必填）
- 可选：目标时长、风格、是否要配音/字幕/BGM、配图用 AI 生图还是用户素材
- **画幅确认硬门**：用户或上游任务未明确横版/竖版（或 16:9/9:16/具体分辨率）时，制作/付费调用前必须追问并等确认；不得从平台、Profile 或默认值静默推断，已明确则不重复问

## 输出

成品短视频写入 `outputs/主题名/final.mp4`；分镜图、配音、字幕和 storyboard 写入 `outputs/主题名/assets/`。

## 执行步骤（按需裁剪，缺 API key 的环节自动降级或询问）

1. **写脚本分镜**：用 [video-script](../video-script/SKILL.md) 把主题写成口播文案，拆成 N 句（每句一个分镜），每句配一个画面描述。

2. **生成画面**（每个分镜一张图/一段片）：
   - 有图像 API key → [ai-image-gen](../ai-image-gen/SKILL.md) 逐句 text2img（按已确认画幅）
   - 要动态 → [ai-video-gen](../ai-video-gen/SKILL.md) text2video/image2video
   - 用户自带素材 → 用 [image-editing](../image-editing/SKILL.md) `pad` 到已确认画幅
   - 都没有 → 按已确认画幅选图卡（竖版用 card-xiaohongshu/poster-hero，横版用 card-quote）再 pad，避免画幅错配。

3. **配音**：[tts-voiceover](../tts-voiceover/SKILL.md) 把文案合成口播（同时出 SRT）。**配了 `VOICE_PROVIDER` 默认走闭源好嗓子**（有情感、像真人），没 key 才退 edge（机械）——想要口播不"生硬"务必配闭源 key。不需要配音才跳过。

4. **字幕**：用 TTS 附带的 SRT，或对配音跑 [auto-subtitle](../auto-subtitle/SKILL.md)；也可让 assemble 用各分镜 caption 自动生成。

5. **BGM**：[ai-music](../ai-music/SKILL.md) 生成，或用用户提供的音乐。可选。

6. **合成成片**：把上面的素材写成 storyboard JSON，调合成器：
   ```bash
   python skills/openclaw/auto-short-video/scripts/assemble.py assemble \
     --storyboard outputs/主题名/assets/storyboard.json \
     -o outputs/主题名/final.mp4
   ```
   storyboard 结构（图/片二选一，narration/bgm/subtitle 可选，缺 duration 时按配音均分）：
   ```json
   {
     "size": "<已确认尺寸，如1080x1920或1920x1080>",
     "image_motion": "ken-burns",
     "shots": [
       {"image": "outputs/主题名/assets/shot1.png", "duration": 3, "caption": "第一句", "motion": "static"},
       {"video": "outputs/主题名/assets/clip2.mp4", "caption": "第二句"}
     ],
     "narration": "outputs/主题名/assets/voice.mp3",
     "bgm": "outputs/主题名/assets/bgm.mp3",
     "subtitle": "outputs/主题名/assets/voice.srt"
   }
   ```
   `image_motion` 设整条图片默认运动，单镜 `motion` 可覆写：照片用 `ken-burns`，含文字的 slide/图表/界面必须用
   `static`（等比缩放 + 补边，不裁切、不平移）。
   合成器自动做：按 `image_motion` 生成静帧或 Ken Burns、补边到画幅、拼接、配音+BGM 混音（BGM 自动压低）、烧录字幕。

7. **交付**：产出 final.mp4，附一句制作说明（用了哪些环节、哪些降级了）。

## 编排原则

- **零件可缺**：缺图像/视频/TTS API key 的环节自动降级（图卡兜底 / 跳过配音），不阻断整体，并如实告知用户降级了什么。
- **先出 Plan**：涉及多个付费 API（生图/生视频/生乐）时，先向用户说明将调用哪些、大致耗时/花费，确认后再跑。
- **中间产物留档**：分镜图、配音、字幕和 storyboard 都写进 `outputs/主题名/assets/`，方便单独替换后重新合成。

## Profile 感知

- 有 Profile：从 `style.md` 取调性/视觉风格贯穿文案与配图 prompt；`platforms.md` 只用于给出画幅/时长建议，画幅仍须确认；`preferences.md` 红线过滤。
- 无 Profile：先确认横版/竖版，再用通用口播风格。
