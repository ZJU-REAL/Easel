# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | ai-video-gen |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研（`shared/scripts/ai_video.py`） |
| **参考项目** | 沉淀自 AIDC-AI/Pixelle-Video（多供应商视频生成统一配置：DashScope-Wan / ARK-Seedance / Kling）、LuoGen-AI/LuoGen-agent（数字人口播流程）；各 provider 依据其公开 REST API 文档实现 |
| **依赖** | Python 标准库（urllib/hmac/hashlib，无第三方）；用户自备各 provider 的 API key |
| **许可** | 待核实（参考项目 Apache-2.0 / GPL-3.0，本实现为自研封装） |

> 整理时间: 2026-08-26
> 用途: 来源溯源与致谢

## 说明

文/图生视频 + 数字人首帧驱动，6 个可插拔 provider：DashScope / ARK / Kling / OpenAI-compatible / 小红书 MaaS / Agnes。异步提交→轮询→下载，统一声明原生音频与对白能力；Kling 用标准库实现 HS256 JWT。Agnes 已用真实 key 端到端验证生成 H.264 + AAC 成片，其余 provider 的实测状态以提交记录为准。model/base_url 可由 env 覆盖。与 video-strategy（策略选型）/video-editing（剪辑）/clipify（切片）划清边界。
