# 上下文预算诊断

`easel doctor` 会读一遍 OpenClaw 已保存的配置，把**声明的上下文窗口**和它隐含的
**默认参数下的参考压缩阈值**显示出来。诊断是只读的：不改配置、不回显凭证、也不声称运行时已加载。

```
OpenClaw 上下文预算（只读配置诊断，不计入环境就绪结果）
    └─ deepseek/deepseek-flash：声明 128,000 → 默认参数参考压缩阈值约 108,000
    └─ openai/mimo-v2.6-pro：未声明 contextWindow；阈值由 OpenClaw 推导
    └─ skills.limits：已设置 maxSkillsPromptChars=60,000，maxSkillsInPrompt=200
```

## 为什么声明值值得单独看一眼

`models.providers.*.models[].contextWindow` 不只是"描述模型能吃多少"。OpenClaw 用它做两件事：

**1. 影响压缩阈值。** 在常见默认预留参数下，参考换算公式是：

```
压缩阈值 = contextWindow − min(20_000, contextWindow × 0.25)
```

（`reserveTokens` 默认 16_384，先抬到下限 20_000，再按窗口的 25% 封顶。）

实际行为还依赖所装 OpenClaw 版本、当前预留参数、`agents.defaults.contextTokens`
上限与 `compaction.enabled` 开关。诊断会考虑已保存的全局 contextTokens 上限并提示
显式关闭压缩，但不会据此保证网关何时压缩；Agent 单独覆盖、运行时模型和上下文引擎
也可能改变结果。以上不是所有模型或版本的统一保证。

**2. 本地校验请求预算。** 声明值会被用来判断这次请求装不装得下；装不下就直接拒发，
请求根本到不了 provider：

```
Context window exceeded: estimated input 34934 leaves only 0 output tokens
within the 20000-token context.
```

所以声明值填错有两个方向的后果：

| 声明 | 后果 |
|---|---|
| 偏小 | 请求被本地拒绝，对话直接报错 |
| 偏大 | 可能延后压缩、增加上下文负担；缓存失效时可能增加未缓存输入成本 |

缓存命中与成本取决于供应商、缓存 TTL、提示前缀是否稳定及请求形态；不能仅凭窗口
大小断言缓存必然失效，或宣称调整后一定省钱。Issue #156 的表现是特定环境的实测，
不是所有后端的通用规律。

## 调整声明值

`setup.sh` 的 OpenAI 兼容分支支持环境变量覆盖：

```bash
OPENAI_CONTEXT_WINDOW=128000
OPENAI_MAX_TOKENS=16384
```

Gemini 分支现在同样支持 `GEMINI_CONTEXT_WINDOW` / `GEMINI_MAX_TOKENS`，默认值仍为
1048576 / 65535，不改变已有安装行为；它们不是所有 Gemini-compatible 模型的统一上限。
两项必须为正整数且输出上限不能超过声明窗口；按实际选用模型能力填写，不要虚报上限。

改完重跑 `setup.sh`（或直接改 `~/.openclaw-easel/openclaw.json` 的
`models.providers.*.models[].contextWindow`）并重启网关：

```bash
python -m easel gateway restart
python -m easel doctor   # 确认新阈值
```

## 技能目录预算

同一段诊断会报出 `skills.limits`。技能目录参与提示构建；部分版本使用
150 个技能 / 18,000 字符的默认预算。放不下时可能精简描述或截断技能清单，具体排序
与截断规则以所装版本为准。设 `skills.limits.maxSkillsPromptChars` 和
`maxSkillsInPrompt` 可以显式控制：

```jsonc
"skills": { "limits": {
  "maxSkillsInPrompt": 200,
  "maxSkillsPromptChars": 80000
}}
```

`setup.sh` / `setup.ps1` 在 OpenClaw 安装路径中，现在只为**缺失的叶子键**补默认
200 个 / 80,000 UTF-16 字符；如果内置目录的离线上界估算更大，默认数量随之增加，
字符预算至少为估算值加 8,192。当前 115 个内置技能的完整描述、路径可放入该预算，
但这不是网关运行时资格或可见性的保证，也不保证额外安装任意数量的第三方技能都装得下。
重跑保留所有已保存的 `skills.limits` 字段，包括用户主动设置的小预算或 0；不改 Agent
级覆盖、不启用循环保护、不限制工具调用次数或任务运行时间、不修改模型窗口默认值。

需要有意覆盖已保存的两项目录预算时，可在进程环境或项目 `.env` 中设置：

```bash
EASEL_MAX_SKILLS_IN_PROMPT=200
EASEL_MAX_SKILLS_PROMPT_CHARS=80000
```

两项分别生效，进程环境优先于 `.env`；未提供的项继续保留已存设置或补默认。
值须为非负十进制安全整数（不大于 9,007,199,254,740,991）；0 是主动设置零目录预算，
不是“不限”。输入无效、配置无法读取或目录设置使用未解析的 `$include` 时，不写任何
目录预算，给出降级警告。
写入经过 OpenClaw 自身的 `config set` 校验，不直接改写 JSON；不支持这些字段的版本
保留其当前配置并告警，安装默认继续（显式 `EASEL_SETUP_STRICT=1` 仍遵循严格模式）。
这不会修改开发者本机的配置；只有用户主动运行安装脚本才执行写入。

### 离线估算与实际可见性

doctor 只读源码 `skills/builtin/*/SKILL.md` 的元数据，使用已保存的 workspace 路径
（缺失时假设现代版本默认路径）估算完整目录的 UTF-16 字符上界。**它不是精确渲染器**：
不包含第三方技能，不判断环境依赖、资格过滤、Agent allowlist，也不读取运行时提示快照。
诊断标明预算低于估算的风险及 Agent 级 `skillsLimits` / `skills` 覆盖；较大的预算也只能
说明覆盖了该离线估算，不能证明全部技能已加载。按字母序截断的版本可能遗漏靠后的
技能（比如 `video-*`、`tts-*`），但不能凭源码估算列出实际遗漏的技能。

在用户自己的安装环境中可运行以下只读命令，再检查当前会话的实际系统提示快照或
网关截断警告，确认描述与核心发布/视频技能是否真的入提示：

```bash
openclaw --profile easel skills list --json
openclaw --profile easel skills check
```

清单的 Eligible 数量不等于系统提示中实际可见的数量。上游还可能根据本次上下文预算
再次压缩描述，这不受目录预算单独保证。已有会话可能保留旧快照，配置
调整后应按所装版本的机制重新加载网关/技能快照，必要时用新会话核验。
较大的目录会增加常驻提示体积；不承诺单机报告的 56% 节省或供应商缓存命中。

## 与工具结果裁剪的关系

OpenClaw 的 `agents.defaults.contextPruning`（如 `mode: "cache-ttl"`）可在受支持后端
裁剪旧工具结果。其效果取决于运行时支持、请求内容与配置；较长 TTL 可能保留更多上下文，
但不能保证某个 TTL（包括 5 分钟）让所有会话始终低于压缩阈值。

相关： [OpenClaw 循环保护诊断](tool-loop-diagnostics.md)
