# 内置 SDK 快照说明

`video-production` 为「薄壳 + 内置快照」结构：产线逻辑全部来自来源仓，`sdk/` 是其**完整目录快照**，随技能分发、开箱即用。

| 项 | 值 |
|---|---|
| 来源 | https://github.com/mengyuyuan/video-pipeline-sdk （MIT） |
| 快照版本 | **v0.3.3**（2026-09-17，对应源仓 tag `v0.3.3`） |
| 快照方式 | 源仓 `git archive v0.3.3` 整目录导出，未做内容改动 |
| 版本核对 | `sdk/pipeline/run.py` 的 `VERSION` 与 `sdk/CHANGELOG.md` |
| 默认发现 | 薄壳脚本自动识别本目录（零配置）；可用 `VIDEO_PIPELINE_SDK` 环境变量或 `--sdk` 覆盖 |
| 同步策略 | 上游发新版时整目录替换 `sdk/` 并更新本文件版本行；不逐文件手改 |

> 快照内 `assets/fonts/simhei.ttf` / `simkai.ttf` 为 Windows 系统字体（不可再分发），未随包；需要时按 `sdk/assets/fonts/README.md` 自备。
