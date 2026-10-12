---
name: meme-generator
description: "表情包 / Meme 生成：给图片加经典上下大字（白字黑边）做梗图，或在图上/下加配文条做反应图（'当…的时候'格式）。中英文都支持，自动换行和字号自适应。当用户说 表情包、做表情包、meme、梗图、reaction 图、配图加字、给这张图加字、做个梗、反应图、当xx的时候 时使用。基于 shared/scripts/meme_ops.py（Pillow）。与 card-quote 区别：card-quote 做精致金句卡片，meme-generator 做梗图/表情包；与 image-editing watermark 区别：那个加水印，本 SKILL 加梗字。"
layer: produce
---

# 表情包 / Meme 生成

> 给图片加梗字做表情包。两种排版：经典上下大字叠在图上，或加纯色配文条（反应图格式）。
> 走 `skills/shared/scripts/meme_ops.py`，**不要手算字号/换行**——脚本已做自适应字号、
> 中英文换行、白字黑边。

> 精致金句卡片见 **card-quote**；小红书知识卡见 **card-xiaohongshu**；加水印见 **image-editing**。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 底图 | 是 | 表情包底图/截图/反应图（没给就问） |
| 文字 | 是 | 上下字（overlay）或配文（bar） |
| 排版 | 否 | `overlay` 上下叠字（默认）/ `top-bar` 顶配文 / `bottom-bar` 底配文 |

## 输出（`outputs/主题名/`）

- 表情包图片（jpg/png）

## 执行步骤

脚本路径（相对项目根）：`skills/shared/scripts/meme_ops.py`（`make -h` 看参数）。

```bash
# 经典上下大字（白字黑边叠图上）
python skills/shared/scripts/meme_ops.py make -i cat.jpg \
  -o outputs/主题名/out.jpg --top "老板说" --bottom "这个需求很简单"

# 反应图：顶部配文条（"当…的时候"格式）
python skills/shared/scripts/meme_ops.py make -i react.jpg \
  -o outputs/主题名/out.jpg --layout top-bar \
  --caption "当我周一早上打开电脑看到一堆消息"

# 底部黑条白字
python skills/shared/scripts/meme_ops.py make -i img.jpg -o out.png \
  --layout bottom-bar --caption "这就是生活" --bar-color black --text-color white
```

## 排版怎么选

| 排版 | 效果 | 适用 |
|------|------|------|
| `overlay`（默认） | 白字黑边叠在图上、顶/底 | 经典梗图（top/bottom text） |
| `top-bar` | 图上方加白条黑字 | 反应图、"当…的时候" |
| `bottom-bar` | 图下方加配文条 | 吐槽、点题 |

- 英文默认转大写（更"梗"），`--no-upper` 关闭。
- 描边粗细 `--stroke`（overlay，默认按字号自适应）。

## 规则

1. 文字精炼——梗图靠短句，别写长段。
2. 字号/换行由脚本自适应，别手动塞超长文本（会自动缩小但太长仍不好看）。
3. overlay 用 --top/--bottom；bar 布局用 --caption。
4. 要透明或多次叠加时输出 `.png`，一般发图用 `.jpg`。
5. 产物统一进 `outputs/主题名/`。

## 参考来源

经典 meme（Impact 白字黑边上下排）与中文反应图（配文条）是社媒高传播格式。用 Pillow 做
自适应字号、中英混排换行、描边，输出确定可复现。
