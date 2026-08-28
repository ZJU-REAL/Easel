---
name: short-drama
description: >
  制作多集 AI 微短剧：建立剧集圣经和角色参考，完成分集剧本、逐镜 I2V、对白审计、配音字幕 BGM 与成片，保持跨镜跨集一致性。
  当用户说“AI/横屏/竖屏/微短剧、拍短剧、分集剧本、连续剧情视频、做几集短剧”时使用。
  单条非剧情视频用 auto-short-video；只写单条脚本用 video-script；只生成一个视频片段用 ai-video-gen。
layer: produce
---

# AI 短剧制作（横屏/竖屏微短剧，多集）
> **配置检查路径铁律**：整条流水线开始前先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认 `.env` 与 `skills/shared/scripts/` 存在。生图、视频、配音配置必须从这里运行注册表/`check`；不得在 OpenClaw workspace 使用 `./shared/scripts/...`，不得用 `env` / `printenv` 判定缺少 `IMG_BASE_URL`、`VOICE_BASE_URL` 或 Key。发现缺项先核对 `pwd`，回项目根并显式传 `--env-file .env` 重查。
## ⛔ 三条铁律（最容易翻车，动手前先记死）

1. **每镜必须「图生视频」成动态片段——绝不能拿静态图冒充。** 关键帧图(frame)只是 I2V 的**首帧**，必须再用 **ai-video-gen `image2video`** 驱动成会动的 `clip`。跳过这步 = 一堆静态图配音，垃圾。合成前 `storyboard` 会**硬拦**只有 frame 没 clip 的镜头。
2. **配音必须闭源云 provider（有情感、像真人）——绝不用 edge(AI 味平读)。** 先 `.env` 配 `VOICE_PROVIDER` + `voice_clone.py check` 验 key；配了 key 后 `dubbing align/dub` **合成前就硬拦** edge，任何角色（含旁白）想落到 edge 直接失败。只有完全没 key 才 `--allow-edge` 兜底。
3. **原生音频优先、环境音每镜必留、台词务必喂给模型。** 视频模型原生音频（环境音/脚步/物理音效）质量好，**环境音默认整轨全用**。**头号要点：生视频必须把台词写进 `generation_prompt`（`prepare` 生成）喂给模型**，否则模型不知说啥、台词全错。默认 **native-first**（让模型逐字说、能说就用、不默认丢 TTS）→ `audit` 逐镜 ASR 核验：对上用原生对白（常态）、说错转 `dub` 换 TTS、旁白/动作镜走 TTS/环境音。决策与探针细节见步骤 16/18 及 `references/native-audio-workflow.md`。
4. **画面/声音/字幕按时间线对齐，自然播放。** 画面用真实片段全长（台词只占其中一段，按实际说话时间放置），**绝不慢放/循环/冻结**；片段盖不住台词就重生成/拆镜（`align` 硬拦）。

> **⚠️ 不许抄近路（执行纪律，最常翻车）**：`prepare → drama_ops.py generate(生视频) → audit → align` 是**不可跳的链**，脚本已加**链式硬门**：① 生视频**必须走 `drama_ops.py generate`**（它逐镜读 `generation_prompt` 自己调视频模型，agent 无从传成只有画面的 prompt）——别再逐镜手调 ai-video-gen；② `generate`/`audit` 见有台词的镜缺 `generation_prompt` → 判定「没跑 prepare」直接失败；③ `align` 见缺 `clip-audit.json` → 判定「没跑 audit」直接失败（不再静默把全部对白降级成 TTS）。「手调生视频只传画面 prompt + 直接 TTS」这条错误捷径会被拦回来——才有「台词喂给模型 + 用视频原声」。

> 编排层 SKILL：创意（圣经/剧本/分镜/lines）你 LLM 写，生成动作全委派已有 SKILL（ai-image-gen/ai-video-gen/ai-music），确定性 IO 走 `scripts/drama_ops.py` + `scripts/dubbing.py`；角色一致性靠「先定参考图再 I2V」+ 剧集圣经锁成同一部剧。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 题材/梗概 | 是 | 一句话剧情或改编源（没给就问） |
| 集数 | 否 | 由题材/需求定，**不强制**（微短剧常 10–30 集只是常见值；起号测试可先 1–3 集验证链路） |
| 单集时长 | 否 | **不强制固定分钟数**——由题材/平台/剧情节奏定，几十秒到数分钟皆可；成片总时长 = 各镜片段时长之和（脚本不设上限，用户说多长就多长） |
| 画幅 | 是 | 用户或上游任务未明确横版/竖版（或 16:9/9:16/具体分辨率）时，制作前必须追问并等确认；不得按平台、Profile 或默认值静默推断，已明确则不重复问 |
| 视觉风格 | 否 | 都市港风/古装/校园/悬疑…（定统一风格前缀）|

