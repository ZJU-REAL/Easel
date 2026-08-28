# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | skill-wechat-publisher |
| **所属层** | publish |
| **来源仓库** | jiji262/wechat-publisher |
| **GitHub 地址** | https://github.com/jiji262/wechat-publisher |
| **Star 数** | ~500+ |
| **功能描述** | 微信公众号自动创作+发布+多平台同步 |
| **SKILL.md 行数** | 612 |
| **文件总数** | 172 |
| **自包含** | 需要公众号Cookie/API |
| **备注** | 612行，含MD→公众号排版转换 |

> 收录时间: 2026-07-16
> 用途: Easel SKILL 验证测试

## Wave4 瘦身说明（2026-07-23）

- **Easel 路由名**：frontmatter `name` 与目录统一为 `skill-wechat-publisher`；上游项目名和配置文件名仍为 `wechat-publisher`。
- **瘦身**：612 → 117 行。把主题库、配图风格、错误码、反 AI 清单、行内标色、结构库等领域知识下沉到 `references/`；正文只留流程 + 引用指针。
  - references 原有：`anti-ai-checklist.md` / `api_reference.md` / `article-structures.md` / `image-styles-guide.md` / `multi-platform-sync.md` / `newspic-mode.md` / `themes.md` / `typeset-card.md`
  - 本次新增：`inline-markup.md`（8 种行内标色 + 主题文件结构）、`errors.md`（错误码 + 约束）
- **环境标注**：SKILL.md 顶部新增「⚠️ 环境依赖（部分可跑）」表 —— 核心链路（`publish.py` 官方 HTTP API 发草稿 + `ai_score.py` 反 AI 检测 + `html_converter.py` 排版）配好 `app_id`/`app_secret` 后**可跑**；`generate_image.py` 需图像 API key、`multi_publish.py` 多平台同步需浏览器扩展，标注**当前不可用**。
- **移除的臃肿物**（不该进 SKILL）：
  - `docs/`（602K，GitHub Pages 主题预览 HTML + 截图，与 `assets/theme-previews/` 重复）
  - `tech/`（6.7M，示例文章配图）
  - `scripts/baoyu_danger_gemini_web/`（112K，逆向 Gemini Web API 库）
  - 目录体积 ~10M → 2.7M。
- **保留的可跑核心脚本**：`publish.py` / `wechat_api.py` / `ai_score.py` / `html_converter.py` / `api.py` / `config.py` / `wechat_token.py` / `image_handler.py` / `newspic_build.py`；生图后端 `baoyu_image_gen.ts` / `baoyu_image_gen_core.ts` 保留（默认生图入口，非逆向库）。`assets/`（themes / image-styles / theme-previews / typeset-card）保留。
