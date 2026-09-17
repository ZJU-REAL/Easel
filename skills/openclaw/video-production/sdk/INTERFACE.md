# 接口契约（INTERFACE）

> v0.1 · 2026-09-16 · 对外平台（Easel 等）**只经本契约调用**；SDK 内部件（脚本/资产/规范）不出包。

## 输入

| 字段 | 必需 | 说明 |
|------|------|------|
| `source` | ✅ | 原片视频（口播/独白，16:9，任何常见编码；SDK 负责摸底/转码） |
| `transcript` | 可选 | 现成文字稿（无则由内置转录链生成，本地 large-v3） |
| `brief` | ✅ | 本片主题与风格基调说明（**风格由内容推出**，不接受"照上片做"） |
| `brand` | 可选 | 品牌包（字体/色彩/署名；默认取"世于我愿"包） |
| `out_dir` | ✅ | 产物目录 |

## 输出（一次运行产出全套）

| 产物 | 说明 |
|------|------|
| `final.mp4` | 成片（口播大片：A/B 双态 + 概念动画 + 素材对位 + 音效） |
| `design-table.md` | 设计表：每场概念演出清单、形式×变体分配、转场、对照表 |
| `asset-match.md` | 素材↔台词对位表（含每支素材的抽帧核验记录） |
| `gate-report.md` | 核验报告：八件门逐项结果 + 气质抽检记录 |
| `sources.json` | 素材/音效来源登记（许可与出处） |

## 调用形态

- **v0.1（当前）**：按 `pipeline/RUNBOOK.md` 驱动（每步命令 + 门；可由任何 agent 照做）
- **v0.2（计划）**：单入口 `python pipeline/run.py --source X --brief "..." --out Y`（全自动九步；门不过则中止并回报）

## 边界与约定

1. 平台侧适配层负责把平台任务转成本契约输入；不得绕过契约直取 SDK 内部件。
2. 门不过＝不交付：`gate-report.md` 有任一 FAIL，视为未完成。
3. 风格约定：参照物只作验收标尺；交付须附「本片 × 参照物」对照表（机制保留 vs 风格更换，写到构图/材质/运动语言级）。
4. 版权：素材/音效登记进 `sources.json`；生成通道（AI 生成音效等）禁用。

---

# v0.2 契约（机器接口，本版）

## 命令族（python pipeline/run.py …）

| 命令 | 用途 |
|------|------|
| `doctor` | 环境自检（硬依赖不过 = 退出 1） |
| `init --source S --out O [--brief B] [--transcript T] [--scenes C] [--config F] [--run-dir R]` | 建运行态 |
| `run [--through STAGE]` | 连跑机械段；遇问题/审批停 |
| `stage <name>` | 单步执行 |
| `resume [--approve design-table|preview] [--note "…"]` | 放行确认门并续跑 |
| `gates` | 门聚合（等价 gates/aggregate.py） |
| `ask --emit｜--serve [--port 8898]` | 出题（交宿主）/ 起本地卡面 |
| `status` | 进度 / 待作答 / 下一动作 |

## 退出码（宿主靠它决策）

`0` 完成 ｜ `2` 门失败（报告在 run-dir） ｜ `3` 待作答/待审批（questions/*.json） ｜ `1` 异常

## 运行态（run-dir）

`run-state.json` ｜ `questions/*.json` ｜ `answers/<id>.json` ｜ `checkpoints/*.json` ｜ `artifacts/` ｜ `logs/` ｜ `workdir/` ｜ `gates.json`

## 问答协议（宿主对接面）

- 出题：`questions/<id>.json`：`{id, type: multi-select|single-select|approval|free-text, title, description, options[{value,label,preview?}], allow_notes, gate}`
- 作答：`answers/<id>.json`：`{id, values:[…], notes, answered_by, answered_at}`
- 两份 JSON 即全部对接面：宿主（Easel 等）读 question → 渲染（映射到 ask_user 卡片或卡面）→ 写 answer → 调 `resume` 续跑；SDK 不为任何宿主改主线。

## 门分期

`gates.json` 每项可标 `phase: verify|render`（缺省 verify）：verify 在写码后、render 在成片后各跑一轮；报告按 id 合并。