## 产物结构（`outputs/剧名/`）

```
series-bible.md         剧集圣经（戏剧承诺+角色表【行动模型+want/need/wound/flaw+可跟随四问+音色档案】+剧情线+情绪曲线/爽点节奏+反派阶梯+分集反转+钩子+风格前缀）
cast.json               选角表（角色→音色：edge 音色 + pitch/rate，或克隆音色）
ref_index.json          参考图索引（C 角色 / S 场景 / P 道具，跨镜跨集复用）
refs/                   参考图（C01_林策.png ...）
episodes/ep01/
  script.md             本集剧本（因果节拍四幕 + 对白 + 集末钩子）
  lines.json            本集逐行对白（{speaker,text,emotion,shot,at?}，shot=所属镜头、at=镜内起始秒/对齐说话时刻，喂时间线配音）
  shots.json            本集分镜（逐镜：时间轴 prompt + @参考 + 尾帧描述 + 可选 sfx[定时音效]；align 回写每镜 duration）
  shots/                逐镜关键帧图 + 生成的片段
  voice.mp3 / voice.srt 多角色配音（每角色独立声线、镜对齐）+ 同轴字幕
  timing.json           逐镜时长 + 逐行起止（align 产出，留档/校验）
  clip-audit.json       原生音轨、ASR、语言、说话时间与 native/dub/regenerate 决策
  final.mp4             本集成片
progress.json           逐集/逐镜生成进度（控费、断点续跑）
```

脚本（相对项目根）：`skills/openclaw/short-drama/scripts/drama_ops.py`（资产/分镜/进度）、
`skills/openclaw/short-drama/scripts/dubbing.py`（多角色配音）；
合成器复用：`skills/openclaw/auto-short-video/scripts/assemble.py`。

## 执行步骤

> ⚠️ 生图/生视频/配音是**异步 + 按量计费**。**先出 Plan**（几集、每集几镜、调哪些付费 API、
> 大致耗时/花费），确认后再跑。起号测试建议先跑 **1 集** 验证全链路再放量。

### 0. 剧集策划（新脑子，必做）

1. **选题材 + 定爽点**：先读 `references/genre-hooks-handbook.md` 选一个主题材（逆袭/战神/重生复仇/甜宠/马甲…）+ 其核心爽点，避免「剧情太简单/太散」。
2. **搭骨架**：`python skills/openclaw/short-drama/scripts/drama_ops.py scaffold --series "<剧名>"`。
3. **过故事引擎**（治「剧情简单/人物扁平」，写 bible 前必做）：读 `references/story-engine.md`——
   - 写**戏剧承诺**一句话并过其自检（主体/追求/昂贵阻力/反复回报，换名不失独特、阻力有筹码、主角有能动性、中段有回报）；
   - 每个主要角色建 **8 字段行动模型 + want/need/wound/flaw/弧光 + 可跟随四问（ep1 可见其一）**；
   - 反派按 `references/satisfaction-and-villain.md` 排 **4 层阶梯**（治工具人/爽点通胀）。
4. 写 `series-bible.md`（读 `references/series-bible-schema.md`，已含上述深度字段）：一句话卖点、**戏剧承诺**、世界观、**角色表（行动模型+深度）**、剧情主线、**情绪曲线 + 爽点节奏表 + 反派阶梯**、**分集大纲（每集：剧情 + 因果反转点 + 集末悬念）**、**统一视觉风格前缀**。
5. **过 A/B 门**：按 `references/drama-review-rubric.md` 的 A（故事引擎门）+ B（人物可跟随门）逐项**引证自评**，任一 ⛔ 硬伤必修再往下。

### 1. 分集剧本（因果节拍 + 台词功底，别写流水账）

