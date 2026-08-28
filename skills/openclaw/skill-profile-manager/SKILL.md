---
name: skill-profile-manager
description: >
  管理账号画像全生命周期：创建空白画像、编辑六维字段、更新记忆、切换、导出和对比。
  当用户说“新建/编辑/更新/切换/导出/对比画像、写进画像记忆”时使用。
  首次从社媒数据生成画像用 skill-profile-builder；只提炼语言风格用 skill-voice-builder；品牌首次入驻引导用 skill-brand-onboarding。
layer: general
---

# 账号画像管理器

> 创建、编辑、记忆更新、导出、对比 — 画像的全生命周期管理

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| action | 是 | 操作类型：`create` / `edit` / `memory-update` / `export` / `diff` / `list` / `switch` |
| profile_name | 视操作 | 画像名称（create 时必填，list 时不需要） |
| field | 否 | 要编辑的文件：`identity` / `style` / `audience` / `platforms` / `preferences` / `memory` |
| content | 否 | 要写入的内容（edit / memory-update 时使用） |
| profile_b | 否 | 第二个画像名称（diff 操作时必填） |
| data_source | 否 | 记忆更新的数据来源：用户口述 / 数据报告 / 帖子反馈 |

## 输出

### create 操作

输出新画像目录结构确认：

```markdown
## 画像创建完成

**画像名称**: {profile_name}
**目录**: profiles/{profile_name}/

### 已创建文件
| 文件 | 状态 | 说明 |
|------|------|------|
| identity.md | ✅ 已填写 | 定位、差异化、内容方向 |
| style.md | ✅ 已填写 | 语气、开头结构、视觉风格 |
| audience.md | ✅ 已填写 | 人口统计、兴趣、痛点 |
| platforms.md | ⬜ 待补充 | 平台账号、内容格式 |
| preferences.md | ⬜ 待补充 | 合规规则、红线 |
| memory.md | ⬜ 空 | 将随使用积累 |
```

### diff 操作

输出两个画像的逐文件对比表：

```markdown
## 画像对比：{profile_a} vs {profile_b}

| 维度 | {profile_a} | {profile_b} | 差异摘要 |
|------|-------------|-------------|----------|
| 定位 | ... | ... | ... |
| 风格 | ... | ... | ... |
| 受众 | ... | ... | ... |
| 平台 | ... | ... | ... |
| 偏好 | ... | ... | ... |
```

### list 操作

```markdown
## 当前画像列表

| 画像 | 完整度 | 最后更新 | 记忆条数 |
|------|--------|----------|----------|
| 科技数码达人 | 85% | 2026-07-15 | 12 |
| 搞笑整活博主 | 60% | 2026-07-10 | 3 |
```

## 执行步骤

### 操作路由

1. **解析用户意图**：从用户输入识别 action 类型
   - "创建画像" / "新建账号" → `create`
   - "编辑画像" / "改一下画像" → `edit`
   - "写进画像" / "画像记忆" / "记住这个" → `memory-update`
   - "导出画像" → `export`
   - "画像对比" / "两个画像比较" → `diff`
   - "有哪些画像" / "画像列表" → `list`
   - "切换画像" / "用另一个画像" → `switch`

### create 流程

2. **检查画像是否已存在**：读取 `profiles/` 目录，确认同名画像不存在
3. **复制模板**：将 `profiles/_template/` 复制为 `profiles/{profile_name}/`
4. **引导填写核心信息**：依次向用户提问，收集以下信息
   - **identity.md**：你是谁？做什么内容？和别人有什么不同？
   - **style.md**：你的语言风格是什么？正式/轻松/搞笑？常用口头禅？
   - **audience.md**：你的目标受众是谁？年龄、兴趣、痛点？
5. **写入文件**：将收集到的信息按模板格式写入对应文件
6. **提示后续**：告知用户可后续补充 platforms.md 和 preferences.md

### edit 流程

7. **定位文件**：根据 field 参数确定要编辑的文件路径 `profiles/{profile_name}/{field}.md`
8. **读取当前内容**：展示该文件的当前内容给用户确认
9. **应用修改**：根据用户指示修改指定字段，保持文件其他部分不变
10. **确认变更**：输出修改前后的 diff 摘要

### memory-update 流程

11. **读取现有记忆**：读取 `profiles/{profile_name}/memory.md`
12. **格式化新记忆条目**：按以下格式追加
    ```
    ### {日期} — {来源标签}
    - 发现：{具体发现}
    - 行动建议：{可执行的建议}
    ```
13. **去重检查**：与已有记忆条目比对，避免重复记录
14. **追加写入**：将新条目追加到 memory.md 末尾

### export 流程

15. **汇总画像**：读取画像目录下所有 .md 文件
16. **生成摘要卡片**：合并为一份结构化的画像摘要（Markdown 格式）
17. **输出到 outputs/**：保存为 `outputs/profile-export-{profile_name}-{日期}.md`

### diff 流程

18. **读取两个画像**：分别读取 `profiles/{profile_a}/` 和 `profiles/{profile_b}/` 下所有文件
19. **逐维度对比**：按 identity / style / audience / platforms / preferences 五个维度对比
20. **生成差异表**：输出结构化对比表，高亮关键差异点

### list 流程

21. **扫描 profiles/ 目录**：列出所有子目录（排除 `_template`）
22. **计算完整度**：检查每个画像的 6 个文件是否有实质内容（非空非模板）
23. **输出列表**：按完整度排序输出

## Profile 感知

这个 SKILL 本身就是 Profile 的管理工具：

- **有 Profile 上下文时**：默认操作当前激活的画像，edit / memory-update 不需要再指定 profile_name
- **无 Profile 上下文时**：list 操作展示所有可用画像，其他操作必须显式指定 profile_name
- **首次使用时**：如果 profiles/ 目录下没有任何画像（只有 _template），自动进入 create 流程

> 自研溯源与参考项目见同目录 `EASEL-META.md`。
