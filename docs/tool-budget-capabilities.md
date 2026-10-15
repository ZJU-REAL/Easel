# 工具限额能力与启动检查

在本机环境或 `.env` 设置 `EASEL_REQUIRE_TOOL_BUDGET=1`，要求 Easel 在启动任务前确认
执行前工具限额保障。默认 `0` 保持原有行为；其他值报错，不会默默关闭检查。
检查覆盖 Web 聊天、同步 Agent 操作、CLI chat/ping/skill 和直接调用的原生适配器。
它不是新的预算执行器，不设置调用次数，也不把权限弹窗当成预算控制。

`/api/settings/harness` 返回的运行时描述增加 `tool_budget` 字段（与 `installed` 分开）：

| 通道 | admission | enforcement_verified | 严格要求下的行为 |
| --- | --- | --- | --- |
| API 直连聊天 | no_tools | true | 可运行：此路径不执行工具 |
| Codex / ACP / OpenCode | observation_only | false | 拒绝启动 |
| OpenClaw | plugin_required | false | 拒绝启动：尚无活动 Gateway 插件证明 |

Codex 的 item/started 和 ACP 的工具通知可能发生在工具已启动之后，取消也不能撤销已产生
的副作用；部分授权请求不覆盖全部工具。OpenClaw 需要执行端插件的 before-tool 拦截，
安装了 CLI 或本地存在插件文件不能证明正在连接的 Gateway 已加载并执行该插件。
当前不会接受环境变量或客户端自报的“已验证”标记来绕过检查。

因此，本功能启用时暂时没有可用的工具执行通道，只有不执行工具的 API 聊天可运行。
这是明确的能力边界，不代表 OpenClaw 插件本身不能执行限额。后续只有具备可信的活动
执行端证明才能开放严格通道；不能靠静态配置推断。未设置此要求的现有任务不受影响。
检查只约束 Easel 启动路径，不控制用户直接运行的第三方 CLI，也不会终止已启动的任务。