6. 每集读 `references/four-act-drama.md`、`references/causal-beats.md`、`references/vertical-pacing.md` 和 **`references/dialogue-craft.md`**，按**因果节拍**写 `episodes/epNN/script.md`：
   目标(3秒钩)→阻碍→转折(爽/虐爆点)→集末钩子，相邻节拍用「因为/所以」串；**爽点密度**每 15–30s 一个情绪事件。
   - **反转按因果生成**：每个反转过 `genre-hooks-handbook.md` 的「因果反转一句话测试」+ 公平揭示 5 问，填不出=空降反转，重做。
   - **台词按 `dialogue-craft.md`**：禁直给/禁全员一个腔（过 swap-test）/曝光转冲突/每人有想要+想藏/每集 ≥1 金句/单行 ≤15 字。
   - **每句台词必须标清说话人**：剧本里对白一律写成 **`角色名：台词`**（角色名用 cast/bible 里的准确名字，别用「他/她/众人」）——后续抽 lines.json 时 speaker 直接照抄，避免配音配错角色。
7. **写完过 C/D/E 门**：按 `references/drama-review-rubric.md` 的 C（反转揭示）+ D（节奏）+ E（台词）逐项**引具体节拍/台词**自评，任一 ⛔ 硬伤（无 ep1 钩/腔调雷同/空降反转）必修，别凑合。

### 2. 角色 / 场景定妆（一致性地基）

8. 用 **ai-image-gen** 为每个角色生成**定妆参考图**（正面/多角度，喂角色外貌关键词 + 统一风格前缀）；关键场景/道具同理。
9. 逐个登记进索引（自动分配 C/S/P 编号）：
   ```bash
   python skills/openclaw/short-drama/scripts/drama_ops.py ref add --series "<剧名>" \
     --kind character --name 林策 --image refs/C01_林策.png --desc "男主，冷峻西装" --style "都市港风"
   ```
   读 `references/character-consistency.md` 了解为什么必须先定参考图。
9.5 **⛔ 定妆图必须肉眼复核（做完图绝不跳过）**：用图片工具**逐张看每个角色定妆图**，确认发型/年龄/服装/气质**符合角色设定**，逐个记录：
   ```bash
   python skills/openclaw/short-drama/scripts/drama_ops.py ref review --series "<剧名>" \
     --code C01 --observation "看到：冷峻短发西装男，符合男主设定"
   ```
   形象跑偏（如男主长成大叔、萝莉长成成年）→ 重生成定妆图再复核，**别拿跑偏形象往下生视频**（跨镜长相全崩）。角色定妆图没复核，后面 `generate` 会**硬拦**。

### 2.5 选角（角色→音色，多声线关键，**闭源优先 + 音色贴角色**）

10. 读 `skills/shared/references/voice-casting.md`。**音色由角色的真实定妆参考图形象决定**——先看 §2 生成出来的定妆图长什么样，按 voice-casting.md〇.6「形象原型 → 音色速查」对号入座：图里是**萝莉就配萝莉音（女童声/高而快）**、御姐配成熟音、大叔配低沉老成音、霸总配浑厚音…**绝不能形象与音色错位**（女主配大妈音、小孩配成年音 = 出戏）。**每个角色用 `--archetype` 写形象原型、`--ref` 绑定其定妆图 C 编号**（`cast check` 会核对：ref_index 里每个有定妆图的角色都必须被配音，漏配直接拦）。旁白单列且与所有角色不同。
   - **闭源强制优先（铁律②，含旁白/普通配音）**：先 `.env` 配 `VOICE_PROVIDER` + `python skills/shared/scripts/voice_clone.py check --provider <..> --env-file .env` **验 key 能用**；`cast init` 旁白与 `cast add` 都默认 `clone` 并自动取 `VOICE_PROVIDER`。**配了 key 后：`cast check` 拦静态配置里的 edge，`align/dub` 合成前再拦一道**——任何角色（含旁白）想落到 edge 直接失败（clone 缺 voice_id / clone 调用失败都算），逼你修好闭源再出片。只有完全没 key 才 `--allow-edge` 兜底。预置音色见 voice-casting.md〇.5。
   ```bash
   python skills/openclaw/short-drama/scripts/dubbing.py cast init --series "<剧名>"   # 建模板（旁白默认闭源）
   # 按角色定妆图形象挑贴合的闭源预置音色，并标注 archetype/ref
   python skills/openclaw/short-drama/scripts/dubbing.py cast add --series "剧名" --name 林策 --role male_lead \
     --engine clone --provider openai-compatible --voice-id FunAudioLLM/CosyVoice2-0.5B:benjamin \
     --archetype "冷峻男主" --ref C01 --note "低沉磁性，贴 C01 定妆图"
   python skills/openclaw/short-drama/scripts/dubbing.py cast add --series "剧名" --name 朵朵 --role child \
     --engine clone --provider openai-compatible --voice-id FunAudioLLM/CosyVoice2-0.5B:bella \
     --pitch=+6Hz --rate=+5% --archetype "萝莉/小女孩" --ref C03 --note "童声,贴 C03 幼态定妆图"
   python skills/openclaw/short-drama/scripts/dubbing.py cast check --series "剧名"
   ```
   需要**专属克隆嗓音**（非预置）→ `--provider minimax/dashscope` + 先 `voice_clone.py enroll` 拿 `--voice-id`。
   完全没配任何闭源 key 时才回退 edge（`cast check` 出 💡 提醒升级）。分层与配置见 voice-casting.md〇 与 `multi-voice-dubbing` SKILL。

