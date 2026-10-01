---
name: multi-voice-dubbing
description: >
  多角色对话配音：按 cast 和逐行对白为不同角色分配音色与情绪，合成多声线音轨和带角色名字幕。
  当用户说“多角色/双人/剧本/对话配音、多人对白、不同角色不同声音、有声剧配音”时使用。
  单一公共音色用 tts-voiceover；克隆本人音色用 voice-clone；整部短剧制作由 short-drama 编排。
layer: produce
---

# 多角色 / 对话配音（Multi-voice Dubbing）

把「多人对话 / 多角色脚本」合成为**多声线音轨**——每个角色一个符合其人设的声音，
不再是「全程一个声音」。核心引擎 `skills/shared/scripts/multivoice.py`：
逐行调 `tts.py`（edge-tts 免费多音色）或 `voice_clone.py`（云端表现力 provider / 克隆音色）合成，
把每行 emotion 喂进 provider 的**真情感通道**，`ffmpeg` 拼成一轨 + 生成对齐的说话人字幕。

> 创意（谁说什么、什么情绪）由你 LLM 产出；音色映射在 cast。确定性 IO（逐行合成/拼接/字幕）走引擎。
> 产物 `voice.mp3` 可直接当 narration 喂 `auto-short-video/assemble.py` 或加进任意视频；`voice.srt` 是带角色名的字幕。

## 配音质量分层（重要：治「像 AI 平读」）

**edge-tts 没有情感引擎**，只能变速变调，再怎么调也像机器平读。要"像人"必须用有情感通道的**云 provider**（用户自备 key，**无需 GPU**）：

| 引擎（cast 里 `engine`）| 质量 | 需要 | 情感机制 |
|---|---|---|---|
| `edge`（默认，免费兜底）| ⚠️ 平、机器感，仅供草稿 | 无 key、外网 | 仅 rate/pitch/volume 微调 |
| `clone`+`openai-compatible`→**SiliconFlow CosyVoice2**（推荐）| 好、中文自然 | VOICE_API_KEY（便宜/新用户赠额）| 内联 `<\|endofprompt\|>` 指令 |
| `clone`+`gemini` | 好、**真免费** | GEMINI_API_KEY（Google 免费层，国内需代理）| 自然语言前缀 |
| `clone`+`minimax` / `dashscope` | 好、有情绪 | 各家 key | emotion 枚举 / instruct |

**推荐 SiliconFlow**（云端 CosyVoice2、无需 GPU、中文最稳）配置落 `.env`：
```bash
VOICE_PROVIDER=openai-compatible
VOICE_BASE_URL=https://api.siliconflow.cn/v1
VOICE_API_KEY=<你的key>
VOICE_MODEL=FunAudioLLM/CosyVoice2-0.5B
VOICE_INSTRUCT_MODE=inline
```
cast 里角色：`--engine clone --provider openai-compatible --voice-id FunAudioLLM/CosyVoice2-0.5B:alex`（8 音色 alex/anna/benjamin/…）。

- **逐行 emotion 自动驱动演绎**：`lines.json` 每行的 `emotion`（愤怒/崩溃大哭/冷笑/温柔…）→ 引擎按 provider 转成对应情感参数。写具体越贴戏越好。
- 想要「像人」→ 至少给主角/关键角色配一个云 provider（`engine=clone`）；配了 key 才有情绪，没 key 自动回退 edge（平）并告警。
- provider 配置见 `voice_clone.py` 头部（各家 env）；`voice_clone.py check --provider <名>` 离线校验 key 是否齐。

## 谁会用到

短剧对白（short-drama 已内部委派）、**论文双人问答讲解**（paper-explainer：主讲+提问者）、
访谈/播客脚本、有声剧、任何「多个说话人」的口播。单人整段口播用 **tts-voiceover** 即可。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| cast.json | 是 | 选角表：每个说话人 → 音色（edge 音色 + pitch/rate，或克隆音色）。含「旁白/主讲」条目 |
| lines.json | 是 | 逐行对白：有序 `[{speaker, text, emotion}]`（speaker 用 cast 里的名字；emotion 如 冷/怒/紧张/温柔，自动匹配语气） |
| 输出路径 | 否 | voice.mp3（默认与调用方约定）；voice.srt 同名 |

## 执行步骤

### 1. 选角（cast.json）——读选角指南定音色

