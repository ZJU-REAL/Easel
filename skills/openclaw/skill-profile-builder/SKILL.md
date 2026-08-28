---
name: skill-profile-builder
description: "首次使用引导：从社媒链接分析、从零生成账号画像 Profile。收集社媒链接+运营意图，分析已发内容与收藏喜好，生成 6 维 Profile。当用户说 创建画像/第一次用/帮我建个人设/分析我的账号建画像/从链接生成画像 时使用。与 skill-profile-manager 的区别：本 SKILL 专做首次从零分析生成；已有画像的编辑/记忆更新/导出/对比/切换找 profile-manager。"
layer: general
---

# Profile 构建器（首次引导）

> 把"空白/半空的画像"变成"可用的 6 维 Profile"。用户首次使用 Easel 时先跑这个：收集社媒链接 + 运营意图 → 分析已发内容/收藏喜好 → 生成 `profiles/<名>/` 下 6 个维度文件。生成后交给 [account-diagnosis](../skill-account-diagnosis/SKILL.md) 做起号诊断。

## 与 profile-manager 的区别

- **profile-builder（本 SKILL）** = 从 0 到 1 **生成**画像（引导填写 + 社媒分析 + 综合成稿）。
- **profile-manager** = 已有画像的 CRUD、切换、字段增删改。

## 输入

用户按需提供（缺的通过追问补，不编造）：

| 项 | 说明 |
|----|------|
| 画像名 | 一个人设 = 一个画像（非一个平台），如"科技数码达人" |
| 社媒链接 | 各平台主页 URL（小红书/抖音/B站/微博/知乎/公众号），用于分析已发内容与收藏喜好 |
| 运营意图 | 想做什么方向、为什么做、自己的特点/优势/资源 |
| 内容偏好 | 喜欢看什么类型、想产出什么类型、参考/对标的账号 |
| 红线 | 明确不做的内容、合规底线 |

## 输出

`profiles/<画像名>/` 下生成 6 个文件（结构见 `profiles/_template/`）：
`identity.md` / `style.md` / `audience.md` / `platforms.md` / `preferences.md` / `memory.md`。
每个字段标注来源：`[用户自述]` / `[链接分析]` / `[待补充]`。

## 执行步骤

1. **确定画像名**，检查 `profiles/<名>/` 是否已存在（存在则问是覆盖还是完善）。不存在则复制 `profiles/_template/` 为骨架。

2. **收集社媒链接**。按 [onboarding-questions.md](references/onboarding-questions.md) 的清单引导用户给出主页链接与基础信息。

3. **分析社媒链接**。按 [social-link-analysis.md](references/social-link-analysis.md) 用 web_fetch 抓取可获取的公开内容（近期发帖标题/题材/互动、公开收藏/点赞），推断：常发题材、风格语气、受众画像、高互动内容特征。
   - 抓取受限（多数平台反爬）时**降级**：明确告诉用户哪些没抓到，改由用户口述 + 追问补齐，**不臆造数据**。

4. **收集运营意图与偏好**。按 onboarding-questions.md 逐维度提问：想运营的方向、原因、自己的特点/资源、内容偏好、对标账号、红线。

5. **综合生成 6 维**。把[链接分析]与[用户自述]融合，按 `profiles/_template/` 各文件的字段填写：
   - identity ← 定位/差异化/内容方向
   - style ← 语气/开头结构/视觉/节奏/标志元素（链接分析里的高频风格优先）
   - audience ← 核心人群/兴趣/痛点/互动特征
   - platforms ← 各平台账号名/粉丝量级/内容形式（来自链接）
   - preferences ← 要做/不做/合规底线
   - memory ← 首次留空或只放链接分析得到的初步洞察

6. **标注缺口 + 追问**。任何维度信息不足就在该处写 `[待补充]` 并**列出需要用户回答的具体问题**（做成 plan 让用户逐条补），不要用通用套话填满。

7. **写入并回执**。写 `profiles/<名>/` 各文件，输出一份"画像已生成"摘要：各维度完成度、哪些来自链接分析、哪些待补充，并建议下一步跑 account-diagnosis。

## Profile 感知

本 SKILL 是**生成** Profile，不消费。生成质量取决于用户提供的链接可抓取程度与自述完整度——信息越全，后续 account-diagnosis 越准。