### 3. 分镜脚本 + 逐行对白 + **时长规划**（自然的关键：先定好每镜停留多久，再去生视频）

11. 按本集时长与节奏**拆镜**（镜数不强制——时长短几个镜、时长长就多几个镜，跟着剧情走），写 `episodes/epNN/shots.json`（格式见 `references/shot-prompt-format.md`）：
   每镜含 `idx / desc / prompt(风格头+逐秒画面节拍+【声音】) / refs(引用 C/S/P) / tail(尾帧描述)`。
12. **同时抽本集逐行对白 `episodes/epNN/lines.json`**（有序 `[{speaker, text, emotion, shot}]`；字段规则见步骤 17）——**在生视频之前就写好**，因为每镜停留多久由它的台词决定。
13. **规划每镜时长 + 检查能否塞进片段**（治「画面停住/太赶」的根本）：
   ```bash
   python skills/openclaw/short-drama/scripts/dubbing.py plan --series "<剧名>" --episode N
   ```
   ⚠️ **现实约束：AI 视频只能生成固定档位（多为 5s，部分 5/10s），不能按任意秒数出片。** 所以 `plan` 的作用是：① 估出每镜台词时长（= 最终画面应停留的时间，写回 `target_duration`）② **检查每镜台词能否塞进一个片段档**——**塞不下（台词 > ~5s）就拆成多镜或精简台词**（`plan` 会 ⚠️ 标出来），别硬生成再靠后期拉伸 ③ 给出每镜建议生成的片段档位 `gen_duration`（5 或 10）。**把每镜台词控制在一个片段档内，是画面自然的关键。**
14. **校验分镜**：`drama_ops.py shots validate --series "<剧名>" --episode N`（风格前缀/引用参考图/编号已登记/idx 连续）。

### 4. 关键帧生成（只是 I2V 的首帧，不是成片）

15. 用 **ai-image-gen** 按每镜 prompt 生成首帧图（**图生图并引用该镜 refs 的参考图**，保角色一致），落 `episodes/epNN/shots/`，路径写回 shots.json 的 `frame`。⚠️ 到此还只是**静态图**，下一步必须驱动成视频。

### 5. 逐镜生视频（I2V，**铁律①：每镜必做，绝不跳过**）

16. **生成音频契约和 prompt（把台词喂给模型）**：先跑 `model_registry.py configured --group video --env-file .env`；多个可用且用户没点名时先询问，本集选定后全链路锁定。
    ```bash
    python skills/openclaw/short-drama/scripts/dubbing.py prepare --series "<剧名>" --episode N --language zh-CN --provider "$VIDEO_PROVIDER"
    ```
    `prepare` 读 `lines.json` 把台词契约写进每镜 `generation_prompt`：默认 **native-first**（要求模型**逐字说台词**、成片用原生对白）；旁白/纯动作镜不给台词。
    - **一镜可有多句画内对白**：视频模型能连着说，`prepare` 会把该镜多句按时间顺序全写进 `generation_prompt`（各句按 `at` 定位、缺则顺排，累计须塞进片段档）。**不必为「多句」硬拆成一句一镜**——只有旁白与画内对白仍不同镜（避免原生人声与旁白重叠）。
    - **别用 dub 躲避 native-first**：`prepare --dialogue-mode dub`（全剧不给台词、后期全 TTS）**已加硬门**——没有 `ai_video.py probe-dialogue` 实测模型不忠实、也没显式 `--force-dub` 时会被拒绝。撞到多句/一句约束**不是**改 dub 的理由（多句直接一起塞进 prompt）。默认让模型试原生、`audit` 只对真说错的镜逐镜换 TTS。
