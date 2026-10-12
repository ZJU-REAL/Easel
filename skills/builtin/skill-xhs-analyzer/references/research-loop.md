# 研究循环 —— 读操作节流与风控安全

> XHS 风控节流的是**读取**，不只是写入。任何读超过几篇笔记的研究都必须走这个循环。

## 为什么：读操作是研究真正会猛敲的部分

`read` / `comments` / `analyze-viral` 都命中笔记详情 API（带 `xsec_token`）。在紧循环里连发 30–50 次，XHS 就返回 `NeedVerify`/验证码或 IP 封禁（300012），账号会降级**数小时**。所以研究必须**串行节流，不并行**：一次一篇在途，间隔看起来像人在读而非脚本在爬。

机制是**基于文件的循环**：磁盘上一个工作队列，每"tick"处理一项，每个结果立即 checkpoint。所有状态存文件 → 可恢复、能扛过会话结束。

## 真正的规则：像人在读（不是"慢就行"）

检测是**分布式的，不是速率阈值**。XHS 不问"是否超过 N 次请求"，而是建模人类会话长什么样，标记不像的。三个暴露脚本的破绽：
- **时序微结构**：人的动作间隔高方差、重尾（2 秒、然后 40 秒、然后 5 分钟）；脚本发出紧凑低方差流。"5 秒内 3 次不同搜索"方差近零、比人读一页结果还快 —— 这单一事实比总次数更强。
- **会话宏结构**：人深度优先浏览（搜索→打开一篇→停留→打开相关→游走）；爬虫广度优先枚举（搜 A、搜 B、搜 C…从不点进、从不停留）。关键词列表从头跑到尾**就是**签名。
- **动作构成**：真实会话混合点赞/收藏/停留/滚动/看视频；研究跑 100% 是读、零停留、零互动 —— 对人不可能的比例。

所以规则是**让会话与人在读无法区分**：人形方差（jitter + 偶尔长停顿）、一次一篇带停留、深度优于广度、有上限（人不会开几百个东西）、**遇到第一次摩擦就退避**（人碰到验证码会停，机器会重试 —— 所以熔断器本身就是人类行为）。

> **安全优先是更"能动"的姿态，不是胆小。** agent 的真正优势不是速度，是**规模化的耐心**：它能跑 8 小时人形循环，没人做得到。激进模仿了唯一会害你被抓的人类特质（急躁）。

## 三种模式

| 模式 | 每篇节奏 | ~读/分 | 何时用 | 门槛 |
|------|---------|--------|--------|------|
| 🚶 Steady（默认） | **20 s ± 50% jitter**（≈10–35 s） | ~2–3 | 所有常规/多篇研究 | **无 —— 这是默认** |
| 🐢 Deep/overnight | 60–120 s | ~0.5–1 | 超大语料，或最小化足迹 | 大任务时 opt in |
| ⚡ Fast（应急） | **5 s ± jitter 下限**，最多 30 篇突发后冷却 | ~10+（超安全上限） | 真正无法等的截止 | **必须逐字打印 fast-mode 警告 + 用户明确 opt-in** |

**所有模式不变量**：绝不零延迟、绝不并行、恰好一篇在途；除已警告的 Fast 外，**绝不持续超过 ~5 读/分**。Steady 下 100 篇队列 ~35–50 分钟完成。

## 严格规则（不可协商）

1. **循环强制，Steady 是默认节奏。** 任何触及 >~5 篇的研究都走循环。Deep/Fast 是显式 opt-in，Fast 还需打印警告 + 用户确认。
2. **一篇在途。** 绝不批量/并行读。无 `for url in …; do redbook read …; done` 而不带间隔。无后台 `&` 扇出。（`MAX_CONCURRENCY = 1`）
3. **保持 <~5 读/分，始终 jitter。** 每次等待加 ±50% 随机 jitter（匀速是机器签名）。只有已警告的 Fast 可越线。
4. **限制评论分页。** 评论/子评论读是最高风险端点（最先触发风控）。`--comment-pages ≤ 3`，每页计入节奏 + 预算，绝不深爬评论线程。
5. **每项 checkpoint。** 下一 tick 前把结果写盘并更新 manifest，绝不只在内存。
6. **尊重每日预算。** 默认软上限 **~200 详情读/天**（异常量本身就是风控触发器）。`consumedToday >= dailyBudget` 就停到次日。
7. **熔断器绝对。** 第一个风控信号出现即 STOP 整个循环、持久化、告知用户，**绝不自动重试穿过它**。仅在人工显式"resume"后恢复。
8. **读非写。** 此循环仅供读/分析。互动动作（评论/回复/点赞）另有写侧限制，绝不折进研究 tick。

