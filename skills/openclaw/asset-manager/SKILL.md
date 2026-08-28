---
name: asset-manager
description: >
  outputs/ 目录下的产物管理：按日期/平台/类型归档、打标签、搜索历史内容、生成素材清单。
  当用户说"整理素材"、"归档"、"找之前的内容"、"搜索历史"、"素材管理"、
  "outputs 整理"、"之前做的"时使用。
  与其他 produce 层 SKILL 的区别：produce 层负责生成内容，
  asset-manager 负责生成后的产物管理（归档、检索、标签）。
layer: general
---

# 素材管理器

> outputs/ 产物的归档、标签、检索 — 让历史内容随时可查可复用

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| action | 是 | 操作类型：`scan` / `search` / `archive` / `tag` / `list` / `report` |
| query | 否 | 搜索关键词（search 操作时使用） |
| path | 否 | 指定操作的文件或目录（默认 `outputs/`） |
| tags | 否 | 要添加的标签列表，逗号分隔（tag 操作时使用） |
| filter_platform | 否 | 按平台筛选：`xiaohongshu` / `weibo` / `douyin` / `zhihu` / `wechat` / `x` |
| filter_type | 否 | 按类型筛选：`image` / `video` / `text` / `card` / `poster` / `script` |
| filter_date | 否 | 按日期筛选：`today` / `this-week` / `this-month` / `2026-07` / `2026-07-15` |
| profile_name | 否 | 按画像筛选（有 Profile 上下文时自动填入） |

## 输出

### list 操作

```markdown
## 素材清单

**目录**: outputs/
**统计**: 共 {n} 个文件，{size} MB

| 文件名 | 类型 | 来源 SKILL | 创建日期 | 标签 |
|--------|------|-----------|----------|------|
| hero-poster-科技新品-20260715.png | 海报 | poster-hero | 2026-07-15 | #科技 #新品发布 |
| xhs-card-护肤-01.png | 卡片 | card-xiaohongshu | 2026-07-14 | #护肤 #小红书 |
| ... | ... | ... | ... | ... |
```

### search 操作

```markdown
## 搜索结果："{query}"

找到 {n} 个匹配项：

| 文件 | 匹配位置 | 相关度 | 创建日期 |
|------|----------|--------|----------|
| outputs/主题名/科技-对比评测.md | 文件名+内容 | ★★★ | 2026-07-12 |
| outputs/主题名/科技产品-开箱.md | 内容 | ★★☆ | 2026-07-10 |
```

### report 操作

```markdown
## 素材统计

### 按类型分布
| 类型 | 数量 | 占比 |
|------|------|------|
| 图片 | 45 | 38% |
| 文案 | 32 | 27% |
| 视频脚本 | 20 | 17% |
| 卡片 | 15 | 13% |
| 海报 | 6 | 5% |

### 按平台分布
| 平台 | 数量 | 最近产出 |
|------|------|----------|
| 小红书 | 30 | 2026-07-15 |
| 微博 | 25 | 2026-07-14 |
| 抖音 | 20 | 2026-07-13 |

### 产出趋势（近 30 天）
| 周 | 产出数量 | 日均 |
|----|----------|------|
| 本周 | 12 | 1.7 |
| 上周 | 18 | 2.6 |
| 上上周 | 8 | 1.1 |
```

## 执行步骤

> 所有有副作用、需状态一致的文件操作（扫描索引、移动归档、维护 tags.json）已固化为
> `scripts/assets.py`（纯 stdlib，argparse 子命令）。**LLM 只做意图路由和结果呈现，不手动
> find/grep/mv 或手写 JSON。** 索引与 tags 用原子写入（临时文件 + rename）。

### 操作路由

1. **解析用户意图**，映射到脚本子命令：
   - "整理素材" / "归档" / "outputs 整理" → `archive`
   - "打标签" / "标记" → `tag`
   - "找之前的" / "搜索历史" / "之前做的" → `search`
   - "素材列表" / "看看有什么" → `list`
   - "素材统计" / "产出报告" → `report`
   - （检索前若索引可能过期，先跑一次 `scan`；search/list 在索引缺失时会自动扫描）

### 调用脚本

2. 统一入口（默认 `--root outputs`）：
   ```bash
   S=skills/openclaw/asset-manager/scripts/assets.py
   python3 $S scan                                    # 生成/更新 INDEX.json
   python3 $S search "关键词" --platform xiaohongshu --type card --date this-week
   python3 $S search --tag 护肤,种草                   # 标签需全部命中
   python3 $S list --platform weibo                    # 素材清单
   python3 $S report                                   # 类型/平台/日期分布
   python3 $S tag "招人贴/card_1.png" --add 护肤,小红书 --remove 草稿
   python3 $S archive                                  # 预览归档计划（dry-run）
   python3 $S archive --apply                          # 确认后真正移动
   python3 $S archive 招人贴 --apply                    # 只归档某目录/文件
   ```

3. **归档规则**：文件被移动到 `outputs/{日期}/{平台}/{类型}/`。日期取自文件名中的
   `YYYYMMDD`/`YYYY-MM-DD`，无则取 mtime；平台/类型由文件名与扩展名推断。

4. **安全保证（脚本内置，无需 LLM 判断）**：
   - `archive` 默认 **dry-run**，只打印 `MOVE`/`CONFLICT`/`skip` 计划；加 `--apply` 才移动
   - **幂等**：source==target 跳过；目标已存在且内容一致跳过；已在 `日期/平台/...` 结构下的不再归档
   - 目标已存在但内容不同 → 标 `CONFLICT` 跳过，**绝不覆盖**
   - 移动时 tags.json 的 key 自动跟随新路径

5. **结果呈现**：把脚本输出整理成"输出"章节的 Markdown 表格返回给用户。
   归档前务必先展示 dry-run 计划、得到确认后再 `--apply`。

## Profile 感知

- **有 Profile 上下文时**：
  - 读取 `identity.md` / `platforms.md` 获取账号名与平台，作为 `--tag`（画像名）或
    `--platform` 传给脚本，缩小 search/list 范围
  - 素材若按画像分目录存放，`archive <画像目录> --apply` 只归档该画像的产物
- **无 Profile 上下文时**：
  - 显示 outputs/ 下所有素材，不做画像筛选
  - 附注："如提供账号 Profile（含 identity.md / platforms.md），可按账号和平台维度管理素材"

> 自研溯源与参考项目见同目录 `EASEL-META.md`。
