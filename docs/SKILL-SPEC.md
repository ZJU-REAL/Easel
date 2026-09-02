# Easel SKILL 接口规范 v0.3

> 所有 Easel SKILL 遵循此规范。SKILL 是独立可调的原子能力单元。

## 目录结构

```
skills/
├── openclaw/              五层 SKILL（发现/策划/制作/发布/归因），由 OpenClaw 直接执行
└── shared/                跨 SKILL 共享工具（脚本、配置、依赖）
```

每个 SKILL 是一个独立目录：

```
skill-xxx/
├── SKILL.md               必须 — 执行流程（精简，< 200 行）
├── references/            可选 — 领域知识（按需加载，不常驻 prompt）
│   └── *.md
├── scripts/               可选 — 可执行脚本（运行时调用，代码不进 prompt）
│   └── *.py / *.sh
└── tests/                 可选 — 测试用例
    ├── test1.prompt           输入
    └── test1.expected         期望输出（关键字匹配）
```

### 三层加载机制

| 层 | 内容 | 加载时机 | token 开销 |
|---|---|---|---|
| Metadata | frontmatter（name, description） | 常驻，用于 SKILL 路由 | 极小 |
| Instructions | SKILL.md 主体 | SKILL 被触发时 | 中等 |
| Resources | references/ + scripts/ | SKILL 执行中按需读取 | 按需 |

**核心原则：SKILL.md 只写"怎么做"，领域知识写在 references/ 里。**

### 共享工具层

`skills/shared/` 存放多个 SKILL 共用的工具脚本和配置（如 ffmpeg 封装、API client、通用模板）。SKILL 通过相对路径引用。

## SKILL.md 格式

```markdown
---
name: skill-xxx
description: >-
  用中文说明本 SKILL 做什么、用户在什么场景或用哪些说法时应触发，以及与相邻 SKILL 的边界。
layer: discover / plan / produce / publish / attribute / general
---

# SKILL 名称

> 一句话描述

## 输入

描述接受什么输入

## 输出

描述输出格式（字段说明，不写具体值）

## 执行步骤

1. 步骤（引用 references/ 下的文件获取领域知识）
2. ...

## Profile 感知

有 Profile 时怎么用，没有时怎么退
```

**frontmatter 规则：**
- 只保留 `name`、`description`、`layer` 三个常规字段，减少常驻路由上下文和无效元数据
- `description` 是 Agent 的主要触发依据，必须用中文同时写清能力、触发场景/用户说法和相邻 SKILL 边界；可使用 YAML 块标量
- `layer` 标明所属层：五个流水线层 `discover / plan / produce / publish / attribute`，外加 `general`（跨切面基础设施，如画像管理、产物管理、模板库——不属于任一流水线阶段）
- 仅在 OpenClaw 需要判断操作系统、二进制、环境变量或安装方式时，允许增加 `metadata.openclaw` 运行时清单
- 禁止 `version`、`profile_aware`、`self_developed`、普通 `metadata.trigger/impl/source`、`allowed-tools`、`tags`；来源信息放 `EASEL-META.md`，执行约束和 Profile 行为写正文
- SKILL.md 主体控制在 200 行以内

全库校验：

```bash
python scripts/validate_skills.py
python scripts/validate_skill_commands.py
```

第一条检查 frontmatter、资源链接、输出和发布安全契约；第二条解析 Skill 中的 Python 命令，对照脚本的 argparse 定义检查路径与参数漂移。

## 调用方式

```bash
easel skill check-compliance -i "内容"
easel skill check-compliance -i "内容" -p 画像名
```

所有调用统一走 OpenClaw agent，由 OpenClaw 读对应 SKILL、按 AGENTS.md 规则自己执行。

## SKILL 同步

`openclaw/sync.sh` 把 `skills/openclaw/` 与 `skills/shared/` 同步到 `~/.openclaw/workspace-easel/`。

## Profile 注入

- OpenClaw 直接读取 Profile 文件夹，按 AGENTS.md 凝练后用于产出。
- 检测标记：`=== EASEL ACCOUNT PROFILE ===`

## 产物管理