## 状态契约（可恢复，扛过会话死亡）

所有状态在一个 job 目录下，默认 `research/xhs/<job-slug>/`：

| 文件 | 角色 |
|------|------|
| `queue.jsonl` | 工作队列，每行一项：`{ "id", "kind": "read\|comments\|analyze-viral\|search\|user\|user-posts", "arg", "status": "pending\|done\|error", "note" }` |
| `results/<id>.json` | 每项的原始 `--json` 输出（语料） |
| `loop-state.json` | `{ "mode", "intervalSec", "jitterPct", "dailyBudget", "consumedToday", "budgetDate", "lastTickAt", "breaker": "ok\|tripped", "breakerReason" }` |
| `manifest.md` | 人读的计划 + 进度（每完成项打勾）—— 恢复检查点，每 tick 更新 |
| `SUMMARY.md` | 队列排空后的最终综合 |

**播种队列**：便宜的列表端点（`search`/`feed`/`user-posts`）用来*建*队列，不算在节流循环内。先跑 `search`/`feed`，抽出每篇 `webUrl`，为每篇写一条 `read`/`analyze-viral` 到 `queue.jsonl`。始终带新鲜 `webUrl`（含 token），别排 bare noteId。

## 一个 tick = 一篇笔记

1. 载入 `loop-state.json`。若 `breaker != "ok"` → 立即退出（告知原因）。
2. 滚动每日预算。若 `budgetDate != today` 重置；若 `consumedToday >= dailyBudget` → 退出到明天。
3. 弹出下一 `pending` 项。若无 → **finalize**：从 `results/` 综合 `SUMMARY.md`，标记完成。
4. 跑恰好一次读：`redbook <kind> "<arg>" --json`。
5. 检查风控信号（空 `{}`、`NeedVerify`/验证码、`Session expired`、IP 封 300012）。若有 → **触发熔断**：`breaker:"tripped"` + reason，该项留 `pending`，持久化，告知用户，STOP。
6. 成功：写 `results/<id>.json`，项设 `status:"done"`，manifest 打勾，`consumedToday += 1`，设 `lastTickAt`。
7. 停。只一篇 —— 驱动器在（jitter 后）间隔后重新调用。

## 驱动器（后台保活）

- **A) 会话内节奏（默认 Steady）**：一会话内背靠背跑 tick，每次读之间 sleep `intervalSec` ± jitter。100 篇 ~35–50 分钟。（按*每次读*节奏，别用一个长阻塞 sleep 造假。）
- **B) `/loop` 自节奏（Deep/overnight）**：不带间隔，做一 tick 后 `ScheduleWakeup`（≥60 s，适配 Deep 60–120 s）再触发。
- **C) Hook — Push 循环 issue（多天/真后台）**：建 recurring issue，每次触发 = 一 fresh session = 一 tick，指向同一 job 目录。

## ⚡ Fast-mode 警告（应急，逐字打印后需用户"yes"）

```
⚠️  XHS FAST RESEARCH MODE — elevated 风控 risk
    Reading at ~12 notes/min crosses the safe ~5/min ceiling and
    materially raises the chance of:
      • captcha / NeedVerify mid-run (stops the loop)
      • IP block (error 300012) for hours
      • account-level recommendation throttling
    Steady mode (the default, ~20s/note) stays inside the safe band
    and still finishes a typical job in well under an hour.
    Proceed with fast mode for this run only? (yes / no)
```

Fast 仍守下限（≥5 s ± jitter，绝不零）、单突发 30 篇后强制冷却回 Steady、熔断器仍在第一个风控信号硬停。

## 熔断器

第一次出现任一即触发并 STOP：`NeedVerify`/验证码 · 空 `{}`（多为 token 过期，重新播种别盲重试）· `Session expired`/"No 'a1' cookie"（cookie 失效，重登）· IP 封 `300012`（硬限速，等/换网）。触发后设 `breaker:"tripped"` + reason，当前项留 `pending`，持久化，告知用户。**绝不自动重试穿过封禁** —— 那会把软节流升级成数小时封禁。仅人工清除原因并显式说继续后恢复。

## 写侧安全阈值（互动动作，非研究读）

| 动作 | 安全间隔 | CLI 默认 | 硬上限 |
|------|---------|---------|--------|
| 发帖 | 3-4 小时（2-3 帖/天） | 手动 | — |
| 评论/回复 | ≥3 分钟 | 手动 | — |
| 批量回复间隔 | ≥3 分钟 | 5 分 ±30% jitter | — |
| 批量回复数 | — | 10 | 30 |

触发风控的行为：匀速时序、>50 互动/分、活动比率异常（评论多于浏览）、设备指纹不匹配（XHS 指纹 21 项硬件参数）。
