# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | ai-music |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研；封装共享脚本 `skills/shared/scripts/ai_music.py`，纯标准库 urllib 实现异步提交→轮询→下载，无第三方依赖 |
| **参考项目** | 阿里云 DashScope / 百炼（Model Studio）—— https://help.aliyun.com/zh/model-studio/ （异步任务规范：`X-DashScope-Async: enable` 提交 → `output.task_id` → 轮询 `GET /api/v1/tasks/{task_id}`，状态 PENDING/RUNNING/SUCCEEDED/FAILED）；Suno 类第三方 API 通用格式（POST /generate → 轮询 /feed/{id} → audio_url）；后处理复用 FFmpeg（`audio_ops.py` / `video_ops.py`） |
| **许可** | 待核实（DashScope / Suno 均为商用在线服务，需用户自备 API key；脚本本身为项目自研，仅用 Python 标准库） |
| **实测状态** | 代码依据公开 API 文档实现，**未用真实 key 实测**；离线校验（--help / check / 缺 key 报错 / ast.parse）已通过。model 名与端点路径均可用 env / --model 覆盖以适配各家实际参数 |

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
