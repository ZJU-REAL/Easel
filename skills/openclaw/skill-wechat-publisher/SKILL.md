---
name: skill-wechat-publisher
description: |
  微信公众号文章自动创作与发布工具。给定参考文章、文字或文档，自动搜索整理全网相关信息、生成图文并茂的公众号文章，并发布到微信公众号草稿箱。特别强调反 AI 检测写作。
  触发场景（沾边就用）：用户提到"公众号 / 微信文章 / 推文 / 公号 / 发文 / mp / 草稿箱 / 群发"，或要求把话题/文档/笔记写成公众号文章并发布到微信。
layer: publish
---

# 微信公众号文章自动创作与发布

从素材输入到公众号草稿箱的完整自动化流程：用户只需提供话题或参考资料，skill 完成搜索调研、撰写、配图、排版、AI 味自检、发布。

> **不要调用 `baoyu-post-to-wechat` skill。** 路由时同时看到两者，一律选本 skill（`wechat-publisher`），它带多账号 / 主题排版 / 反 AI 检测 gate。

## ⚠️ 环境依赖（部分可跑）

| 能力 | 状态 | 依赖 |
|------|------|------|
| 公众号发草稿（`publish.py` → 官方 HTTP API） | ✅ 可跑 | `wechat-publisher.yaml` 里的 `app_id` / `app_secret` + IP 白名单 |
| 反 AI 检测（`ai_score.py`） | ✅ 可跑 | 纯本地，无外部依赖 |
| MD→公众号排版（`html_converter.py`） | ✅ 可跑 | 纯本地 |
| 生成配图（`generate_image.py`） | ❌ 当前不可用 | 需图像 API key（OpenAI Images / Gemini 代理） |
| 多平台同步（`multi_publish.py`，阶段七） | ❌ 当前不可用 | 需浏览器 + Wechatsync Chrome 扩展 |

核心链路（写作→排版→反 AI 检测→发草稿）在配好 `app_id`/`app_secret` 后可跑；配图缺 key 时改用外部生图或跳过，多平台同步默认不启用。

## 账号与人格

默认 2 个账号（见 `wechat-publisher.yaml`）：`main`（刷屏AI / 飞哥 / `refined-blue`，热情北京口语，面向 AI 产品）与 `tech`（蒜是哪根葱 / 葱哥 / `minimal-mono`，冷幽默技术直男，面向工程实践）。不指定 `--account` 用 `main`。

**必须按当前账号的 voice 改写语气** —— 两个号写出明显风格差异，这本身就是反 AI 检测的关键（平台对每个号建历史文风基线）。

## 前置条件

```bash
cp wechat-publisher.yaml.example wechat-publisher.yaml   # 填 app_id / app_secret / author / theme
python3 skills/openclaw/skill-wechat-publisher/scripts/wechat_api.py list-accounts
# 验证 API 连接
cd skills/openclaw/skill-wechat-publisher/scripts && python3 -c "from wechat_api import get_access_token; print('OK:', get_access_token()[:10])"
pip install requests pyyaml --break-system-packages 2>/dev/null || pip install requests pyyaml
```

配置文件固定放 skill 根目录（`config.py::_find_unified_yaml()` 只查此处），账号下必须有 `app_id` 和 `app_secret`。API 参数细节见 [references/api_reference.md](references/api_reference.md)，错误码见 [references/errors.md](references/errors.md)。

## 完整工作流程（7 阶段，第 7 为可选 opt-in）

### 阶段一：理解需求与收集素材
搞清用户要什么，同时采集**真人味原料**（具体人名/时间/金额/产品版本/踩过的坑 —— 反 AI 检测最重要原料）。识别目标账号（AI 产品→main，工程→tech），选定 `article_structure` + `opening_hook`。产出 `outputs/主题名/brief.md`。

### 阶段二：全网信息搜索与整理
既搜**权威层**（WebSearch：资讯/数据/案例/官方报告），也搜**真人层**（Reddit/HN/V2EX/即刻/X/小红书的原话作语料）。关键数据多源交叉。产出 `research.md`，每条标来源、分层。

### 阶段三：撰写骨架稿（第一轮）
按结构写初稿，**允许有 AI 味**（下一阶段专门人味化）。`article_structure` 8 种、`opening_hook` 7 种的完整选择规则与写法见 [references/article-structures.md](references/article-structures.md)。骨架稿阶段就主动**混用行内标色**（见 [references/inline-markup.md](references/inline-markup.md)）。避免"首先/其次""值得一提的是""随着…的发展"等 AI 套话。

### 阶段 3.5：人味化改写 pass（反 AI 检测核心）
独立 pass，不与阶段三混。对骨架稿逐段过 **9 条强制清单**（Burstiness / 句式多样性 / AI 高频词黑名单 / 开头破冰 / 人称立场 / 事实密度 / 标点多样性 / 结构不完美 / 按账号 voice 过滤）。每条阈值、完整禁用词表、改写示例**必须逐条对照** [references/anti-ai-checklist.md](references/anti-ai-checklist.md)。

