---
name: video-production
description: >-
  整片视频产线（原片 → 包装级成片）：九步流程 + 八件质量门 + 两道人工确认门，产出成片与全套交付物。
  当用户说"用视频产线做一支整片""把这条原片做成片""整片包装""走视频产线"时使用。
  全程经独立接口驱动：每步可核验、门不过不交付。
layer: produce
---

# 整片视频产线（video-production）

> 把一支原片（口播 / 独白）做成**包装级成片**：摸底 → 转录 → 分场 → 设计表 → 脚手架 → 写码
> → 验证 → 预览 → 渲染 → 交付。质量不靠自觉，靠可执行的门。
>
> 本技能是**薄壳**：只调用独立接口（视频产线 SDK 的 `run.py`），不在本仓库实现任何产线逻辑。

## 什么时候用

用户说「用视频产线做一支整片 / 把这段素材做成片 / 整片包装」时使用。

### 开工前检查（缺源片不要动工）

- **源片必需**：必须有可读的本地路径。用户没给 → **先向用户要**（要路径，或提示他把文件拖进聊天 / 拷到内容库收件箱）；严禁用占位素材开工
- 主题与基调（`--brief`）建议要一句；现成材料（转录稿 / 分场 / 设计表）有就给、没有就按流程走（流程会在需要时停下）

### 让用户看得见（产物贴进对话 · 免上传）

对话消息**直接支持图片与视频**（站内媒体通道 `/api/media/`，零上传、零改前端）。产物落盘后，把它们贴进消息、再配卡片：

- 图片：Markdown 图片语法（`!` + 方括号说明文字 + 圆括号地址），地址写 `/api/media/<outputs 相对路径，逐段 URL 编码>`（示例文件名：`视频产线/<时间戳>/run/preview/f60.png`）
- 视频：`<video src="/api/media/<outputs 相对路径>" controls style="max-width:420px">` 标签
- 文件：Markdown 链接语法（方括号文字 + 圆括号地址）指向 `/api/media/<outputs 相对路径>`，或把要点直接摘进消息

三处必用：
1. **设计表确认卡之前**：先贴设计表要点摘要 + 全文链接（用户"看得见才审得动"）
2. **预览确认卡之前**：把 `run/preview/*.png` 逐张贴成图片，再出预览卡
3. **交付时**：成片贴成 video 标签（`视频产线/<时间戳>/out/final.mp4`），附门报告链接

### 素材怎么给（用户问"怎么把视频给你"时这样答）

1. **首选 · 本地路径**：文件放本机任意位置，对话里报路径即可（例：`E:/clips/raw.mp4`）。无大小限制、不复制文件
2. 小文件可直接**拖进聊天上传**（进内容库收件箱）；大文件不走上传——直接报本地路径（见第 1 条）
3. 也可先手动拷进 `outputs/_inbox/` 再报路径

### 看图自检（see.py · 有就必过）

写码后、进预览门前，用 `skills/shared/scripts/see.py` 把关键帧交给视觉模型自查（先 `cd` 到 Easel 项目根，同 ai-image-gen 的路径铁律）：

```bash
python skills/shared/scripts/see.py describe --image run/preview/f200.png --question "对照设计规范（每场≥3层元素、禁大素场、字幕可读）：①元素够不够 ②字幕有没有问题 ③其他缺陷。只列问题，全过说通过。"
```

- 有明确问题（素/糊/字幕不可读/穿帮）→ **先改再重渲复查**，全过才进预览门
- 素材入场前抽帧核语义：`--question "画面内容是什么？是否对应台词『…』"`；不符就换，不许硬凑
- 它用来发现明显问题；最终审美以用户拍板为准

## 快速开始

```bash
python <ROOT>/skills/video-production/scripts/video_pipeline.py doctor
python <ROOT>/skills/video-production/scripts/video_pipeline.py start --source "C:/path/raw.mp4" --brief "主题一句话"
```

`start` 依次做：建运行态 → 机械段（摸底 / 转录 / 分场）→ **停在需要人参与的地方**。

## 交互循环（重要）

每个命令最后一行是 `STATE: ...`：

| STATE | 含义 | 你要做的 |
|-------|------|---------|
| `awaiting-answer` | 有题待作答 | `pending` 读题 → 用 **ask_user 工具**转问用户 → `answer` + `resume` |
| `done` | 全流程完成 | 报告产物路径（见下） |
| `gate-failed` | 质量门失败 | 把失败项如实报告，**不要交付** |
| `error` | 异常 | 把错误原文报告用户 |

### 转问用户（ask_user 映射规则）

- ask_user 限制：一次 1–3 问、每题 2–4 个选项、header ≤12 字——按此裁剪，选项 label 用中文原样
- 收到回答后，把用户所选 label 对照问题 JSON 的 `options[].value` 映射回：

| 问题 id | 选项 label → value |
|---------|--------------------|
| checkpoint-1（设计表确认） | 通过，按设计表开工→`approve` ｜ 带意见修改→`revise` ｜ 打回重做→`reject` |
| checkpoint-2（预览确认） | 通过，渲全片→`approve` ｜ 有场次要改→`revise` |

- 写回答并续跑：

```bash
python <ROOT>/skills/video-production/scripts/video_pipeline.py answer --id checkpoint-1 --values approve --notes "可选备注"
python <ROOT>/skills/video-production/scripts/video_pipeline.py resume
```

### 自由输入题（如 need-design-table）

题目会写明要产出的文件与放置位置。把说明转给用户；文件就位后重新 `resume`（自动检测在档）。
开工时已有设计表的话，`start` 直接加 `--design-table <md 路径>`。

## 命令一览

| 命令 | 用途 |
|------|------|
| `doctor` | 环境自检（SDK 路径 / 依赖 / 版本） |
| `start --source ... [--brief] [--transcript] [--scenes] [--config] [--gates] [--design-table]` | 开工，跑到第一个停点 |
| `pending` | 打印待作答问题（JSON） |
| `answer --id ... --values a,b [--notes ...]` | 写入作答 |
| `resume` | 从停点续跑 |
| `status` | 进度 / 待作答 / 路径 |

所有命令支持 `--run-dir`（默认最近一次 start）、`--base`（运行态根）、`--sdk`（SDK 路径；或环境变量 `VIDEO_PIPELINE_SDK`）。
`--gates` 可带质量门清单 JSON（内部支持 `{run_dir}` / `{out_dir}` 占位符自动替换）。

## 产物

默认运行态在 `<工作区>/outputs/视频产线/<时间戳>/`（**交付物进「视频产线」项目，内容库里可见**）：
- `run/`：run-state、questions / answers、checkpoints、gate-report、logs
- `out/`：`final.mp4`、`design-table.md`、`gate-report.md` / `gate-report.json`、`manifest.json`

## 红线

- **只转发，不复制 SDK 逻辑**；SDK 升级不改本技能
- 门不过不交付；任何 FAIL 必须如实报告
- 写长代码/大文件务必**分块写**（单次输出有上限，被截断会中断任务；分 2-4 段续写）
- 交付自动带**人审包**（`review-pack/`：每场定格帧 + 核对表）；把它贴给用户，照单核对（交付前已用 `see.py` 自检；终审仍是人眼）
- 设计表是创作步：与用户确认后产出，机器只校验在档

## 退出码（机器语义）

`0` 完成 ｜ `2` 门失败 ｜ `3` 待作答 / 待审批 ｜ `1` 异常
