# 模型无关的原生音频协议

## 原则

把视频模型差异限制在 `ai_video.py` 的 capability profile。短剧层只使用统一语义：

- `native_audio`：能否生成原生同步音频。
- `dialogue`：能否按 prompt 尝试生成画内对白。
- `dialogue_faithful`：能否**逐字忠实**生成指定台词（决定用原生对白还是"无台词生成+后期配音"，默认 `false`，由 `probe-dialogue` 探针或覆盖确认）。
- `audio_reference`：能否使用音频参考。
- `audio_field` / `audio_location`：provider 请求字段映射。

如果网关默认返回有声视频但尚未确认开关字段，只声明 `audio_default: true`，不要向接口猜测并注入未知参数；产物仍进入相同审计流程。

能力声明不是质量证明。下载后始终用 ffprobe 和 ASR 审计实际产物。

## 覆盖新模型

内置 provider 未及时收录新模型时，用 `VIDEO_CAPABILITIES_JSON` 覆盖，不修改短剧脚本：

```json
{
  "openai-compatible:new-video-model": {
    "native_audio": true,
    "dialogue": true,
    "dialogue_faithful": false,
    "audio_reference": false,
    "audio_field": "generate_audio",
    "audio_location": "root"
  }
}
```

运行 `ai_video.py capabilities --provider ... --model ...` 检查最终能力。

## 默认就让视频模型说台词（native-first）——能用模型原声**一定**用

**第一原则：视频模型能说台词就让它说、并优先采用它的原生人声**（自然、口型天生同步、省 TTS、无双重人声）。视频模型的音轨**绝不是"只留环境音"**——默认就要求它逐字说出台词。是否采用**由逐镜 audit 按实际产物判定**，不预先假设模型不行、更不能"反正有 TTS 就默认不让模型说话"。

**默认流程（`--dialogue-mode auto`，不需要预先探针）：**
1. `prepare` 默认 **native-first 契约**：把台词写进每镜 `generation_prompt`，要求模型逐字说出。（治「台词全对不上」的根本就是**把台词喂给模型**；`shots validate --pre-video` 硬门保证喂到位。）
2. 逐镜生视频（带 generation_prompt）。
3. `audit` 逐镜 ASR 核验，**按实际产物**决策：
   - **`native`（常态）**：一镜一句画内对白、语言正确、相似度 ≥ 阈值（默认 0.6，偏向「可用就留」），或纯动作镜无意外语音 → **整轨原音（人声+环境音）直通、字幕用 ASR 起止、不配音**。这是主路径。
   - **`dub`（例外）**：这一镜人声**真的坏了**（语言错/内容明显不符），或完全无原音 → 该镜改用 TTS。⚠️ 无人声分离时，**dub 镜的原生音轨（含说错的人声）整轨丢弃、补静音**——保留会与 TTS **双重人声/回声**（真机踩过），故 dub 镜牺牲环境音换不重复。
   - **`regenerate`**：片段缺失/ASR 读不出/动作镜意外语音 → 带反馈重生成，拿到好原声即转 native。
4. 旁白（画外音）永远走独立 TTS 轨（视频模型不生成旁白）。语言正确是强制前置门。

**`dub-reserve`（生成阶段就不给台词、只留口型+预留时长、全靠后期配音）只在模型被 `probe-dialogue` 实测判「不逐字忠实」时才用**（或显式 `--dialogue-mode dub`）——是**少数说不好台词的模型的兜底，不是默认**。绝不能默认走它。

- **`dialogue_faithful` 探针 = 可选诊断**：只有成片对白**反复**不准、怀疑模型天生说不好时才跑 `probe-dialogue`（真发 1 次生成让模型说测试台词 → ASR 比对语言+相似度阈值 0.9 → 判定并按 `provider:model` 缓存）。默认（未实测）走 native-first、不据默认判 dub。
  - 建议探针用真实短剧画面 + 中英混杂台词压测（`--scene`）。缓存按 `provider:model` 存；`prepare --provider/--video-model` 会把解析后的选择锁进 shots.json，`generate` 必须复用，保证探针、契约和实际生成命中同一模型。
  - 探针默认 t2v、短剧走 i2v，忠实度可能不同：**首个对白镜生成后务必跑 `audit` 抽验**（如月站v2 实测 i2v 亦忠实）。

## 音色固定（换配音时）

需要换配音的角色，**音色由 `cast.json` 按角色绑定的 `voice_id` 决定，且贴合其定妆参考图形象**（萝莉→童声、御姐→成熟音…）。同一角色**跨镜跨集音色恒定**（一部剧一份 cast.json，一个角色一个 voice_id）；只有情绪/语调随 `emotion` 逐行变化（`multivoice.emotion_prosody` 叠加 rate%/pitchHz/volume% 增量），**音色身份绝不改变**。

## 旁白/TTS 是短板（实战要点）

对白走原生视频音时很自然（模型忠实即可）；但**旁白（画外音）永远走 TTS**，其自然度**取决于 TTS provider**——小模型（如 SiliconFlow CosyVoice2-0.5B）旁白偏机械、"AI 味"。想让旁白更像真人：① 配更强的 TTS provider（minimax 最自然 / dashscope CosyVoice 大模型），见 voice-casting.md；② **少用旁白、多用画内对白**（对白走原生音更自然）；③ 旁白情绪词别写"平静克制"这种"叫它平"的词，用有叙事张力的语气。
- **旁白 `at` 越界会自动前移适配**（画外音无口型约束，`shot_layout` 自动处理），不必人工反复调；**画内对白 `at` 越界仍硬拦**（要对齐嘴动，必须拆镜/精简/改 at）。

## 候选与重试

每镜最多生成首个候选加两次重试。每次保留原文件和审计报告，不覆盖候选。重试 prompt 必须带上具体失败反馈，例如“检测为英文”“漏掉后半句”“2.1 秒才开口”。**`regenerate` 优先**——重生成拿到好原声，既用上模型自然人声又保住整轨环境音（比转 dub 好）；重生成用尽仍说不好，才按 `dub` 换 TTS 配音（该镜原生轨丢弃、无环境音）。

最终拼接前统一为 H.264、CFR、AAC 48 kHz stereo。**只有 `native` 镜保留其原生音轨（人声+环境音）**；`dub` 镜与无原音镜补等长静音轨（dub 靠独立 TTS 配音），保证跨模型、跨编码拼接稳定、不产生双重人声。侧链闪避仅用于让旁白/配音干净盖在 native 镜的环境音之上。
