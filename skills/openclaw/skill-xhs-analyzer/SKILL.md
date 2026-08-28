---
# ⚠️ name 保持 "redbook" —— clawhub 安装（`clawhub install redbook`）与下方 metadata.openclaw
#    install 块均以此 name 为键；改名会破坏 OpenClaw/ClawHub 安装。目录名 skill-xhs-analyzer
#    与此 name 有意不一致，勿"对齐"目录名而改动 name。
name: redbook
description: >-
  小红书内容分析：搜索笔记、拉取互动数据、分析爆款规律、创作者画像、限流检测，支持 CLI 自动化操作。
  当用户说"小红书数据分析""小红书爆款分析""笔记数据""小红书限流检测""小红书创作者画像""分析小红书账号"时使用。
  发布与日常互动运营请用 skill-xhs-publisher。
layer: attribute
metadata:
  openclaw:
    requires:
      bins:
        - redbook
    install:
      - kind: node
        package: "@lucasygu/redbook"
        bins: [redbook]
    os: [macos]
    homepage: https://github.com/lucasygu/redbook
---

# Redbook — 小红书内容分析 CLI

用 `redbook` CLI 搜索笔记、读内容、分析创作者、提取爆款规律、研究选题。**OpenClaw 用户：** `clawhub install redbook` 或 `npm install -g @lucasygu/redbook`。

## ⚠️ 环境依赖（当前环境不可用）

本 SKILL 依赖以下运行时，**在当前"macOS 专属 / Linux"环境下不可用**，属于死代码保留，仅供部署到 macOS 桌面时启用：

| 依赖 | 说明 |
|------|------|
| macOS | cookie 抽取用原生 keychain（`os: [macos]`） |
| Node.js ≥ 22 | 运行 `@lucasygu/redbook` CLI |
| `redbook` binary | 经 `clawhub install redbook` / npm 安装 |
| Chrome 登录 cookie | 需在 Chrome 登录 xiaohongshu.com（或 Safari/Firefox + `--cookie-source`） |
| puppeteer-core + marked | 仅 `render` 卡片渲染需要（可选） |

## 与 skill-xhs-publisher 的分工边界

- **xhs-analyzer（本 SKILL）** = **分析**：搜索/数据/爆款规律/关键词矩阵/创作者画像/限流检测。
- **skill-xhs-publisher** = **发布 + 互动运营**：发图文/视频、日常评论/回复/点赞收藏、内容数据、通知抓取。
- 本 SKILL **只读**。不得调用 `comment`/`reply`/`like`/`collect`/`post` 等写命令；发布交给 `skill-xhs-publisher`，评论与回复交给 `skill-xhs-comment-reply`，由对应 Skill 执行确认和出站安全检查。

## Research discipline（先读这条）

XHS 风控节流的是**读取**，不只是写入。任何读超过几篇笔记的研究，都**必须**走 **[references/research-loop.md](references/research-loop.md)** 的研究循环 —— 默认 human-paced（~20 s/篇，一次一篇）。在紧循环里猛敲 `read`/`comments`/`analyze-viral` 会在几十次内触发验证码/IP 封（300012），账号降级数小时。⚡ Fast 模式仅应急，需打印警告 + 用户明确 opt-in。绝不并行或零延迟发读。

## Usage

```
redbook search "AI编程" --json       # 搜索笔记
redbook read <webUrl> --json         # 读笔记（用 search 返回的 webUrl，含 xsec_token）
redbook user <profileUrl> --json     # 创作者档案
redbook analyze-viral <webUrl> --json # 单篇爆款分析（0-100 分）
redbook account-report --file ids.txt --json  # 批量账号指标
redbook health --all --json          # 笔记限流检测
```

**始终加 `--json`** 供程序解析。全部命令、选项、JSON 结构见 **[references/commands.md](references/commands.md)**。

## 能力概览

分析能力拆成 13 个可组合模块（A–M）+ 组合工作流，详见 **[references/modules.md](references/modules.md)**：

| 模块 | 能力 |
|------|------|
| A 关键词参与度矩阵 · B 跨主题热力图 · C 参与度信号 | 需求版图 |
| D 创作者画像 · D2 已知账号报告 · E 内容形态分解 | 竞争/形态 |
| F 机会评分 · G 受众推断 · H 内容头脑风暴 | 策略产出 |
| I 评论洞察 · J 爆款结构拆解 · K 互动机会识别 | 只读分析 |
| L 卡片渲染（离线） · M 笔记限流检测 | 产出/健康 |

组合示例：快速主题扫描 `A→C→F`；完整细分分析 `A→B→C→D→E→F→G→H`；单篇深挖 `analyze-viral`。

## 关键领域知识（references/）

| 文件 | 内容 |
|------|------|
| [platform-signals.md](references/platform-signals.md) | 收藏/点赞、评论/点赞、分享/点赞比率基准；排序语义；图文 vs 视频 |
| [modules.md](references/modules.md) | 13 个分析模块 A–M + 组合工作流 |
| [commands.md](references/commands.md) | 所有 redbook 命令详解 + 选项 + JSON 结构 + 全局选项 |
| [research-loop.md](references/research-loop.md) | 读操作节流：三模式/严格规则/状态契约/tick/驱动器/熔断器/写侧阈值 |
| [technical-reference.md](references/technical-reference.md) | 大陆 vs 全球后端、xsec_token、中文数字、错误处理、API vs 浏览器限制、输出格式 |

## Requirements

- macOS（cookie 抽取用原生 keychain）· Node.js ≥ 22 · 已在 Chrome 登录 xiaohongshu.com
- 仅卡片渲染额外需 `puppeteer-core` + `marked`（用本机 Chrome，无需额外下载浏览器）
