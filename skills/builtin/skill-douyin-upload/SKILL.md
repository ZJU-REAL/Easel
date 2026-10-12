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
  → 成功校验（脚本内置：发布后**读回创作者中心作品列表对账**——标题+时间窗对上该作品才算 success）
  → 发布后留痕（见下）
```

## 短信验证码处理（对话页发布必读）

抖音发布点「发布」后可能弹**风控短信墙**（提示『接收短信验证码』）。脚本已内置完整过墙能力（`_handle_publish_sms`：下发验证码 → 轮询码文件 → 填码提交，最多等 300s，可多次重输），**但对话页里 agent 必须主动把验证码递进去**——否则脚本会空等 300s 超时失败。

要码有两种姿势，**先探测本部署支持哪种**：

```bash
printenv EASEL_ASKUSER_CARDS   # "1"=支持选项卡片(OpenClaw 2026.9.x)；"0"/空=不支持(如 2026.6.11)
```

- `=="1"` → 走 **A. 卡片模式**（同轮弹卡、当场拿码，体验最好）。
- `=="0"` 或空 → 走 **B. 文字等待模式**（发文字要码 → **结束本轮** → 用户下一条消息回码 → 你写码文件）。**2026.6.11 必须用这条**，卡片在这版桥接不了、弹了也收不到答案。

无论哪种，前两步（后台启动 + 轮询）完全一样。

### 第 1 步：**后台脱离**启动发布（关键：必须能跨对话轮存活）

务必带 `--status-file` 和 `--sms-code-file`（路径放 `outputs/_login/` 下）。下列命令适用于 Linux：用 `setsid`+`&`+日志重定向**把进程脱离当前 shell**，避免当前执行引擎退出时一并终止登录等待；Windows 使用 Web「账号」页启动登录，不照抄这组 shell 命令：

```bash
mkdir -p outputs/_login
setsid python skills/shared/scripts/douyin_publish.py publish-video --exec --no-proxy \
  --title "标题" --content "简介" --video /abs/v.mp4 --tags "旅行,攻略" \
  --status-file outputs/_login/douyin.publish.json \
  --sms-code-file outputs/_login/douyin.code \
  > outputs/_login/douyin.publish.log 2>&1 &
```

### 第 2 步：轮询状态

**每 2–3 秒查一次，用短命令**——别一次性长睡眠干等，墙一出现你才能立刻反应：

```bash
sleep 3; cat outputs/_login/douyin.publish.json
```

状态机（JSON 字段 `state`）：`starting`→可能 `sms_required`→`verifying`→`success`/`error`。**`success` 只在发布后读回创作者中心作品列表、对账通过才写入**，message 里带核验到的作品 id 与状态；读回没对上落 `error`，message 区分三种：登录态失效（需重新登录）/ 列表暂未见本次内容（需到内容管理页人工核对）/ 读回通道异常。

读到 `state=="sms_required"`（含『正在发送验证码』阶段——**看到就立即要码，不必等短信到**）后，按探测结果分流：

### A. 卡片模式（EASEL_ASKUSER_CARDS==1）

**马上调用 `ask_user` 工具弹【验证码卡片】要码——不要用普通文字消息**（卡片自带「自行输入…」填空，用户填完提交你直接拿到数字）。参数模板（`options` 必需 2–4 个；验证码本身走卡片自带的自由输入）：

```json
{"questions":[{"id":"sms_code","header":"发布验证","question":"抖音发布触发短信验证：请把手机收到的 6 位验证码填进来（点「自行输入…」后输入数字）。","options":[{"label":"重新发送验证码"},{"label":"取消本次发布"}]}],"timeoutSeconds":300}
```

用户提交后按答案分流：**纯数字（4–8 位）** → 写码文件（见下）；**「重新发送验证码」** → 建重发信号文件后**立刻再弹一张卡**（问题改为「已重发——把新收到的验证码填进来」）；**「取消本次发布」** → 告知脚本会自行超时退出。整轮不结束，卡片答完接着轮询到 `success`/`error`。

### B. 文字等待模式（EASEL_ASKUSER_CARDS==0 或空，如 2026.6.11）

后台进程已用 `setsid` 脱离、会一直等码（≤300s），所以你可以放心**结束本轮**、把要码交给下一轮：

1. 发一条**普通文字消息**告诉用户：抖音发布触发短信验证，请把手机收到的 6 位验证码直接发给你；若没收到可回「重发」。**然后结束本轮**（不要在本轮里 `sleep` 干等，用户此刻还没输码，Bash 白卡）。
2. **用户下一条消息**就是验证码（同一会话，你能看到发布上下文）。按内容分流：
   - **纯数字（4–8 位）** → 写码文件（见下），然后**立即恢复轮询**（后台进程还活着，`cat` 状态文件即可）；
   - 含「重发/没收到/重新发送」→ 建重发信号文件（见下），告诉用户已请求重发、收到新码再发你，本轮再结束等下一轮；
   - 「取消」→ 建取消/等超时，告知用户本次发布将退出。
3. 恢复轮询后若又回到 `sms_required`（码错/重发），重复本流程：再发文字要码 → 结束本轮 → 下轮收码。

> 跨轮要点：**别每轮都重新起发布进程**——第 1 步只在最开始跑一次。后续轮里先 `cat outputs/_login/douyin.publish.json` 看它是否还在 `sms_required`/`verifying`，在就只写码/轮询，不要重复 publish。

### 写码文件 / 重发信号（两种模式通用）

把**纯数字**写进码文件（一次性消费，脚本读走即删）：

```bash
printf '%s' "123456" > outputs/_login/douyin.code
```

请求重发（脚本收到信号会在墙上点「重新发送」再下发验证码，一次性）：

```bash
touch outputs/_login/douyin.code.resend
```

继续轮询直到 `success`/`error`。码错会退回 `sms_required`，可再要一次重写。

要点：验证码文件内容是纯数字（4–8 位）；**全程保持"后台脚本 + 短轮询"模式**——绝不要同步前台阻塞跑发布（不带 `&`）再想中途问用户（Bash 会一直卡住直到脚本退出）。发布页（Web「发布中心」）已用同一套文件协议自动弹原生输入框，与对话页无关、无需 agent 介入，任何版本都能用。

**速度要点（决定成败）**：墙出现 → 脚本识别（≤15s）→ 你读到 `sms_required` → **数秒内**要码（卡片模式弹卡 / 文字模式发消息，别先长篇解释）→ 拿到码 → **立即**写码文件（一条 `printf` 的事，不拖）。任何环节拖 30 秒以上，用户手机上的验证码就可能过期要重发。文字模式跨轮无妨（后台等 300s），但你自己收到码后别拖着不写。

## 发布前人设检查（有 Profile 时）

按 AGENTS.md「发布前人设一致性检查」：先 **skill-persona-check** 比对内容×画像，评分喂
`python skills/shared/scripts/persona_gate.py check --score 85`——低于 80 分时警告并给修改建议，
但不阻断发布；用户已明确要发布就继续执行。

## 发布后留痕

```
python skills/shared/scripts/persona_gate.py record --topic 露营攻略 --profile 户外达人 --score 85 --verdict pass
python skills/builtin/skill-publish-log/scripts/log.py record --platform 抖音 --title "周末露营攻略" --profile 户外达人 --persona-score 85 --persona-verdict pass --skill-source skill-douyin-upload
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
