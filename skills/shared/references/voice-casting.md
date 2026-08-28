# 配音选角（voice casting）——让每个角色有自己的声线

> 跨 SKILL 共享的选角指南（短剧、论文双人问答、访谈、有声剧…都用）。治「配音永远只有一个声音」+「像 AI 平读」。
> 每个说话人用**符合其性别/年龄/气质/身份**的音色，**音色必须贴合该角色的定妆参考图与性格设定**
> （冷峻男主→低沉磁性、元气少女→清亮跳脱、霸总→浑厚压迫、老者→苍老缓慢…）；旁白单独一个音色。
> 选角落 `cast.json`，配音走 `skills/shared/scripts/multivoice.py`（引擎）或 multi-voice-dubbing SKILL。
> **【闭源优先】主要角色一律用闭源云 provider（有情感、像真人）；edge-tts 仅作无 key 兜底 / 群众演员。**

## 〇、引擎分层：闭源云 provider（首选·有情感·像人）vs edge（兜底·平·机器味）

**成品级配音必须用有情感通道的闭源云 provider**（用户自备 key，**无需 GPU**）。edge-tts 没有情感引擎——只能变速变调、语气平、机器感，是「配音像 AI」的根因，**只在没配 key 时兜底或给一句话的群演用**。

| cast `engine` | 质量 | 需要 | 情感机制 |
|---|---|---|---|
| `clone`+`openai-compatible` → **SiliconFlow CosyVoice2**（**首选·推荐**）| **好、中文自然、有情感** | VOICE_API_KEY（硅基流动，便宜/新用户赠额，**无需 GPU**）| 内联 `<|endofprompt|>` 指令 |
| `clone`+`minimax` | 好、有情绪、可克隆 | MINIMAX_API_KEY | emotion 枚举（自动映射中文情绪词）|
| `clone`+`dashscope`（CosyVoice）| 好、中文自然 | DASHSCOPE_API_KEY | 「用<情绪>的语气说」指令 |
| `clone`+`gemini` | 好、真免费 | GEMINI_API_KEY（Google AI Studio 免费层）| 自然语言前缀（国内需代理）|
| `edge`（**仅兜底**）| 平、机器感，仅草稿/群演 | 无 key、外网 | 只有 rate/pitch/volume 微调 |

**配置示例（二选一，落 `.env`；配好后 `dubbing.py cast add --engine clone` 不写 provider 会自动取 `VOICE_PROVIDER`）**：
```bash
# A) SiliconFlow 云端 CosyVoice2（首选，无需 GPU）
VOICE_PROVIDER=openai-compatible
VOICE_BASE_URL=https://api.siliconflow.cn/v1
VOICE_API_KEY=<你的key>
VOICE_MODEL=FunAudioLLM/CosyVoice2-0.5B
VOICE_INSTRUCT_MODE=inline      # ⚠️ CosyVoice2/SiliconFlow 必设：情感指令用 <|endofprompt|> 内联进文本；
                                #    不设会走默认 field 模式(独立 instructions 字段)，被 CosyVoice2 忽略 → 情绪失效、平读
# 注：CosyVoice2-0.5B 是小模型，旁白/长句仍偏"AI 味"；要更自然的旁白配 minimax(最像真人)/dashscope CosyVoice 大模型
# 注：inline 模式下 0.5B 偶尔"吃不干净"分隔符前的情感指令 → 把指令念成杂音（已把指令收成最短「用X的语气说」缓解）；仍频繁出杂音就换 minimax/dashscope 或去掉逐行 emotion
#   cast add 时 --engine clone --provider openai-compatible --voice-id FunAudioLLM/CosyVoice2-0.5B:alex
# A2) SiliconFlow 云端 MOSS-TTSD-v0.5（另一可选，同一 openai-compatible 通道）
#   VOICE_MODEL=fnlp/MOSS-TTSD-v0.5   —— 预置音色 alex/anna… 通用
#   ⚠️ MOSS 必须 VOICE_INSTRUCT_MODE=field，不能 inline（inline 的 <|endofprompt|> 会被念成杂音）
# B) Gemini 免费层
VOICE_PROVIDER=gemini
GEMINI_API_KEY=<你的免费key>     #   --voice-id Kore（30 音色）
```

