# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | copywriting |
| **所属层** | produce |
| **来源类型** | 自研（本地化重写） |
| **原始来源** | Easel 自研。v0.2.0 本地化重写：从西方 SaaS 落地页转化文案重定位为国内营销文案 |
| **参考项目** | 无（frontmatter 无 `references` 字段；references/ 目录为内部文案框架文档，非外部来源） |
| **许可** | 随 Easel 项目许可 |

## 本地化重写记录（2026-07-23，v0.2.0）

- **问题**：原 SKILL 整篇为西方 SaaS 落地页转化文案（首页/着陆页/定价页、Above the Fold、Meta title、CTA 示例"开始免费试用"），但功能映射把它定位为"小红书种草文案/信息流广告文案/卖点提炼"，声明与内容严重错配；references/copy-frameworks.md 与 natural-transitions.md 为全英文西方 SaaS 内容。
- **重定位**：改为国内营销文案——种草文案、信息流广告文案、卖点提炼、活动/促销文案、电商详情页文案；落地页/产品页作为其中一种场景保留，不再是主体。
- **框架处理**：保留经典框架（AIDA / FAB / 痛点-方案 / 4U / BAB）但全部落到国内平台语境，`references/copy-frameworks.md` 重写为中文框架库 + 六类文案结构模板，公式用占位符不写死案例。
- **references 本地化**：`natural-transitions.md` 从全英文 web SEO 过渡语重写为中文口语化衔接 + AI 味黑名单；`writing-style-rules.md` 已是中文，保留。
- **职责边界**：SKILL.md 内新增边界表，与 `social-content`（通用社媒/涨粉）、`post-formatter`（PAS/AIDA 帖子框架排版）划清分工。
- **description** 改为中文并反映新定位。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
