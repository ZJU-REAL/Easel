# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | xiaohongshu-skills |
| **所属层** | publish |
| **来源仓库** | white0dew/XiaohongshuSkills |
| **GitHub 地址** | https://github.com/white0dew/XiaohongshuSkills |
| **Star 数** | ~300+ |
| **功能描述** | 小红书自动发布/评论/检索，支持OpenClaw/Codex/CC |
| **SKILL.md 行数** | 316 |
| **文件总数** | 19 |
| **自包含** | 需要小红书Cookie |
| **备注** | 316行，含Playwright自动化发布 |

> 收录时间: 2026-07-16
> 用途: Easel SKILL 验证测试

## 实现重写（2026-07 参考 xiaohongshu-mcp）

发布实现从旧 **CDP-to-真实Chrome** 栈（`cdp_publish.py` 7000+ 行，headless 环境不可用，已删除）
**整体重写为 Playwright 版** `../../shared/scripts/xhs_publish.py`（headless 可用）。

- **参考来源**：[xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)（Go/go-rod，作者称跑一年未封号）——**仅参考其实现代码**，未引入 Docker/MCP 依赖。
- **移植的健壮技巧**：发布成功校验（URL 离开 /publish/publish）、逐图上传等预览、视频等处理完成、话题联想真绑定、新旧发布按钮兼容、遮挡检测+移弹层、DOM 长度校验、逐字符输入反检测。
- **本次范围**：图文/视频发布 + 登录。检索/互动（feeds/search/comment/like）选择器参考里有，列为后续。
- **旧来源存疑辨析见下**（保留历史），但当前实现已是我们基于 xiaohongshu-mcp 的 Playwright 移植。

## Wave4 瘦身说明（2026-07-23）

### 来源冲突订正（结论）

收录时发现两处来源标注不一致：

- 本 META 原记：`white0dew/XiaohongshuSkills`
- SKILL.md frontmatter `metadata.source` 及正文标题：`Angiin/Post-to-xhs`

**核实结论（选定其一并注明理由）：主来源 = `white0dew/XiaohongshuSkills`；上游祖先 = `Angiin/Post-to-xhs`。**

理由：
1. 现有 SKILL.md 的命令集（`get-login-qrcode` / `content-data` / `get-notification-mentions` / `note-upvote|bookmark` 等发布+互动+数据全套）与 white0dew/XiaohongshuSkills 的功能描述（自动发布/评论/检索 + 二维码导出 + 内容数据看板，~3.2k star）完全对应，而非 Angiin 精简版。
2. 目录内含 `public/whitedew.jpg`（作者标识资产），指向 white0dew。
3. `Angiin/Post-to-xhs`（现已归档并迁移）是 white0dew fork 的上游祖先，因此 frontmatter/标题保留了旧名 —— 这是 fork 未改名所致，而非收编源本身。

已在 SKILL.md frontmatter 补记 `source: white0dew/XiaohongshuSkills` + `ancestor: Angiin/Post-to-xhs`，两者均如实保留。

### 规范与瘦身

- **frontmatter 补全**：新增 `layer: publish` / `version: 0.1.0` / `profile_aware: false`；`name` 由 `RedBookSkills` 改为 `skill-xhs-publisher`（与目录一致）。
- **环境标注**：SKILL.md 顶部新增「⚠️ 环境依赖」块 —— 需 Python + CDP 连 Chrome + 小红书 cookie，当前环境不可用。
- **xhs 去重**：SKILL.md 新增「与 xhs-analyzer 的分工边界」—— 本 SKILL 专做发布+互动，分析/爆款规律归 xhs-analyzer。
- **瘦身**：316 → 约 130 行。命令样例堆叠全部下沉到 `references/commands.md`，正文只留输入判断 + 约束 + 流程概览 + 脚本表 + references 指针。
