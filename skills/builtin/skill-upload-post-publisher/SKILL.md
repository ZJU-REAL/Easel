---
name: skill-upload-post-publisher
description: >-
  海外平台发布（可选 provider：Upload-Post 托管 API）：把视频 / 图文 / 纯文本一次发到 TikTok、Instagram、
  YouTube、LinkedIn、X、Facebook、Threads、Pinterest、Bluesky。当用户说"发TikTok""发Instagram/Reels"
  "发YouTube Shorts""发海外平台""出海发布""同时发到 TikTok 和 YouTube"时使用。纯 API，无需浏览器或 cookie。
layer: publish
---

# 海外平台发布（Upload-Post）

> 走 `scripts/upload_post_publish.py`：一次上传，Upload-Post 分发到各海外平台并逐平台返回结果。
> **可选 provider，与现有 publisher 并列、不替换**：国内平台仍走各自 SKILL；skill-cross-platform-publish
> 按平台把海外平台路由到本 SKILL。

## Provider 说明

| 平台键 | Provider | 入口 |
|------|------|------|
| `tiktok` `instagram` `youtube` `linkedin` `x` `facebook` `threads` `pinterest` `bluesky` | Upload-Post API（第三方托管） | 本 SKILL |
| `twitter-x` | 浏览器自动化（Easel 自带） | 发布中心 / `skills/shared/scripts/web_publisher.py` |

- 本脚本里的 `x`（派发表里叫 `x-upload-post`）只指 Upload-Post 的 X 通道；传 `twitter-x` 会被拒绝并提示走浏览器路由。
- 用户只说「推特 / X」时先问用哪条，不要默认替换 `twitter-x`。

## ⚠️ 环境依赖

| 依赖 | 说明 |
|------|------|
| Upload-Post 账号 | 在 https://upload-post.com 创建 profile，并在其中连接要发布的平台账号 |
| `UPLOAD_POST_API_KEY` | 控制台创建的 API key，写入 `.env` |
| `UPLOAD_POST_USER` | 上面那个 Upload-Post profile 的名字（也可每次传 `--user`）。**不是** Easel 画像 |
| 外网 | 调用 api.upload-post.com |

