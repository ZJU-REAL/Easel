# Easel ↔ Hermes 原生 MCP 接入

## 状态

- MCP server：`D:/Garyai/opensource/Easel/easel_mcp_server.py`
- 传输：本机 stdio
- Hermes 配置：`~/.hermes/config.yaml` 的 `mcp_servers.easel`
- MCP SDK：Easel `.venv` 中 `mcp 1.30.0`
- 已发现工具：31 个
- Easel Web：仍可保留在 `127.0.0.1:7860`，作为人工排查/扫码后台；MCP 不依赖 Web 端口

## 调用关系

```text
Hermes 任意 bot
  └─ mcp_easel_*
       └─ Easel MCP stdio server
            ├─ Easel outputs / profiles / skills
            ├─ 隔离浏览器登录态的只读检查
            ├─ analytics / schedule / ideas
            └─ 受控发布脚本（默认关闭）
```

这不是 Easel ACP 单 bot 连接，也不需要新建 `easel` bot；所有已授权的 Hermes bot 都可以发现同一组 MCP 工具。是否让某个 bot 实际调用，仍由该 bot 的工具集和任务边界决定。

### 全技能路由

Easel 的 114 个内置技能可以通过统一的 `easel_run_skill` 调用，仍复用 Easel 原有 `easel skill` 路由，而不是暴露任意 shell。先用 `easel_skill_policy` 查看风险；上传、发布、评论、账号/画像修改、直播和声音克隆等高风险技能必须先调用 `easel_request_skill_confirmation`，确认凭证绑定完整的技能名、输入和画像，10 分钟过期且只能使用一次。

风险分两级，实测分类（`easel_skill_policy` 可查）：

- **主机发布闸**（11 个）：`skill-bilibili-upload`、`skill-channels-upload`、`skill-douyin-upload`、`skill-kuaishou-upload`、`skill-xhs-publisher`、`skill-zhihu-publisher`、`skill-wechat-publisher`、`skill-cross-platform-publish`、`skill-xhs-comment-reply`、`skill-community-ops`、`skill-livestream`。闸关闭时直接 `blocked`，连确认凭证都申请不到。
- **仅需一次性确认**（3 个）：`skill-publish-scheduler`、`skill-profile-manager`、`voice-clone`。排期/日志/清单/复盘类技能属于内部写操作，发布闸关闭时仍可运行，但要确认。
- 其余 100 个技能为只读或纯生成类，可直接运行。

技能输入可以是文本，也可以是 Easel 项目、`outputs/`、`profiles/` 或 `EASEL_SHARED_ROOT` 指向共享目录内的文件路径；其他本机文件路径会被拒绝。输出会做敏感信息过滤并保留退出码/未知状态。

### 已知行为（实测）

内置 agent 类技能（如 `copywriting`）在 MCP 子进程里跑的是同一套 Easel agent 链路，生成内容正常返回，但**落盘需要审批**：非交互子进程拿不到 ACP 审批，写文件会被拒，技能以退出码 1 结束，内容仍在 `output` 里。要让技能直接写共享库，需在 Easel Web / ACP 会话里批准，或由调用方把返回内容另行落盘。这不是 MCP 路由失败。

## 工具分层

### 只读

`easel_status`、`easel_list_personas`、`easel_read_persona`、`easel_list_skills`、`easel_read_skill`、`easel_list_outputs`、`easel_read_output`、`easel_list_accounts`、`easel_login_status`、`easel_check_account`、`easel_fetch_analytics`、`easel_get_publish_policy`、`easel_plan_publish`、`easel_publish_status`、`easel_list_schedule`、`easel_schedule_context`、`easel_list_ideas`

### 受控写入

排期和选题的创建、更新、删除都必须先调用 `easel_request_write_confirmation`，再把一次性 `confirmation_id` 传给对应写工具。确认凭证与操作 payload 绑定，10 分钟过期且只能使用一次。

人工发布包同样先请求确认，再调用 `easel_export_manual_package`。导出包不会上传、不含登录凭据，也不代表发布成功。

### 高风险发布

`easel_request_publish_confirmation` 只生成发布摘要和一次性确认凭证，不启动发布。`easel_publish` 还要求：

1. 主机显式设置 `EASEL_MCP_ALLOW_PUBLISH=1`；
2. 提供与平台、标题、正文、素材完全匹配的未使用确认凭证；
3. 发布脚本返回退出码 0。

MCP 默认不满足第 1 条，因此真实发布默认被阻断。发布脚本退出码 0 也只表示已提交，`verified` 永远为 false，必须另行做平台读回对账，未知状态不改写为成功。

## 明确禁止

- 不暴露 cookie、密码、AppSecret、token、环境变量或原始凭据文件；
- 不提供任意 shell、任意 Python 或任意文件写入工具；`easel_run_skill` 只能调用已安装 Easel 技能，不能拼任意命令；
- 不通过 MCP 自动扫码、导入 cookie、删除浏览器 profile 或修改平台账号；
- 上传/发布类技能未经主机发布闸允许时不得执行；
- 不把 Web API 的启动状态当作发布成功；
- 不开放局域网 HTTP MCP 端点；当前只用本机 stdio。

## Hermes 侧配置

除默认 `mcp_servers.easel` 外，各 bot profile（`radar`/`director`/`design`/`huasheng`/`qianfan`/`collector`）写入同一 server，并附带：

```yaml
mcp_servers:
  easel:
    command: D:/Garyai/opensource/Easel/.venv/Scripts/python.exe
    args: [D:/Garyai/opensource/Easel/easel_mcp_server.py]
    enabled: true
    timeout: 180
    connect_timeout: 30
    env:
      EASEL_SHARED_ROOT: D:/Garyai/Token纪年视频创作/shared
```

## 验收记录

```text
hermes mcp test easel
✓ Connected
✓ Tools discovered: 31

C:/Python314/python.exe -m pytest tests/test_easel_mcp_server.py -q
12 passed
```

独立 stdio client 已完成 initialize、tools/list、`easel_status`、`easel_plan_publish` 往返验证。
