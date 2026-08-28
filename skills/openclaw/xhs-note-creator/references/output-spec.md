# 小红书笔记输出目录规范

xhs-note-creator 的产物统一保存到仓库的 `outputs/xhs/` 目录下，便于查找、归档与发布。与 SKILL.md Step 7 的落盘结构一致。

## 目录结构

```
outputs/xhs/{YYYY-MM-DD}/{短标题}_{YYYYMMDDHHmm}/
├── {完整标题}.md          # 长文原稿（正文，供拆卡/caption 使用）
├── meta.json              # 元数据（卡片/分镜/caption/hashtags/合成策略）
├── images/                # 最终卡图 / 封面
│   └── card_01_cover.jpg ...
└── reference/             # 素材与生成过程
    ├── materials.json     # 素材清单（如有用户素材）
    ├── search_results.json# 参考搜索结果
    └── summary.md         # 参考资料摘要
```

## 文件命名规则

**目录名和文件名**中以下字符必须去除或替换为 `_`：

- 冒号 `：` `:`、问号 `？` `?`、感叹号 `！` `!`、各类引号、斜杠 `/` `\`、星号 `*`、尖括号 `<` `>`、竖线 `|`、省略号、破折号 `——`
- 空格 → `_`；连续的 `_` 合并为单个 `_`

目录名用精简短标题（≤15 字，中文 + 字母 + 数字 + 下划线 + 连字符）；文件名可用较长标题，同样不含上述特殊字符。归一化可用 `scripts/normalize_slug.py`。

## 时间与时区

- 日期用 **Asia/Shanghai** 时区；日期目录 `YYYY-MM-DD`；时间戳 `YYYYMMDDHHmm`（精确到分钟）。

## Markdown 正文约定

### 不写 H1 标题

`.md` 正文**不写 H1**（`# 标题`）——小红书有独立标题字段，正文再写 H1 会重复。正文从 H2（`## 章节标题`）开始，标题存入 `meta.json.title`。

### 参考来源不写入正文

正文末尾**不要**附"参考来源/参考文献/References"。参考资料只放 `reference/` 目录，正文保持干净。

### 图片引用

图片存 `images/`，Markdown 用相对路径 `![描述](images/card_01.jpg)`。最终 `.md` **不允许**保留 `【插入图片：…】` 占位符——写作时同步完成配图（见 `image-sourcing.md`）。

### 去 AI 化

遵守去 AI 味规则（完整见 `../../text-polisher/references/zh-ai-markers.md`）：

- **避免**：首先 / 其次 / 再次、通过……来……、不仅……更……、综上所述
- **推荐**：短句、口语化、具体例子、个人感受、碎片化叙事、疑问句
