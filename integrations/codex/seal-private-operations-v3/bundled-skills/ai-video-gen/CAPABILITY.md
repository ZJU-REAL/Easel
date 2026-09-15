---
name: ai-video-gen
description: "AI 视频生成：文生视频 / 图生视频 / 数字人首帧驱动。通过可插拔 provider（通义万相 Wan / 火山 Seedance / 快手可灵 / OpenAI 兼容）异步生成视频，用户自备 API key。当用户说 AI 视频生成、文生视频、图生视频、AI 生成视频、AI 短视频、让图片动起来、数字人视频、生成一段视频 时使用。与 video-strategy（选型/策略）、video-editing（剪辑处理）、clipify（切片）区别：本 SKILL 是从 0 用 AI 生成新视频。"
layer: produce
---

# AI 视频生成

> 文生视频 / 图生视频 / 数字人首帧驱动。封装 `shared/scripts/ai_video.py`，多 provider 可插拔、异步提交→轮询→下载。**用户自备 API key**（在 `.env` 配置）。

## 前置：配置 API key

> **配置检查路径铁律**：先 `cd` 到 `AGENTS.md` 末尾给出的 Easel 项目根，确认当前目录有 `.env` 和 `skills/shared/scripts/`，再运行注册表、`check` 或生成命令。不得改用 workspace 的 `./shared/scripts/...`，也不得以 `env` / `printenv` 没显示变量为由判断未配置。

先选 provider 并在 `.env` 填对应 key，然后 `check` 离线校验：

```bash
python skills/shared/scripts/ai_video.py check --provider dashscope
```

| provider | 服务 | 需在 .env 配 |
|----------|------|-------------|
| `dashscope` | 阿里通义万相 Wan | `DASHSCOPE_API_KEY`（可选 `DASHSCOPE_VIDEO_MODEL`/`DASHSCOPE_BASE_URL`；兼容旧名 `DASHSCOPE_MODEL`） |
| `ark` | 火山引擎 Seedance | `ARK_API_KEY`（可选 `ARK_MODEL`/`ARK_BASE_URL`） |
| `kling` | 快手可灵 | `KLING_ACCESS_KEY` + `KLING_SECRET_KEY`（JWT 鉴权） |
| `openai-compatible` | 通用 /videos 端点 | `VIDEO_API_KEY` + `VIDEO_BASE_URL`（可选 `VIDEO_MODEL`） |
| `xhs-maas` | 小红书内网 MaaS（happyhorse 文/图生视频）| `XHS_MAAS_API_KEY`（可选 `XHS_MAAS_VIDEO_BASE`/`XHS_MAAS_T2V_MODEL`/`XHS_MAAS_I2V_MODEL`）。DashScope 风格异步 + api-key 头，内网直连 |
| `agnes` | Agnes（agnes-video-2.5-flash）| `AGNES_API_KEY`（可选 `AGNES_BASE_URL`/`AGNES_MODEL`/`AGNES_SIZE`）。OpenAI Videos 兼容创建 + 自定义端点轮询；**默认带原生音频**（prompt 描述声音）；外网走代理 |

也可设 `VIDEO_PROVIDER` 免去每次 `--provider`。

执行前先跑 `model_registry.py configured --group video --env-file .env`：只有一个可用就显式选它；多个可用且用户没点名时，列出 provider/模型询问本次使用哪个，不按默认值擅自选择。

## 输入

> **画幅确认硬门**：用户或上游任务未明确横版/竖版（或 16:9/9:16/具体比例）时，任何生成/付费调用前必须追问并等确认；不得从平台、Profile 或脚本默认值静默推断。已明确则不重复问。

- 文生视频：画面/镜头/风格描述（prompt）
- 图生视频：一张输入图（本地路径或 URL）+ 可选运动描述
- 可选：时长 `--duration`、画幅 `--ratio`（16:9 / 9:16 / 1:1）、模型 `--model`、原生音频 `--audio auto|on|off`

## 输出

生成的视频文件；必须用 `-o` 指定到 `outputs/主题名/`。异步任务自动轮询到完成再下载。

## 执行步骤

1. **确认配置与能力**：先运行 `check`，再运行 `capabilities --provider <p> --model <m>`。短剧不得根据品牌名猜测模型是否支持原生音频；新模型用 `VIDEO_CAPABILITIES_JSON` 登记能力和请求字段，无需修改调用流程。
   - **`probe-dialogue`**（短剧用）：真发 1 次生成 + ASR，测该模型能否**逐字忠实**说出指定台词，判 `dialogue_faithful` 并缓存——短剧据此决定用原生对白，还是"无台词生成 + 后期配音"。用法 `probe-dialogue --provider <p> --model <m>`。
2. **写好 prompt**：AI 视频对 prompt 敏感，按 [AI 视频提示词规范](../video-strategy/references/ai-video-prompting.md) 写镜头、运镜、风格与时长。竖版短视频用 `--ratio 9:16`。
3. **文生视频**：
   ```bash
   python skills/shared/scripts/ai_video.py text2video --provider dashscope \
     --prompt "海边日落，慢镜头推进，暖色调，电影感" --ratio 9:16 --duration 5 \
     --audio auto \
     -o outputs/主题名/clip.mp4
   ```
4. **图生视频 / 让图动起来 / 数字人首帧**：
   ```bash
   python skills/shared/scripts/ai_video.py image2video --provider kling \
     --image outputs/主题名/cover.png --prompt "人物微笑挥手，头发轻微飘动" \
     -o outputs/主题名/clip.mp4
   ```
5. **后续加工**：生成的片段可交给 `video_ops.py`（拼接/加字幕/加 BGM/横竖转）、`auto-subtitle`（字幕）、`tts-voiceover`（配音）串成成片，或直接进 `auto-short-video` 端到端流程。

## Profile 感知

- 有 Profile：从 `style.md` 取视觉风格倾向注入 prompt；`platforms.md` 只用于给出画幅建议，不能替代用户确认。
- 无 Profile：先确认横版/竖版，再按已确认比例生成。

## 注意

- 视频生成 API 均为异步且**耗时较长**（数十秒到数分钟）+ **按量计费**，先与用户确认。
- 各 provider 的 model 名/字段各版本有差异，均可用 `--model` 或 env 覆盖；如报错对照官方最新文档调整。
- `--audio auto` 只按 capability profile 映射已知字段；能力声明不等于质量保证，下载后仍须 ffprobe/ASR/视觉审计。网关默认有声但开关字段未知时，不猜测注入参数。
