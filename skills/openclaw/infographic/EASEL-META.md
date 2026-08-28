# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | infographic |
| **所属层** | produce |
| **来源生态** | AntV（蚂蚁集团数据可视化）+ 自研 GIF 动画脚本 |
| **上游库** | @antv/infographic（AntV Infographic DSL 渲染引擎） |
| **参考仓库** | https://github.com/antvis |
| **功能描述** | 本地渲染信息图（AntV DSL 静态模式）与动画 GIF 图表（scripts/gif_chart.py，matplotlib+Pillow） |
| **自研脚本** | `scripts/gif_chart.py`（自研，matplotlib+Pillow+numpy）：bar-race / count-up / progress / line-grow 四类动画 GIF，`--selftest` 自检 |
| **SKILL.md 行数** | 见文件 |
| **自包含** | 是（含 references/ + scripts/） |
| **profile_aware** | false |
| **备注** | 2026-07-23 GIF 模式真封装：新增自研 `scripts/gif_chart.py`，把原先只在 md 里描述的 GIF 动画落地为确定性 Python 脚本（Agg 后端 + 中文字体自动注册 + 自适应调色板控体积），SKILL.md 模式 B 从"描述"改为"调脚本"。原浏览器 Canvas 版（core/ + templates/ + examples/）已移除 |

> 收录时间: 2026-07-23
> 用途: 内容 → 结构化信息图 / 动画 GIF 图表

## 致谢

静态模式基于 AntV 开源生态（antvis）的 `@antv/infographic` DSL 渲染引擎，特此致谢。动画 GIF 模式（`scripts/gif_chart.py`）为 Easel 侧自研，基于 matplotlib（Agg 逐帧渲染）+ Pillow（GIF 合成）+ numpy。旧版浏览器 Canvas 实现（`core/` + `templates/`）已移除。
