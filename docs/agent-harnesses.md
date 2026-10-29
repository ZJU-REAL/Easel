# Agent 底座接入与本地测试

Easel 将执行底座与模型供应商分开。Web **设置 → 模型配置 → 对话 → 执行引擎**
统一选择仅聊天模式、OpenClaw、OpenCode、Codex 或通用 ACP。
标准安装默认安装并使用 OpenClaw；设置中可切换到已安装的其它底座，不自动安装 Codex / OpenCode。
仅使用 `--api` 安装或没有任何 Agent 配置的环境回退到仅聊天模式。
已经保存的底座、旧版连接配置和已有 OpenClaw 安装继续生效，不自动切换。
改动目前用于本地验证，不要求迁移原有凭证。

底座决定谁负责执行对话和工具，连接由适配器自动管理。Codex、OpenCode、通用 ACP
不需要再选择 API / OpenClaw 连接方式；模型供应商与认证沿用各自原生 CLI 配置。
原有 API 直连整合为执行引擎列表中的 **仅聊天模式**，不再单独展示连接方式。
选择框右侧的说明图标支持悬停和键盘聚焦，说明它直接调用模型 API、不启动 Agent，
适合问答、写作和内容分析，但不能运行本机工具或技能。API 地址、模型与 Key 在下方配置。
媒体通道配置独立，不随对话底座迁移。这里保留原有配置键和会话历史，避免删入口造成回归。

## 原生客户端交互并发上限

Easel 默认不增加工具调用次数或任务总运行时间预算。可选的 OpenClaw 工具预算插件
只有显式配置次数和时长后才注册限制钩子；未配置或空配置保持不限制。
这不改变底座既有超时、权限或以下协议资源保护。

Codex / ACP 的每条原生连接最多保留 64 个尚未完成的客户端请求（例如权限确认）。
收到超限请求时，本轮以明确错误结束并关闭连接，清理待处理交互；会话池不会复用此连接。
完成的请求会释放名额，不累计计入后续批次。此限制不自动重试或重新发送原始提示词。
它是协议资源保护，不是工具调用预算，也不证明外部工具副作用已经撤销。

私有 stdio JSON-RPC 单行消息上限为 64 MiB（UTF-8 字节，不含换行），允许 ACP
`session/load` 回放超过旧 4 MiB 上限的合法历史。超过上限时明确报告消息过大并关闭
连接，不自动截断、重发提示词或改建新会话；更大的历史应由 Agent 分块发送。
其它读取异常只显示异常类型，不附原始消息、异常正文或子进程 stderr，避免泄露
对话和凭证。无效 JSON / UTF-8 仍按协议错误终止；客户端请求的 64 并发保护不变。
原生请求解析、格式或参数错误（含 `INVALID_REQUEST`）使用固定提示，不回显原生
错误正文或 `data`；其它原生错误仍沿用限长与环境凭证脱敏。

## OpenClaw 执行侧工具限额（可选）

需要限制每轮实际工具准入次数与执行时限时，可在 Easel 使用的 Gateway 配置中启用
[工具预算插件](../agents/tool-budget/README.md)。插件在原生执行前预占额度，失败不退款；
超限取消只针对同一会话中的指定执行，保留并发任务。文档包含配置、运行时核验和真实
Gateway 验收命令，验证版本为 OpenClaw 2026.10.2 / Node 24.19。
本插件不会随安装自动启用，不覆盖其他底座，也不在重启后保留预算。不要将已保存配置
或单纯安装了 CLI 当成活动执行端的证明；启用前须按插件文档核验当前 Gateway。

## 设计与 PR #40

PR #40 的运行时适配层思路值得保留，但其基于较早的主分支，直接覆盖会丢失后续的
Windows 启动、API 直连、会话锁和登录修复。这次不整块合并旧文件，也不迁移原有
OpenClaw 会话与供应商设置。内部 `Adapter.run` 契约统一事件、问答、取消和原生会话 ID：

| 底座 | 接入方式 | 认证 | 权限 |
| --- | --- | --- | --- |
| 仅聊天模式 | 模型 API 直连，无需 CLI | 独立 `EASEL_DIRECT_API_*` 配置 | 无本机工具 |
| OpenClaw | 保留现有 gateway / CLI 路径 | 原有 OpenClaw 配置 | 原有策略 |
| OpenCode | `opencode acp`，私有 stdio ACP v1 | `opencode auth login` | OpenCode 原生策略，ACP 权限请求交由 Web 确认 |
| Codex | `codex app-server`，私有 stdio 原生 RPC | `codex login` 或原生配置 | 默认 workspace-write，网络受限；额外授权需逐次确认 |
| 通用 ACP | 本机管理员配置的 argv | 对应 Agent 原生登录 | 对应 Agent 原生策略，不声称提供操作系统沙箱 |

