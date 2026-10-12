# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | ai-image-gen |
| **所属层** | produce |
| **来源** | Easel 自研 |
| **参考** | OpenAI Images API（/images/generations、/images/edits、/images/variations）；apimart.ai 异步图片任务 API |
| **功能描述** | 通用 AI 生图：文生图 / 图生图（图像编辑）/ 图像变体，OpenAI 兼容同步 + apimart 异步双模式自动检测 |
| **核心脚本** | `skills/shared/scripts/ai_image.py`（纯标准库 urllib/http，无第三方依赖） |
| **子命令** | text2img / img2img / variations / check |
| **配置** | `.env` 三项：IMG_BASE_URL / IMG_MODEL / IMG_API_KEY（含 OPENAI_* 等别名），用户自备 key |
| **profile_aware** | true |
| **自包含** | 需用户配置图像生成 API（OpenAI 兼容 或 apimart） |

> 创建时间: 2026-07-23
> 用途: 补齐 produce 层通用 AI 生图能力（区别于电商专用 ecom-details-image 与 HTML 渲染类 card-*）

## 设计说明

- **复用**：脚本复用了项目已验证的 `ecom-details-image/scripts/generate_image.py` 的核心约定与逻辑——
  env 别名解析（IMG_* + OPENAI_* 别名）、就近 `.env` 加载、base_url 自动检测同步/异步、
  apimart 异步提交→轮询 `/tasks/<id>`→下载、b64_json / URL 结果落盘、统一中文 `fail()` 错误处理。
- **新增**：argparse 子命令（text2img/img2img/variations/check）；
  `check` 离线校验（读 env、脱敏打印、报模式、缺项给示例，不发任何请求）；
  OpenAI `/images/edits` 与 `/images/variations` 的纯标准库 multipart 上传；
  `.env` 宽松解析（跳过非 KEY=value 行并告警，避免 check 因用户 .env 杂行崩溃）。

## 离线验证（无真实 key）

- `python skills/shared/scripts/ai_image.py --help` 及各子命令 `-h`：正常
- `ai_image.py check`：正常打印配置状态，缺项退出码 2、不崩溃
- 缺 key 时 `text2img`：输出友好中文错误，无 traceback
- `ast.parse` 通过
- 未使用真实 key 做端到端联网测试（用户自备 key 后可实际出图）
