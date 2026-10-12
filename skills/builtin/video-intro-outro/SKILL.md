---
name: video-intro-outro
description: "视频片头 / 片尾：生成带标题、副标题、logo、关注引导的片头卡片和片尾卡片，并拼接到主视频（硬切或淡入淡出转场）。当用户说 片头、片尾、加片头片尾、开场卡片、结尾卡片、标题卡、关注引导页、订阅引导、视频开头加标题、结尾加点赞关注、intro、outro、片头动画 时使用。基于 shared/scripts/intro_outro.py 确定性 ffmpeg 封装。与 poster-hero 区别：poster-hero 出静态封面图，本 SKILL 出可拼接的视频卡片片段。"
layer: produce
---

# 视频片头 / 片尾

> 生成片头/片尾**视频卡片**（标题 + 副标题 + logo + 关注引导），并把 片头 + 主视频 + 片尾
> 归一化后拼接成一条成片。全部走 `skills/shared/scripts/intro_outro.py`，**不要手拼
> drawtext / xfade**——脚本已处理字体路径、音画参数一致、转场时间偏移计算。

> 只做"片头/片尾卡片 + 拼接"。静态封面图见 **poster-hero**；通用剪辑见 **video-editing**；
> 完整"一句话→成片"流水线见 **auto-short-video**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 主视频 | 拼接时必填 | 要加片头/片尾的视频（没给就问） |
| 标题/副标题 | 推荐 | 片头主题、片尾致谢等文案 |
| 关注引导 CTA | 片尾常用 | 如"点赞 + 关注 不迷路" |
| logo | 可选 | 品牌 logo 图片，叠在标题上方 |
| 画幅 | 可选 | 默认竖版 1080x1920；拼接时默认对齐主视频 |
| 背景 | 可选 | 纯色 / 双色渐变 / 图片 |

## 输出（`outputs/主题名/`）

- 片头 / 片尾卡片片段（`intro.mp4` / `outro.mp4`）
- 拼接后的成片（`*-final.mp4`）
- 报告：卡片时长、画幅、转场方式

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/intro_outro.py`（各子命令支持 `-h`）。

### 1. 生成片头卡片
```bash
python skills/shared/scripts/intro_outro.py card \
  --title "本期主题" --subtitle "3 分钟讲清楚" \
  --gradient --color 0x1a2a6c --color2 0xb21f1f \
  --size 1080x1920 --duration 2.5 -o outputs/主题名/intro.mp4
```

### 2. 生成片尾卡片（带关注引导）
```bash
python skills/shared/scripts/intro_outro.py card --preset outro \
  --title "感谢观看" --cta "点赞 + 关注 不迷路" \
  --color black --size 1080x1920 --duration 2.5 \
  -o outputs/主题名/outro.mp4
```
背景三选一：`--color <色>`（纯色）/ `--gradient`（配 `--color`/`--color2` 双色渐变）/
`--bg-image <图>`（图片背景，自动裁切填满）。`--logo <图>` 叠加品牌 logo。

### 3. 拼接到主视频
```bash
# 硬切（默认，最稳）
python skills/shared/scripts/intro_outro.py attach --main <主视频> \
  --intro outputs/主题名/intro.mp4 \
  --outro outputs/主题名/outro.mp4 \
  -o outputs/主题名/<名>-final.mp4

# 淡入淡出转场
python skills/shared/scripts/intro_outro.py attach --main <主视频> \
  --intro outputs/主题名/intro.mp4 --transition fade --trans-duration 0.5 \
  -o outputs/主题名/<名>-final.mp4
```
`--intro` / `--outro` 至少给一个，可只加其一。`--transition` 可选
`none/fade/fadeblack/fadewhite/wipeleft/slideup/circleopen`。画幅默认对齐主视频，
`--size` 可强制。

## Profile 感知

- 有 Profile：标题/CTA 语气贴合 `style.md` 人设；有品牌 logo/主色时用作 `--logo` 与
  `--color`；默认画幅按 `platforms.md` 主平台（抖音/小红书竖版 1080x1920，B站/横版 1920x1080）。
- 无 Profile：用中性文案与默认深色背景，竖版 1080x1920，末尾提示可提供品牌信息定制。

## 规则

1. 卡片时长默认 2.5s，片头别太长（2-3s 为宜），避免劝退。
2. 文案精炼——标题一句、副标题一句、CTA 一句，不堆字。
3. 拼接前脚本会自动把三段归一化到同画幅/帧率/音轨，**不要**自己先转格式。
4. 转场时长自动限制在相邻片段时长内，过长会被收窄。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

片头片尾/关注引导卡片是短视频与 B站/YouTube 的标准件；实现参考 ffmpeg drawtext（文字层）
与 xfade/acrossfade（转场音画交叠）的确定性组合，把易错的时间偏移与参数对齐封装进脚本。
