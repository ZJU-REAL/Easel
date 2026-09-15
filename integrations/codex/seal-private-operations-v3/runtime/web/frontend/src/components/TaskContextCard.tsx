export interface TaskContext {
  taskId: string;
  title: string;
  platform?: string;
  scenario?: string;
  accountId?: string | null;
  stage?: string;
  status?: string;
  goal?: string;
}

const STATUS: Record<string, string> = { draft: '草稿', ready: '待开始', active: '进行中', paused: '已暂停', blocked: '已阻塞', completed: '已完成', cancelled: '已终止' };
const SCENARIO: Record<string, string> = { w1: '持续运营', w2: '增长与变现', w3: '新号启动', W1: '持续运营', W2: '增长与变现', W3: '新号启动' };
const STAGE: Record<string, string> = { draft: '草稿', preparation: '任务准备', account_verification: '账号核验', creator_data: '创作中心数据', research: '公开市场研究', diagnosis: '账号诊断', strategy: '运营策略', topics: '选题计划', production: '内容生产', preflight: '发布准备', publish: '发布', review: '复盘' };

export default function TaskContextCard({ task, onExit }: { task: TaskContext; onExit?: () => void }) {
  return <section className="task-context-card" style={{ flex: '0 0 auto', height: 'auto', minHeight: 0 }} aria-label="当前运营任务">
    <div className="task-context-main">
      <div className="task-context-kicker"><span className="task-context-dot" />当前工作对象</div>
      <h2>任务「{task.title || '未命名任务'}」</h2>
      <div className="task-context-meta">
        {task.platform && <span>{task.platform}</span>}
        {task.scenario && <span>{SCENARIO[task.scenario] || task.scenario}</span>}
        {task.accountId && <span>账号：{task.accountId}</span>}
        {task.stage && <span>阶段：{STAGE[task.stage] || task.stage}</span>}
      </div>
      {task.goal && <p className="task-context-goal">目标：{task.goal}</p>}
    </div>
    <div className="task-context-side">
      {task.status && <span className={`task-status task-status-${task.status}`}>{STATUS[task.status] || '未知状态'}</span>}
      <span className="task-context-id">任务编号 · {task.taskId.slice(0, 12)}</span>
      <div className="task-context-actions">{onExit && <button className="btn btn-sm btn-ghost" onClick={onExit}>退出任务</button>}</div>
    </div>
  </section>;
}