- `lines.json` 每行的 `emotion`（愤怒/崩溃大哭/冷笑/温柔…）→ 引擎按 provider 自动转成情感参数驱动演绎；写具体越贴戏越好。
- 缺对应 key → 该角色自动回退 edge（平）并告警。`voice_clone.py check --provider <名>` 离线校验 key。

## 〇.5、闭源预置音色 → 人物原型（按角色「图片 + 性格」挑）

**先按角色定妆参考图 + 性格档案挑一个贴合的闭源音色**（性别/年龄/气质/身份对上），在 cast 的 `note` 里写清「为何选它」。预置音色无需 enroll，直接当 `--voice-id` 用：

| provider | 预置音色（`--voice-id`）| 适配人物原型 |
|---|---|---|
| openai-compatible（CosyVoice2）| `FunAudioLLM/CosyVoice2-0.5B:alex` | 男声沉稳 → 冷峻男主 / 霸总 / 旁白 |
| openai-compatible（CosyVoice2）| `FunAudioLLM/CosyVoice2-0.5B:benjamin` | 男声磁性 → 深情男主 / 熟男 |
| openai-compatible（CosyVoice2）| `FunAudioLLM/CosyVoice2-0.5B:anna` | 女声温婉 → 温柔女主 / 治愈系 |
| openai-compatible（CosyVoice2）| `FunAudioLLM/CosyVoice2-0.5B:bella` | 女声清亮活泼 → 元气少女 / 妹妹 / 闺蜜 |
| gemini | `Kore` / `Puck` / `Charon` … | 30 音色，男女多气质（查 provider 文档挑贴合的）|
| minimax / dashscope | enroll 得到的 `voice_id` | 需要**专属克隆音色**时（上传样本 → voice_id）|

> CosyVoice2 预置音色名以 provider 实际支持为准（`alex/anna/...` 为常见预置）；不确定就先用 `alex`（男）/`anna`（女）打样，再按听感换。**同性别多角色**先换不同预置音色，换不开再叠 pitch/rate（见二）。

## 〇.6 形象原型 → 音色 速查（**先看定妆图长什么样，再挑音色**）

**铁律：音色必须与画面里的人物形象一致**——图里是萝莉就配萝莉音，是大叔就配大叔音，绝不能反过来（女主配成大妈音、小孩配成成年音 = 出戏）。按角色定妆图的**年龄段 + 性别 + 气质**对号入座：

| 形象原型（看图判断）| 闭源云 provider 首选 | edge 兜底 | 额外微调 |
|---|---|---|---|
| **萝莉 / 小女孩**（幼态、大眼、童颜）| CosyVoice2 女声预置 + `--pitch=+6Hz --rate=+5%`；或 gemini 童声系 | `zh-CN-XiaoshuangNeural`（女童声）| 童声不够就再 `+pitch` |
| **正太 / 小男孩** | CosyVoice2 男声预置 + `--pitch=+6Hz` | `zh-CN-YunxiaNeural`（男童）| |
| **少女 / 元气女主**（青春、活泼）| CosyVoice2 `bella`（清亮）| `zh-CN-XiaoyiNeural`（活泼年轻）| |
| **温婉女主 / 治愈系** | CosyVoice2 `anna`（温婉）| `zh-CN-XiaoxiaoNeural`（温暖）| |
| **御姐 / 女总裁**（成熟、气场）| CosyVoice2 女声 + `--pitch=-3Hz --rate=-5%` | `zh-CN-XiaoxiaoNeural` + `--pitch=-4Hz` | 压低放慢显成熟 |
| **冷峻男主 / 都市精英** | CosyVoice2 `alex`（沉稳）| `zh-CN-YunxiNeural`（清朗）| |
| **霸总 / 反派大佬 / 硬汉** | CosyVoice2 男声 + `--pitch=-3Hz` | `zh-CN-YunjianNeural`（浑厚）| 浑厚压迫 |
| **深情男主 / 熟男** | CosyVoice2 `benjamin`（磁性）| `zh-CN-YunxiNeural` + `--pitch=-2Hz` | |
| **大叔 / 长辈 / 上司** | CosyVoice2 男声 + `--pitch=-4Hz --rate=-8%` | `zh-CN-YunyangNeural`（沉稳）| 老成放慢 |
| **老人**（苍老）| CosyVoice2 + `--pitch=-5Hz --rate=-12%` | `zh-CN-YunyangNeural` + 同微调 | |
| **旁白 / 画外音** | CosyVoice2 `alex`（沉稳中性）| `zh-CN-YunyangNeural` | 与所有角色区分 |

