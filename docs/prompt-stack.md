# Easel Prompt Stack

> Easel Agent 的 prompt 由多层文件组合而成，与所选执行引擎解耦，每层职责明确、互不干扰。

## 组合顺序

```
Layer 1: SOUL.md         人格 + 能力总览（搭子语气、沟通风格、对五层能力的自我认知）
Layer 2: AGENTS.md       分工规则 + 编排逻辑 + Plan Mode + 制作层执行流程
Layer 3: 运行时说明       当前引擎、项目路径与权限（OpenClaw 同步时另生成 CONTEXT.md）
Layer 4: SKILL           被触发时加载 SKILL.md + 按需读取 references/ 下的文件
```

> **画像（Profile）如何进入 prompt**：不再写全局 USER.md（会有并发竞态）。CLI 与 Web 统一把画像**作为消息内联**传入，由当前 Agent 按 AGENTS.md 自行读取 `profiles/<X>/` 并凝练。每个请求自包含，无全局文件污染。
> - **Web / skill**（单轮）：每条消息前缀 `我当前使用的画像是「X」。`（`easel/persona.py:persona_prefix`）。
> - **CLI `easel chat`**（多轮交互）：选画像后通过所选底座的原有消息通道注入同一前缀，画像随原生 session 历史留存供后续 turn 沿用（超长会话被压缩后可能丢，属已知取舍）。
> - 三入口的画像逻辑统一收敛到 `easel/persona.py`（`list_personas` / `load_profile_text` / `persona_prefix`）。

> **记忆作用域**：Easel 不使用任何引擎工作区的全局 `MEMORY.md` 承载账号知识；OpenClaw 的该文件由同步脚本保持为空。账号长期记忆只存放在 `profiles/<当前画像>/memory.md`，每个会话按自身绑定的画像直接读取。通用模式不读取任何画像记忆，也不通过动态改写全局文件切换画像。

共享源文件位于 `agents/workspace/`。OpenClaw 沿用 `bash agents/sync.sh` 同步到它的隔离工作区；
Codex 沿用 `developerInstructions`，OpenCode / 通用 ACP 沿用消息前缀注入方式，加载同一组 Markdown。
各适配器追加当前引擎、实际 Easel 根目录与权限说明，不将 OpenClaw 的能力假定为其它引擎的能力。
原生进程复用期间共享说明变更会使缓存失效，下一轮重新加载说明并续接原有会话。

## 各层说明

### Layer 1 — SOUL.md（常驻）
定义 agent 的**人格**（创作者的社媒内容"搭子"：懂策略、能上手、务实诚实）、沟通方式，以及一份**能力总览**，让 agent 心里有数、遇事先想"怎么帮他做成"而不是"我做不了"。通过对应适配器的常驻指令或每轮消息前缀提供。
保持精简且**类目级**：能力总览按五层写"能做什么"，**不写具体 skill 名**（避免像 weibo 那样过时）、也**不写"去调某某 skill"这类操作机制**（那属 AGENTS 与技能库）；语气是好伙伴，不是工具说明书。

### Layer 2 — AGENTS.md（常驻）
核心业务逻辑：五层分工、Plan Mode 触发规则、纵向编排原则、制作层执行全流程。
通过对应适配器的常驻指令或每轮消息前缀提供。是最重要的文件。

### Layer 3 — 运行时说明（半静态）
OpenClaw 由 `agents/sync.sh` 生成运行时项目根和 CONTEXT.md，换机器后重新同步。
Codex / OpenCode / ACP 每次从请求构建同源运行时说明，并以实际 Easel 根目录启动原生进程。
所有引擎跑项目脚本前都从这里确认项目根路径，**先 `cd` 到该目录再跑脚本**。

### Layer 4 — SKILL（按需）
只有当 SKILL 被触发时才加载。加载顺序：
1. SKILL.md 主体（执行流程）
2. references/ 下的文件（按 SKILL.md 中的引用按需读取）
3. scripts/ 下的脚本（执行时调用，脚本本身不进 prompt）

> 五层 SKILL（含制作层）由当前 Agent 按需读取并直接执行，产出成品到 `outputs/`。
> OpenClaw 保留工作区技能同步，其他底座直接读取项目 `skills/builtin/` 和 `skills/shared/`。

## 设计原则

- 每层只管自己的事，不越界
- 常驻层（1-3）保持精简，控制 token 消耗
- SKILL 层按需加载，不用的不加载
- references/ 里的文件只在 SKILL 执行过程中被读取，不常驻
