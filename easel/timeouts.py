"""统一超时常量（秒）——CLI / Web / skill 三入口单一真相源。

此前三处各写各的（skill.py=900、web 非流式 chat=300、cli chat=7200），
同一个任务经不同入口会被不同超时掐断、行为不一致。收敛到这里，一处改全生效。

- 制作层 SKILL（生视频 / 多镜合成）由 OpenClaw 自己执行，可能跑很久 → 给足预算。
- 直接执行层（发现 / 策划 / 发布 / 归因）较快。
- chat 入口可能中途触发制作层任务 → 按制作层预算，别被 turn 超时掐断。
"""

TIMEOUT_HARNESS_CANCEL = 2      # 协议取消收尾预算，超时后仍清理本机进程树
TIMEOUT_MODEL_TOOL_PROBE = 60

# 热点采集预算；用户可在来源配置中覆盖单次采集预算。
TIMEOUT_TREND_COLLECT = 20
TIMEOUT_TREND_MAX = 120
TIMEOUT_TREND_UPSTREAM = 8
TIMEOUT_TREND_STARTUP = 2
TIMEOUT_TREND_SCRIPT_CHECK = 5
TIMEOUT_TREND_CPU = 30
TIMEOUT_TREND_CONFIG_LOCK = 1
TIMEOUT_TREND_BUSY_WAIT = 0.1
TIMEOUT_TREND_BUSY_RETRY = 1
TIMEOUT_TREND_FAILURE_RETRY = 30
TREND_POLL_INTERVAL = 0.02

TIMEOUT_PRODUCE = 7200   # 制作层：生视频 / 多镜合成给足时间
TIMEOUT_DIRECT = 300     # 轻量直接执行层
TIMEOUT_CHAT = TIMEOUT_PRODUCE   # chat 可能中途触发制作任务，按制作层预算