**目录布局规约**（一个内容项目 = `outputs/<主题>/` 一个目录）：
```
outputs/<主题>/
├── note.md / final.mp4 / card_1.png   成品（用户要发/读的最终文件，放项目根）
├── assets/                            中间件：frames/ clips/ 构建脚本 原始素材 草稿 重复文件
└── .easel.json                    唯一元数据：展示头 + 层间产物契约（隐藏）
```
- **成品放项目根、中间件进 `assets/`**：前端「内容库」据此把成品与素材分区展示。
- 项目名用人类可读主题（中文可），禁泛名（xhs/test）；测试/临时产物写 `outputs/_scratch/`。
- 任何新脚本在创建产物前必须调用 `skills/shared/scripts/output_paths.py` 的 `validate_output_path()`；系统写入需显式传 `allow_system=True`，且只能使用已注册的 `_` 路径。
- 系统状态一律 `_` 前缀目录（`_login/_publish/_analytics/_profile_build/_scratch`）；
  **内容库只展示项目目录**，忽略根目录散文件与系统目录。

### 元数据契约（`.easel.json`）

单一元数据文件（隐藏），由 `skills/shared/scripts/manifest.py` 读写（带 selftest），含两部分：

**① 展示头**（供前端「内容库」富展示：标题/平台/状态/封面/标签 + 成品高亮）。收尾登记：
```bash
python skills/shared/scripts/manifest.py meta --topic <主题> \
  --title "<人类可读标题>" --platform 小红书 --kind cards --status draft \
  --tags "标签1,标签2" --cover cover.png --deliverables card_1.png,card_2.png
```
`kind` 取 `article/xhs-note/video/cards/poster/audio/other`；`status` 取 `draft/ready/published`。
`meta` 为 upsert：只改传入字段、其余保留；缺省有兜底（title→topic、cover→首张成品媒体）。

**② 层间产物契约 steps[]**：纵向编排跨层时，上游产物路径与关键结论通过 manifest 结构化传递，下游无需重新推导。
```bash
# 上游每步产出后登记（失败也登记 --status failed，供断点续跑）
python skills/shared/scripts/manifest.py record --topic <主题> \
  --layer plan --skill video-script --profile <画像> \
  --outputs script.md,brief.md --summary "3 幕结构，钩子在前 3s"

# 下游步骤前取上游最近一步作为输入
python skills/shared/scripts/manifest.py latest --topic <主题> [--layer plan]
python skills/shared/scripts/manifest.py read   --topic <主题>   # 看全链路
```

Schema：`{topic, profile, created, updated, title, summary, platform, kind, status, tags[], cover, deliverables[], steps:[{layer, skill, at, status, outputs[], upstream[], summary}]}`。
`layer` 取 `discover/plan/produce/publish/attribute/general`；step `status` 取 `done/failed`（默认 done）。契约稳定、可被任一层消费。

> 存量目录用 `scripts/migrate_outputs.py`（dry-run→apply 回填展示头，`--reorganize` 归整中间件进 assets/）收敛；测试残渣用 `scripts/cleanup_outputs.sh` 清理。

## 出站内容安全闸门（发布/评论类 SKILL 契约）

任何把文本**发到公开平台**的脚本（xhs/douyin/web_publisher/xhs_comment/zhihu_answer 等），在真发（`--exec`）前**必须**过 `skills/shared/scripts/content_guard.py` 的 `guard_or_die(...)`。**分两级**（见 `BLOCK_CATEGORIES`）：**BLOCK 级**=真·敏感信息（API key、内部 URL/域名、代理 IP、内部路径、env 名 + `.env` 真值）→ **fail-closed 退出码 7 阻止发布**；**WARN 级**=AI 措辞（由 AI 生成/OpenClaw/Claude/system prompt/大模型）与模型名（claude-*/gpt-image-2）→ 论文解读、AI 科普里可能是正常内容，**只提醒不拦截**。dry-run 全部只告警。放行硬拦须显式 `--allow-unsafe`。新增发布类脚本照此接入。

**有界编排约定**：manifest 只当**薄索引**（`summary` 一行给编排层路由 + `outputs[]` 指路径），**不复制内容**。跨层要传的东西分两类，都落 `outputs/<主题>/` 成文件，不留在对话里：
- **产物（载荷）**：脚本/图/视频/文案 → 写文件，`--outputs` 指过去，下游按路径读全文。
- **决策/意图**（基调、受众、钩子、do/don't 等不体现在产物里的）→ 写进 `outputs/<主题>/brief.md`（策划层的创作简报），同样列入 `--outputs`。

## 测试

SKILL 可带 `tests/` 目录，用低成本模型验证基本功能：
- `test1.prompt` — 测试输入
- `test1.expected` — 期望输出关键字/pattern

## 设计约束

1. **独立可调** — 不依赖其他 SKILL
2. **无 Profile 也能用** — Profile 是加持不是前提
3. **接口一致** — 输出格式稳定，可被下游消费
4. **SKILL.md 精简** — 执行流程在主文件，领域知识放 references/
5. **泛化** — 定义规则和模式，不给具体 case 示例