17. **逐镜生视频（脚本驱动，强制把台词喂给模型）**：
    ```bash
    python skills/openclaw/short-drama/scripts/drama_ops.py generate --series "<剧名>" --episode N --ratio "<9:16或16:9>"
    ```
    `prepare` 会把最终 provider/model 锁进 shots.json；`generate` 必须复用，显式传入冲突值会硬拦。它过 prompt 硬门后逐镜调 ai-video-gen（自动带 `--audio auto --ratio <已确认画幅> --duration gen_duration`），clip 写回并记进度；已有 clip 自动跳过，`--dry-run` 看计划、`--only 1,3` 单镜重生、`--force` 强制重生。
    - **片段档必须 ≥ 该镜台词时长**（步骤 13 `plan` 已选档、超长镜已拆）：画面时长由真实片段主导，成片只做**自然裁剪**，绝不慢放/循环/冻结。片段比台词还短 → `align` 硬失败，重生成/拆镜。
    - 跨镜/跨集连贯用 `references/character-consistency.md`「尾帧→下一镜首帧」（`--only` 单镜重生成时把上一镜尾帧填进该镜 frame）。

### 6. 多角色配音 + 字幕 + 音效 + BGM（时间线对齐）

> lines.json 已在步骤 12 写好；这里做实际配音并**按时间线对齐**。
> **核心模型（时间线/轨道式）**：每镜 = 一条完整片段的时间线，**台词只占其中一段**，其余时间是
> 动作/停顿/音效——**片段时长通常 > 台词总长**。配音不是把台词首尾相接填满片段，而是把每行
> **按 `at` 偏移**放到片段时间线上（对齐说话/嘴动时刻），空白留给动作与音效。

18. **审计每个生成片段的原生音轨**（环境音优先，决策见 `references/native-audio-workflow.md`）：
    ```bash
    python skills/openclaw/short-drama/scripts/dubbing.py audit --series "<剧名>" --episode N
    ```
    输出 `clip-audit.json`，逐镜决策 `native / dub / regenerate`：`native`＝有对白（**可多句**）+语言对+整段 ASR 相似度≥阈值（默认 0.6）或纯动作镜无意外语音 → 整轨原音直通+字幕不配音；`dub`＝人声真坏了（语言/内容不符）或完全无原音 → 换 TTS，**该镜原生轨丢弃**（无人声分离时保留会与配音重复）；`regenerate`＝片段缺失/ASR 读不出/动作镜意外语音 → 带反馈重生成、拿到好原声转 `native`（优先，既用模型原声又保环境音），最多两次。语言正确为强制前置门；阈值用 `--threshold` 调；嘴型/人物明显不符时视觉复核重生成。
19. **逐行对白 `lines.json` 字段规则**（步骤 12 写、此处复核）——有序 `[{speaker, text, emotion, shot, at?}]`：
    - `speaker` **必须精确等于 cast.json 里的角色名**（照抄剧本「角色名：」，别写「他/她」泛称）——`align` 会严格校验，speaker 不在 cast 直接拦截报错（**治「配音配错角色」**），不再静默用旁白音色顶替。
    - `emotion` 是给配音引擎的**情感通道**（不是让角色把情绪念出来），写具体：愤怒/冷笑/隐忍/崩溃大哭/颤抖/惊恐/得意/温柔/失望/嘲讽/急切/沉痛/撒娇 等——闭源云 provider 转成「用<情绪>的语气说」驱动演绎。**⚠️ 音色不随情绪改变**：`emotion` 只调语调/语速/情感（`emotion_prosody` 叠加 rate/pitch/volume 增量），角色音色身份始终是 cast.json 里绑定的那一个 `voice_id`——同一角色跨镜跨集音色恒定，只有情绪语调在变。
    - **`shot` = 这句台词所属的镜头 idx（必填）**：让每句配音/字幕落到对应画面片段上；一镜可多句；纯动作镜无台词就不出现在 lines 里。
    - **`at` = 这句台词在**本镜片段内**的起始秒（可选，秒）**：对齐画面里角色**开始说话/嘴动**的时刻（如角色前 1.5s 在走动、之后才开口 → `at: 1.5`）。不写则从头顺序排。**这是「说话时刻对得上画面」的关键**；台词之间的空白就是动作/停顿/音效的时间。