Codex 不必通过第三方 ACP 桥接，以免丢失原生流式事件和权限控制。ACP 作为可复用适配器，
供 OpenCode 与后续实现 ACP 的 harness 接入；非 ACP 底座可在 registry 中注册独立 Adapter。
不公开服务端口，不开启 `danger-full-access`，不自动批准工具权限。

## 安装与配置

安装向导默认安装或复用 OpenClaw，也可以在「是否安装或复用 OpenClaw？」处输入 `n`。
跳过后仍安装 Easel、构建 Web，并准备浏览器登录依赖；不会安装、初始化或启动 OpenClaw，
也不自动安装其它 Agent。无人值守安装可以显式选择：

```bash
bash setup.sh --skip-openclaw
# 默认安装 OpenClaw，并跳过选择提示
bash setup.sh --openclaw
```

Windows PowerShell：

```powershell
.\setup.ps1 -SkipOpenClaw
.\setup.ps1 -OpenClaw -NonInteractive
```

安装后运行 `easel web`，在「设置 → Agent 底座 → 执行引擎」选择已检测到的 Codex / OpenCode，
保存后新建对话。跳过 OpenClaw 的新安装初始为「仅聊天模式」，只需使用已有原生 Agent 时，
无需填写 OpenClaw 的 API Key；尚未选择 Agent 时也可以进入 Web、管理配置与账号，
但对话需选择已认证的 Agent 或配置仅聊天模式的模型 API。
重跑跳过安装不会覆盖已保存的底座、模型、沙箱或凭证，不用 `EASEL_AGENT_RUNTIME` 锁住页面选择。
以后需要 OpenClaw，可以重新运行上述默认安装命令，再在 Web 中自行切换。
Linux / macOS 原有 `--api` 参数保留，用于显式设置仅聊天模式的传输兼容配置；
它与不改已有传输配置的 `--skip-openclaw` 不同。

在运行 Web 的同一服务器账户下安装所需 CLI，并完成原生认证：

```bash
npm install -g @opencode/cli
opencode auth login
npm install -g @openai/codex
codex login
```

CLI 需要在 Web 的 PATH 中。`easel web` 在非交互启动遗漏 PATH 时，会补充当前服务器账户下
常见的 npm、nvm、fnm、Volta、用户本地与 OpenCode 安装目录，包括自定义 npm 前缀、
用户 `.npmrc` 和 Windows 的 `%APPDATA%\npm`。macOS 会兼顾 Homebrew 安装路径。
只补充 Web 子进程缺失的 PATH，不覆盖已有 CLI 的优先级，不修改系统环境或任何 Agent 配置。
OpenClaw 的 npm 入口优先使用同目录的 Node，避免系统旧 Node 影响恢复的安装；
Windows 的 npm shim 使用 Node 或原生程序调用，不通过 shell 拼接命令。
OpenCode Windows npm 入口兼容 V2 `@opencode/cli` 和 V1 `opencode-ai`，按照 PATH
命中的 `.cmd` / `.bat` 实际引用的包和入口启动，不在两个包之间盲目回退。缺失或
无法识别的入口需重新安装并检查 PATH；若 V1/V2 共存且出现原生数据库版本错误，
先核对当前命中的 CLI 版本，不删除或自动迁移用户的数据库。
安装后必要时重启 Web。执行引擎列表不会隐藏未检测到的底座，仍可选择查看配置及安装提示，
但未安装的底座不能保存为当前引擎。配置读取失败时可以点击「重新读取」，无需先切换底座。
自动查找限于运行 Web 的账户及已指定的安装路径，不读取其它用户的登录配置；
自定义服务账户、容器或其它目录安装仍需设置该进程的 PATH 并重启 Web。
选择 OpenClaw 后下方展示 API 配置；OpenCode 展示原生模型设置，
认证仍由其原生 CLI 管理，不把 OpenClaw 的 API Key 复制过去。设置保存到
`outputs/_harness/config.json`，不修改 README、项目 `.env` 中的供应商凭证、
`opencode.json` 或 Codex 配置。从旧版 API 模式切回 OpenClaw 时只归一化
`EASEL_CHAT_TRANSPORT`，不删除独立 API 凭证。模型覆盖留空时沿用 CLI 原生默认；OpenCode 模型通常是
`provider/model`。环境变量 `EASEL_AGENT_RUNTIME` 可固定底座，此时 Web 禁止覆盖。

