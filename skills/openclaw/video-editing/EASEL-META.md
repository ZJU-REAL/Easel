# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | video-editing |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研（frontmatter 与正文均无来源信息，如实标注） |
| **参考项目** | 无（技术上依赖 ffmpeg/ffprobe） |
| **许可** | 随 Easel 项目许可 |
| **版本** | 0.2.0 |

## 依赖脚本

| 脚本 | 位置 | 说明 |
|------|------|------|
| `video_ops.py` | `skills/shared/scripts/video_ops.py` | 通用视频处理封装（subprocess 调 ffmpeg/ffprobe）。12 个子命令：`cut / concat / speed / silence-cut(别名 mute-cut) / text / aspect / frame / gif / compress / bgm / watermark / info`。`--selftest` 用 testsrc+sine 跑通 cut/aspect/frame/gif。中文字体自动探测（wqy-microhei）。与 clipify 划边界：不做人脸 pan / 字幕烧录。多个视频类 SKILL 共享。 |

## 变更记录

- **0.2.0（2026-07-23）**：SKILL.md 从"md 里列 ffmpeg 命令、无脚本"重构为
  统一调 `skills/shared/scripts/video_ops.py`；新增 concat/aspect/frame/gif/
  compress/bgm/watermark/info 覆盖；内联平台规范简表。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢
