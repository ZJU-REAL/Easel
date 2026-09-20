# vendor/ 来源与同步策略

`video-production` 技能的产线本体不是 Easel 自研，而是**整包内置**（vendored）了外部仓的一份快照。
本文记录它从哪来、内置的是哪一版、我们在上面改了什么、以及怎么跟上游同步。

## 来源

| 项 | 值 |
|----|-----|
| 上游仓 | <https://github.com/mengyuyuan/video-pipeline-sdk> |
| 作者 | mengyuyuan |
| 许可证 | MIT（原文随包保留在 `video-pipeline-sdk/LICENSE`） |
| 内置版本 | **v0.3.5**（上游 commit `e81c6121`，2026-09-17） |
| 内置路径 | `skills/openclaw/video-production/vendor/video-pipeline-sdk/` |
| 体积 | 约 6.1 MB（字体 5.7 MB 是大头） |

上游自身的第三方依赖致谢见 `video-pipeline-sdk/ATTRIBUTIONS.md`，版本历史见其 `CHANGELOG.md`。

> **版本号对账**：引入内置快照的那次提交（`bcf6960`）的 commit message 写的是 v0.3.3，
> 但实际拷进来的树是 v0.3.5（`VERSION` 文件与 `CHANGELOG.md` 顶部条目一致，且与上游
> `e81c6121` 逐文件相符）。**以 `VERSION` 为准**，commit message 是笔误。

## 为什么内置而不是让用户克隆

早期做法是运行时去找外部仓（`--sdk` / `VIDEO_PIPELINE_SDK` 指路）。三个问题：

1. **不自包含** —— 用户装完 Easel 还要单独克隆一个仓，`doctor` 找不到就直接报错。
2. **不可复现** —— 上游随时会动，技能文档描述的工序和用户机器上那份可能对不上。
3. **改不动** —— 我们需要在产线里加三级转录降级（见下），外部仓里改了也留不住。

所以源码与资产整包进仓。**不进仓的**是重依赖，由 `deps/bootstrap.sh` 本地还原：
`deps/remotion/node_modules/`（约 540 MB）、whisper large-v3 模型（约 3 GB）、
`.remotion/` 缓存。根 `.gitignore` 已按此排除。

## 我们在上游之上的改动

内置快照**不是原样不动**的，有 4 处本地修改。同步上游时这几处需要重新套用：

| 文件 | 改动 |
|------|------|
| `pipeline/run.py` `st_transcribe()` | **三级转录降级**。上游只有本地 whisper 一条路，且把 `.srt` 当纯文本塞进 `{"text": …}`、时间轴整个丢掉。改为：tier1 现成稿（`.json` 直接用，`.srt`/`.vtt` 转段级 transcript）→ tier2 云端 ASR（配了 `SILICONFLOW_API_KEY` 才走）→ tier3 本地 whisper 兜底 |
| `tools/srt_to_transcript.py` | 新增。字幕 → 段级 `transcript.json`（`start`/`end`/`text`），tier1 用 |
| `tools/transcribe_api.py` | 新增。云端 ASR 调用，tier2 用。**key 只从环境变量读**，不落配置文件 |
| `tools/render_slideshow.py` | 新增。图片分镜 + TTS 配音这类「非真人出镜」素材的渲染路径（上游假设的是真人出镜，人脸安全区/proxy 那套对幻灯片式素材不适用） |
| `deps/bootstrap.sh` | 新增。Linux 依赖还原脚本（上游 `DEPS.md` 明列为待补）。装 `deps/remotion/` 的 npm 依赖，走 `--ignore-scripts` |

## 同步上游的做法

1. 克隆或更新上游，checkout 目标 tag。
2. 把源码与资产拷进 `vendor/video-pipeline-sdk/`，**排除** `.git`、`node_modules`、已下模型、`__pycache__`。
3. 按上表逐项重新套用本地改动（`run.py` 那处是手工 patch，其余 4 个是新增文件，直接保留即可）。
4. 更新本文的「内置版本」行与上游 commit。
5. 跑 `python3 skills/openclaw/video-production/scripts/video_pipeline.py doctor`，确认找到的是**内置**路径、三级转录状态正确。

同步前先 `diff -rq --exclude=.git --exclude=node_modules <上游> vendor/video-pipeline-sdk`
看清楚当前实际漂移了什么 —— 上表是对已知改动的记录，不是自动校验。

## 致谢

感谢 [@mengyuyuan](https://github.com/mengyuyuan) 开源这套产线并允许内置分发。
Easel 的完整来源清单见 [docs/ACKNOWLEDGMENTS.md](../../../../docs/ACKNOWLEDGMENTS.md)。