通用 ACP 的启动参数只能通过服务器上的 `outputs/_harness/acp.json` 配置，
Web 不提供任意命令输入。内容是 JSON argv 数组，不走 shell。例如：

```json
{"command": ["opencode", "acp"]}
```

只对可信管理员提供这个配置入口。Windows 使用可执行程序，npm 工具推荐
`node` 加原生脚本路径，而不是 `.cmd` 或 `.bat`。

## 会话与兼容性

- 切换前必须结束或停止所有运行中任务；切换后新建对话，不在已有会话中悄悄换边。
- 原生会话 ID 与底座持久化绑定，服务重启后续接同一原生会话。
- 旧 OpenClaw / API 对话通过原有历史、transport pin 和结果文件识别。
- 浏览器 SSE 断开不取消后台 Agent；可用现有 job 回放和 last 接口取回结果。
- Web 的 Codex / OpenCode / ACP 按对话复用私有 stdio 进程，连续追问不重复握手或加载历史。
  空闲 5 分钟自动回收，最多保留 8 个空闲进程；下一轮按原生 ID 续接，而非新建历史。
  显式停止、超时、协议错误、配置变更、删除对话和服务关闭回收相应进程。
  CLI 单次执行仍在结束后回收进程；不自动重试失败的原生会话为新会话。
- 删除 Easel 的对话绑定不会删除 Codex / ACP 的原生历史。
- Easel 提供统一技能目录、Python 环境与输出目录提示，不把 OpenClaw 的 slash 命令当成其他 CLI 的原生命令。
- 内置技能统一存于 `skills/builtin/`，跨技能共享层仍为 `skills/shared/`。
  Windows 安装、OpenClaw 同步、脚本示例和检查入口使用相同路径。
  Web 启动 Agent 的 cwd 固定为实际安装的 Easel 根目录，不接受用户传入工作目录。
  共享身份、业务规则和人格说明位于 `agents/workspace/`，不绑定某个引擎。
  OpenClaw 沿用 `bash agents/sync.sh` 同步；Codex 通过原有 `developerInstructions`、
  OpenCode / ACP 通过原有消息前缀加载全部工作区 Markdown，再追加当前引擎与运行时路径。
  仅聊天模式没有文件执行能力，不能声明已经加载或执行本地技能。
- Web 展示的聊天记录保存在当前浏览器本地，原生上下文按服务器持久化的会话 ID 续接；
  刷新或 Web 重启不会新建原生会话，但清空浏览器数据或换浏览器不等同于迁移聊天记录。
- ACP 不声明客户端文件 / terminal 能力，因此依赖客户端代执行这些工具的 Agent 暂不支持；
  需要 Agent 自带工具。协议版本必须是 ACP v1；历史续接要求 `loadSession`。
- “CLI 已安装”不是认证成功或模型在线的证明；用实际消息或 `easel ping` 验证。
- `easel chat`、`easel skill`、`easel ping` 使用所选底座。新底座不需要 OpenClaw gateway。

## 验收建议

### API 配置与模型选择

- 执行引擎选择 OpenClaw 或仅聊天模式后，会立即显示该引擎自己的 API 配置，
  不需要先切换正在使用的底座。修改 API 前先点击“保存底座”，再保存下方配置；
  仅预览不会更改当前引擎、密钥或模型。
- Codex 和 OpenCode 的“模型覆盖”提供下拉框，点击“拉取模型”才启动原生 CLI
  读取列表，不创建对话，也不在打开设置时自动读取。Codex 使用 `model/list`，
  OpenCode 使用 `opencode models`；列表由原生配置提供，不代表每个模型都已授权可用。
- 可选择其它 GPT 模型或 OpenCode 供应商模型，也可手动填写模型 ID；
  留空沿用原生 CLI 默认模型。保存后请新建对话，原有历史仍绑定原底座与会话。
  读取列表失败时保留原有模型设置；原生认证仍由对应 CLI 管理。

