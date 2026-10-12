# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-xhs-comment-reply |
| **所属层** | publish（互动运营） |
| **实现** | `../../shared/scripts/xhs_comment.py`（Playwright，headless 可用） |
| **原型来源** | 本项目自研原型 `/tmp/xhs_reply.py`（async 版）+ `/tmp/xhs_get_comments.py`（响应拦截抓评论） |
| **自研** | ✅ Easel 自研 |
| **自包含** | 需小红书登录态（与 skill-xhs-publisher 共用持久化目录） |
| **备注** | 抓评论走接口响应拦截（comment/page），回复走 DOM 定位 + 逐字符输入反检测 |

> 沉淀时间: 2026-07-30

## 定位与由来

第七次会话打通小红书发布链路后，评论区**互动运营**是自然的下一步能力。原型在探索阶段以
一组散脚本验证可行（`/tmp/xhs_*.py`：抓评论、找回复按钮、逐字输入发送，真机跑通并有截图佐证），
本 SKILL 把其中两条能力（抓评论 + 回复）**沉淀为对齐 Easel 规范的单一确定性脚本**：

- **async → sync**：重写为 `sync_playwright`，与 `xhs_publish.py` 同风格，可复用同款
  `_launch/_proxy/_profile_dir/LAUNCH_ARGS` 与 `login_state` 协议。
- **硬编码 → 参数化**：note-id/xsec-token/profile 目录/代理全部走 argparse，不再写死。
- **补规范**：新增 `selftest`（离线自检评论抽取/子评论展开/去重/代理/URL 构造/plan 渲染）、
  `check`、`plan`、`fetch --out`、`--replied-file` 去重、`--gap` 防风控间隔。
- **截图**：从硬编码 `/tmp/*.png` 改为默认关闭，`EASEL_COMMENT_DEBUG=1` 才存到
  `outputs/_login/`（与 xhs_publish 的 `EASEL_PUBLISH_DEBUG` 约定一致）。

## 与既有 SKILL 的边界

- 发布 → **skill-xhs-publisher**；分析爆款/限流 → **skill-xhs-analyzer**；
  评论情感/高频词/诉求量化 → **skill-comment-insights**（吃本 SKILL `fetch` 的评论 JSON）。
- 本 SKILL 做**评论区互动**：列我的笔记（notes）+ 抓评论（fetch）+ 回复（reply）+ 删除（delete）。点赞/收藏/私信列为后续（选择器同源，按需移植）。

## 2026-07-31 增补（免手动拆 token + 删除评论）

用户反馈两处摩擦，均已补齐（不破坏原接口）：
- **拉笔记评论太绕**（agent 曾自己写脚本去创作后台捞 xsec_token）：加 `_parse_note_url` + `fetch/reply/delete` 支持 `--url`（贴链接自动解析 id+token）；新增 `notes` 子命令列自己的笔记，**token 从 note-manager 的接口 JSON 响应里拦截取**（`_extract_note_tokens` 递归找同时含 note-id 与 xsec_token 的对象，端点/字段无关、抗改版；DOM href 仅兜底）。`account_stats.py` 抓小红书笔记用同法存 `note_id`/`xsec_token`，两个入口统一。
- **没有删除评论**（agent 曾用硬编码坐标点删）：新增 `delete` 子命令，按昵称(+内容片段去歧义)定位 → hover「···」→「删除评论」→ 确认，**全文本/结构定位、无坐标**；默认 dry-run、`--exec` 才真删。选择器/文案集中在 `SELECTORS["comment_more"]` + `DELETE_MENU_TEXTS` + `CONFIRM_TEXTS`。
- ⚠️ `delete` 的「···」触发/菜单/确认选择器 **best-effort，需真机校准**（`EASEL_COMMENT_DEBUG=1` dump DOM）。`notes` 的 token 走接口拦截通常可靠；万一某篇没取到（接口改版/未加载），回退 `fetch --url` 贴分享链接（已 selftest，可靠）。

## 待办 / 后续

- 回复/删除定位目前按**昵称**（+`--content` 去歧义）；如需精确到 comment-id，可移植按 id 的 DOM 锚点（当前 DOM 未稳定暴露 id）。
- 真机选择器为 best-effort，平台改版频繁；排错开 `EASEL_COMMENT_DEBUG=1` 看截图/DOM +
  改顶部 `SELECTORS` 字典与删除文案常量。
