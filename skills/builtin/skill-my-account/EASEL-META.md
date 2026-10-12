# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-my-account |
| **所属层** | general（跨切面自查，类似 profile-manager / asset-manager） |
| **实现** | `../../shared/scripts/account_stats.py`（数据）+ `xhs_publish.py`/`douyin_publish.py`/`web_publisher.py` 的 `whoami`（身份），均 Playwright、headless 可用 |
| **自研** | ✅ Easel 自研 |
| **自包含** | 需对应平台登录态（`~/.easel-browser-profiles/<平台>Profile`，Web「账号」页扫码留存）；不依赖画像 |
| **备注** | 只读登录态与创作数据；不改登录态、不发布、不做深度分析 |

> 沉淀时间: 2026-07-31

## 定位与由来

第九次会话做归因层「创作数据」卡片时新增了 `account_stats.py`（抓已登录账号的粉丝/获赞/作品列表），
但**只有 Web 后端 `/api/analytics` 在用**；三个 publisher 的 `whoami` 也只被账号页调用。结果 OpenClaw
agent **没有指向这些能力的 SKILL 入口**——用户问"我小红书最近发了什么帖子"，agent 因为不知道自己能查
登录态，反而回问用户账号名（真机翻车，2026-07-31）。

本 SKILL 把这两条既有能力（`whoami` 查身份 + `account_stats fetch` 查数据）**沉淀为一个可路由的自查
入口**，description 堆足"我的账号/我的粉丝/我最近发了什么"等触发词，让 agent 遇到关于用户自己账号的
问题能**先查登录态、别回头问用户**。不写新确定性代码，只包装既有脚本（都带 selftest）。

## 与既有 SKILL 的边界

- **快速自查"我的账号/数据/帖子"** → 本 SKILL（读登录态即答）。
- 发布后**效果深度分析/复盘** → skill-publish-analytics / skill-social-performance-review。
- 小红书**爆款规律/限流** → skill-xhs-analyzer；**账号诊断/起号** → skill-account-diagnosis。
- **评论**抓取与情感/诉求分析 → skill-xhs-comment-reply + skill-comment-insights。
- 本 SKILL 只做"读取已登录账号的身份与创作数据"，是这些深度分析的**数据来源**。

## 配合的 prompt 规则

AGENTS.md「## 先查站内已有信息，别回头问用户」一节点名了本 SKILL：关于用户自己账号/内容的问题
先走这里查登录态与站内数据，查不到（未登录）再让去账号页扫码。SKILL 负责"怎么查"，AGENTS 负责
"记得先查"，两者配合。

## 待办 / 后续

- whoami 目前昵称/头像选择器为 best-effort，各平台登录后需按真机校准（抖音/视频号尤其）。
- 可扩展：一次性 whoami 全平台汇总（现按平台逐个跑）；把作品列表的每条 stat 标准化。
- account_stats 各平台数据完整度见 SKILL.md「支持平台」表，随平台改版需校准 `account_stats.py` 的 `PLATFORMS` 配置。
