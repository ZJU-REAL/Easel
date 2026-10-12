# redbook 命令详解

**始终加 `--json`** 供程序解析（否则输出人读文本）。全局选项见文末。

## 读取（reading）

### `redbook search <keyword>`
按关键词搜索笔记，返回标题/URL/点赞/作者。
```bash
redbook search "AI编程" --sort popular --json    # sort: general(默认)/popular/latest
redbook search "Cursor" --type image --json       # type: all(默认)/video/image
redbook search "MCP Server" --page 2 --json       # 分页
```

### `redbook read <url>`
读笔记全文 —— 标题/正文/图片/点赞/评论数。接受完整 URL 或短 noteId（bare noteId 常返回 `{}`，需 xsec_token）。API 返回验证码时回退 HTML 抓取。

### `redbook comments <url>`
获取评论，`--all` 拉全部页。`redbook comments "<url>" --all --json`

### `redbook user <userId|profileUrl>`
创作者档案 —— 昵称/简介/粉丝数/笔记数/获赞。bare userId 返回 `code=-1` 时用含 `xsec_token` 的完整 profile URL，或 `--xsec-token <token> --xsec-source pc_search`。

### `redbook user-posts <userId|profileUrl>`
列出创作者所有笔记（标题/URL/点赞/时间）。

### `redbook account-report <userId|profileUrl...>`
批量汇总账号发帖与参与度。
```bash
redbook account-report --file accounts.txt --month 2026-07 --json
redbook account-report "<url1>" "<url2>" --max-pages 2 --json
```
选项：`--file`（换行分隔 ID/URL）· `--month YYYY-MM`（默认当月）· `--max-pages n`（默认 1）· `--all`（全页）· `--delay ms`（默认 3000）。KOS/KOC 报告用已知 ID，勿用关键词搜索。

### `redbook feed`
浏览推荐流。`redbook feed --json`

### `redbook topics <keyword>`
搜索话题标签。`redbook topics "Claude Code" --json`

### `redbook favorites [userId]`
列出收藏笔记，默认当前登录用户。`--all` 拉全页。他人收藏仅在未设私密时可见。

### `redbook analyze-viral <url>`
分析爆款原因，返回确定性 0–100 分。`--comment-pages n`（默认 3，最大 10）。
JSON：`{ note, score, hook, content, visual, engagement, comments, relative, fetchedAt }`
- `score.overall` = hook(20)+engagement(20)+relative(20)+content(20)+comments(20)
- `hook.hookPatterns[]` · `engagement`（点赞/评论/收藏/分享 + 三比率）· `relative.viralMultiplier`（点赞/作者中位）· `relative.isOutlier`（>3）· `comments.themes[]`

### `redbook viral-template <url> [url2] [url3]`
从 1-3 篇爆款提取可复用模板。`--comment-pages n`（默认 3，最大 10）。
JSON：`{ dominantHookPatterns, titleStructure, bodyStructure, engagementProfile, audienceSignals, sourceNotes, generatedAt }`

### `redbook health`
检测笔记隐藏限流 level（见 modules.md Module M）。`redbook health --all --json`

### `redbook whoami`
检查连接状态，验证 cookie 并显示登录用户。

### `redbook boards` / `redbook board <board-url>`
列出用户合集 / 列出合集内笔记。

## 写操作边界

本 Skill 只允许上面的读取与分析命令。不要调用 CLI 内置的发布、评论、回复、点赞、收藏或批量互动命令；这些路径没有 Easel 的确认与内容安全闸门。发布改用 `skill-xhs-publisher`，评论和回复改用 `skill-xhs-comment-reply`。

### `redbook render <file>`（离线，无需 cookie）
markdown → styled PNG 卡片，用本机 Chrome。
选项：`--style purple/xiaohongshu(默认)/mint/sunset/ocean/elegant/dark` · `--pagination auto(默认)/separator` · `--output-dir` · `--width`(1080) · `--height`(1440) · `--dpr`(2)。需 `puppeteer-core` + `marked`；Chrome 非标准位置设 `CHROME_PATH`。

### `redbook auth`
为 OpenClaw/云/CI 管理保存的 cookie。
```bash
redbook auth export                                  # 从本地浏览器导出到 ~/.redbook/cookies.json
redbook auth save --cookie-string "a1=...; web_session=..."
redbook auth path / inspect --json / clear
```
cookie 解析顺序：`--cookie-string` → `REDBOOK_COOKIE_STRING` → `REDBOOK_COOKIE_FILE` → `~/.redbook/cookies.json` → 浏览器抽取。cookie 文件是明文凭证（`0600`），勿提交/记录。

## 全局选项（所有命令）
- `--cookie-source chrome(默认)/safari/firefox`
- `--chrome-profile <name>`（省略则自动发现）
- `--cookie-string "a1=...; web_session=..."`
- `--platform xhs(大陆)/rednote(全球)`（默认自动检测，见 technical-reference.md）
- `--global`（= `--platform rednote`）
- `--json`
