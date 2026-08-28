---
name: skill-douyin-upload
description: |
  将视频/图文内容发布到抖音（creator.douyin.com）。基于 Playwright + 持久化登录态，headless 即可运行，
  流程与选择器移植自开源实现 douyin-upload-mcp-skill（含高清发布入口、切 tab、上传等转码、AI 封面、
  发布成功 toast 校验、二维码登录）。适用场景：发布抖音视频、发布图文、扫码登录、发布前预检。
layer: publish
---

# 抖音发布助手（douyin-upload）

在用户确认后，调用 `douyin_publish.py` 完成**视频/图文发布**。

## 运行方式（Playwright，headless 可用）

统一走 **`../../shared/scripts/douyin_publish.py`**（CWD=项目根）。Playwright + 持久化登录态驱动
抖音创作者后台，headless 即可发布——**替代了旧的 CDP/puppeteer/MCP Node 死栈**（需真实 Chrome，
本环境跑不了，已删除）。

| 依赖 | 说明 |
|------|------|
| playwright + chromium | 本环境已装（`douyin_publish.py check` 验证） |
| 已扫码登录 | `login` 抠二维码成 PNG（默认 `outputs/_login/douyin.png`，Web「账号」页可扫）→ cookie 持久化到 `~/.easel-browser-profiles/DouyinProfile` |
| 干净网络 IP | 抖音对机房/代理 IP 更易触发风控短信墙（登录与**发布**都可能弹）。短信墙**可过**——脚本支持验证码回填（见「短信验证码处理」），无需家宽 IP；仍建议尽量用干净 IP 降低触发频率 |

## 能力范围

- **现做**：视频发布、图文发布、扫码登录、发布前预检（plan）。
- 话题：写进作品简介的 `#话题`（抖音自动联想成话题）。
- 视频发布含：上传等转码（≤5min）+ 选 AI 推荐封面。

## 风险提示

抖音自动化发布存在被平台风控/限流风险。默认提醒用测试号、小流量、人工复核。脚本已内置反检测
（`--disable-blink-features=AutomationControlled` + 逐字符输入 + zh-CN）；风险不可完全消除。

## 执行流程

```
check（环境就绪？）
  → 未登录 → login（抠二维码，Web 账号页扫 或 CLI 扫）
  → plan（dry-run 预检：标题长度/媒体路径/步骤）— 给用户确认最终标题、简介、媒体
  → 发布前人设检查（见下）
  → publish / publish-video --exec（首次建议 --headed 校验选择器，OK 后 headless 复跑）
  → 【若弹短信墙】问用户验证码 → 回填 → 脚本自动过墙（见「短信验证码处理」）
  → 成功校验（脚本内置：发布后 toast「发布成功」）
  → 发布后留痕（见下）
```

## 短信验证码处理（对话页发布必读）

抖音发布点「发布」后可能弹**风控短信墙**（提示『接收短信验证码』）。脚本已内置完整过墙能力（`_handle_publish_sms`：下发验证码 → 轮询码文件 → 填码提交，最多等 300s，可多次重输），**但对话页里 agent 必须主动把验证码递进去**——否则脚本会空等 300s 超时失败。

**对话页正确姿势（后台跑 + 轮询状态 + 问用户 + 写码文件）**：

1. **后台**启动发布（务必带 `--status-file` 和 `--sms-code-file`，路径用 `outputs/_login/` 下）：
   ```bash
   python skills/shared/scripts/douyin_publish.py publish-video --exec \
     --title "标题" --content "简介" --video /abs/v.mp4 --tags "旅行,攻略" \
     --status-file outputs/_login/douyin.publish.json \
     --sms-code-file outputs/_login/douyin.code
   ```
2. **轮询** `outputs/_login/douyin.publish.json`（JSON，字段 `state`：`starting`→可能 `sms_required`→`verifying`→`success`/`error`）。
3. 读到 `state=="sms_required"`：把该文件里的 `message`（含发码手机尾号）转达用户，**在对话里向用户要验证码**。
4. 拿到验证码后，把**纯数字**写进码文件（一次性消费，脚本读走即删）：
   ```bash
   printf '%s' "123456" > outputs/_login/douyin.code
   ```
5. 继续轮询直到 `success`/`error`。码错会退回 `sms_required`，可再要一次重写。

要点：验证码文件内容是纯数字（4–8 位）；不要同步前台阻塞跑发布再想中途问用户（Bash 会一直卡住直到脚本退出）。发布页（Web「发布中心」）已用同一套文件协议自动弹框，无需 agent 介入。

## 发布前人设检查（有 Profile 时）

按 AGENTS.md「发布前人设一致性检查」：先 **skill-persona-check** 比对内容×画像，评分喂
`python skills/shared/scripts/persona_gate.py check --score 85`——低于 80 分时警告并给修改建议，
但不阻断发布；用户已明确要发布就继续执行。

## 发布后留痕

```
python skills/shared/scripts/persona_gate.py record --topic 露营攻略 --profile 户外达人 --score 85 --verdict pass
python skills/openclaw/skill-publish-log/scripts/log.py record --platform 抖音 --title "周末露营攻略" --profile 户外达人 --persona-score 85 --persona-verdict pass --skill-source skill-douyin-upload
```

## 必做约束

- 发布前必须让用户确认最终标题、简介、媒体（先跑 `plan`）。
- 图文发布必须有图片，视频发布必须有视频（二选一）。
- 标题 ≤ 30 字（脚本校验，超限拦下）。
- 文件路径必须绝对路径（脚本解析并校验存在）。
- 首次或疑似改版：先 `--headed` 观察，校验通过再 headless。
- 定位失败改 `douyin_publish.py` 顶部 `SELECTORS` 字典（单点集中，每条标了参考源）。

## 命令样例

```bash
python skills/shared/scripts/douyin_publish.py check
python skills/shared/scripts/douyin_publish.py login                     # 抠二维码扫码
python skills/shared/scripts/douyin_publish.py plan --title T --video /abs/v.mp4 --tags "旅行,攻略"
python skills/shared/scripts/douyin_publish.py publish-video --exec --headed \
  --title "标题" --content "简介" --video /abs/v.mp4 --tags "旅行,攻略"
python skills/shared/scripts/douyin_publish.py publish --exec --headed \
  --title "标题" --content "简介" --images /abs/a.jpg,/abs/b.jpg
```
