# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | gzh-design |
| **所属层** | produce |
| **来源类型** | 第三方开源集成 |
| **原始来源** | GitHub: isjiamu/gzh-design-skill（微信公众号排版技能） |
| **GitHub 地址** | https://github.com/isjiamu/gzh-design-skill |
| **作者/版权** | 甲木 (Jiamu) × 摸鱼小李 (Moyu Xiaoli)，2026 |
| **许可** | 见目录内 LICENSE（随原项目许可） |
| **功能描述** | Markdown/docx/pdf/纯文本 → 可直接粘贴进公众号编辑器的 HTML；自定义主题组件库（references/theme-index.md 为单一来源）+ 校验脚本（scripts/validate_gzh_html.py 等），纯 Python 标准库无外部依赖。 |
| **自包含** | 是（SKILL.md + references + scripts + assets 完整） |

> 集成时间: 2026-09-14
> 用途: 与 skill-wechat-publisher 配合——gzh-design 负责把文章排成公众号 HTML，publisher 负责发到草稿箱/数据回收。
> 备注: 补了 `layer: produce` 到 frontmatter；其余保持上游原样（仅删除 .git/.github）。
