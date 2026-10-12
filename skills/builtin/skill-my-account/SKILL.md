---
name: skill-my-account
description: |
  查询用户自己在 Easel 已登录的小红书、抖音、快手、知乎和视频号身份、粉丝、获赞、关注及作品列表。
  当用户问“我登录了哪些号、我是谁、我的粉丝/获赞、我最近发了什么、我有哪些帖子”时，先用本 SKILL 查本地登录态，不要先向用户索要账号名或链接。
  某条帖子的评论抓取与分析分别用 skill-xhs-comment-reply 和 skill-comment-insights。
layer: general
---

# 我的账号（my-account）

你是"账号自查助手"。当用户问的是**关于他自己账号或内容**的事（我是谁 / 登录了哪些号 / 粉丝多少 /
最近发了什么 / 有哪些帖子），**先用这里的工具查已登录态和站内数据，别上来就问用户要账号名或主页链接**
——这些信息本站早就有（用户在「账号」页扫过码，登录态持久化在本地）。

## 核心原则

- **先查，别问**：用户说"我的账号/我的帖子/我的粉丝/最近发了啥"，直接跑脚本查当前登录账号。
- **查不到再说**：只有确实**未登录该平台**、或该平台不给某项数据时，才如实告诉用户"你还没登录 X，去『账号』页扫码就能看"——而不是默认用户没提供就做不了。
- **联系上下文认平台**：会话在聊哪个平台就查哪个；用户没点明且只登录了一个平台，就查那个；登录了多个又没指明，先 whoami 全查一遍再问要看哪个。

## 运行方式（Playwright，headless 可用）

统一走确定性脚本（CWD=项目根）。读的是**本地登录态**（`~/.easel-browser-profiles/<平台>Profile`），
不是画像；登录一次长期复用，登录/退出在 Web「账号」页操作，本 SKILL 只读不改登录态。

| 依赖 | 说明 |
|------|------|
| playwright + chromium 内核 | `account_stats.py check` 验证 |
| 已扫码登录 | 未登录时脚本返回 `logged_in/loggedIn=false`，据此提示去账号页 |
| 网络 | 代理**自动按平台**处理（小红书直连、其它走 env），无需手动指定 |

## 能力范围

- **查登录身份 `whoami`**（轻量，秒级）：某平台是否登录 + 昵称 + 头像。回答"我是谁 / 登录了吗 / 我的账号名"。
- **查创作数据 `account_stats fetch`**：粉丝 / 获赞 / 关注 / 作品数 + **作品列表（标题 + 链接 + 每条数据）**。回答"我多少粉丝 / 最近发了什么 / 我有哪些帖子 / 获赞多少"。
- **评论**：某条帖子的评论抓取与分析不在本 SKILL——用 **skill-xhs-comment-reply**（抓评论）+ **skill-comment-insights**（情感/诉求分析）。

## 支持平台

whoami：小红书 / 抖音 / 知乎 / 快手 / 视频号。
account_stats fetch `--platform`：`xiaohongshu` / `douyin` / `kuaishou` / `zhihu` / `weixin-channels`。

> 各平台数据完整度不同（真机现状）：**小红书**最全（粉丝/获赞/关注/近 7 日环比 + 笔记带链接封面）；
> **知乎**（粉丝=关注者、获赞=赞同总量 + 文章列表）；**快手**创作中心不给粉丝/获赞总数，只有近 7 日互动 + 作品列表；
> **抖音/视频号**登录后按各自创作页取。拿不到的项如实显示"—"，不编不凑。

## 执行流程

```
判断用户问的是「身份」还是「数据」
  ├ 身份（我是谁/登录了哪些号） → whoami（可多平台各跑一次）
  └ 数据（粉丝/帖子/获赞/最近发啥） → account_stats.py fetch --platform <平台>
        ├ logged_in=true  → 按用户问题提取对应字段回答（粉丝数 / 最近 N 条作品标题+链接 …）
        └ logged_in=false → 提示"你还没登录 X，去『账号』页扫码"
```

## 与其他 SKILL 的分工

- **本 SKILL（my-account）** = 快速自查"我的账号/数据/帖子"，读登录态即答。
- **skill-publish-analytics / skill-social-performance-review** = 发布后**效果深度分析**（对标基准、复盘）。
- **skill-xhs-analyzer** = 小红书**爆款规律/关键词矩阵/限流检测**。
- **skill-account-diagnosis** = 账号**诊断/起号体检**（病因→处方）。
- **skill-xhs-comment-reply + skill-comment-insights** = 评论抓取与情感/诉求分析。
- 需要**深度**时，本 SKILL 的数据可作为它们的输入。

## 约束

- 只读登录态、不改；登录/退出让用户去 Web「账号」页。
- 未登录不报错收场，明确提示去哪登录。
- 作品链接原样给出（小红书 explore 链接、知乎 zhuanlan/p 链接；快手无公开链接则说明）。
- 平台改版导致抓取字段为空时，如实说"这项这次没取到"，可 `EASEL_STATS_DEBUG=1` dump 正文排查（见 commands）。

## 命令样例

全部命令（whoami 各平台、account_stats fetch、未登录处理、字段解析、debug dump）见
**[references/commands.md](references/commands.md)**。