> 闭源预置音色本身没有"童声/老人"细分时，用 **pitch/rate 往目标年龄推**（幼→高而快、老→低而慢）；差距实在大（如必须真萝莉音）就用 edge 童声兜底或 enroll 一个贴合的克隆音色。**挑完在 cast 的 note 里写「贴 C0X 定妆图·<原型>」**，便于回看核对。

## 一、edge-tts 中文音色 → 人物原型对照（**仅无 key 兜底 / 群众演员**）

> 没配任何闭源 key 时的免费兜底；成品配音请优先用上面的闭源 provider。

| 音色名 | 声音特征 | 适配人物原型 |
|---|---|---|
| `zh-CN-YunxiNeural` 云希 | 男声，清朗自然、偏年轻 | 冷峻男主 / 都市精英 / 少年感男主 / 讲解者 |
| `zh-CN-YunyangNeural` 云扬 | 男声，专业沉稳、播报感 | **旁白/主讲首选** / 沉稳大叔 / 上司 / 长辈 |
| `zh-CN-YunjianNeural` 云健 | 男声，浑厚有力 | 霸总 / 反派大佬 / 战神 / 硬汉 |
| `zh-CN-XiaoxiaoNeural` 晓晓 | 女声，温暖亲和 | 温婉女主 / 治愈系 / 妻子 / 主持人 |
| `zh-CN-XiaoyiNeural` 晓伊 | 女声，活泼年轻 | 元气少女 / 妹妹 / 闺蜜 / 学生 / 提问者 |
| `zh-CN-XiaoshuangNeural` 晓双 | **女童声**，稚嫩 | **萝莉 / 小女孩 / 妹妹（幼态）** |
| `zh-CN-YunxiaNeural` 云夏 | 男童声，可爱 | 正太 / 小男孩 / 弟弟 |
| `zh-CN-liaoning-XiaobeiNeural` 晓北 | 女声，东北口音 | 泼辣 / 喜感 / 市井大姐 |
| `zh-CN-shaanxi-XiaoniNeural` 晓妮 | 女声，陕西口音 | 方言喜感 / 乡土角色 |
| `zh-TW-HsiaoChenNeural` 曉臻 | 台湾女声 | 台系甜妹 / 温软女配 |
| `zh-TW-YunJheNeural` 雲哲 | 台湾男声 | 台系男角 / 温和男配 |
| `zh-HK-HiuMaanNeural` 曉曼 | 香港女声（粤） | 港味女角 |
| `zh-HK-WanLungNeural` 雲龍 | 香港男声（粤） | 港味男角 / 港片大佬 |

> 完整列表：`python skills/shared/scripts/tts.py voices`（`--all` 看全量）。

## 二、同性别多角色怎么区分（关键）

中文 edge 音色有限，一部剧常有多个男/多个女。**先换音色，换不开再用 pitch/rate 拉开距离**：

- **男主 vs 男反派**：男主 `云希`（清朗）+ 反派 `云健`（浑厚）已天然区分；若都用云希，反派 `--pitch=-4Hz --rate=-5%`。
- **女主 vs 女配**：女主 `晓晓`（温婉）+ 闺蜜 `晓伊`（活泼）区分；不够再 pitch ±3~5Hz。
- **年龄**：偏老 → `--pitch=-3Hz --rate=-8%`；偏小 → `--pitch=+4Hz --rate=+5%`。
- **气质**：冷 → 慢+低（`--rate=-5% --pitch=-2Hz`）；急/爆 → 快+响。
- pitch 建议 **±6Hz** 内、rate **±15%** 内，过了会失真。

## 三、旁白/主讲规则（硬性）

- 旁白/主讲**必须单列一个音色**，且**与所有出场角色的音色都不同**（`cast check` 会拦）。
- 默认旁白用 `云扬`（沉稳播报感）；若某角色已占云扬，旁白换 `云希` 或反过来。
- **论文双人问答**：主讲=`云扬`（沉稳权威）、提问者=`晓伊`（活泼好奇），一问一答更抓耳。
- 旁白语气中性，一般不加情绪韵律。

## 四、情绪 → 韵律（引擎自动叠加，无需手填）

`lines.json` 每行可带 `emotion`，`dub` 会在角色基础音色上自动叠加增量（clamp 到安全区）：

