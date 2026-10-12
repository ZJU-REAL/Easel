# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | data-report |
| **所属层** | produce |
| **来源类型** | 自研 |
| **原始来源** | Easel 自研 |
| **参考项目** | 无（技术上依赖 pandas + matplotlib 生成报告，均为标准开源库，无外部 SKILL 来源） |
| **许可** | 随 Easel 项目许可 |

## 脚本

| 脚本 | 说明 | 依赖 | 自研 |
|------|------|------|------|
| `scripts/report.py` | CSV/Excel/JSON → 数据概览 JSON（`analyze`）/ 整页可视化报告 HTML（`report`）。pandas 读数聚合 + matplotlib（Agg 后端、系统中文字体）自动选型出图（折线/柱状/饼）+ 内嵌 base64 拼自包含 HTML。含 `--selftest`。 | pandas、matplotlib、标准库（Excel 需 openpyxl，缺失时提示降级 CSV） | 是 |

## 变更记录

- 2026-07-23 **真封装**：新增 `scripts/report.py`（`analyze` + `report` 两个子命令 + `--selftest`），把"读数据 → 算 KPI → 出图 → 拼 HTML"从 LLM 心算/手拼改为确定性脚本。SKILL.md 升级到 v0.2.0，执行步骤改为 analyze → report → 补洞察 →（可选）render_card.py 渲染长图；与 chart-visualization / infographic 边界保留。selftest 已验证真出 HTML + KPI + 图表，中文字体 WenQuanYi Micro Hei 不乱码。

> 整理时间: 2026-07-23
> 用途: 来源溯源与致谢

## 致谢

图表渲染基于 matplotlib、数据处理基于 pandas（均为开源库），报告封装脚本
`scripts/report.py` 为 Easel 侧自研。
