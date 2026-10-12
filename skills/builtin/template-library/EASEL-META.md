# Easel SKILL 元数据 — template-library

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | template-library |
| **所属层** | general |
| **自研** | 是（Easel 原创） |
| **脚本** | `scripts/templates.py`（纯 stdlib，python3.11） |

## 脚本说明

`scripts/templates.py` 把模板文件读写、`INDEX.json` 维护、`usage_count` 自增、
`{{var}}` 占位符提取与替换从 LLM 手动操作固化为确定性代码。
子命令：`save / list / get / edit / delete / use`。

- 模板文件与 `INDEX.json` 均**原子写入**（临时文件 + `os.replace`），增删模板同步更新索引
- 变量统一用 `{{var}}` 占位符：`save`/`edit` 自动提取变量清单，`use` 做替换并 `usage_count += 1`
- `use` 未填变量保留占位符并 stderr 警告；`delete` 默认 **dry-run**，`--apply` 才删并清索引
- `edit` 改分类会移动文件并清理旧文件

## 外部参考

脚本为**原创实现，未复制任何外部代码**；设计模式（分类目录 + INDEX 索引、Markdown 模板 +
变量替换、使用计数）参考了 frontmatter `references` 中列出的开源项目思路：

| 参考来源 | 借鉴点（仅设计思路） |
|----------|--------|
| [enescingoz/awesome-n8n-templates](https://github.com/enescingoz/awesome-n8n-templates) | 按分类分目录 + INDEX 索引 + 使用统计 |
| [danielmiessler/fabric](https://github.com/danielmiessler/fabric) | 每个模板是可复用 Markdown 文件，支持变量替换 |

> 更新时间: 2026-07-23