20. **时间线对齐配音**（必须在每镜生成并审计后运行）：
    ```bash
    python skills/openclaw/short-drama/scripts/dubbing.py align --series "<剧名>" --episode N
    ```
    读 `clip-audit.json` 后，`native` 画内对白**不合成 TTS、直接用模型原声**，原生 ASR 起止时间写入字幕；旁白和 `dub` 对白进入独立配音轨（`dub` 镜原生轨在合成时丢弃、纯 TTS，避免双重人声）。产出 `voice.mp3`、同轴 `voice.srt`、`timing.json`，并把真实片段时长写回 shots.json。
    - **画面时长 = 真实片段时长（铁律③）**：`align` 探测每镜真实 clip 时长作画面时长，台词按 `at` 叠在其上、其余留给动作/停顿/音效——成片就是**片段原样播放、绝不冻结/拉伸/循环**。
    - **时间线硬拦**：有台词镜缺 clip、`at` 为负、同镜台词重叠、或 `at`+真实配音时长超出片段，任一情况均失败；必须重生成、拆镜、精简台词或修正 `at`，禁止让字幕/声音拖到下一镜。
    - lines 没标 `shot` 或 speaker 配错 → `align` 拦截/告警，按提示修 lines.json 重跑。
21. **音效 + BGM**（占用非台词时间，让画面有声音层次）：
    - **音效**（枪声/椅子移动/脚步/开门/耳光…）：在 `shots.json` 该镜加 `sfx` 数组 `[{"file": "sfx/gun.wav", "at": 1.2, "volume": 0.9}]`（`at`=**镜内**秒）。音效文件可用 **ai-music** 生成短音（或素材库），把路径填进 `file`。`storyboard` 会把镜内 `at` 换算成全局时间、`assemble` 定点叠进成片音轨。
    - **BGM**：**ai-music** 按剧情氛围生成（紧张/甜/悬疑），落 `episodes/epNN/bgm.mp3`（assemble 混音时自动对旁白闪避压低）。
    （字幕已由 `align` 产出 `voice.srt`，无需再单独跑 auto-subtitle。）

### 7. 逐集合成 + 交付

22. 把本集分镜转成合成输入并合成。`storyboard` 自动读取审计结果：`native` 镜**整轨原音（模型原声+环境音）直通**；`dub` 镜原生轨**丢弃、改用独立 TTS 配音**（无人声分离时保留会与配音双重人声）；完全无原音的镜补等长静音；侧链闪避仅让旁白/配音干净盖在 native 镜环境音上；合成器统一 AAC 48 kHz stereo 后拼接：
    ```bash
    python skills/openclaw/short-drama/scripts/drama_ops.py storyboard --series "<剧名>" --episode N --size "<1080x1920或1920x1080>" \
      -o episodes/epNN/storyboard.json --narration episodes/epNN/voice.mp3 --bgm episodes/epNN/bgm.mp3 --subtitle episodes/epNN/voice.srt
    python skills/openclaw/auto-short-video/scripts/assemble.py assemble \
      --storyboard episodes/epNN/storyboard.json -o episodes/epNN/final.mp4
    ```
    字幕由 assemble 自动烧成**底部居中、字号合适**的样式（默认按分辨率，可用 `--sub-size/--sub-margin-v/--sub-font` 微调）。
23. 每集结尾可加「下集预告/钩子卡」提升追剧。**成片后过 `references/drama-review-rubric.md`「配音/选角」「成片」评审**（尤其确认**不是全剧一个声音**、声线贴人物、**字幕/配音与画面对齐**）。多集每集重复步骤 6–22（剧本→分镜→生视频→配音→合成）；用 `progress show` 看整部进度。
24. **发布**：按已确认画幅/平台交对应发布层 SKILL（如竖屏抖音/快手，横屏 B站）。

## 编排原则（承 auto-short-video）

- **降级是例外、不是默认**（对齐三条铁律）：视频每镜必做 I2V、配音默认硬拦 edge，成片默认硬拦静态图；只有用户明确要静态图短剧才 `storyboard --allow-static`、完全没闭源 key 才 `--allow-edge`；任何降级都**如实、显式告知**用户降了什么、为什么。**中间产物留档+断点续跑**：参考图/分镜/片段/进度都落文件，某镜不满意可单独重生成，progress 防重复烧钱。

## Profile 感知

- **有 Profile**：`platforms.md` 只用于给出画幅建议，仍须用户确认；`style.md` 融进统一视觉风格前缀与配色；`identity.md` 定题材调性；`preferences.md` 红线过滤（暴力/软色情/价值观）。
- **无 Profile**：先问横版/竖版、题材/集数/单集时长与风格偏好；**时长不预设固定值**（用户不指定就按题材节奏定，别硬套某个分钟数）。

> 开源方法论溯源见 `EASEL-META.md`。