1. 先用原有 OpenClaw 对话确认没有回归。
2. 设置切换到新底座，新建对话让它仅回复一段文字。
3. 同一对话再问上一轮内容，刷新页面 / 重启 Web 后再续接。
4. 让它读取公开技能说明，再生成小文件到 `outputs/`，确认没有虚构工具执行。
5. 对实际出现的额外权限请求分别拒绝、允许一次；不要使用发布等不可逆动作做初测。
6. 点击停止，确认可立即再发消息；检查断线回放和错误提示。
7. 切回 OpenClaw，确认原有对话历史仍能续接。

首次接入不承诺所有 OpenClaw 专属工具或供应商设置在其他 harness 中完全等价。
原生 CLI 和协议更新后应重新运行协议测试、完整 Python 测试与前端构建。

## 本次本地验证

2026-10-11，在服务器现有原生登录配置下，Codex 与 OpenCode 均实际完成：
文字回复、保存并续接同一原生会话、正确回忆上一轮内容，以及在临时工作目录通过
真实工具生成文件。测试文件不写入项目，不进行网络操作或平台发布。

自动化回归覆盖协议握手、模型覆盖、授权允许 / 拒绝、停止与超时、子进程回收、
会话隔离、断线继续执行与回放、配置保护以及 Web 底座设置。
2026-10-12，将仅聊天模式整合进统一执行引擎列表后，完整 Python 回归为
818 项通过、9 项跳过；前端 22 项测试通过，生产构建成功。
设置界面另经真实 Chromium 验证输入框样式、深浅色主题、下拉菜单键盘操作、
Escape 关闭层级、悬停与键盘聚焦说明，以及 1440 / 600 / 390 像素布局。
保存接口使用模拟响应，不改用户实际配置；服务重启后确认原有 OpenClaw 底座未切换。
前端 lint 保留两条已有警告，构建另有 bundle 体积提示，不作为功能验收已完成的证明。
Windows 启动入口通过单元测试验证，尚未在真实 Windows 系统做完整登录与对话验收。

2026-10-12，继续验证设置加载、技能目录迁移与原生会话复用：

- 114 个内置技能迁移到 `skills/builtin/`，716 个原有受版本控制文件全部保留。
  技能结构校验与 273 条文档 Python 命令路径校验通过；隔离运行 OpenClaw 同步后，
  114 个技能及共享目录均可读取。运行中的 OpenClaw 工作区只更新未被用户修改的副本，
  不覆盖私人记忆、用户资料或自定义共享脚本。
- Codex 和 OpenCode 均通过真实三轮对话验证：第二轮复用同一进程与原生会话，
  真实工具确认 cwd 为 Easel 根目录并读取 `skills/builtin/social-content/SKILL.md`；
  回收进程后第三轮续接相同原生会话，正确回忆前文。
- 删除浏览器初始化中的过期历史清空逻辑，回归覆盖旧会话、当前会话和断线恢复标记保留。
  页面记录仍保存在浏览器本地，不声称支持跨浏览器同步。
- 真实 Chromium 在 1440 / 900 / 600 / 390 像素宽度下验证左下角“设置”不换行；
  以模拟接口验证底座和模型配置各只加载一次，环境工具仅在进入环境安装页时加载。
- 完整 Python 回归 833 项通过、9 项跳过；前端 26 项测试通过，生产构建成功。
  本轮保留用户自行选择的 Codex 底座，不修改供应商配置，不执行提交或推送。

2026-10-12，恢复 OpenClaw API 配置预览并增加原生模型下拉框：

- 运行中的 Web 实际读取 Codex 7 个模型和 OpenCode 11 个模型，不公开私人模型别名。
  真实 Chromium 验证 OpenClaw / 仅聊天模式的 API 配置预览、未保存底座时的 API
  保存保护，以及两个原生模型下拉框；各自只请求一次列表，未保存用户配置。
  本轮服务器 Chromium 普通点击和截图出现等待超时，界面检查使用强制点击；
  这不是对普通鼠标交互或小红书 App 扫码确认的完整验收。
- 小红书回归覆盖二维码图案尺寸、扫码后不换码、维护页与未知校验结果、
  创作平台真实账号标识与账号接口、过期校验丢弃和前后端缓存失效。
  服务端账号接口在当前持久化会话返回登录过期，但这不能单独证明首页会话已退出；
  实际 App 扫码与确认仍需用户验收，不承诺解除平台维护或服务器出口风控。
- 完整 Python 回归 881 项通过、9 项跳过；前端 33 项测试通过，生产构建成功。
  lint 保留两条已有警告，构建有 bundle 体积提示。README 未修改，未提交或推送。
