# Easel SKILL 元数据 — asset-manager

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | asset-manager |
| **所属层** | general |
| **自研** | 是（Easel 原创） |
| **脚本** | `scripts/assets.py`（纯 stdlib，python3.11） |

## 脚本说明

`scripts/assets.py` 把"有副作用、需状态一致"的文件操作从 LLM 手动 find/grep/mv/改 JSON
固化为确定性代码。子命令：`scan / search / archive / tag / list / report`。

- 索引 `INDEX.json` 与标签 `tags.json` 均**原子写入**（临时文件 + `os.replace`）
- `archive` 默认 **dry-run**，`--apply` 才移动；**幂等**（source==target / 目标已存在且内容
  一致 / 已在归档结构下 → 跳过；内容不同 → 标 CONFLICT 绝不覆盖）
- 平台/类型/日期由文件名与扩展名启发式推断，日期优先取文件名中的 `YYYYMMDD`

## 外部参考

脚本为**原创实现，未复制任何外部代码**；设计模式（本地优先索引、元数据标签、目录树归档）
参考了 frontmatter `references` 中列出的开源项目思路：

| 参考来源 | 借鉴点（仅设计思路） |
|----------|--------|
| [unopim/unopim-digital-asset-management](https://github.com/unopim/unopim-digital-asset-management) | 目录树结构管理、元数据标签系统 |
| [biagiomaf/smart-comfyui-gallery](https://github.com/biagiomaf/smart-comfyui-gallery) | 本地优先索引、按关键词/标签搜索 |

> 更新时间: 2026-07-23