### 阶段四：生成配图（当前环境需外部 key）
默认风格 `hand-drawn-blue`；有具体数字/对比→用 `infographic-*`，金句大字→用 `marker-*`；图内需一字不差的文字→改走**排版卡 typeset-card**（HTML/CSS → 无头 Chrome 2× 截图）。风格选择、共享视觉原则见 [references/image-styles-guide.md](references/image-styles-guide.md)；排版卡设计系统见 [references/typeset-card.md](references/typeset-card.md)。一篇 6-10 张，统一一种风格。生图入口 `scripts/generate_image.py`（需图像 API key），上传用 `scripts/image_handler.py upload`。

### 阶段五：格式转换与排版
```bash
python3 skills/openclaw/skill-wechat-publisher/scripts/html_converter.py article.md --theme refined-blue -o article.html
python3 skills/openclaw/skill-wechat-publisher/scripts/html_converter.py article.md --list-themes
```
主题一般由 `publish.py --account` 自动从 yaml 读。15 套主题的推荐表与视觉简介见 [references/themes.md](references/themes.md)，行内标色系统见 [references/inline-markup.md](references/inline-markup.md)。主题预览：`assets/theme-previews/index.html`。

### 阶段 5.5：AI 味自检 gate（publish.py 内置强制拦截）
`publish.py` 发草稿前自动调 `ai_score.check_ai_score()`，分数 ≥ 阈值（默认 45）直接拦住。阈值：<35 🟢PASS / 35-45 🟡WARN / ≥45 🔴FAIL。手动看细节报告：
```bash
python3 skills/openclaw/skill-wechat-publisher/scripts/ai_score.py outputs/主题名/article.md --threshold 45
```
命中时按脚本列出的 AI 套话/高频词逐句**重写整个句式**（不只换词），重跑到通过。可选双保险：朱雀 / GPTZero 第三方检测。

### 阶段六：发布到草稿箱（不自动群发）
```bash
python3 skills/openclaw/skill-wechat-publisher/scripts/publish.py --account main \
  --input outputs/主题名/article.md \
  --cover .../cover.jpg --title "标题" --digest "120 字以内摘要" --exec
```
先省略 `--exec` 预览账号、模式和输入，向用户展示标题/摘要并取得确认后再执行。`publish.py` 真执行时自动读账号 `author`/`theme` → 出站敏感信息检查 → 排版 → 处理图片 → 转 HTML → 上传封面 → 建草稿 → 返回 `media_id`。成功后调用 `skill-publish-log` 记录草稿；再告知用户登录 mp.weixin.qq.com 手动确认发布。

### 阶段七：多平台同步（可选，默认不启用，当前环境不可用）
一键同步到知乎/掘金/CSDN/头条（均存草稿）。基于 Wechatsync Chrome 扩展 + `@wechatsync/cli`，需浏览器。触发方式与失败处理见 [references/multi-platform-sync.md](references/multi-platform-sync.md)。

## 贴图模式（newspic，与文章模式并列）
对标公众号"图片消息"：5-10 张卡片墙 + 100-300 字短描述。4 步：`brief.md → newspic_build.py 拆卡 → generate_image.py 批量生图 → publish.py --type newspic`。短文本过精简版 AI 味 gate（`ai_score.py --mode newspic`）。字段说明、判据、限制见 [references/newspic-mode.md](references/newspic-mode.md)。

## 文件组织约定
所有产物放项目内 `outputs/主题名/`：最终稿和封面在目录顶层，研究稿、调试 HTML、配图等中间文件放 `assets/`。不要把临时产物写到 Skill 根目录。

## 脚本说明

| 脚本 | 用途 |
|---|---|
| `publish.py` | 完整发布（一键，含 AI 味 gate），支持 `--type news\|newspic` |
| `generate_image.py` | 统一生图入口（需图像 API key） |
| `newspic_build.py` | 贴图拆卡器（brief.md → card_plan.json） |
| `wechat_api.py` | facade —— 重导出下述模块 + CLI |
| `config.py` | （内部）yaml + 配图风格加载 / `set_account` / `get_config` |
| `wechat_token.py` | （内部）`get_access_token`，本地缓存 |
| `api.py` | （内部）图片上传 / 草稿 / 发布 |
| `html_converter.py` | Markdown → 微信 HTML（多主题 + 行内标色） |
| `image_handler.py` | 图片下载 / 上传 / 替换 |
| `ai_score.py` | 反 AI 检测自检（`--mode news\|newspic`） |
| `multi_publish.py` | 多平台同步（阶段七，默认不启用，需浏览器） |

## Profile 感知
有 Easel Profile 时，用 Profile 的账号定位/受众/语气凝练覆盖账号 voice；无 Profile 时退到 yaml 内置 `main`/`tech` 双账号 voice。

## 注意事项
- 文章始终发**草稿箱**，不自动群发；默认 `main`，`--account tech` 切换。
- 默认 dry-run；没有用户对当前标题、摘要、账号和素材的明确确认，不得添加 `--exec`。
- Markdown、HTML 与贴图三条入口都会在上传前扫描密钥、内部地址和路径，命中时必须改稿，不得绕过。
- 两账号 voice/theme 差异是反 AI 检测策略的一部分，不要趋同。
- 错误码（40164 IP 白名单 / 40001 token / 48001 未授权等）见 [references/errors.md](references/errors.md)。
