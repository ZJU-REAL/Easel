# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | short-drama |
| **所属层** | produce（编排型） |
| **来源类型** | 自研（借鉴多个开源方案的方法论） |
| **参考项目** | 原有故事方法论来源不变；音视频生产链新增参考 [HBAI-Ltd/Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app)（模型音频能力/音频参考显式建模）、[Forget-C/Jellyfish](https://github.com/Forget-C/Jellyfish)（对白候选确认、生成 readiness、多轨时间线与 lip-sync）、[wanglongxiao/seedance-drama-maker](https://github.com/wanglongxiao/seedance-drama-maker)（视频审核→有限重试→选优、AAC 统一）、[drasstry/shortdrama-pipeline](https://github.com/drasstry/shortdrama-pipeline)（一镜一句、时长约束、分镜独立重试），以及 [火山方舟视频生成 API](https://www.volcengine.com/docs/82379/1520757) 的 `generate_audio` 能力和 [Google DeepMind Veo](https://deepmind.google/models/veo/) 对原生音频能力边界的说明。 |
| **借鉴方式** | 仅借鉴方法论与产物结构（角色参考图 + I2V + series bible + 时间轴 prompt + 尾帧续接 + **戏剧承诺/故事引擎/人物行动模型/因果反转测试/爽点矩阵/反派阶梯/举证式分级 review**），未引入其代码/模型。剧情/人物/台词深度沉淀为 references（`story-engine.md`/`dialogue-craft.md`/`satisfaction-and-villain.md`/因果反转版 `genre-hooks-handbook.md`/A–E 门 `drama-review-rubric.md`）。确定性资产管理自研 `scripts/drama_ops.py`；**多角色配音自研 `scripts/dubbing.py`**（cast.json 选角 + 逐行 lines.json + 按角色音色/情绪逐行合成 + ffmpeg 拼多声线 voice.mp3/srt）——所有参考项目均为纯文本、**不含 TTS/配音**，这是 Easel 增量。均纯标准库 + selftest。 |
| **内部复用** | ai-image-gen（角色/场景定妆图、关键帧）、ai-video-gen（逐镜 I2V 生视频）、tts.py（edge-tts 逐行多音色合成，dubbing.py 委派）、voice_clone.py（主角/反派克隆音色，可选）、ai-music（BGM）、auto-short-video 的 assemble.py（逐集合成，吃 voice.mp3/srt）、video-reframe（画幅）、skill-douyin-upload/skill-kuaishou-upload（发布） |
| **刻意不做** | 模型级一致性 LoRA（StoryMem/StoryDiffusion，太重）、在未通过 ASR/视觉审核时盲信模型原生对白、把 dub 镜的原生人声与 TTS 配音**叠加成双重人声**（现策略：默认 native-first 让模型说台词、audit 通过就直接用模型原声；只有说错的镜转 dub，且**该镜原生轨整轨丢弃、纯 TTS**——无人声分离时留原生轨必与配音重复，故 dub 舍环境音换不重复；干净保留环境音需 demucs，因重依赖暂不引入）、数字人 |
| **许可** | 随 Easel 项目许可 |

> 整理时间: 2026-08-04
> 用途: 来源溯源与致谢
