# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | ecom-details-image |
| **所属层** | produce |
| **来源仓库** | liangdabiao/ecom-details-image |
| **GitHub 地址** | https://github.com/liangdabiao/ecom-details-image |
| **Star 数** | ~200+ |
| **功能描述** | 电商商品图：25种场景（主图/场景图/详情图），GPT-Image-2 |
| **SKILL.md 行数** | 108（Wave4 瘦身后，原 620） |
| **文件总数** | 30 |
| **自包含** | 需生图 API（默认 GPT-Image-2，可经 IMG_MODEL 切换） |
| **备注** | 京东/淘宝/拼多多三平台适配 |

> 收录时间: 2026-07-16
> 用途: Easel SKILL 验证测试

## Wave4 瘦身说明（2026-07-23）

原 SKILL.md 620 行严重超出 SKILL-SPEC <200 行规范，将大段内联领域知识下沉到 `references/`，SKILL.md 只保留执行流程 + references 指针 + `scripts/generate_image.py` 调用说明。脚本与 frontmatter 未改动。

新建 references：

- `references/templates.md` — 25 个场景模板匹配表、使用方式、风格变体速查
- `references/image-gen-rules.md` — 通用 Prompt 结构、GPT-Image-2 铁律、精简原则、Anti-AI 技巧、常见翻车点防护
- `references/campaign-style-lock.md` — 多图任务的 Campaign Style Lock 规则与默认模板
- `references/pdp-sequences.md` — 转化驱动诊断、主图/详情页序列、多角度镜头、详情页信息图结构、字体搭配

（`references/templates/` 下 25 个 JSON 模板为原有资产，未改动。）