先读 `skills/shared/references/voice-casting.md`（音色→人物原型对照 + 同性别区分 + 旁白独立 + 情绪韵律）。
为**每个说话人**定一个符合其性别/年龄/气质/身份的音色，旁白/主讲单列且与所有角色不同：

```bash
python skills/shared/scripts/multivoice.py cast init  --cast <路径>/cast.json
python skills/shared/scripts/multivoice.py cast add   --cast <路径>/cast.json \
    --name 林策 --role male_lead --voice zh-CN-YunxiNeural --rate=-5% --pitch=-3Hz --note "冷峻男主"   # 负值参数用等号
python skills/shared/scripts/multivoice.py cast add   --cast <路径>/cast.json \
    --name 苏晚 --role female_lead --voice zh-CN-XiaoxiaoNeural --note "温婉女主"
python skills/shared/scripts/multivoice.py cast check --cast <路径>/cast.json    # 校验：音色有效/旁白独立/无撞音色
```
> cast.json 也可直接写（就是 JSON）。想让某角色**像真人有情绪**（治 AI 平读）→ 该角色用云 provider：
> ```bash
> python skills/shared/scripts/multivoice.py cast add --cast <路径>/cast.json \
>     --name 霸总 --role male_lead --engine clone --provider minimax --voice-id <你的音色id> --note "克隆/表现力音色"
> ```
> 需在 `.env` 配对应 provider 的 key（`voice_clone.py check --provider minimax`）；缺 key 该角色**自动回退 edge**（平）并告警。

### 2. 逐行对白（lines.json）

把脚本 / 对话稿拆成有序逐行：
```json
{"lines":[
  {"speaker":"主讲","text":"这篇论文解决了一个关键问题。","emotion":"平"},
  {"speaker":"提问","text":"等等，为什么现有方法不行？","emotion":"惊"},
  {"speaker":"主讲","text":"因为它们忽略了时序依赖。","emotion":"坚定"}
]}
```
speaker 必须与 cast 里的名字一致（不一致会回退旁白音色并告警）；emotion 可选。

### 3. 合成多声线音轨 + 字幕

```bash
python skills/shared/scripts/multivoice.py dub \
    --cast <路径>/cast.json --lines <路径>/lines.json -o <路径>/voice.mp3
```
产出 `voice.mp3`（每角色独立声线、情绪自动调韵律）+ `voice.srt`（带角色名，时序按逐行实测时长对齐）。
`dub` 会打印**用了几种声线**——确认 ≥2 种（多人对话不该只有一个声音）。

### 4. 用到视频里

- `voice.mp3` 作 narration + `voice.srt` 作字幕，喂 `auto-short-video/scripts/assemble.py`（图/视频合成）。
- 或与 BGM 混音（**audio-mix**）、加进已有视频（**video-editing**）。

## 降级

- 缺外网/edge-tts 不通 → 无法合成，如实告知（多声线依赖 edge-tts）。
- cast 指定克隆音色但缺 key/失败 → 该角色**自动回退 edge 免费音色**并告警，不阻断。
- 说话人不在 cast → 回退旁白音色并告警（建议补进 cast）。

## Profile 感知

- **有 Profile**：`style.md` 融进音色气质选择（角色气质→音色）；`preferences.md` 红线过滤台词。
- **无 Profile**：按 voice-casting.md 默认对照选音色。

## 规则

1. **多人对话必须多声线**：每个说话人独立音色、旁白/主讲单列——绝不允许全程一个声音（`cast check` + `dub` 声线数把关）。
2. **要像人就上云 provider**：edge 只配草稿；成品/关键角色用 `engine=clone`+provider（有真情感通道），无需 GPU。
3. **音色贴人物**：按 voice-casting.md 的原型对照 + 同性别用 pitch/rate 区分。
4. **情绪标注要具体**：lines 每行标 emotion（愤怒/崩溃大哭/冷笑/温柔…），会喂进 provider 情感通道驱动演绎。
5. **确定性留档**：cast.json / lines.json 落文件，改台词/换音色重跑 `dub` 即可，不必重来。

## 参考来源

见 `EASEL-META.md`。多声线配音（cast + 逐行 lines + 按角色音色逐行合成 + ffmpeg 拼接 + 说话人字幕）为 Easel 自研；
底层封装 edge-tts（tts.py）与云端克隆（voice_clone.py）。
