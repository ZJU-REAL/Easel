---
name: skill-channels-upload
description: >-
  微信视频号发布：把竖版短视频发布到微信视频号（channels.weixin.qq.com）。当用户说
  "发视频号""上传视频号""视频号发布""发到微信视频号""视频号投稿"时使用。基于通用浏览器
  发布框架（Playwright + 登录态持久化），微信扫码登录。
layer: publish
---

# 微信视频号发布

> 基于通用浏览器发布框架 `../../shared/scripts/web_publisher.py`（`--platform weixin-channels`）。

## ⚠️ 环境依赖

- `pip install playwright` + `playwright install chromium`
- 首次 `login` 用**微信扫码**登录视频号助手，登录态持久化复用
  - 远程/headless 环境用 `login-qr --platform weixin-channels`（抠二维码成图轮询），或走 Web「账号」页登录
- **选择器时效**：视频号发布页描述区可能是富文本 div 而非 textarea，内置选择器为最佳努力，
  **首次务必 `plan` + `--headed` 校验**，失效时更新 `web_publisher.py` 的 weixin-channels 配置。

无浏览器环境可用 `platforms` / `plan` / `check`。

## 执行

```bash
ROOT=<项目根>; WP=$ROOT/skills/shared/scripts/web_publisher.py
python $WP check
python $WP login   --platform weixin-channels           # 微信扫码
python $WP plan    --platform weixin-channels --media out.mp4 --title "标题"
python $WP publish --platform weixin-channels --media out.mp4 --title "标题" --exec --headed
```

## Profile 感知

- 有 Profile：标题短（≤22字）贴合人设；竖版 9:16；可带话题与合集。
- 无 Profile：按视频号通用规范（短标题、竖版、正向内容）。

## 规则

1. 视频号竖版 9:16；横版先 video-reframe 转制。
2. 标题要短（视频号标题偏短），正文可展开。
3. 首次 `--headed` 目视确认扫码与发布流程；选择器失效即更新配置。
4. 视频号内容审核偏严，发布前过 skill-quality-gate 合规检查。

## 参考来源

视频号助手网页发布流程；复用统一 Playwright 框架。微信登录需扫码，选择器按平台现状维护。
