# my-account 命令样例

脚本（CWD=项目根，用 `python` 直接调）：
- 身份：`skills/shared/scripts/{xhs_publish,douyin_publish,web_publisher}.py whoami`
- 数据：`skills/shared/scripts/account_stats.py fetch --platform <平台>`

代理**自动按平台**处理：小红书直连、其它走 env——`account_stats` 无需手动指定；whoami 见下方各平台注意。

## 0. 环境检查

```bash
python skills/shared/scripts/account_stats.py check
```

## 1. 查登录身份 whoami（回答"我是谁 / 登录了吗 / 我的账号名"）

输出单行 JSON：`{"loggedIn": true/false, "name": "昵称", "avatar": "头像URL"}`。

```bash
# 小红书（必须直连，走代理常被判风险）
python skills/shared/scripts/xhs_publish.py whoami --no-proxy

# 抖音（走代理，默认取 env，勿加 --no-proxy）
python skills/shared/scripts/douyin_publish.py whoami

# 知乎 / 快手 / 视频号（web_publisher，--platform 三选一）
python skills/shared/scripts/web_publisher.py whoami --platform zhihu
python skills/shared/scripts/web_publisher.py whoami --platform kuaishou
python skills/shared/scripts/web_publisher.py whoami --platform weixin-channels
```

- `loggedIn=false` → 告诉用户"你还没登录 X，去 Web『账号』页扫码"。
- 用户问"我登录了哪些号"且没指明平台 → 各平台各跑一次 whoami，汇总哪些已登录。

## 2. 查创作数据 / 帖子 account_stats fetch（回答"我的粉丝 / 最近发了什么 / 有哪些帖子"）

`--platform` 取 `xiaohongshu` / `douyin` / `kuaishou` / `zhihu` / `weixin-channels`。
输出 JSON（关键字段）：

```json
{
  "logged_in": true,
  "nickname": "昵称",
  "followers": 12345, "likes": 67890, "following": 200, "posts": 42,
  "notes": [ {"title": "帖子标题", "url": "https://...", "cover": "封面URL", "stat": "赞/评/播放",
              "note_id": "小红书笔记id", "xsec_token": "从接口拦截取的token"} ]
}
```

> 小红书的 `notes` 每条带 `note_id` 和 `xsec_token`（token 从 note-manager 接口响应拦截取，通常可靠）——
> 想接着看某条笔记的**评论**时，把它的 `url` 直接喂给 **skill-xhs-comment-reply** 的 `fetch --url`，不用再手动拆 token。

```bash
# 小红书：粉丝/获赞/关注 + 笔记列表（带 explore 链接、封面、每条数据）
python skills/shared/scripts/account_stats.py fetch --platform xiaohongshu

# 抖音 / 快手 / 知乎 / 视频号
python skills/shared/scripts/account_stats.py fetch --platform douyin
python skills/shared/scripts/account_stats.py fetch --platform zhihu
python skills/shared/scripts/account_stats.py fetch --platform kuaishou
python skills/shared/scripts/account_stats.py fetch --platform weixin-channels
```

**按用户问题取字段回答**：
- "我多少粉丝 / 获赞" → `followers` / `likes`（拿不到显示"—"，不编）。
- "我最近发了什么 / 最近的帖子是什么" → `notes[0]`（列表通常按时间倒序），给标题 + 链接。
- "我有哪些帖子 / 都发过什么" → 遍历 `notes`，列标题 + 链接（+ 每条 `stat`）。
- `logged_in=false` → 提示去账号页扫码，别继续硬答。

## 3. 各平台数据完整度（真机现状，如实告知用户）

| 平台 | 粉丝/获赞 | 作品列表 | 备注 |
|------|:-:|:-:|---|
| 小红书 | ✓ | ✓ 带链接+封面 | 最全，含近 7 日环比 |
| 知乎 | ✓ | ✓ 文章带链接 | 粉丝=关注者、获赞=赞同总量 |
| 快手 | ✗ 总数不给 | ✓ 无公开链接 | 创作中心只给近 7 日互动 |
| 抖音 / 视频号 | 登录后取 | 登录后取 | 选择器需真机校准 |

拿不到的项**如实显示"—"，不编不凑**（诚实呈现数据是硬约束）。

## 4. 排错

抓取字段为空/疑似平台改版：

```bash
EASEL_STATS_DEBUG=1 python skills/shared/scripts/account_stats.py fetch --platform <平台>
# 正文 dump 到 outputs/_analytics/<平台>-page.txt，据此校准 account_stats.py 的 PLATFORMS 配置
```

## 5. 与深度分析串联

本 SKILL 拿到的数据是入口，深度需求转对应 SKILL：
- 效果复盘/对标 → skill-publish-analytics、skill-social-performance-review
- 小红书爆款/限流 → skill-xhs-analyzer；账号诊断 → skill-account-diagnosis
- 评论 → skill-xhs-comment-reply（抓）→ skill-comment-insights（析）
