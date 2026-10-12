# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | douyin-upload |
| **所属层** | publish |
| **来源仓库** | WJZ-P/douyin-upload-mcp-skill |
| **GitHub 地址** | https://github.com/WJZ-P/douyin-upload-mcp-skill |
| **Star 数** | ~100+ |
| **功能描述** | 抖音视频/图文上传，OpenClaw适用 |
| **SKILL.md 行数** | 115 |
| **文件总数** | 24 |
| **自包含** | 需要MCP Server+抖音Cookie |
| **备注** | 115行，轻量MCP SKILL |

> 收录时间: 2026-07-16
> 用途: Easel SKILL 验证测试

## 实现重写（2026-07 参考 douyin-upload-mcp-skill）

发布实现从旧 **CDP/puppeteer/MCP Node 栈**（`src/` + package.json，headless 跑不了，已删除）
**整体重写为 Playwright 版** `../../shared/scripts/douyin_publish.py`（headless 可用）。

- **参考来源**：[WJZ-P/douyin-upload-mcp-skill](https://github.com/WJZ-P/douyin-upload-mcp-skill)——**仅参考其 `src/douyin-ops.js` 的 creator.douyin.com 选择器与流程**，未引入 Node/MCP 依赖。
- **移植**：高清发布入口 → 切 tab（视频/图文）→ 隐藏 file input 上传 → 视频等转码(≤5min)+AI 封面 → 标题/简介(Ctrl+A 清空逐字输入) → 发布 → toast「发布成功」校验 → 二维码登录。
- **接入**：Web「账号」页扫码登录（`douyin` backend）+ 发布前人设检查（低分仅警告）+ manifest/log 留痕。
- **删除**：src/ package*.json .env markdown/ README.en.md 等整套 Node 死栈（无外部依赖）。

## Wave4 瘦身说明（2026-07-23）

- **frontmatter 补全**：新增 `layer: publish` / `version: 0.1.0` / `profile_aware: false`；`name` 由 `douyin-upload-mcp-skill` 改为 `skill-douyin-upload`，与目录名一致。
- **环境标注**：SKILL.md 顶部新增「⚠️ 环境依赖」块 —— 需 MCP Server + Node + puppeteer + CDP 连真实 Chrome + 抖音 cookie，当前"无浏览器/无 MCP/Linux"环境不可用（死代码保留）。
- **行数**：135 行（原 115，加环境块后仍 < 200），流程正文未删改。
- 未删除任何脚本/资源，仅补规范 + 环境标注。
