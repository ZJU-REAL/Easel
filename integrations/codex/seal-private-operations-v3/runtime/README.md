# Seal 私人运营顾问 V3 Runtime

本目录是 V3 的自包含运行时，源自开源项目 Easel 并针对 Codex 深度适配。产品入口位于上级 `SKILL.md`，113 项内部能力位于上级 `bundled-skills/`。

- macOS 安装：`bash ../scripts/install-macos.sh`
- Windows 安装：`powershell -ExecutionPolicy Bypass -File ..\scripts\install-windows.ps1`
- 环境检查：`seal doctor`
- 连通检查：`seal ping`
- 工作台：`seal web --port 7862` 或使用上级平台启动脚本

本运行时使用 Codex、Playwright、Node.js 和 FFmpeg，不需要其他 Agent 运行环境。
