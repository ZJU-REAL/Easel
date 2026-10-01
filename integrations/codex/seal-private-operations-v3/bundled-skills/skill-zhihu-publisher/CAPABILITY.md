---
name: skill-zhihu-publisher
description: >-
  知乎发布：把文章发布到知乎专栏（也可用于回答草稿）。当用户说"发知乎""知乎发布"
  "发布知乎文章""知乎专栏""投知乎"时使用。基于通用浏览器发布框架（Playwright + 登录态持久化）。
layer: publish
---

# 知乎发布

> 基于通用浏览器发布框架 `../../shared/scripts/web_publisher.py`（`--platform zhihu`）。
> 发布到知乎专栏写作页（zhuanlan.zhihu.com/write）。

## ⚠️ 环境依赖

- `pip install playwright` + `playwright install chromium`
- 首次 `login` 登录知乎，登录态持久化复用
  - 远程/headless 环境用 `login-qr --platform zhihu`（抠二维码成图轮询），或走 Web「账号」页登录
- **选择器时效**：知乎正文为 Draft.js contenteditable，发布可能有二次确认弹窗；内置选择器为
  最佳努力，**首次务必 `plan` + `--headed` 校验**，失效时更新 `web_publisher.py` 的 zhihu 配置。

无浏览器环境可用 `platforms` / `plan` / `check`。

## 执行

```bash
ROOT=<项目根>; WP=$ROOT/skills/shared/scripts/web_publisher.py
python $WP check
python $WP login   --platform zhihu
python $WP plan    --platform zhihu --title "标题" --desc "正文..."
python $WP publish --platform zhihu --title "标题" --desc "正文..." --exec --headed
```

## Profile 感知

- 有 Profile：文风专业、有逻辑链，贴合 `style.md`；话题标签按垂类。
- 无 Profile：按知乎通用规范（专业、结构化、有论据）。

## 规则

1. 知乎重深度与专业性，正文结构清晰、有论据；标题克制不标题党。
2. 长文可先用 video-to-article / social-content 成稿，再来发布。
3. 首次 `--headed` 目视确认写作页与发布弹窗；选择器失效即更新配置。
4. 正文为富文本编辑器，复杂排版建议登录后人工微调再发。

## 参考来源

知乎专栏写作页网页流程；复用统一 Playwright 框架。正文 Draft.js 编辑器，选择器按现状维护。
