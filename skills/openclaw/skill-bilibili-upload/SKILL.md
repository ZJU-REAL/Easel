---
name: skill-bilibili-upload
description: >-
  B站视频投稿：把视频投稿到哔哩哔哩，支持标题/简介/分区/标签/封面/转载声明/定时发布。
  当用户说"投稿B站""发B站""上传到哔哩哔哩""B站视频发布""投个稿""发到bilibili"时使用。
  包装成熟的 biliup CLI，扫码登录 + cookie 复用。
layer: publish
---

# B站视频投稿（bilibili-upload）

> 包装成熟的 **biliup** CLI 做 B站投稿。走 `scripts/bili_upload.py`（分区名映射 + 参数校验 +
> dry-run 预览 + 执行）。

## ⚠️ 环境依赖

| 依赖 | 说明 |
|------|------|
| biliup CLI | `pip install biliup`（Rust 后端投稿工具） |
| B站 cookie | 首次需 `login` 扫码登录生成（默认 `cookies.json`），之后复用 |
| 外网 | 登录与投稿需访问 B站 |

无头/无网环境可做 `check` 与 `upload`（省略 `--exec` 即 dry-run 预览命令），真实投稿需上述条件。

## 输入

| 字段 | 必填 | 说明 |
|------|------|------|
| 视频 | 是 | 要投稿的视频文件 |
| 标题 | 推荐 | 默认取文件名 |
| 分区 | 推荐 | 分区名（知识/科技/生活…）或 `--tid` 数字 |
| 标签/简介/封面 | 可选 | 标签逗号分隔；封面图；简介 |

## 执行

脚本路径（相对项目根）：`skills/openclaw/skill-bilibili-upload/scripts/bili_upload.py`（各子命令 `-h`）。

```bash
# 0) 检查环境
python <skill>/scripts/bili_upload.py check
# 1) 首次登录（扫码，生成 cookies.json）
python <skill>/scripts/bili_upload.py login --cookie cookies.json
# 2) 看分区
python <skill>/scripts/bili_upload.py tid
# 3) 预览投稿命令（dry-run）
python <skill>/scripts/bili_upload.py upload --video out.mp4 --title "标题" \
  --partition 知识 --tag "AI,教程,效率" --desc "简介" --cover cover.jpg
# 4) 真正投稿
python <skill>/scripts/bili_upload.py upload --video out.mp4 --title "标题" \
  --partition 知识 --tag "AI,教程" --cover cover.jpg --cookie cookies.json --exec
```

- 转载：`--copyright 2 --source <原链接>`。
- 定时发布：`--dtime <10位时间戳>`（距今需 >4 小时）。
- 分区可用中文名（内置 30 个常用）或 `--tid` 数字。

## Profile 感知

- 有 Profile：默认分区/标签贴合 `platforms.md` 的 B站定位与 `style.md` 垂类；标题风格对齐人设。
- 无 Profile：询问分区，标签按内容主题给。

## 规则

1. 投稿前先 `check` 确认 biliup 与 cookie；未登录先 `login`。
2. 先省略 `--exec` 预览命令与参数（默认即 dry-run），确认后再加 `--exec` 投稿。
3. 脚本会在 dry-run 提醒风险、真发前强制扫描标题/简介/标签/转载来源，发现密钥、内部地址或路径时阻止投稿。
4. 投稿成功后调用 `skill-publish-log` 记录平台、时间、标题与内容标识；失败不得记为成功。
5. B站以横版 16:9 为主；竖版素材可先用 video-reframe 处理。
6. 分区选错会影响推荐，拿不准让用户确认分区。
7. 封面、标签（≤10）显著影响点击与推荐，尽量补全。
8. cookie 属敏感信息，妥善保存，不外泄。

## 参考来源

包装 biliup（biliup/biliup-rs，成熟的 B站命令行投稿工具，Rust 后端），支持完整投稿参数
（分区 tid、标签、封面、转载、定时）。本 SKILL 加中文分区映射、参数校验与 dry-run 预览。
