# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-seo-quality |
| **所属层** | publish |
| **来源类型** | 自研（内部合并 + 本地化重写） |
| **原始来源** | Easel 内部血缘：合并了原 skill-blog-seo-check（技术 SEO 校验）+ skill-seo-content（E-E-A-T 内容评估）。v0.3.0 本地化重写：从西方 web/blog SEO 重定位为国内平台原生搜索流量优化 |
| **参考项目** | 无 GitHub 库/工具。方法论引用：Google E-E-A-T「Who/How/Why」框架（仅保留于可选的网页/博客模式 `references/web-blog-seo.md`） |
| **许可** | 待核实 |

## 本地化重写记录（2026-07-23，v0.3.0）

- **问题**：原 SKILL 整套为西方 web/blog SEO（Meta 描述 120-155 字符、Open Graph、H1/H2 层级、URL/Slug、E-E-A-T/YMYL、Google Who-How-Why），对国内原生平台几乎不适用。
- **重定位**：改为「平台原生 SEO / 搜索流量优化」——覆盖小红书、抖音、知乎、公众号、B站、微博的站内搜索机制（关键词布局、话题标签搜索权重、封面/首帧文字关键词、搜索流量 vs 推荐流量取舍）。
- **web SEO 处理**：Meta/OG/Slug/E-E-A-T 收成可选的「网页/博客模式」下沉到 `references/web-blog-seo.md`，仅对会被搜索引擎抓取的内容（独立站/博客、被收录的公众号长文、冲搜索引擎的知乎回答）适用，并在 SKILL.md 明确适用边界。
- **知识下沉**：各平台搜索规则写入 `references/platform-search.md`；SKILL.md 主体 <200 行，只写流程与判断维度，不写死具体产品/行业案例。
- **description** 改为中文并反映新定位。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
