# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | video-production |
| **所属层** | produce |
| **来源类型** | 自研（内置 SDK + Easel 侧改造） |
| **原始来源** | 世于我愿 · 视频产线 SDK（https://github.com/mengyuyuan/video-pipeline-sdk，MIT）——已**内置**进 `vendor/video-pipeline-sdk/`，并在其基础上加 Linux `bootstrap.sh` 与**三级转录**（SRT → 硅基流动 ASR API → 本地 whisper） |
| **参考项目** | 视频产线 SDK（run.py 单入口契约 / 问答协议 questions-answers / 八件门聚合） |
| **许可** | 随 Easel 项目许可；所调用 SDK 为 MIT |

> 整理时间: 2026-09-17
> 用途: 来源溯源与致谢