额度（以 [官网价格页](https://upload-post.com/pricing) 为准）：免费版每月 10 次上传，**按平台计**（一条内容发
3 个平台算 3 次），且**不能发 TikTok**；付费版（Basic 起）不限上传次数。无 key 时仍可 `platforms`、
`publish`（dry-run 预览）与 `selftest`。

## 发布模式（与发布中心一致）

- 遵循 `EASEL_PUBLISH_MODE`：未设置或 `automated` 时可 `--exec`；设为 `manual`（或任何其他值）时
  **拒绝 `--exec`**（退出码 5），提示改走发布中心「人工审核发布」。dry-run 不受影响。
- 自动路径下仍是：dry-run 预览 → 用户确认 → `--exec`。

## 支持平台

| 平台 | 视频 | 图文 | 文字 |
|------|:---:|:---:|:---:|
| tiktok / instagram | ✅ | ✅ | — |
| youtube | ✅ | — | — |
| linkedin / x / facebook / threads / bluesky | ✅ | ✅ | ✅ |
| pinterest | ✅ | ✅ | — |

`--media` 传 1 个视频 → 视频；传 1~N 张图 → 图文；不传 → 纯文本。

## 执行

脚本路径（相对项目根）：`skills/builtin/skill-upload-post-publisher/scripts/upload_post_publish.py`。

```bash
S=skills/builtin/skill-upload-post-publisher/scripts/upload_post_publish.py
# 0) 校验 key + 看 Upload-Post profile 已连接哪些平台
python $S check
# 1) 预览（默认 dry-run：打印请求、检查目标平台是否已连接，不发布）
python $S publish --platforms instagram,youtube --media out.mp4 \
  --title "30 秒看懂 RAG" --tags "AI,RAG" --ai-generated --profile 科技博主
# 2) 用户确认后真正发布（等待各平台结果，最多 10 分钟）
python $S publish --platforms instagram,youtube --media out.mp4 \
  --title "30 秒看懂 RAG" --tags "AI,RAG" --ai-generated --profile 科技博主 --exec
# 3) 定时发布 / 查询结果并补记日历
python $S publish --platforms linkedin,x --media out.mp4 --title "新品发布" \
  --schedule 2026-10-01T09:00:00 --timezone Asia/Shanghai --exec
python $S status --id <request_id> --record
```

- YouTube 默认 `--youtube-privacy private`；TikTok 默认沿用账号设置，可 `--tiktok-privacy SELF_ONLY` 先自测。
- Pinterest 必须 `--pinterest-board`；Facebook 多主页时用 `--facebook-page-id`。
- `--desc` 是长描述（YouTube / LinkedIn / Facebook / Pinterest 使用）；`--tags` 以 `#tag` 接在文案后。
- `--schedule` 不带时区时，是 `--timezone` 所指时区的当地时间（不传 `--timezone` 按 UTC）。

## 结果判定

逐平台归为以下几类，只有 **published** 记为「已发」：

| 归类 | 条件 | 日历 | publish-log |
|------|------|------|------|
| published | 服务端报成功，且有作品链接或作品 ID 可核验 | 已发 | ✅ |
| draft | `fallback_to_inbox`：进了 TikTok 收件箱，需在 App 内手动发布 | 草稿 | — |
| skipped | 该 Upload-Post profile 没连这个平台 | — | — |
| failed | 平台明确失败（带原因） | — | — |
| unverified | 服务端报成功，但没有链接也没有 ID | — | — |
| unknown | 条目里没有任何状态或成功证据 | — | — |

提交本身：

- 每次 `--exec` 生成一个 `request_id`，同时作为 form 字段和 `Idempotency-Key` 发送。
- 只有 4xx（408 / 409 除外，含 429 额度用尽）和 HTTP 2xx + `success:false` 算**确定失败**（退出码 3，内容没发出，可修正后重试）。
- 5xx、超时 / 连接中断、2xx 但响应无效都**不算失败**：脚本不重发，只查同一个 `request_id`——查到就继续跟踪，
  查不到就判为 **unknown（待确认）**，退出码 4。
- 定时发布必须拿到 `job_id` 才报「已排期」；没有 `job_id` 判为待确认（退出码 4）。
- **出现待确认（unknown / unverified / 等待超时）后绝不再跑 `--exec`**（新 `request_id` 会重复发布），只用
  `status --id <request_id> --record` 核对，确认后自动补记日历（已记过的平台不重复）。

### 服务端去重契约与本地台账

- Upload-Post 对 `Idempotency-Key`（也接受 `X-Idempotency-Key`）按 **账号 + 上传类型（视频 / 图片 / 文字）**
  去重，**有效期为首次请求起 24 小时**；同一 key 再次提交会返回原任务（`idempotent_replay`），即使请求体变了。
  同一 key 的请求仍在处理时返回 `409 IDEMPOTENCY_KEY_IN_USE`（本脚本按「不确定」处理，去查询，不重发）。
  见 [Rate limits · 去重](https://docs.upload-post.com/guides/rate-limits/)、
  [Upload video · Idempotency-Key](https://docs.upload-post.com/api/upload-video/)、
  [Upload status](https://docs.upload-post.com/api/upload-status/)。
- 文档没有承诺 `status` 按 `request_id` 可查询的保留期限，所以**不能把查不到当作没发出**。脚本在提交前就把
  请求写进本地台账 `outputs/_publish/upload-post/<request_id>.json`，进程重启后仍可 `status --id` 核对与补记。
- 无论服务端契约如何，提交结果不明时脚本都不会自动重发。

## 发布前人设检查（有 Profile 时）

按 AGENTS.md「发布前人设一致性检查」：先 **skill-persona-check** 比对内容×画像，评分喂
`python skills/shared/scripts/persona_gate.py check --score 85`——低于 80 分时警告并给修改建议，
但不阻断发布；用户已明确要发布就继续执行。发布时传 `--profile <画像名>`（默认 `EASEL_ACTIVE_PROFILE`），
写入日历归因。

- 有 Profile：目标平台取 `platforms.md` 里已开通的海外账号；文案语言与语气贴合 `style.md`
  （海外平台一般用英文或目标市场语言）。
- 无 Profile：询问目标平台与文案语言。

## 规则

1. 先 `check`，再省略 `--exec` 预览；**用户确认文案与平台清单后**才加 `--exec`。
2. 真发前脚本强制扫描标题 / 描述 / 标签，检出密钥、内部地址或路径时阻止发布。
3. TikTok / Reels / Shorts 用竖版 9:16；横版素材先用 video-reframe。
4. AI 生成的画面或配音建议加 `--ai-generated`（平台 AI 标识）。
5. 一稿多发走 skill-cross-platform-publish 的 `plan`，按各平台约束适配后再调用本 SKILL。

## English

Optional provider: publishes video, images or text to TikTok, Instagram, YouTube, LinkedIn, X, Facebook,
Threads, Pinterest and Bluesky through the hosted Upload-Post API — no browser, no cookies. It sits next to
the existing publishers and does not replace them; `x` here is the Upload-Post route and is distinct from the
browser route `twitter-x`. Honours `EASEL_PUBLISH_MODE`: `--exec` is refused unless the mode is automated.
`publish` is a dry-run by default. Each platform result is classified as published (needs a link or post id),
draft (TikTok inbox fallback), skipped, failed, unverified (success without a link or id) or unknown (no
status); only published is recorded as published. A client `request_id` doubles as the `Idempotency-Key`
(server-side dedup per account and upload type for 24 hours). Only a 4xx other than 408/409, or a 2xx with
`success:false`, is a definitive failure. A 5xx, a timeout or an unreadable 2xx is never re-sent; a local
ledger keeps the `request_id` so `status --id <id> --record` can confirm and record later, even after a
restart. Free plan: 10 uploads a month counted per platform, no TikTok; paid plans are unlimited.

## 参考来源

Upload-Post（https://upload-post.com，API 文档 https://docs.upload-post.com）——托管的多平台发布 API，
统一处理各平台 OAuth 与上传。本 SKILL 做参数校验、dry-run 预览、内容安全闸门、结果归一与日历记录。
