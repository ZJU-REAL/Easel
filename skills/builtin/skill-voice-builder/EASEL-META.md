# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-voice-builder |
| **所属层** | plan |
| **来源仓库** | charlie947/social-media-skills |
| **GitHub 地址** | https://github.com/charlie947/social-media-skills |
| **Star 数** | ~1.7k |
| **功能描述** | 结构化访谈 + 写作样本分析，生成个人声音画像（about-me.md + voice.md） |
| **SKILL.md 行数** | 119 |
| **文件总数** | 4 |
| **自包含** | 是 |
| **备注** | 原始为英文 + B2B/LinkedIn 语境（作者 Charlie Hills），已本地化为中文社媒创作者语境 |

> 收录时间: 2026-07-16
> 用途: Easel SKILL 验证测试

## 本地化说明

原 SKILL 面向 LinkedIn/B2B 场景（访谈选项为 Founder/Marketing lead/Job seekers，默认样本为英文 LinkedIn 帖，产物模板用英文 header）。本次本地化为中文社媒创作者（个人 IP）语境：

| 项 | 改动 |
|------|-----|
| interview-questions.md | 身份选项改为 知识博主/好物测评/生活方式/职场副业/垂类专家；受众/主题/渠道全部换成中文社媒语境；追问要求具体化 |
| sample-content.md | 换成中文样本：小红书笔记 + 抖音口播 + 公众号段落各一篇，体现跨平台语气差异（原为英文 LinkedIn 帖） |
| voice-analysis-dimensions.md | voice.md 模板 header 中文化；缺失信号示例改为中文社媒场景（emoji/话题标签/"家人们"等） |
| SKILL.md | about-me.md / voice.md 产物模板 header 中文化；批次与输出字段术语对齐；frontmatter 未改动 |

## 参考的 GitHub 库（致谢）

本地化过程中调研了以下声音/风格画像相关实现，吸收其访谈维度与缺失信号设计：

| 仓库 | 地址 | 借鉴点 |
|------|------|--------|
| charlie947/social-media-skills | https://github.com/charlie947/social-media-skills | 原始来源：voice-builder 的 about-me.md + voice.md 双文件结构、访谈 + 样本分析流程 |
| omeyazic/ai-voice-capture-framework | https://github.com/omeyazic/ai-voice-capture-framework | Ruben Hassid "I am just a text file" 方法：多维度访谈、对模糊回答追问逼具体 |
| angelarose210/ghostwriter | https://github.com/angelarose210/ghostwriter | 反 AI 感模式库、句子节奏/用词/口头禅等可复用画像维度 |
| danielrosehill/My-Tone-Of-Voice | https://github.com/danielrosehill/My-Tone-Of-Voice | 跨格式收集真实样本、保留原始排版做参数化分析（段落长度/句子节奏） |
| jaimeschwarz/brandvoice | https://github.com/jaimeschwarz/brandvoice | 品牌声音治理理念（阶段化构建、以"拒绝什么"定义声音） |
