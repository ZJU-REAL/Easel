# 错误码与处理

## 微信 API / 配置错误

| 错误 | 原因 | 解决 |
|---|---|---|
| `ConfigError` | `wechat-publisher.yaml` 缺失或账号不存在 / 字段不全 | 检查文件是否存在、`default` 字段、`app_id`/`app_secret` |
| `40164 IP 不在白名单` | 机器 IP 未加白名单 | `curl ifconfig.me` 取 IP → 公众平台加白名单 |
| `40001 access_token 无效` | token 过期或凭证错 | 检查 `wechat-publisher.yaml` 的 `app_id`/`app_secret` |
| `40002` | AppID / AppSecret 错 | 同上 |
| `40009 图片大小超限` | 图片超 10MB | 压缩或换图 |
| `48001 接口未授权` | 公众号类型不支持 | 需要已认证的服务号 / 订阅号 |
| `ai_score.py` 返回 FAIL | AI 味太重 | 按命中清单重写段落；或 `--skip-ai-score` 临时绕过 |

## 常见约束

- access_token 有效期 2 小时，脚本自动管理（`wechat_token.py` 本地文件缓存）。
- 微信 API 频率限制：每日 100 次素材上传。
- 正文图片通过 `uploadimg` 接口上传，不占永久素材名额；newspic 每张图占永久素材名额。
- 文章始终发布到**草稿箱**，不自动群发。
