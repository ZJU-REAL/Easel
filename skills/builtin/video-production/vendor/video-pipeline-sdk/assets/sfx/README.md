# sfx

现成音效（Mixkit）。**mp3 因许可不入库**（Mixkit Free License 允许用于成品，但不允许再分发素材文件本身）。

- 台账：`SOURCES-mixkit.json`（id / 名称 / 直链 / 来源页）
- 抓取脚本：[fetch_sfx.py](../../tools/fetch_sfx.py)（assets.mixkit.co 直链）。在 Easel 项目根使用项目 Python，先把 `REMOTION_PROJECT` 设为本次任务实际的 Remotion 项目目录，再执行 `python skills/builtin/video-production/vendor/video-pipeline-sdk/tools/fetch_sfx.py`；下载文件写入该目录的 `public/sfx/`，不写入技能源目录。
- 硬规：音效只用现成、禁一切生成通道；转场类常用段 0.4–0.8s
