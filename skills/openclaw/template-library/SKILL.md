---
name: template-library
description: >
  内容模板的保存、复用、管理。把成功的内容结构保存为模板，下次直接套用，支持模板分类和版本管理。
  当用户说"保存模板"、"用模板"、"模板管理"、"模板列表"、"复用上次的结构"、
  "常用模板"时使用。
  与 post-formatter（帖子框架）的区别：post-formatter 提供通用营销框架（PAS/AIDA/BAB），
  template-library 管理用户自己沉淀的个性化模板。
  与 social-content（社媒内容）的区别：social-content 从零生成内容，
  template-library 基于已有模板快速复制结构。
layer: general
---

# 模板库

> 保存、复用、管理内容模板 — 把成功经验变成可复制的结构

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| action | 是 | 操作类型：`save` / `use` / `list` / `edit` / `delete` / `get` |
| template_name | 视操作 | 模板名称（save / use / edit / delete / get 时必填） |
| source_file | 否 | 要保存为模板的源文件路径（save 操作时使用） |
| source_text | 否 | 要保存为模板的文本内容（save 操作时，与 source_file 二选一） |
| category | 否 | 模板分类：`xiaohongshu` / `weibo` / `douyin` / `zhihu` / `wechat` / `x` / `general` |
| variables | 否 | 模板变量的填充值，JSON 格式（use 操作时使用） |
| topic | 否 | 使用模板时的主题/话题（use 操作时使用） |
| profile_name | 否 | 绑定画像名称（有 Profile 上下文时自动填入） |

## 输出

### save 操作

```markdown
## 模板已保存

**名称**: {template_name}
**分类**: {category}
**存储位置**: templates/{category}/{template_name}.md

### 提取的模板结构
| 部分 | 结构描述 | 可变区域 |
|------|----------|----------|
| 标题 | 数字 + 痛点提问 | {{title_number}}, {{pain_point}} |
| 开头 | 反常识钩子 | {{hook_statement}} |
| 正文 | 3 段式（问题-方案-证据） | {{problem}}, {{solution}}, {{evidence}} |
| 结尾 | 行动号召 + 互动引导 | {{cta}}, {{question}} |

### 模板变量
共提取 {n} 个变量，下次使用时填入具体内容即可。
```

### use 操作

```markdown
## 模板应用结果

**使用模板**: {template_name}
**主题**: {topic}

---

{根据模板结构 + 变量填充生成的内容}

---

> 基于模板 `{template_name}` 生成，可进一步调整。
```

### list 操作

```markdown
## 模板库

**总数**: {n} 个模板

### 按分类

#### 小红书 ({n1} 个)
| 模板名 | 说明 | 变量数 | 使用次数 | 创建日期 |
|--------|------|--------|----------|----------|
| 种草对比 | 双产品对比种草结构 | 8 | 5 | 2026-07-10 |
| 教程步骤 | N 步教程卡片结构 | 6 | 3 | 2026-07-08 |

#### 微博 ({n2} 个)
| 模板名 | 说明 | 变量数 | 使用次数 | 创建日期 |
|--------|------|--------|----------|----------|
| 热点评论 | 热搜话题评论结构 | 5 | 7 | 2026-07-12 |

#### 通用 ({n3} 个)
| ... | ... | ... | ... | ... |
```

## 执行步骤

> 模板文件读写、INDEX.json 维护、usage_count 自增、`{{var}}` 提取与替换已固化为
> `scripts/templates.py`（纯 stdlib，argparse 子命令）。**LLM 只做意图路由、内容结构分析
> （把成功内容改写成含 `{{var}}` 占位符的模板正文）和结果呈现，不手写 JSON、不手动
> 增删文件。** 索引与模板文件均原子写入（临时文件 + rename），增删模板同步更新 INDEX.json。

### 操作路由

1. **解析用户意图**，映射到脚本子命令：
   - "保存模板" / "存为模板" → `save`
   - "用模板" / "套用模板" / "复用上次的结构" → `use`
   - "模板列表" / "有哪些模板" / "常用模板" → `list`
   - "编辑模板" / "改模板" → `edit`
   - "删除模板" → `delete`
   - "预览模板" / "看看模板" → `get`

### LLM 侧职责（save/use 前的分析）

2. **save 前**：LLM 阅读源内容，识别固定结构与可变区域，把具体值改写成 `{{变量名}}`
   占位符（如产品名 → `{{product_name}}`、痛点 → `{{pain_point}}`），再把改写后的正文
   通过 `--text` 或 `--file` 交给脚本。脚本负责提取变量清单、写文件、登记索引。
3. **use 前**：LLM 根据 topic/Profile 为每个变量推导填充值，通过 `--var`/`--vars` 传入。
   脚本负责替换、usage_count 自增、原子写回索引。

### 调用脚本

4. 统一入口（默认 `--root templates`）：
   ```bash
   S=skills/openclaw/template-library/scripts/templates.py
   python3 $S save 种草对比 --category xiaohongshu --description "双产品对比" \
           --text "标题：{{title}} A={{product_a}} vs B={{product_b}} CTA={{cta}}"
   python3 $S list --category xiaohongshu                  # 按分类列出，按使用次数降序
   python3 $S get 种草对比                                  # 预览内容 + 元信息
   python3 $S use 种草对比 --var title=夏日防晒 --var product_a=安耐晒
   python3 $S use 种草对比 --vars '{"title":"夏日防晒","cta":"点赞收藏"}'
   python3 $S edit 种草对比 --category general --description "改描述" --text "新正文 {{x}}"
   python3 $S delete 种草对比                                # 预览（dry-run）
   python3 $S delete 种草对比 --apply                        # 确认后真正删除
   ```

5. **脚本内置保证（无需 LLM 判断）**：
   - `save` 同名默认报错，需 `--force` 覆盖；`edit` 改分类会移动文件并清理旧文件
   - `use` 未填的变量保留 `{{占位符}}` 并在 stderr 警告，不会静默出错
   - `delete` 默认 **dry-run**，仅打印将删除的模板，加 `--apply` 才真正删并清理索引
   - 所有写操作原子化，增删模板与 INDEX.json 始终一致

6. **结果呈现**：把脚本输出整理成"输出"章节的 Markdown 返回给用户。

## Profile 感知

- **有 Profile 上下文时**：
  - save 操作自动将模板绑定到当前画像
  - list 操作优先显示当前画像的模板，其他画像的模板标记为"共享"
  - use 操作自动加载画像的 style.md 做语气适配
  - 模板文件的 frontmatter 中记录 `profile: {画像名称}`
- **无 Profile 上下文时**：
  - 所有模板标记为 `profile: shared`（共享模板）
  - list 操作显示全部模板，不做画像筛选
  - use 操作不做语气适配，直接输出模板填充结果

> 自研溯源与参考项目见同目录 `EASEL-META.md`。
