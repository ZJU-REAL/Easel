# video-pipeline-sdk · 视频产线 SDK

> 把「Remotion 口播视频」的制作从手工艺变成流水线：**九步流程 + 八件核验门 + 弹药仓 + 音画同步核验**。
>
> v0.2.1 · MIT · 2026-09

一个自包含、可移植的视频制作产线包：任何执行者（人 / AI agent / 不同模型）照它跑，输出质量有下限保证——质量不靠自觉，靠**可执行的门**：不过门 = 不交付。

已在真片全流程验证：110s / 25 场 / 3313 帧（Remotion 4.0.503）。

**English** — A self-contained production-pipeline SDK for talking-head videos built with Remotion: 9-step runbook, 7 executable quality gates (frames / transitions / de-dup / material↔script match / five-piece completeness / layout grid / audio loudness), ms-level A/V sync verification, and a curated effect & asset magazine. MIT.

## 特性

- **两道确认门**：设计表确认 → 才写码；Studio 预览确认 → 才渲全片
- **八件核验门（全可跑）**：帧检 / 转场可感知 / 查重 / 素材↔台词对位 / 五件套自检 / 排版网格 / **分场时间轴** / 音频响度 —— `gates/selftest.ps1` 一键自检
- **人审包（review-pack）**：交付自动生成每场定格帧 + 核对表（`tools/make_review_pack.py`）——**有视觉工具的执行者先自检，人眼终审兜底**
- **看图自检（see.py）**：`tools/see.py` 把关键帧/素材交给多模态端点核查（密度/字幕/素场）——把"无视觉执行者"升级为"能自检的执行者"（工序见 RUNBOOK Step 7）
- **音画同步核验**：互相关实测到 ms 级（`tools/check_sync.py`），交付前 |偏移| ≤ 15ms（实测可达 0.0ms）
- **弹药仓**：19 件效果件（含卡片系统 + 空间融合件）、字体、胶片 LUT、现成音效库、素材台账；**FX-15/16 用法与硬规则见 `references/fx-usage.md`**
- **坑位总表**：`PITFALLS.md` —— Windows / Remotion / ffmpeg / whisper 实战血账
- **防滑坡设计**：机制可复用、风格不复用——每片风格由内容现长；参照物只作验收标尺

## 结构

```
video-pipeline-sdk/
├── README.md / INTERFACE.md / PITFALLS.md / CHANGELOG.md / ATTRIBUTIONS.md
├── LICENSE
├── pipeline/RUNBOOK.md           九步流程（每步：命令 + 质量门）
├── gates/                        八件核验门 + selftest（全数可跑）
├── tools/                        同步核验 / 转录 / 转码 / 场景数据 / 抓取 / 运维
├── assets/                       弹药仓
│   ├── fx/                       19 件效果件（含卡片系统 + 空间融合件 FX-15/16）
│   ├── fonts/                    MaShanZheng（OFL 随包）；系统字体自备
│   ├── luts/                     胶片 LUT（受限，说明见内）
│   ├── sfx/                      现成音效（受限，脚本拉取）
│   └── stock-ledger.json         素材台账
├── references/                   规范与机制快照（产线规范 / 质量机制 / 排版基线）
└── deps/                         前置依赖（Remotion 精确锁 + bootstrap 自检/还原）
```

## 快速开始（Windows）

1. `powershell -ExecutionPolicy Bypass -File deps/bootstrap.ps1` —— 自检 Node/ffmpeg/Python 并还原依赖
2. 读 `INTERFACE.md`（输入/输出契约）与 `pipeline/RUNBOOK.md`（九步流程）
3. 每步产出后跑 `gates/` 对应门；一键自检：`powershell -ExecutionPolicy Bypass -File gates/selftest.ps1`

## 设计原则（为什么效果不会滑坡）

- 质量不靠执行者自觉：参照物只作验收标尺；八件门 + 对照表 + 新机制配额硬卡
- 机制可复用、风格不复用：每片风格由内容现长；一眼像参照物 = 返工
- 素材必须对应台词、入场前抽帧核验；真人不压暗；五件套齐才交付
- 音画同步以实测为准，不以预览观感为准

## 集成形态

- 对外只暴露 `INTERFACE.md` 契约（输入原片 + 稿 + 风格说明 → 输出成片 + 对位表 + 核验报告）
- 可作为独立产线接入上游工作流；SDK 内部件不出包

## 许可与致谢

- 本包代码：MIT（见 `LICENSE`）
- 第三方来源与「不入库资产」清单：见 `ATTRIBUTIONS.md`
- 字体 马善政（OFL，随包附许可）；Mixkit 音效/素材（Free License，素材文件不再分发）；其余见各 assets 子目录说明
