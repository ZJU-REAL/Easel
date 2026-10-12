---
name: skill-kuaishou-upload
description: >-
  快手视频发布：把竖版短视频发布到快手创作者中心。当用户说"发快手""上传快手""快手投稿"
  "发布到快手""快手视频发布"时使用。基于通用浏览器发布框架（Playwright + 登录态持久化）。
layer: publish
---

# 快手视频发布

> 基于通用浏览器发布框架 `../../shared/scripts/web_publisher.py`（`--platform kuaishou`）。
> 网页自动化发布——需真实浏览器 + 已登录快手创作者中心。

## ⚠️ 环境依赖（同 skill-xhs-publisher 定位）

- `pip install playwright` + `playwright install chromium`
- 首次 `login` 扫码/登录快手创作者中心，登录态持久化到 `~/.easel-browser-profiles/KuaishouProfile` 后复用
  - 远程/headless 环境用 `login-qr --platform kuaishou`（抠二维码成图轮询），或走 Web「账号」页扫码
- **选择器时效**：快手网页改版频繁，内置选择器为最佳努力，**首次发布务必先 `plan` 预览 +
  `--headed` 目视校验**，失效时更新 `web_publisher.py` 中 kuaishou 配置。

无浏览器环境可用 `platforms` / `plan` / `check`。

发布成功输出形如 `✅ 快手发布成功（读回核验：作品 <id>，<状态>；账号：<昵称>）`——
该判定来自**平台作品列表对账**（不是「点完就算」）；未核实的档位会在输出里明确写出原因与「先别重发」提示。

## 执行

脚本：`../../shared/scripts/web_publisher.py`（各子命令 `-h`）。

```bash
python <ROOT>/skills/shared/scripts/web_publisher.py check
python <ROOT>/skills/shared/scripts/web_publisher.py login   --platform kuaishou
python <ROOT>/skills/shared/scripts/web_publisher.py plan    --platform kuaishou \
  --media out.mp4 --title "标题" --tags "#恐怖故事 #都市怪谈 #灵异事件"
# 有头执行，便于首次核对选择器：
python <ROOT>/skills/shared/scripts/web_publisher.py publish --platform kuaishou \
  --media out.mp4 --title "标题" --tags "#话题1 #话题2 #话题3 #话题4" --exec --headed
```

## 登录态：确认「真能发」而不只是「已登录」

快手创作者中心的「外壳」登录态比发布/上传子系统的授权活得久——**外壳显示已登录、昵称头像都在，却可能已经发不出去**（上传 token 过期）。为此 `whoami` 已内置发布子系统鉴权探针（`login_probe`），真校验能否发布而不只看页面外壳，账号页据此自愈假阳性。

- 仍出现「显示已登录、发布却失败」= 发布态过期：去 Web「账号」页重新扫码，或清空
  `~/.easel-browser-profiles/KuaishouProfile` 后重跑 `login-qr`。
- 快手发布 token 偏短命，需要比别的平台更勤地重新扫码，属正常现象。

## Profile 感知

- 有 Profile：标题/话题贴合 `style.md` 与快手生态（生活化、接地气）；竖版 9:16。
- 无 Profile：按快手通用规范（竖版、话题#、口语化描述）。

## 规则（含 2026-08 真机校准）

1. 快手以竖版 9:16 为主，横版素材先用 video-reframe 转竖版；发布走视频流程，只收视频。
2. **话题标签最多 4 个**：超过报「话题标签数量超过上限：4」，`--tags` 控制在 4 个以内。
3. 发布前先 `plan` 预览、`--headed` 目视确认；确认无误再无头批量。
4. **发布按钮靠 JS 派发点击**（脚本已用 `js_click`）：底部提交按钮 class 带哈希后缀（如
   `_button-primary_xxx`）、每次改版都变，纯 CSS `:has-text('发布')` 在 headless 下命中不稳；
   脚本改为定位「可见 + `innerText=='发布'` + class 含 `button-primary`」的元素派发点击。
   注意别误点右上角下拉菜单里的「发布作品」（那不是提交按钮）。
5. **成功判定 = 读回对账（权威）**：点击「发布」后的界面信号（URL 离开 `publish/video`）只作旁证——
   脚本随后回到作品管理页**读本人作品列表对账**（标题前缀 + 时间窗，发前快照排除旧作品），
   输出 `✅ 快手发布成功（读回核验：作品 <id>…）` 才算真成功。另外三档绝不冒报成功，也**不许盲目重发**：
   `unverified`（多轮未见新作品，可能索引延迟——先人工确认再决定）、
   `login_required`（读回时登录态失效——重登后核对，先别重发）、
   `readback_error`（读回通道失败——人工核对，先别重发）。
   **读回未核实 ≠ 没发出去**；视频初始「审核中」，稍后过审公开。
6. 选择器/流程失效不要硬跑——先看截图定位阶段，再更新配置或提示用户平台已改版。
7. 登录态与 Cookie 属敏感信息，妥善保存、不外泄。

## 发布失败排错顺序

① 先看报错档位与读回证据（发布输出/`outputs/_publish.log`）：`unverified`/`login_required`/`readback_error`
先到创作者中心**人工核对是否已发出**（先别重发）→ ② 看 `outputs/_login/kuaishou-publish-fail.png`
截图确认停在哪一步 → ③ `whoami` + 实际打开发布页看 `input[type=file]` 在不在（不在＝没真正登录、
停在营销介绍页）→ ④ 截图核对标题/话题填写、有无标签超限提示 → ⑤ dump `innerText=='发布'` 的元素
确认 class 仍含 `button-primary` → ⑥ 确认 JS 点击后 URL 跳转离开 `publish/video`。据此更新
`web_publisher.py` 配置。

## 参考来源

网页发布思路同 social-auto-upload 的快手模块；本 SKILL 复用统一 Playwright 框架，配置驱动、
登录态持久化。选择器需按平台现状维护；2026-08-19 真机调试校准（登录态发布子系统探针、JS 派发
发布按钮、话题上限 4）；2026-09 起成功判定升级为**读回对账**（作品列表比对，界面 URL 信号仅作旁证）。
