# EASEL-META — skill-content-calendar-log

- **类型**：🔧 自研（Easel）
- **层**：attribute（归因）
- **引擎**：`skills/shared/scripts/calendar_ops.py`（读写 `outputs/_schedule.json`，与 Web `/api/schedule` 同一文件）
- **由来**：把"每次发布/排期/平台活动记到统一日历 + Agent 读回规划"从分散在发布页回流、publish-log、event-calendar 三处的割裂逻辑，收敛成一个时间线底座。
- **关键设计**：
  - 记录做在 publisher 脚本层（发布页/对话页唯一公共汇聚点），确定性覆盖两条发布路径；发布页由 web 设 `EASEL_CALENDAR_AUTORECORD=0` 防重复。
  - record-publish 一次写日历底座 + 转发 `skill-publish-log`，两库不漂移。
  - 与 `skill-content-calendar`（plan，生成计划）、`skill-event-calendar`（discover，查节点）、`skill-publish-log`（attribute，指标）分工互补，不重复存储。
- **参考**：无外部移植，纯自研编排。
