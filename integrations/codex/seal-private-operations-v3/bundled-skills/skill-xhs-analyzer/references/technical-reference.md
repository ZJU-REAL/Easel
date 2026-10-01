# 技术参考

## 大陆小红书 vs 全球 RedNote

XHS 跑**两个独立后端，不共享 session/cookie**：

| | 大陆 | 全球 |
|---|---|---|
| App/站点 | 小红书 / `xiaohongshu.com` | RedNote / `rednote.com` |
| API host | `edith.xiaohongshu.com` | `webapi.rednote.com` |
| Cookie 域 | `.xiaohongshu.com` | `.rednote.com` |

RedNote 按 IP/地区路由，一台机器一次只能登一个 —— **CLI 自动检测**你登的是哪个，通常**不传任何 flag**。检测：探测两个 cookie 域，只一个有 session 就用它；两个都有则用一次 `/user/me` 验证。结果缓存 `~/.redbook/platform-cache.json`（按 cookie 指纹），登入/登出自失效。stderr 显示 `Platform: … [auto-detected|cached]`。

强制覆盖（罕见）：`--global` / `--platform xhs` / `export REDBOOK_PLATFORM=rednote`。web 签名（x-s/x-t）两端**相同**，只 host + cookie 域不同。

全球后端已知缺口：`user-posts`/`user` 可能需新鲜 profile `xsec_token`；`health` 需先登 RedNote 创作者面板。

## xsec_token —— 读取与分享笔记必需

XHS API 需有效 `xsec_token` 才能取笔记内容，否则 `read`/`comments`/`analyze-viral` 返回 `{}`。无 token 的 `explore/<id>` URL 会被反爬层 302 重定向到 404 页。

**用 `webUrl`（v0.7.0 起）**：每个返回笔记的命令（`feed`/`search`/`user-posts`/`favorites`/`board`/`read`/`post`）都含 `webUrl` 字段，token 已内嵌 + 正确 `xsec_source`。直接用 `webUrl`，别手工拼 URL。`xsec_source` 按命令设：`pc_feed`/`pc_search`/`pc_user`/`pc_board`/`pc_share`。

关键规则：
1. **token 会过期。** 上个会话的 URL 会返回 `{}`，绝不缓存/复用旧 URL。
2. **`search` 和 `feed` 总返回新鲜 token。**
3. **bare noteId 返回 `{}`。** 正确工作流：先 `search`，从结果取 `webUrl`，再 `read "<webUrl>"`。

需笔记 xsec_token：`read`/`comments`/`analyze-viral`；可能需 profile xsec_token：`user`/`user-posts`；不需要：`search`/`feed`/`whoami`/`topics`。

## 中文数字格式

API 返回带中文单位的缩写数字，解析 `interact_info` 时注意：

| API 值 | 实际 |
|--------|------|
| `"1.5万"` | 15,000 |
| `"2.4万"` | 24,000 |
| `"1.2亿"` | 120,000,000 |
| `"115"` | 115 |

`万`=×10,000，`亿`=×100,000,000。<10,000 是纯整数字符串。`analyze-viral` 自动处理，手动解析 `--json` 时留意后缀。

## 错误处理

| 错误 | 含义 | 修复 |
|------|------|------|
| `{}` 空响应 | 缺/过期 xsec_token | 先 search 拿新鲜 token |
| "No 'a1' cookie" | 未登录 XHS | 在 Chrome 登录 xiaohongshu.com |
| "Session expired" | cookie 太旧 | 重登 Chrome |
| "NeedVerify"/验证码 | 反爬触发 | 等待重试，或降频（见 research-loop.md） |
| "IP blocked" (300012) | 限速 | 等待或换网 |

## API vs 浏览器 限制

- API 可靠：读（search/notes/comments/user/feed/favorites）、写（一级评论/回复/收藏）、分析（viral 评分/模板/批量回复计划）。
- API 不可靠（常触发验证码）：发布笔记（`--private` 成功率高些）、超高频批量。
- 需浏览器自动化（本 CLI 不支持）：验证码求解、实时通知、点赞/关注（重反自动化）、私信、封面生图。

## 输出格式指引

- 数据表：Markdown 表 + 精确字段映射，含单位。
- 热力图：ASCII 条形图做跨主题对比。
- 最终报告章节顺序：1.市场概览 → 2.关键词版图 → 3.跨主题热力图 → 4.受众画像 → 5.竞争版图 → 6.内容机会（分级）→ 7.内容 idea（具体 hook/角度/目标）。

## 程序化 API

```typescript
import { XhsClient } from "@lucasygu/redbook";
import { loadCookies } from "@lucasygu/redbook/cookies";
const cookies = await loadCookies("chrome");
const client = new XhsClient(cookies);
const results = await client.searchNotes("AI编程", 1, 20, "popular");
```