| emotion 关键词 | rate | pitch | volume | 效果 |
|---|---|---|---|---|
| 怒/愤/吼 | +8% | -1Hz | +15% | 又快又响 |
| 紧张/急/慌 | +12% | +2Hz | +5% | 语速飙升 |
| 悲/哭/难过 | -10% | -2Hz | -5% | 放慢、低沉 |
| 温柔/柔/宠 | -6% | -1Hz | -3% | 放软放慢 |
| 冷/漠/讥/嘲 | -3% | -2Hz | 0 | 平稳压低 |
| 惊/震/愕 | +6% | +4Hz | +10% | 拔高、突兀 |
| 喜/开心/兴奋 | +6% | +3Hz | +5% | 上扬轻快 |
| 坚定/决/郑重 | -2% | -1Hz | +5% | 稳而有力 |

## 五、克隆音色（voice-clone，需专属嗓音时）

除了预置音色（见〇.5），贯穿全程的**主角/反派/固定主讲**要一个**专属克隆嗓音**时 → 先
`voice_clone.py enroll --provider <minimax|dashscope> --sample me.mp3` 拿 `voice_id`，cast 里写
`{"engine":"clone","provider":"minimax","voice_id":"xxx", ...}`。**缺 key/克隆失败自动回退 edge 并告警**，不阻断。

## 六、cast.json / lines.json 落地

**cast.json**（选角，**全员闭源强制**；旁白/普通配音也必须闭源，不用 AI 味 edge）：
```json
{"cast":[
  {"name":"旁白","role":"narrator","engine":"clone","provider":"openai-compatible","voice_id":"FunAudioLLM/CosyVoice2-0.5B:alex","archetype":"旁白/画外音","note":"沉稳画外音"},
  {"name":"林策","role":"male_lead","engine":"clone","provider":"openai-compatible","voice_id":"FunAudioLLM/CosyVoice2-0.5B:benjamin","archetype":"冷峻男主","ref":"C01","note":"低沉磁性，贴定妆图C01"},
  {"name":"朵朵","role":"child","engine":"clone","provider":"openai-compatible","voice_id":"FunAudioLLM/CosyVoice2-0.5B:bella","pitch":"+6Hz","rate":"+5%","archetype":"萝莉/小女孩","ref":"C03","note":"童声，贴C03幼态定妆图"}
]}
```
- **`archetype`**（形象原型）+ **`ref`**（定妆图 C 编号）：**音色由真实定妆图决定**——先看图判断萝莉/御姐/大叔/冷峻男主…，再对号入座选音色，两字段留痕便于核对。
- **强制**：`cast init` 旁白与 `cast add` 默认 `engine=clone`（取环境变量 `VOICE_PROVIDER`）；**配了闭源 key 后 `cast check` 会硬拦任何仍用 edge 的角色（含旁白）**；短剧入口 `cast check` 还会核对 `ref_index` 里每个有定妆图的角色都被配了音（漏配即拦）。edge 只在完全没配 key 时兜底。
**lines.json**（逐行对白，LLM 从脚本抽；**每行标 `shot`= 该句所属镜头 idx，逐镜对齐用**）：
```json
{"lines":[
  {"speaker":"旁白","text":"三年后，他回来了。","emotion":"平静","shot":1},
  {"speaker":"林策","text":"你以为你赢了？","emotion":"冷笑","shot":2}
]}
```
> `shot` 让配音/字幕与画面片段逐镜对齐（画面时长=该镜台词时长）；不标则退回旧均分、画面/字幕会对不齐。

**通用入口**（任意工作流，显式路径）：
```bash
python skills/shared/scripts/multivoice.py cast init  --cast cast.json
python .../multivoice.py cast add   --cast cast.json --name 林策 --engine clone --provider openai-compatible --voice-id FunAudioLLM/CosyVoice2-0.5B:benjamin --note "冷峻男主"
python .../multivoice.py cast check --cast cast.json    # 通过后会 💡 建议把仍用 edge 的说话角色升级闭源
python .../multivoice.py dub --cast cast.json --lines lines.json -o voice.mp3   # → voice.mp3 + voice.srt
```
**短剧入口**（--series/--episode 便利层，路径自动推导）：
```bash
python skills/openclaw/short-drama/scripts/dubbing.py cast init --series "<剧名>"
python .../dubbing.py align --series "<剧名>" --episode 1   # 逐镜对齐（lines 每行需标 shot），推荐
```
