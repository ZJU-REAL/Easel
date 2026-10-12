# 持久化任务账本（第一阶段）

`easel.run_store.RunStore` 保存每轮 Agent 任务的身份、执行状态和产物引用，
为 [#106](https://github.com/ZJU-REAL/Easel/issues/106) 的状态恢复提供基础。
当前是可单独测试的存储层；聊天入口尚未接入，现有 JSON 快照与 JSONL 回放保持原样。
创建账本或重新打开数据库不会启动 Agent，也不会自动恢复或重复执行工具。

## 记录与状态

- `turn_id` 唯一标识一轮任务；与 `session_id` 按原始字符串存储，不做文件名替换。
- `backend` 为 `openclaw` 或 `direct_api`。
- `version` 从 1 开始，每次成功状态迁移加 1；调用者必须提供预期版本。
- `owner_id` 是执行者的关联标识；进入 `running` 时必填，结束时必须匹配。
  它不是认证凭证，也不能阻止外部工具执行。
- 时间用带 UTC 时区的 ISO 8601 字符串记录。并发判断使用版本号，不依赖机器时钟。
- `result_refs` 保存相对 `outputs/` 的路径引用；存储层不打开文件，也不保证产物已经存在。
  调用者读取文件时仍需使用项目已有的路径和权限校验。
- 不保存提示词、模型配置、令牌或工具响应正文；没有任意附加元数据字段。

| 当前状态 | 允许的新状态 | 含义 |
| --- | --- | --- |
| `queued` | `running` | 获得会话执行权后开始任务 |
| `queued` | `failed`、`cancelled` | 尚未开始执行就失败或取消，无执行者 |
| `running` | `succeeded`、`failed`、`cancelled` | 执行者明确报告本轮结果 |
| `running` | `interrupted` | 有证据确认执行已中断 |
| `running` | `unknown` | 无法确认执行或外部动作的结果 |

所有结束状态在本阶段均不可再次迁移。`unknown` 保留空的 `finished_at`，
避免把“结果未知”表示成“已确认结束”。重开数据库不会把 `running` 改成中断：
任务可能仍由另一个 Web 进程或网关执行。

## 调用示例

```python
from pathlib import Path
from easel.run_store import RunStore

# 实际接入时由调用者传入所用会话目录下的专用数据库路径。
store = RunStore(Path("outputs/sessions/runs.sqlite3"))
queued = store.create("turn-001", "session-001", "openclaw")

# 此前必须已持有运行时的会话锁；账本不能代替现有跨进程锁。
running = store.transition(
    queued.turn_id, expected_version=queued.version,
    state="running", owner_id="executor-instance-001",
)

# 只有确认执行完成后，才提交 succeeded；流结束本身不证明工具成功。
done = store.transition(
    running.turn_id, expected_version=running.version,
    state="succeeded", owner_id=running.owner_id,
    result_refs=["project/report.md"],
)
assert RunStore(store.path).get(done.turn_id) == done
```

`RunConflict` 表示重复任务标识、版本过期、执行者不匹配或会话已有运行记录。
调用方应重新读取状态并核验所有权，不能不经检查就重试工具调用。
数据库为同一会话最多允许一条 `running` 记录；这只是元数据约束，
对 `unknown` 或跨进程仍在执行的任务，仍需运行时对账后才能决定是否启动新任务。

## 持久化边界

使用 Python 标准库 SQLite，无新依赖。每次写入在短事务中完成，
版本检查、所有权检查和状态更新位于同一事务；使用默认回滚日志及 `synchronous=FULL`。
每次操作独立建立并关闭连接，不跨线程或进程共享连接。
写锁等待上限位于 `easel/timeouts.py` 的 `TIMEOUT_RUN_STORE`。
调用是同步的，异步 Web 入口接入时应在线程中调用，避免锁等待阻塞事件循环。

数据库应放在本机持久化文件系统，使用专用文件。网络文件系统、多个独立主机共享文件、
不保证同步写语义的存储设备不在本阶段验证范围内。
数据库损坏、磁盘写入失败和锁等待超时均向调用者报告；不会静默删除、重建或退回内存保存。
SQLite `user_version` 管理数据库结构版本，和每条记录的 `version` 分开；
未知结构版本及已有结构的无版本数据库会被拒绝，避免覆盖不兼容数据。

测试使用真实子进程验证同任务/同会话竞争；在事务提交前与提交后强制结束写入进程，
检查重开后的记录版本和数据库完整性，并注入提交失败及数据库锁超时。
外部动作标记已写入、但本地事务尚未提交的场景会保留旧的 `running` 记录。
这明确展示了后续对账的必要性，不能据此承诺外部动作恰好执行一次。

## 后续接入

下一份 PR 将接入聊天任务生命周期及状态查询，同时保留旧快照/回放的兼容读取。
再单独实现重启对账：检查跨进程所有权和运行时证据，无法确认时展示结果未知。
步骤级续跑还需要选定工作流、保存步骤产物并具备工具结果查询或幂等能力；
该能力不由本存储层自动提供。
