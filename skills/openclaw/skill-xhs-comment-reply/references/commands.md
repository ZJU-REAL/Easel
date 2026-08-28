# xhs-comment-reply 命令样例

脚本：`skills/shared/scripts/xhs_comment.py`（CWD=项目根）。所有命令用 `python` 直接调。
小红书对代理出口常判风险，**评论抓取/回复建议 `--no-proxy` 直连**。

## 定位笔记（不用手动拆 token）

用户说"这条/某条笔记"时，**别自己写脚本捞 token**。两条顺滑路径：

1. **列我的笔记** → 定位是哪条 → 用返回的 `url` / `note_id` 抓评论：
   ```bash
   python skills/shared/scripts/xhs_comment.py notes --no-proxy
   # → {"count":N,"notes":[{"note_id","title","xsec_token","cover","url"}]}
   # xsec_token 从 note-manager 接口响应拦截取（可靠）；url 非空即可直接 fetch --url
   # 万一某篇没取到 token，用该笔记分享链接走 fetch --url（见下）
   ```
2. **贴笔记链接** → `fetch --url` 自动解析 note-id 与 xsec_token：
   ```
   https://www.xiaohongshu.com/explore/6a6aba4d00000000090350b1?xsec_token=YBWco12h9N...=&xsec_source=pc_creatormng
                                       └────────── note-id ──────────┘             └──── xsec_token ────┘
   ```

## 0. 环境检查

```bash
python skills/shared/scripts/xhs_comment.py check
```

登录态与 xhs-publisher 共用。未登录先扫码（本 SKILL 不重复实现登录）：

```bash
python skills/shared/scripts/xhs_publish.py login   # 抠二维码 → 扫码 → 持久化
```

## 1. 抓评论 fetch

```bash
# 推荐：直接贴完整笔记链接（自动解析 note-id + xsec_token）
python skills/shared/scripts/xhs_comment.py fetch \
  --url 'https://www.xiaohongshu.com/explore/6a6a...?xsec_token=YBW...=' --no-proxy

# 或用 notes 拿到的 url
python skills/shared/scripts/xhs_comment.py fetch --url 'https://www.xiaohongshu.com/explore/NOTE_ID' --no-proxy

# 仍可用裸 id+token（写文件 + 只保留最近 50 条 + 多滚几轮加载更多）
python skills/shared/scripts/xhs_comment.py fetch \
  --note-id <id> --xsec-token '<token>' --no-proxy \
  --scroll 12 --max 50 \
  --out outputs/<主题>/comments.json
```

输出：`{note_id, count, comments:[{id, nickname, content, time, time_str, loc, like, parent}]}`。
`parent` 非空表示是某条评论的子回复。

## 2. 回复 reply（默认 dry-run，确认后 --exec）

回复列表由你（agent）结合画像语气拟好，格式 `[{id, nickname, reply}]`（id 可选，用于去重）：

```bash
# ① dry-run 预演（不启浏览器发送，仅打印将要回复什么）
python skills/shared/scripts/xhs_comment.py reply \
  --note-id <id> --xsec-token '<token>' --no-proxy \
  --replies-json '[
    {"id":"6a6abc09...","nickname":"麦克不叫麦","reply":"哈哈哈这条我也觉得！谢谢支持~"},
    {"id":"6a6abbcf...","nickname":"卡森不姓卡","reply":"放心不整你，乖乖出教程🙌"}
  ]'

# ② 用户确认后真发，带去重记录
python skills/shared/scripts/xhs_comment.py reply \
  --note-id <id> --xsec-token '<token>' --no-proxy --exec \
  --replied-file outputs/<主题>/replied.json \
  --gap 5 \
  --replies-json '[...同上...]'
```

- `--replied-file`：记录已成功回复的 comment id，**重跑自动跳过**已回复的，避免重复打扰。
- `--gap`：每条回复之间间隔秒数（默认 4，防风控）。
- 首次或疑似改版：加 `--headed` 观察一遍再 headless 批量。
- 排错：`EASEL_COMMENT_DEBUG=1 python ... reply ...` 会把点击后/输入后截图存到
  `outputs/_login/comment-*.png`。

## 2b. 删除评论 delete（默认 dry-run，确认后 --exec；不可恢复）

删自己笔记下的评论（含自己发的回复）。按昵称定位，`--content` 内容片段给同名去歧义避免误删。
**全程文本/结构定位，无坐标。**

```bash
# ① dry-run 预演（只列将删哪些，不真删）
python skills/shared/scripts/xhs_comment.py delete \
  --url '<笔记链接>' --no-proxy \
  --targets-json '[{"nickname":"麦克不叫麦","content":"催更"}]'

# 单条便捷写法
python skills/shared/scripts/xhs_comment.py delete \
  --url '<笔记链接>' --no-proxy --nickname 麦克不叫麦 --content 催更

# ② 用户看过清单、明确确认后才真删
python skills/shared/scripts/xhs_comment.py delete \
  --url '<笔记链接>' --no-proxy --exec --gap 5 \
  --targets-json '[{"nickname":"麦克不叫麦","content":"催更"}]'
```

- **删除不可恢复** → 必须先 dry-run 给用户确认，再 `--exec`。
- `--content` 强烈建议：同一人多条评论时靠内容片段精确命中，避免误删。
- 删完可重新 `fetch` 核对该评论是否已消失。
- 排错：`EASEL_COMMENT_DEBUG=1` 会把菜单/确认弹窗截图 + DOM 存到 `outputs/_login/`，据此校准
  `SELECTORS["comment_more"]` / `DELETE_MENU_TEXTS` / `CONFIRM_TEXTS`（集中维护，勿散改）。

## 3. 与 comment-insights 串联（先抓后析）

```bash
# 抓评论 → 喂给评论量化分析（情感/高频词/诉求）
python skills/shared/scripts/xhs_comment.py fetch --note-id NOTE_ID --xsec-token 'XSEC_TOKEN' \
  --no-proxy --out outputs/主题名/assets/comments.json
python skills/openclaw/skill-comment-insights/scripts/comment_insights.py \
  analyze --input outputs/主题名/assets/comments.json
```

## 4. 发布后留痕（可选，供人设漂移监控）

回复也是对外发言，批量回评后可留痕：

```bash
python skills/shared/scripts/persona_gate.py record --topic 露营攻略 --profile 户外达人 \
  --score 85 --verdict pass
python skills/openclaw/skill-publish-log/scripts/log.py record --platform 小红书 \
  --title "评论回复×10" --profile 户外达人 --persona-score 85 --persona-verdict pass \
  --skill-source skill-xhs-comment-reply
```

## 5. 离线自检

```bash
python skills/shared/scripts/xhs_comment.py selftest   # 不启浏览器，CI 可跑
python skills/shared/scripts/xhs_comment.py plan --note-id NOTE_ID --replies-json '[...]'
```
