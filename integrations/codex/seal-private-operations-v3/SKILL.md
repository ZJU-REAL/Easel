---
name: seal-private-operations-v3
description: >-
  Seal 私人运营顾问 V3 的唯一 Codex 入口，提供 macOS/Windows 跨平台可视化运营工作台，
  内置 113 项能力并联动六端账号、画像、热点、选题、运营任务、对话、日历、内容库、发布与复盘。
  用户要求启动/使用 Seal V3、进行多平台运营、创建或继续运营任务、检查工作台或调用 Seal 内置能力时使用。
---

# Seal 私人运营顾问 V3

这是一个完整产品 Skill。113 项能力位于本 Skill 的 `bundled-skills/`，只作为 Seal 内部能力库；不要将它们复制到 `$CODEX_HOME/skills`，不要创建 113 个独立 Codex Skill。

## 启动工作台

1. 令 `SKILL_ROOT` 为本 `SKILL.md` 所在目录。
2. 先探测 `http://127.0.0.1:7862/api/status`。若已返回且页面属于 Seal V3，直接复用，不重复启动。
3. 未运行时：
   - macOS：执行 `"$SKILL_ROOT/scripts/start-macos.sh"`。
   - Windows：执行 `powershell -ExecutionPolicy Bypass -File "$SKILL_ROOT\scripts\start-windows.ps1"`。
4. 若提示未安装，使用对应的 `install-macos.sh` 或 `install-windows.ps1`。安装只创建 V3 自身的 `runtime/.venv` 与内部 Node 依赖。
5. 启动后验证 `/api/status` 中 `runtime=true` 且 `skills` 恰好 113 项，再打开 `http://127.0.0.1:7862/`。

## 执行规则

- 完整读取 `runtime/AGENTS.md`，按当前任务选择 `bundled-skills/<能力>/CAPABILITY.md`。这些文件是产品内部能力规范，不是独立 Codex Skill。
- 从 `runtime/` 作为工作目录执行；共享脚本在 `runtime/skills/shared/scripts/`，内置能力在 `bundled-skills/`。
- 工作台对话由本机 Codex CLI 承接。它是 Codex 桌面工作台连接 Agent 的本地非交互入口，不是第二套模型或第二个产品。
- FFmpeg 与 FFprobe 是完整音视频编解码、探测、字幕和合成能力的必要运行依赖。
- `.env`、浏览器登录态、画像和产物只保存在 V3 `runtime/` 内；不要读取或修改 V2 或原 Easel 工作区。
- 外部查询、生成、通知和平台发布按对应能力的权限与 Key 规则执行。付费调用及公开写操作先确认，测试不得真实发布。

## 详细文档

- 安装、启动、迁移与双平台验收：读取 [跨平台安装与验收](references/跨平台安装与验收.md)。
- 架构、进程、数据与外部调用：读取 [运行原理与外部服务](references/运行原理与外部服务.md)。
- 运营任务状态与各页面联动：读取 [运营任务与联动设计](references/运营任务与联动设计.md)。
- 113 项能力及配置边界：读取 [技能目录与外部服务](references/技能目录与外部服务.md)。
