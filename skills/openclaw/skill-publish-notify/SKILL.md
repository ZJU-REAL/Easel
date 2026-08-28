---
name: skill-publish-notify
description: >-
  发布通知推送：内容发布成功/失败后，把结果推送到飞书/钉钉/企业微信群机器人、
  Telegram、Slack 或任意 webhook。当用户说"发布通知""发到飞书群""通知钉钉""推送到企微"
  "发布成功提醒""webhook 通知""发布完通知我""群机器人"时使用。纯脚本无第三方依赖。
layer: publish
---

# 发布通知推送

> 内容发布后把结果推到团队 IM 群机器人或任意 webhook。走 `scripts/notify.py`（纯标准库无依赖）。
> 常与发布类 SKILL 串联：发布成功 → 推送"已发布 + 链接"；失败 → 推送错误。

## 支持渠道

| 渠道 | 需要 | 说明 |
|------|------|------|
| `feishu` | 群机器人 webhook | 飞书/Lark，支持标题富文本 |
| `dingtalk` | webhook（可选加签 secret） | 钉钉群机器人 |
| `wecom` | 群机器人 webhook | 企业微信 |
| `telegram` | bot token + chat_id | Telegram Bot |
| `slack` | Incoming Webhook | Slack |
| `generic` | 任意 webhook | 发 `{"text": ...}` |

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 渠道 | 是 | 上表之一 |
| webhook / token | 是 | 群机器人地址（telegram 用 token+chat_id） |
| 通知内容 | 是 | 正文，可选标题 |

## 执行

脚本路径（相对项目根）：`skills/openclaw/skill-publish-notify/scripts/notify.py`（`send -h`）。

```bash
# 飞书群
python <skill>/scripts/notify.py send --channel feishu \
  --webhook "https://open.feishu.cn/open-apis/bot/v2/hook/xxx" \
  --title "Easel 发布成功" --text "《本期主题》已发布到 抖音+小红书\n链接：..."

# 钉钉（加签）
python <skill>/scripts/notify.py send --channel dingtalk \
  --webhook "https://oapi.dingtalk.com/robot/send?access_token=xxx" \
  --secret "SECxxx" --text "已发布"

# Telegram
python <skill>/scripts/notify.py send --channel telegram \
  --token "123:ABC" --chat-id "456" --text "已发布"

# 先干跑看 payload
python <skill>/scripts/notify.py send --channel feishu --webhook URL --text "..." --dry-run
```

## 规则

1. 发送前用 `--dry-run` 让用户确认内容与目标群，再真发。
2. webhook / token 属敏感信息，从用户配置或 .env 读取，不写死、不外泄。
3. 通知内容简洁：状态 + 标题 + 平台 + 链接即可。
4. 钉钉群若开了"加签"安全设置，必须带 `--secret`。
5. 返回 HTTP 200 且各家成功码正确才算成功，否则提示用户检查 webhook。

## 参考来源

各家群机器人均为「POST JSON 到 webhook」标准协议：飞书 msg_type、钉钉/企微 msgtype、
Telegram Bot sendMessage、Slack Incoming Webhook。钉钉加签用 HMAC-SHA256。纯 urllib 实现，
无需 apprise 等第三方库。
