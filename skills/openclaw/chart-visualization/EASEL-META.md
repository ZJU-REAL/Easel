# Easel SKILL 元数据

| 字段 | 值 |
|------|-----|
| **SKILL 名称** | chart-visualization |
| **所属层** | produce |
| **来源生态** | AntV（蚂蚁集团数据可视化） |
| **上游 API** | https://antv-studio.alipay.com/api/gpt-vis（gpt-vis 服务） |
| **参考仓库** | https://github.com/antvis/GPT-Vis |
| **功能描述** | 调 AntV 远程 API 生成静态图表图片 URL，覆盖 25+ 图表类型 |
| **SKILL.md 行数** | 112 |
| **自包含** | 是（仅依赖 curl 调用远程 API，无本地资源） |
| **profile_aware** | false |
| **备注** | 2026-07-23 Wave4 去冗余：新增「与其他图表 SKILL 的区别」小节，划清与 infographic（本地信息图/GIF）、data-report（整页报告）的机制边界 |

> 收录时间: 2026-07-23
> 用途: 数据 → 单张静态图表图片

## 致谢

图表能力基于 AntV 开源生态（antvis）与其 GPT-Vis / gpt-vis API 服务，特此致谢。本 SKILL 仅封装调用约定与图表选择指南，未复制上游代码。
