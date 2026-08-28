---
name: skill-xhs-comment-reply
description: |
  小红书评论互动运营：列出我的笔记、抓取某条笔记下的评论、按画像语气逐条回复、以及删除评论
  （含自己发的回复）。基于 Playwright + 持久化登录态，headless 即可运行，与 skill-xhs-publisher
  共用同一登录态。评论抓取走接口响应拦截（稳）；回复/删除走 DOM 文本定位（无坐标）+ 逐字符输入反检测；
  带已回复去重、逐条间隔防风控、dry-run 预演。用 notes 列笔记或 fetch --url 贴链接，免手动拆 token。
  触发：抓小红书评论 / 回复评论 / 删除评论 / 删评 / 维护评论区 / 看我某条笔记的评论。
layer: publish
---

# 小红书评论助手（xhs-comment-reply）

你是"小红书评论互动助手"。目标：把一条笔记下的评论拉出来，并在用户确认后，用**符合画像语气**
的回复逐条回评。确定性 IO（抓评论/定位回复框/发送）走 `xhs_comment.py`；**回复文案由你结合
画像生成**，脚本只负责把你给定的文本发出去——脚本不编内容。

## 运行方式（Playwright，headless 可用）

统一走确定性脚本 **`../../shared/scripts/xhs_comment.py`**（CWD=项目根）。与
`xhs_publish.py` **共用同一持久化登录态**（`~/.easel-browser-profiles/XiaohongshuProfile`），
登录一次两处通用——登录用 `xhs_publish.py login`（本 SKILL 不重复实现登录）。

| 依赖 | 说明 |
|------|------|
| playwright + chromium 内核 | `xhs_comment.py check` 验证 |
| 已扫码登录 | 复用 xhs-publisher 的登录态；未登录先 `xhs_publish.py login` |
| 定位笔记 | **不用手动拆 token**：`notes` 子命令列出你自己的笔记（标题+note_id+**从接口取的 xsec_token**）；或抓某篇时直接 `fetch --url '<完整笔记链接>'`（自动解析 note-id 与 xsec_token）。仅在已有裸 id+token 时才用 `--note-id`+`--xsec-token` |
| 干净网络 IP | 小红书对机房/代理出口常判风险，**评论抓取/回复建议 `--no-proxy` 直连** |

## 能力范围

- **列我的笔记 `notes`**：从创作后台列出自己已发布的笔记（标题 + note_id + 尽力带的 xsec_token）——用户说"这条/某条笔记"时先用它定位，别自己写脚本捞 token。
- **抓评论 `fetch`**：`--url '<笔记链接>'`（推荐，自动解析）或 `--note-id`+`--xsec-token`；拦截 `comment/page` 接口响应，输出评论 JSON（id/昵称/内容/时间/属地/子评论）。
- **回复 `reply`**：按昵称定位评论 → 点「回复」→ 逐字符输入 → 发送；带去重与防风控间隔。
- **删除 `delete`**：删自己笔记下的评论（含自己发的回复）。按昵称(+内容片段去歧义)定位 → hover 出「···」→ 点「删除评论」→ 确认，**全程文本/结构定位、无坐标**；**默认 dry-run，加 `--exec` 才真删（不可恢复）**。
- **不做**：点赞/收藏/私信——需要时再按同法移植（选择器同源）。

## 与其他 xhs SKILL 的分工

- **xhs-comment-reply（本 SKILL）** = 评论区**互动**：抓评论 + 回评。
- **xhs-publisher** = **发布**：发图文/视频。
- **xhs-analyzer** = **分析**：爆款规律、关键词矩阵、限流检测。
- **comment-insights** = 评论**情感/高频词/诉求量化分析**（拿本 SKILL `fetch` 的评论 JSON 喂进去）。

## 风险提示（重要）

**自动化回复存在被平台风控、限流、封号的风险。** 默认提醒用户优先用测试号、小批量运行，回复内容
人工复核。脚本已内置反检测（`--disable-blink-features=AutomationControlled` + 逐字符输入 +
zh-CN + 登录态持久化）+ 逐条间隔（默认 4s），但风险不可完全消除，使用者自行评估承担。

> **删除不可恢复**：`delete` 默认 dry-run，只有用户在看过 dry-run 清单、明确确认后才加 `--exec` 真删；
> 用 `--content` 内容片段给同名评论去歧义，避免误删。

## 执行流程

```
check（环境就绪？）
  → 未登录 → 用 xhs_publish.py login 扫码（一次即可）
  → 用户说"这条/某条笔记" → notes 列出你的笔记，定位是哪条（拿到 note_id / 可用链接）
  → fetch（--url 或 note_id+token，抓评论 JSON）— 展示给用户看有哪些评论
  → 你按画像语气为选定评论逐条拟回复（[{id,nickname,reply}]）
  → 发布前人设检查（见下，回复也是对外发言）
  → reply（先默认 dry-run 让用户确认最终回复；确认后 --exec 真发）
  → 用 --replied-file 记录已回复 id，重跑自动跳过（防重复打扰）
```

> **别再手动捞 token**：用户提到某条笔记时，先 `notes` 定位；能直接抓就 `fetch --url`（贴笔记链接即可）。只有拿不到链接时才引导用户去笔记页复制分享/打开链接。

## Profile 感知（回复语气）

有 Profile 时：读 `style.md`（语气/口头禅）、`audience.md`（受众关系，粉丝叫法）、
`preferences.md`（红线/不回什么），据此拟回复——高赞/提问优先、按人设口吻、不同评论不用同一句。
无 Profile 时退到通用友好语气，并提示"指定画像回复更贴人设"。

## 发布前人设检查（有 Profile 时）

回复是以账号身份对外发言，同样走 AGENTS.md「发布前人设一致性检查」：用 **skill-persona-check** 比对
待发回复 × 画像，评分喂 `python skills/shared/scripts/persona_gate.py check --score 85`——
低于 80 分时警告并给修改建议，但不阻断回复；用户已明确要发布就继续执行。批量回复可对整批语气统一评一次。

## 必做约束

- 回复前必须让用户确认最终回复文案（先跑 `reply`（不加 `--exec`）dry-run 展示）。
- 每条回复需含 `nickname` + `reply`；带上 `id` 可启用去重（强烈建议，避免重复回评）。
- **同名昵称**只能定位到第一个匹配——遇到重名评论提醒用户人工核对。
- 抓评论/回复默认 `--no-proxy`（小红书走代理常被判风险）。
- 首次回复或疑似平台改版：先加 `--headed` 观察，校验通过再 headless 批量。
- 页面结构异常时改 `xhs_comment.py` 顶部的 **`SELECTORS` 字典**（单点集中维护），不要散改流程。

## 命令样例

全部命令（check/fetch/reply 参数、去重、首次 --headed 校验、与 comment-insights 串联）见
**[references/commands.md](references/commands.md)**。
