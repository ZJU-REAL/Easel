# 分镜时间轴 Prompt 格式（剧本 → 逐镜生成指令）

> 把单集剧本拆成 5–6 个定时镜头，每镜写成一条「生成就绪」的 prompt。
> 格式借鉴 Seedance2-Storyboard-Generator 的时间轴写法，适配 Easel 的 ai-image-gen / ai-video-gen。
> 落盘为 `episodes/epNN/shots.json`，写完用 `drama_ops.py shots validate` 校验。

## shots.json 结构

```json
{
  "episode": 1,
  "title": "赘婿觉醒",
  "style_prefix": "都市港风，9:16竖屏，冷色调，电影质感，浅景深",
  "shots": [
    {
      "idx": 1,
      "span": "0-3s",
      "target_duration": null,
      "desc": "开场钩：男主被泼酒",
      "prompt": "<风格前缀> + 逐秒画面节拍 + 【声音】",
      "refs": ["C01", "S01"],
      "tail": "尾帧：男主抬眼，眼神变冷（衔接下一镜）",
      "sfx": [{"file": "sfx/glass_break.wav", "at": 0.4, "volume": 0.9}],
      "frame": null,
      "clip": null,
      "caption": "「你也配？」",
      "status": "planned"
    }
  ]
}
```

字段说明：
- **style_prefix**：series-bible 的统一风格前缀，逐镜 prompt 都要带（保画面一致）。
- **refs**：本镜出现的角色/场景/道具，引用 ref_index 的 C/S/P 编号。**每镜至少引用一个**（一致性靠它）。
- **prompt**：完整生成指令（见下格式）。
- **target_duration / gen_duration / span**：由 `dubbing.py plan` 按台词估算后回填（生视频前跑）。`target_duration`≈该镜台词跨度（选片段档的依据）；`gen_duration`=生视频请求的**固定档位**（provider 只认固定值，多为 5s、部分 5/10s，**不能任意秒数**）。⚠️ **片段档必须 ≥ 台词跨度**，`plan` 会对超长镜提示**拆镜或精简台词**。**时间线模型：画面用完整片段（不裁到台词），台词只占其中一段**——生成后 `align` 探测真实片段时长作为该镜画面时长，台词按各行 `at` 叠在片段内，其余留给动作/停顿/音效；若某行放不下则硬失败（别靠拉伸/循环/冻结）。
- **tail**：尾帧描述，用于「尾帧 → 下一镜首帧」的连贯续接。
- **sfx**（可选）：本镜定时音效数组 `[{file, at, volume}]`——`file`=音效文件（可用 ai-music 生成短音或素材库）、`at`=**镜内**起始秒（对齐画面里枪响/椅子移动/关门的时刻）、`volume`=相对音量（默认 0.9）。`storyboard` 会把镜内 `at` 换算成全局时间，`assemble` 定点叠进成片音轨（占用非台词时间，让画面有声音层次）。
- **frame / clip**：生成后回填（首帧图路径 / 片段视频路径），供 storyboard 合成。
- **caption**：本镜字幕/对白（会烧进成片）；对白的**说话时刻**在 `lines.json` 用 `at` 指定。

## 单镜 prompt 推荐写法（逐秒节拍）

> ⚠️ **一个镜头 = 一个可生成的片段档（多为 5s）**，不是 15s 长镜。AI 视频只出固定档、单镜台词必须塞进
> 一个档内（超了 `dubbing.py plan` 会标出、拆成多镜）。所以按 **~5s 内的逐秒节拍**写，一句一秒段：

```
都市港风，9:16竖屏，冷色调，电影质感   ← 风格前缀（必带）
0-2秒：高层办公室落地窗前，男主（@C01）转身，表情冷峻，镜头缓推
2-4秒：对手（@C02）拍桌起身，冲突展现
4-5秒：男主亮出证件，对手错愕（情绪爆点）；定格男主微表情勾下一镜（尾帧）
【声音】紧张弦乐渐强 + 拍桌音效 + 对白见 caption
【参考】@C01 男主定妆图，@C02 对手，@S01 办公室
```

> 需要更长的段落感（如 15s 冲突戏）→ **拆成 3 个 ~5s 镜**（建立 / 交锋 / 爆点），各自一条 prompt +
> 用「尾帧→下一镜首帧」续接，而不是写一条 15s 单镜。

要点：
- **一句一节拍、动作可视化**（别写抽象情绪，写能拍出来的画面/运镜）。
- **@编号引用参考图**：生成时把对应 ref 图作为图生图输入，锁定长相/场景。
- **运镜词**：俯拍/推进/环绕/特写/定格——短剧靠运镜出电影感。
- **忌超长**：单条 prompt 别堆太多（部分生视频服务超字数/敏感词会失败），聚焦这一镜。

## ⚠️ 让台词精准匹配：生视频**必须用 generation_prompt，不是 prompt**

这里是「生成的台词全对不上」的头号原因，务必看懂：

- **`prompt` 字段按设计只有画面**（风格前缀 + 逐秒画面节拍 + `【声音】` 占位「对白见 caption」）——**它不含任何逐字台词**。台词在 `lines.json` 里。
- 直接把 `prompt` 丢给 ai-video-gen＝**模型根本不知道角色要说什么**，只能瞎生成语音 → 台词一个都对不上（这就是历史失败的真因）。
- 真正把台词喂进模型的是 **`dubbing.py prepare`**：它读 `lines.json`，按模型 `dialogue_faithful` 能力，把**逐字台词 + 硬约束**合进每镜的 **`generation_prompt`** 字段。忠实模型走 native-first 契约（示例）：

  ```text
  <画面 prompt> + 【音频硬约束】只允许角色"林策"说话…必须逐字说："你终于来了。"
  禁止翻译/改写/增删/重复；说话期间嘴部与声音同步；台词外只留环境声，不加旁白/BGM。
  ```

- 因此生视频**必须传 `generation_prompt`**（prepare 写的、含台词契约的那个），**不是 `prompt`**。探针实测：用这套逐字契约，happyhorse 连中英混杂情绪台词都能一字不差；不带契约就全错。
- **硬门**：生视频前跑 `drama_ops.py shots validate --pre-video`——有台词的镜若没 `generation_prompt`（＝没跑 prepare）直接拦下，别白烧生成。

## 生成阶段怎么用

1. **关键帧**：把每镜 `prompt`（+ refs 图作图生图输入）喂 **ai-image-gen** → 首帧图，回填 `frame`。
   - **角色一致性**：优先 `img2img` **引用该角色定妆图**（C 编号）保长相稳定；若图生图接口不可用（如 key 只支持 text2img），退 `text2img` 时**务必把角色外貌关键词写进每镜 prompt**（发型/服装/脸型），否则跨镜长相会飘。
2. **准备台词契约**：跑 `dubbing.py prepare` 写好每镜 `generation_prompt`；再 `shots validate --pre-video` 过硬门。
3. **生视频**：把首帧图 + **`generation_prompt`**（含台词契约，**别用 `prompt`**）喂 **ai-video-gen `image2video --ratio 9:16`** → 片段，回填 `clip`。
4. **续接**：下一镜用上一镜的 `tail` 尾帧作为首帧起点（见 character-consistency.md）。
