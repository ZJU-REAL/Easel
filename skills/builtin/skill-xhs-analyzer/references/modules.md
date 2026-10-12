# 分析模块 A–M 与组合工作流

每个模块是可组合的构建块。所有命令详解见 [commands.md](commands.md)，比率基准见 [platform-signals.md](platform-signals.md)，读操作节流规则见 [research-loop.md](research-loop.md)。

## Module A：关键词参与度矩阵
哪些关键词参与度天花板最高？哪些饱和/未被满足？
- 命令：`redbook search "keyword" --sort popular --json`（每个关键词一次）
- 提取 `items[].note_card.interact_info` 的 `liked_count`/`collected_count`/`comment_count` + `user.nickname`
- 解读：Top1 ceiling = `items[0]` 点赞（已验证需求）；Top10 avg = 前 10 均值。高 Top1 低 Top10 = 单个异常值主导，难竞争；高 Top10 avg = 需求稳定，易切入。
- 输出：关键词 × 参与度表，按 Top1 ceiling 排序。

## Module B：跨主题热力图
哪些 主题×场景 交叉有需求？内容缺口在哪？
- 命令：`redbook search "base topic + scene" --sort popular --json`（每个场景组合一次）
- 提取每个组合的 Top1 `liked_count`。高 Top1 = 已验证需求；零/极低 = 内容缺口（机会或无需求）。
- 输出：Base × Scene ASCII 热力图。

## Module C：参与度信号分析
每个关键词是什么内容类型？工具/认知/娱乐？
- 命令：用 A 的搜索结果，或单篇 `redbook analyze-viral "<url>" --json`（含预计算 `engagement.*Ratio`）
- 套用 platform-signals.md 的比率基准。输出：每关键词/每篇分类。

## Module D：创作者发现与画像
谁是这个细分的关键创作者？策略如何？
- 命令：从搜索结果收集 `items[].note_card.user.user_id`，对每人 `redbook user "<userId>"` + `redbook user-posts "<userId>"`
- 提取：`interactions[]` 中 `type==="fans"` 的粉丝数；`notes[].interact_info.liked_count` 算 avg/median/max；`display_title` 看内容模式。
- 解读：avg vs median 差距大 = 爆款拉高均值，median 是真实基线；max/median >5× = 有过爆款，重点研究那些笔记；帖频 >3/周=高产，<1/周=质量导向。

## Module D2：已知账号报告
已有 KOS/KOC 账号 ID 列表时用，勿用关键词搜索近似（会引入无关帖）。
- `redbook account-report --file accounts.txt --month YYYY-MM --json`（换行分隔 ID/profile URL，`#` 注释忽略；优先带 `xsec_token` 的 profile URL）
- 默认每账号只取首页；`complete:false` 表示还有更多页。仅在账号列表小且用户明确要全量时用 `--all`，否则 `--max-pages <n>`。

## Module E：内容形态分解
图文 vs 视频，哪个对该主题表现更好？
- `redbook search "keyword" --type image --sort popular --json` 与 `--type video`，对比两组 Top1/Top10 avg 的 `liked_count`/`collected_count`。

## Module F：机会评分
该做哪些关键词？最佳投入产出比在哪？
- 输入：Module A 矩阵。Demand = Top1 点赞天花板；Competition = Top10 中 >1K 点赞的密度；Score = Demand ×（1/竞争密度）。
- 分级（按 Top1 点赞）：S >10万 / A 2万–10万 / B 5千–2万 / C <5千。

## Module G：受众推断
- 输入：Module C 比率 + `analyze-viral` 的 `comments.themes[]`/`questionRate` + 内容模式。
- 规则：高收藏+高提问率→学习型；高评论+情感主题→社区型；高分享→身份认同型；评论语言→年龄/教育信号。

## Module H：内容头脑风暴
- 输入：F 机会分 + G 画像 + B 热力图缺口。每个 idea 指定：目标关键词 / hook 角度 / 内容类型（工具·认知·娱乐）/ 形态（图文·视频）/ 参与目标（按 Top10 avg）/ 竞品参考 URL。

## Module I：评论洞察
- 用 `redbook comments "<url>" --all --json` 识别高频问题、争议点、购买意图与未满足需求，只输出洞察和候选回复草稿。
- 如需真正评论或回复，将候选内容交给 `skill-xhs-comment-reply`；本 Skill 不执行任何互动写操作。

## Module J：爆款复刻
- `redbook search "keyword" --sort popular` 找 top → `redbook viral-template "<url1>" "<url2>" "<url3>" --json` 提取结构模板。
- 输出 `ContentTemplate`：`dominantHookPatterns` / `titleStructure` / `bodyStructure.lengthRange` / `engagementProfile.type` / `audienceSignals.commonThemes`。喂给 Module H 作结构约束。

## Module K：互动机会识别
组合 I + J 做只读分析：拉取评论 → 筛选高价值问题 → 生成候选回复 → 交给用户审阅。实际互动必须转交 `skill-xhs-comment-reply`。

## Module L：卡片渲染（离线，需 puppeteer-core）
- `redbook render content.md --style xiaohongshu`（带 YAML frontmatter 的 markdown → PNG 卡片）
- 尺寸 1080×1440（3:4），DPR 2；样式 purple/xiaohongshu/mint/sunset/ocean/elegant/dark；分页 auto（按标题/段落启发式）或 separator（按 `---`）。
- 输出 `cover.png` + `card_N.png`，作为候选素材交给 `skill-xhs-publisher`。需 `puppeteer-core` + `marked`，无需 cookie（纯离线，用本机 Chrome）。

## Module M：笔记限流检测（限流检测）
XHS 给每篇笔记隐藏的 `level` 字段控制推荐分发，UI 从不显示。
- `redbook health --all --json`

| Level | 状态 | 含义 |
|-------|------|------|
| 4 | 🟢 正常 | 完整推荐分发 |
| 2-3 | 🟡 基线 | 基本正常，轻微约束 |
| 1 | ⚪ 新 | 审核中（新帖） |
| -1 | 🔴 软限 | 轻度限流 |
| -5 ~ -101 | 🔴 中度 | 中度限流 |
| -102 | ⛔ 严重 | 不可逆，须删除重发 |

附加检查：敏感词（自动化/AI生成/批量等）+ 标签数 >5 告警。

---

## 组合工作流

| 工作流 | 模块链 |
|--------|--------|
| 快速主题扫描（~5 min） | A → C → F |
| 内容规划 | A → B → E → F → H |
| 创作者竞品分析 | A → D |
| 完整细分分析 | A → B → C → D → E → F → G → H |
| 单篇深挖 | `analyze-viral "<url>"`（一次返回 hook/比率/评论主题/基线对比/0-100 分） |
| 爆款研究→内容模板 | search → `viral-template` |
| 评论洞察 | I（只读分析 → 候选回复） |
| 内容复刻 | A → J → H → L |
| 创作素材准备 | A → J → H → L（发布转交 publisher） |
| 账号健康监控 | M（周期跑 `health --all`） |
| 全面分析 | A → C → I → J → K → M |
