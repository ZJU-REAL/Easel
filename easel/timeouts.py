"""统一超时常量（秒）——CLI / Web / skill 三入口单一真相源。

此前三处各写各的（skill.py=900、web 非流式 chat=300、cli chat=7200），
同一个任务经不同入口会被不同超时掐断、行为不一致。收敛到这里，一处改全生效。

- 制作层 SKILL（生视频 / 多镜合成）由 OpenClaw 自己执行，可能跑很久 → 给足预算。
- 直接执行层（发现 / 策划 / 发布 / 归因）较快。
- chat 入口可能中途触发制作层任务 → 按制作层预算，别被 turn 超时掐断。
"""

TIMEOUT_PRODUCE = 7200   # 制作层：生视频 / 多镜合成给足时间
TIMEOUT_DIRECT = 300     # 轻量直接执行层
TIMEOUT_CHAT = TIMEOUT_PRODUCE   # chat 可能中途触发制作任务，按制作层预算
