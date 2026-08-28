# 论文视频分镜结构

> 把 asset-library.json 展开成视频分镜脚本 `script.md`。分镜/留存/口播节奏复用 **video-script** 的
> 方法（喂论文语境）；本文件给论文视频**专属的段落结构**。

## 推荐结构（2–4 分钟中视频）

| 段落 | 时长占比 | 内容（取自 asset-library） | 画面 |
|------|---------|--------------------------|------|
| **钩子** | 0–15s | `hook` + `one_liner` | 冲击性画面/数字大字/概念图（ai-image-gen） |
| **问题** | 15s–25% | `problem` + `prior_gap` | 痛点场景图 / 对比示意 |
| **贡献预告** | | `contributions`（一句话预告"这篇怎么破") | 要点大字条 |
| **方法（主体）** | 25%–65% | `method.idea` + `analogy` + `how` | **核心方法图**（原图或 infographic 重绘）+ 类比动画/示意 |
| **结果（高潮）** | 65%–85% | `results`（关键数字）| **结果对比图**（chart-visualization 重绘，突出那一个结论） |
| **意义 + 局限** | 85%–100% | `takeaway` + `limitations` | 收束画面 |
| **互动钩子** | 结尾 | 抛问题引评论 | — |

## 口播原则

- **对话感**：像给朋友讲，不像念论文。短句、口语、有节奏。
- **一图一议**：切到某张图就只讲这张图要说的那一个点，讲完再切。
- **术语即时解释**：首次出现术语紧跟人话（用 asset-library `terms`）。
- **语速**：中文约 250 字/分钟；口播总字数 ≈ 时长(分钟)×250，用 `wordcount.py` 校验。

## 可选：双人问答口播（更抓耳）

借鉴 paper_to_podcast。设「主持人（好奇提问）+ 讲解者（解答）」两个角色：
- 主持人替观众问出疑问（"等等，这跟以前的方法有啥不一样？"），讲解者回答。
- 一问一答天然制造节奏和悬念，比单人旁白更耐听。
- 配音时用 multi-voice-dubbing 给两角色分配不同音色，别用单声线 tts-voiceover 冒充双人。

## 分镜 → Slide → 成片

1. 每一页只对应一个中心结论：`claim`（屏幕观点）+ `narration`（口播）+ 一个视觉证据；不要把口播全文放上屏。
2. 按 `slide-design.md` 生成 `slide-plan.json`，只用其中定义的 cover/statement/evidence/process/metrics/comparison/takeaway 骨架。
3. 图：`assets/parsed/figures/` 选原图；方法图/结果图用 infographic/chart-visualization 重绘；原图太密就裁关键区域，不能缩成邮票。
4. 必须用 `render_slides.py validate → render → audit`，再肉眼查看 contact sheet；禁止每次在 outputs 临时发明一套 slide 脚本。
5. 单人口播用 tts-voiceover；双人问答用 multi-voice-dubbing。字幕与每页时长按 narration 分段对齐，再交 auto-short-video 合成。storyboard 顶层必须写 `"image_motion": "static"`；slide 不做 Ken Burns 缩放/平移，只在换页时使用克制转场。
6. 画幅按用户确认值；B站通常 16:9，视频号可 16:9 或 9:16，但不能静默推断。

## 封面

- 论文视频封面 = **一个钩子问题/惊人结论 + 3–6 字大字**，别用论文标题。
- 用 poster-hero 或 ai-image-gen 出封面。
