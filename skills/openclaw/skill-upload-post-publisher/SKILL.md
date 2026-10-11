---
name: skill-upload-post-publisher
description: >-
  海外平台发布：把视频 / 图文 / 纯文本通过 Upload-Post API 一次发到 TikTok、Instagram、YouTube、
  LinkedIn、X、Facebook、Threads、Pinterest、Bluesky。当用户说"发TikTok""发Instagram/Reels"
  "发YouTube Shorts""发海外平台""出海发布""同时发到 TikTok 和 YouTube"时使用。纯 API，无需浏览器或 cookie。
layer: publish
---

# 海外平台发布（Upload-Post）

> 走 `scripts/upload_post_publish.py`：一次上传，Upload-Post 分发到各海外平台并逐平台返回结果。
> **与国内平台 publisher 互补**（小红书 / 抖音 / B站 等仍走各自 SKILL），由
> skill-cross-platform-publish 按平台路由到本 SKILL。

## ⚠️ 环境依赖

| 依赖 | 说明 |
|------|------|
| Upload-Post 账号 | 在 https://upload-post.com 创建 profile，并在其中连接要发布的平台账号 |
| `UPLOAD_POST_API_KEY` | 控制台创建的 API key，写入 `.env` |
| `UPLOAD_POST_USER` | 上面那个 profile 的名字（也可每次传 `--user`） |
| 外网 | 调用 api.upload-post.com |

免费版每月 10 次上传，覆盖除 TikTok 外的全部平台（TikTok 需付费版）。无 key 时仍可 `platforms`、
`publish`（dry-run 预览）与 `selftest`。

## 支持平台

| 平台 | 视频 | 图文 | 文字 |
|------|:---:|:---:|:---:|
| tiktok / instagram | ✅ | ✅ | — |
| youtube | ✅ | — | — |
| linkedin / x / facebook / threads / bluesky | ✅ | ✅ | ✅ |
| pinterest | ✅ | ✅ | — |

`--media` 传 1 个视频 → 视频；传 1~N 张图 → 图文；不传 → 纯文本。

## 执行

脚本路径（相对项目根）：`skills/openclaw/skill-upload-post-publisher/scripts/upload_post_publish.py`。

```bash
# 0) 校验 key + 看 profile 已连接哪些平台
python skills/openclaw/skill-upload-post-publisher/scripts/upload_post_publish.py check
# 1) 预览（默认 dry-run：打印请求、检查目标平台是否已连接，不发布）
python skills/openclaw/skill-upload-post-publisher/scripts/upload_post_publish.py publish --platforms tiktok,instagram,youtube --media out.mp4 \
  --title "30 秒看懂 RAG" --tags "AI,RAG" --ai-generated
# 2) 用户确认后真正发布（等待各平台结果，最多 10 分钟）
python skills/openclaw/skill-upload-post-publisher/scripts/upload_post_publish.py publish --platforms tiktok,instagram,youtube --media out.mp4 \
  --title "30 秒看懂 RAG" --tags "AI,RAG" --ai-generated --exec
# 3) 定时发布 / 查询结果
python skills/openclaw/skill-upload-post-publisher/scripts/upload_post_publish.py publish --platforms linkedin,x --media out.mp4 --title "新品发布" \
  --schedule 2026-10-01T09:00:00 --timezone Asia/Shanghai --exec
python skills/openclaw/skill-upload-post-publisher/scripts/upload_post_publish.py status --id <request_id 或 job_id>
```

- YouTube 默认 `--youtube-privacy private`；TikTok 默认沿用账号设置，可 `--tiktok-privacy SELF_ONLY` 先自测。
- Pinterest 必须 `--pinterest-board`；Facebook 多主页时用 `--facebook-page-id`。
- `--desc` 是长描述（YouTube / LinkedIn / Facebook / Pinterest 使用）；`--tags` 以 `#tag` 接在文案后。

## 结果判定

- 上传异步：提交后按 `request_id` 轮询，逐平台输出 ✅ 链接 / ❌ 平台原因 / ⏭️ 跳过（profile 未连该平台）。
- 私密发布没有公开链接：YouTube 仍给出本人可见的链接，其他平台给 post id。
- TikTok 若显示"已进收件箱草稿"，需在 TikTok App 内手动点发布。
- `request_id` 同时作为 `Idempotency-Key`。只有 400/401/403/422（服务端明确拒收，内容没发出）
  算确定失败（退出码 3，可修正后重试）。5xx、超时 / 连接中断、2xx 但响应无效都**不算失败**：脚本
  不重发，只查同一 request_id——查到就继续跟踪，查不到就判为 **unknown（待确认）**，退出码 4。
- **出现 unknown（或等待超时）后绝不再跑 `--exec`**（新 request_id 会重复发布），只用
  `status --id <request_id>` 核对；脚本会把这条命令打印出来。
- `--exec` 成功的平台自动写入内容日历（`_schedule.json`）并转发 skill-publish-log；unknown 的平台
  只在日历记 `unknown`（备注带 request_id），不进 publish-log，核对后再补记。

## Profile 感知

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

Publishes video, images or text to TikTok, Instagram, YouTube, LinkedIn, X, Facebook, Threads,
Pinterest and Bluesky in one call through the Upload-Post API — no browser, no cookies. Set
`UPLOAD_POST_API_KEY` and `UPLOAD_POST_USER` (the Upload-Post profile with your accounts connected)
in `.env`. `publish` is a dry-run by default and only posts with `--exec`; uploads are async and
polled per platform; the client-side `request_id` is also the `Idempotency-Key`. Only an explicit
400/401/403/422 is a definitive failure. A 5xx, a timeout or an invalid 2xx is never re-sent: the
script checks the same `request_id` and, if it can't confirm, reports **unknown** (exit 4) and
records it in the calendar with the `request_id`. After an unknown, never re-run `--exec`, only
`status --id <request_id>`. YouTube defaults to `private`. Free plan: 10 uploads/month on every
platform except TikTok, which needs a paid plan.

## 参考来源

Upload-Post（https://upload-post.com，API 文档 https://docs.upload-post.com）——托管的多平台发布 API，
统一处理各平台 OAuth 与上传。本 SKILL 做参数校验、dry-run 预览、内容安全闸门、结果归一与日历记录。
