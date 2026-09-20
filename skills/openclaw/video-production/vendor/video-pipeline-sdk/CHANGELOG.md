# Changelog

## v0.3.5 — 2026-09-17（抠像链 Unicode 修复）

- **修 `tools/rvm_matte.py` 写帧静默失败**：`cv2.imwrite` 在 Windows 遇非 ASCII 路径（如中文 run 目录）不报错、返回 False、零产出——改用 `cv2.imencode().tofile()`（失败即抛）。实录：模型输出「DONE 2043 frames」但目录为空即此坑
- **修 `references/fx-usage.md` 命令参数**：make_masks 用法 `--in` → `--src`（与 argparse 一致）
- PITFALLS §5 收录（cv2 Windows 非 ASCII 路径静默失败）

## v0.3.4 — 2026-09-17（焊进必经路径 · 二轮实录反哺）

**来源：《试车台》二轮真机实录暴露的问题，全部补上：**

- **空间融合焊进工序**（治「fx-usage 只躺资料区、整轮无人读」）：RUNBOOK Step 5 必读引用 + 设计表必含《空间融合裁决》节；Step 6 拷件/抠像链步骤；Step 7 两条抽帧自查；design-baseline 增「空间融合」节；fx-usage 标注读位与前置
- **无人应答 ≠ 通过**：RUNBOOK Step 8 / 技能层明确——确认卡过期=停下报告，严禁 best-judgment 渲全片；卡传长超时
- **字体渲染坑**（打包渲染 `delayRender('fx-fonts')` 超时）：标准做法改 `@font-face` CSS 注入；PITFALLS §2 收录
- **宿主媒体语法清洗**：清掉快照文档里 `MEDIA:` / 本机盘符残留；预览与交付一律走宿主媒体语法（Easel `/api/media/`）
- PITFALLS §6 增补：规则不进工序单=没人读；卡无人应答越权；贴图语法

## v0.3.3 — 2026-09-17（可移植性）

- 去本机化：`gates/` `tools/` 的默认路径不再指向作者机器——`--project` / `--root` / `--clipsdir` 默认读 `REMOTION_PROJECT` 环境变量（未设=当前目录）；抽帧字体回退 `C:/Windows/Fonts/simhei.ttf`（可用 `CJK_FONT` 覆盖）；模型目录默认 `~/models/...`；临时产物走系统临时目录
- 文档同步（RUNBOOK / DEPS / references）
- `VERSION` 字段修正（0.3.2 文档版未同步该字段，本版起 = 0.3.3）
- 本版起作为内置快照随 Easel `video-production` 技能分发；来源仓：mengyuyuan/video-pipeline-sdk

## v0.3.2 — 2026-09-17（文档 · 工序）

- RUNBOOK Step 7 新增「视觉自检」工序：执行者具备看图工具时，渲关键帧先自检（密度 / 字幕 / 素场）再往下；无工具维持人审包兜底
- README 措辞同步：人审包定位改为「先自检、人眼终审」
- 新 `tools/see.py`：看图工具参考实现（纯标准库；图片 → 多模态端点 → 文字结论；`describe / check / selftest`）

## v0.3.1 — 2026-09-17

**来源：真机全自主跑通实录（执行者从零做出一支 34s 成片）暴露的三处空洞，全部补齐：**

- 新 `gates/check_timeline.py`（门⑧ 分场时间轴）：重叠 / 长间隙 / 过短场——实录中 scenes 时间轴重叠 2s+ 造成 A/B 舞台打架闪切、其余门全过也抓不住；本门实测抓出该片 4 处问题
- 新 `tools/make_review_pack.py` + deliver 阶段自动生成：每场定格帧 + 核对表（人审包）——执行者无视觉时的人眼兜底，残影/闪切/穿帮逐场晒出
- 新 `references/fx-usage.md`：FX-15/FX-16 照抄级用法 + **语义强制规则**（立体/穿越语义禁用平面降级）——实录中执行者把 FX 件复制进工程又当"未使用"删掉
- PITFALLS 增补：「执行者行为坑」一批（输出截断中断任务 → 大文件分块写；弹药件导入未用 = 降级信号）
- README / quality-mechanisms / RUNBOOK / INTERFACE / selftest 同步（七件门 → 八件门）

## v0.3.0（开发中）· 独立接口本体 P2

- 新 `pipeline/run.py`：单入口 stage 机（十段：ingest→transcribe→scenes→design-table→scaffold→build→verify→preview→render→deliver）＋两道确认门（checkpoint-1 设计表 / checkpoint-2 预览）＋退出码（0 完成 / 2 门失败 / 3 待作答 / 1 异常）＋断点续跑（run-state.json）
- 新 `pipeline/ask.py` + `assets/cards/index.html`：问题协议（多选/单选/审批/自由文本 + 预览图）＋本地卡面服务（默认 8898，占用自动 +1，避开端口矩阵）＋ `--emit` 交宿主渲染
- 新 `pipeline/doctor.py`：环境自检（硬依赖 / 软依赖分级）
- 新 `gates/aggregate.py`：七件门聚合，verify / render 双相 + 报告按 id 合并 → gate-report.md/json
- 卡面/协议边界：宿主只经 questions.json / answers/<id>.json 对接（协议是脊柱，界面只是渲染器）
- 冒烟验证：全流程 3→3→3→0（两次停门、两次放行、完成交付五件套 + manifest）；卡面 e2e 通过

## v0.2.1 — 2026-09-16（深夜）

- 弹药仓 +2：`assets/fx/FxPanel3D.tsx`（FX-15 真透视 3D 卡 · 融入现实斜面板）/ `assets/fx/FxBehindMask.tsx`（FX-16 人物蒙版分层 · 背后物件与文字穿人的底座件）——均为真片生产验证件
- 工具 +2：`tools/rvm_matte.py`（RVM 抠像出 RGBA 序列）/ `tools/make_masks.py`（逐帧 PNG 蒙版 · 收紧配方），补齐"空间融合"资产链
- PITFALLS 增补：同文件重复导出同名符号 → 整个 Studio 白屏；无头截屏采样漂移 → 元素核验改用精确单帧
- quality-mechanisms：成组入场节奏（逐项 stagger ≤4 帧/项，整组台词窗口前 1/3 就位）
- 二次生产验证：34s / 4K60 HEVC 源口播全流程一次通过（摸底→转录→设计表→写码→蒙版→音效→预览）

## v0.2.0 — 2026-09-16

- 真片全流程实跑收官（110s / 25 场 / 3313 帧 / Remotion 4.0.503）并把全部经验回灌产线
- 新增 `PITFALLS.md`：音画同步三级偏移、渲染基建（bundle 复用 / 静帧假 OK）、OffthreadVideo 关键帧、字幕子词修正、工程坑总表
- 新增工具：`check_sync.py`（互相关同步核验，实测 0.0ms）、`transcribe.py`、`transcode_material.py`、`build_scenes_data.py`、`clean_remotion_temp.ps1`
- RUNBOOK Step 8/9 升级：预览近似同步注意 + 渲染基建（bundle 复用）+ 音频处理链裁齐 + 同步交付门
- 开源准备：MIT License；ATTRIBUTIONS 复核（受限资产不入库）；scratch 脚本清理

## v0.1.0 — 2026-09-16

- 骨架：九步 RUNBOOK、七件核验门（含自检）、弹药仓（fx 17 件 / 字体 / LUT / 音效 / 素材台账）、Remotion 依赖蓝本、INTERFACE 契约
