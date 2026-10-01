import { useState, useEffect } from 'react';
import {
  fetchTrends, fetchSchedule, fetchOutputs, fetchAccounts, fetchIdeas,
  fetchAnalyticsPlatforms, fetchAccountAnalytics,
  fetchOpsTasks, createOpsTask,
  runOpsTaskAction,
  deleteOpsTask,
} from '../lib/api';
import type {
  TrendGroup, ScheduleItem, OutputNode, AccountItem, Idea,
  AnalyticsPlatform, AccountAnalytics, AccountWhoami, OpsTask,
} from '../lib/api';
import type { Page } from './Sidebar';
import { getWhoamiCache, verifyStale } from '../lib/whoami';
import {
  IconFire, IconCalendar, IconOutputs, IconChat, IconSkills, IconAccounts,
  IconIdea, IconPublish,
} from './icons';

/** 大数格式化：12000 → 1.2万。 */
function fmtNum(n: number | null): string {
  if (n == null) return '—';
  const a = Math.abs(n);
  if (a >= 10000) return (n / 10000).toFixed(a >= 100000 ? 0 : 1) + '万';
  return String(n);
}
/** 增长量渲染信息：正=绿↑，负=红↓，0/缺失=不显示。 */
function growthInfo(n: number | null): { text: string; color: string } | null {
  if (n == null || n === 0) return null;
  return n > 0
    ? { text: `▲+${fmtNum(n)}`, color: 'var(--trend-up)' }
    : { text: `▼${fmtNum(Math.abs(n))}`, color: 'var(--trend-down)' };
}

interface DashboardProps {
  persona: string;
  runtimeStatus: string;
  onNavigate: (page: Page, taskId?: string) => void;
  onUseTopic: (title: string) => void;
  onTaskCreated?: (task: OpsTask) => void;
  onTaskDeleted?: (task: OpsTask) => void;
  onTaskExit?: (task: OpsTask) => void;
  activeTaskId?: string | null;
}

const STATUS_LABEL: Record<string, string> = { idea: '选题', draft: '草稿', ready: '待开始', active: '进行中', paused: '已暂停', blocked: '已阻塞', completed: '已完成', cancelled: '已终止', scheduled: '待发', published: '已发' };
const SCENARIO_LABEL: Record<string, string> = { w1: '持续运营', w2: '增长与变现', w3: '新号启动', W1: '持续运营', W2: '增长与变现', W3: '新号启动' };

export default function DashboardPage({ persona, runtimeStatus, onNavigate, onUseTopic, onTaskCreated, onTaskDeleted, onTaskExit, activeTaskId }: DashboardProps) {
  const [trends, setTrends] = useState<TrendGroup[]>([]);
  const [schedule, setSchedule] = useState<ScheduleItem[]>([]);
  const [outputs, setOutputs] = useState<OutputNode[]>([]);
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  // 归因层：账号创作数据
  const [anaPlats, setAnaPlats] = useState<AnalyticsPlatform[]>([]);
  const [anaSel, setAnaSel] = useState('');
  const [anaData, setAnaData] = useState<Record<string, AccountAnalytics | 'loading' | 'error'>>(() => {
    try { return JSON.parse(localStorage.getItem('easel_analytics') || '{}'); } catch { return {}; }
  });
  const [anaWin, setAnaWin] = useState<'last' | 'day' | 'week' | 'month' | 'year'>('week');
  // whoami 自愈：登录态以真实 profile 为准（与账号页共享 localStorage 缓存）
  const [whoamiMap, setWhoamiMap] = useState<Record<string, AccountWhoami>>(() => getWhoamiCache());
  const [opsTasks, setOpsTasks] = useState<OpsTask[]>([]);
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskPlatform, setTaskPlatform] = useState('xiaohongshu');
  const [taskScenario, setTaskScenario] = useState('W1');
  const [taskAccount, setTaskAccount] = useState('');
  const [taskGoal, setTaskGoal] = useState('');
  const [taskBusy, setTaskBusy] = useState(false);
  const [taskError, setTaskError] = useState('');

  useEffect(() => {
    fetchTrends('weibo,douyin', 6).then((d) => setTrends(d.trends)).catch(() => {});
    fetchSchedule().then(setSchedule).catch(() => {});
    fetchOutputs().then(setOutputs).catch(() => {});
    fetchAccounts().then(setAccounts).catch(() => {});
    fetchIdeas().then(setIdeas).catch(() => {});
    fetchOpsTasks().then(setOpsTasks).catch(() => {});
    fetchAnalyticsPlatforms().then((ps) => {
      setAnaPlats(ps);
      const cache = getWhoamiCache();
      const isLog = (p: AnalyticsPlatform) => p.loggedIn || !!cache[p.platform]?.loggedIn;
      const first = ps.find(isLog);
      if (first) setAnaSel((s) => s || first.platform);
      // 开页后台自愈：对非 B 站的归因平台真校验（whoami），刷新登录态；B 站走 cookie 判定不必。
      verifyStale(ps.filter((p) => p.platform !== 'bilibili').map((p) => p.platform), {
        onUpdate: (platform, r) => {
          setWhoamiMap((m) => ({ ...m, [platform]: r }));
          if (r.loggedIn) setAnaSel((s) => s || platform);
        },
      });
    }).catch(() => {});
  }, []);

  const submitTask = async () => {
    setTaskError('');
    if (!taskTitle.trim()) { setTaskError('请填写任务名称'); return; }
    if (taskScenario !== 'W3' && !taskAccount) { setTaskError('W1/W2 需要先选择已登录账号；也可以切换为 W3 新号启动'); return; }
    setTaskBusy(true);
    try {
      const conversation_id = `ops_${(globalThis.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_.:-]/g, '')}`;
      const created = await createOpsTask({ title: taskTitle.trim(), platform: taskPlatform, scenario: taskScenario, account_id: taskAccount || undefined, goal: taskGoal.trim(), conversation_id });
      setOpsTasks((items) => [created, ...items]);
      onTaskCreated?.(created);
      setShowTaskForm(false); setTaskTitle(''); setTaskGoal('');
    } catch (e) { setTaskError(e instanceof Error ? e.message : '创建运营任务失败'); }
    finally { setTaskBusy(false); }
  };

  const openTaskSurface = async (task: OpsTask, page: Page, action: string) => {
    // 先写入上下文，保证即使能力请求较慢/失败，用户仍能进入目标页面继续工作。
    onNavigate(page, task.task_id);
    try { await runOpsTaskAction(task.task_id, action); } catch { /* 目标页面仍可离线查看并重试 */ }
  };
  const removeTask = async (task: OpsTask) => {
    if (!window.confirm(`确认删除运营任务“${task.title}”？任务对话会删除，关联选题、日历和内容项目会保留并转为全局归属。`)) return;
    try { await deleteOpsTask(task.task_id); setOpsTasks((items) => items.filter((x) => x.task_id !== task.task_id)); onTaskDeleted?.(task); }
    catch (e) { setTaskError(e instanceof Error ? e.message : '删除任务失败'); }
  };

  const runAna = (platform: string) => {
    setAnaSel(platform);
    setAnaData((d) => ({ ...d, [platform]: 'loading' }));
    fetchAccountAnalytics(platform)
      .then((r) => setAnaData((d) => {
        const next = { ...d, [platform]: r };
        try { localStorage.setItem('easel_analytics', JSON.stringify(next)); } catch { /* quota */ }
        return next;
      }))
      .catch(() => setAnaData((d) => ({ ...d, [platform]: 'error' as const })));
  };

  const hour = new Date().getHours();
  const greet = hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
  const todayStr = new Date().toISOString().slice(0, 10);
  const upcoming = [...schedule]
    .filter((s) => s.date >= todayStr && s.status !== 'published')
    .sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time)).slice(0, 5);
  const recent = outputs.slice(0, 5);
  const pendingIdeas = ideas.filter((i) => i.status === 'pending');
  const loggedIn = accounts.filter((a) => a.loggedIn).length;

  const quick: { label: string; page: Page; Icon: typeof IconChat }[] = [
    { label: '开始对话', page: 'chat', Icon: IconChat },
    { label: '看热点', page: 'trends', Icon: IconFire },
    { label: '拆爆款', page: 'breakdown', Icon: IconSkills },
    { label: '记选题', page: 'ideas', Icon: IconIdea },
    { label: '排日历', page: 'calendar', Icon: IconCalendar },
    { label: '去发布', page: 'publish', Icon: IconPublish },
  ];

  const stats: { label: string; value: string; page: Page; Icon: typeof IconChat }[] = [
    { label: '待做选题', value: String(pendingIdeas.length), page: 'ideas', Icon: IconIdea },
    { label: '待发排期', value: String(upcoming.length), page: 'calendar', Icon: IconCalendar },
    { label: '内容项目', value: String(outputs.length), page: 'outputs', Icon: IconOutputs },
    { label: '已登录账号', value: `${loggedIn}/${accounts.length}`, page: 'accounts', Icon: IconAccounts },
  ];

  return (
    <div className="page-scroll dash-page">
      <div className="dash-hero">
        <h1 className="page-title" style={{ fontSize: 26 }}>{greet} 👋</h1>
        <p className="page-subtitle">
          {runtimeStatus === 'connected' ? 'Codex CLI 已就绪。' : 'Codex CLI 不可用。'}
          {persona ? ` 当前画像「${persona}」。` : ' 通用模式——指定画像效果更好。'}
          从热点到发布，一站式搞定今天的内容。
        </p>
        <div className="dash-quick">
          <button className="dash-quick-btn dash-task-btn" onClick={() => { setTaskError(''); setShowTaskForm(true); }}>
            <span className="dash-task-plus">＋</span><span>创建运营任务</span>
          </button>
          {quick.map((q) => (
            <button key={q.page} className="dash-quick-btn" onClick={() => onNavigate(q.page)}>
              <q.Icon size={16} /><span>{q.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 运营任务：工作流入口与当前阶段概览 */}
      <div className="card dash-card dash-ops-card">
        <div className="dash-card-head">
          <span><IconChat size={16} /> 运营任务</span>
          <button className="btn btn-primary btn-sm" onClick={() => { setTaskError(''); setShowTaskForm(true); }}>＋ 新建任务</button>
        </div>
        {opsTasks.length === 0 ? <div className="dash-empty">还没有运营任务。创建一个任务，让 Seal 按阶段协助完成账号运营。</div> : (
          <div className="ops-task-list">
            {opsTasks.slice(0, 6).map((task) => {
              const stage = task.stages?.[task.current_stage_index];
              return <div className="ops-task-row" key={task.task_id}>
                <div className="ops-task-main"><strong>{task.title}</strong><span className="ops-task-meta">{task.platform} · {SCENARIO_LABEL[task.scenario] || task.scenario} · {STATUS_LABEL[task.status] || '未知状态'} · {task.account_id || '未绑定账号'}</span><span className="ops-task-meta">目标：{task.goal || '未填写'} · 会话：{task.conversation_id || '未绑定'}</span></div>
                <div className="ops-task-stage"><span className={`ops-stage-dot ${stage?.status || 'pending'}`} />{stage?.name || '已完成'}
                  <button className="btn btn-ghost btn-sm" onClick={() => openTaskSurface(task,'chat','chat_context')}>进入任务</button>
                  {onTaskExit && activeTaskId === task.task_id && <button className="btn btn-ghost btn-sm" onClick={() => onTaskExit(task)}>退出任务</button>}
                  <button className="btn btn-ghost btn-sm" onClick={() => openTaskSurface(task,'ideas','ideas')}>选题</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => openTaskSurface(task,'calendar','calendar')}>日历</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => openTaskSurface(task,'outputs','content_library')}>内容库</button>
                  <button className="btn btn-ghost btn-sm" onClick={() => removeTask(task)}>删除</button>
                </div>
              </div>;
            })}
          </div>
        )}
      </div>

      {/* 概览数字 */}
      <div className="dash-stats">
        {stats.map((s) => (
          <button key={s.label} className="card card-hover dash-stat" onClick={() => onNavigate(s.page)}>
            <span className="dash-stat-ic"><s.Icon size={18} /></span>
            <span className="dash-stat-val">{s.value}</span>
            <span className="dash-stat-label">{s.label}</span>
          </button>
        ))}
      </div>

      <div className="dash-grid">
        {/* 今日热点 */}
        <div className="card dash-card">
          <div className="dash-card-head">
            <span><IconFire size={16} /> 今日热点</span>
            <button className="dash-more" onClick={() => onNavigate('trends')}>热点雷达 →</button>
          </div>
          {trends.length === 0 && <div className="dash-empty">暂无热点数据，可稍后在热点雷达重试</div>}
          {trends.map((g) => (
            <div key={g.platform} className="dash-trend-group">
              <div className="dash-trend-plat">{g.label}</div>
              {g.items.slice(0, 3).map((it, i) => (
                <div key={i} className="dash-trend-item" title={`${it.title}（点击做成内容）`}>
                  <span className="dash-trend-title" onClick={() => onUseTopic(it.title)}>{it.title}</span>
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* 选题库 */}
        <div className="card dash-card">
          <div className="dash-card-head">
            <span><IconIdea size={16} /> 选题库 · 待做</span>
            <button className="dash-more" onClick={() => onNavigate('ideas')}>全部 →</button>
          </div>
          {pendingIdeas.length === 0 && <div className="dash-empty">还没攒选题，去热点雷达收藏几个吧</div>}
          {pendingIdeas.slice(0, 5).map((it) => (
            <div key={it.id} className="dash-idea" onClick={() => onUseTopic(it.title)} title="点击做成内容">
              <span className="dash-idea-title">{it.title}</span>
              {it.source && <span className="badge">{it.source}</span>}
            </div>
          ))}
        </div>

        {/* 近期排期 */}
        <div className="card dash-card">
          <div className="dash-card-head">
            <span><IconCalendar size={16} /> 近期排期</span>
            <button className="dash-more" onClick={() => onNavigate('calendar')}>日历 →</button>
          </div>
          {upcoming.length === 0 && <div className="dash-empty">暂无排期，去日历安排一条吧</div>}
          {upcoming.map((s) => (
            <div key={s.id} className="dash-sched" onClick={() => onNavigate('calendar')}>
              <span className="dash-sched-date">{s.date.slice(5)}</span>
              <span className="dash-sched-title">{s.platform ? `[${s.platform}] ` : ''}{s.title}</span>
              <span className="badge">{STATUS_LABEL[s.status] || s.status}</span>
            </div>
          ))}
        </div>

        {/* 最近产物 */}
        <div className="card dash-card dash-card-top">
          <div className="dash-card-head">
            <span><IconOutputs size={16} /> 最近产物</span>
            <button className="dash-more" onClick={() => onNavigate('outputs')}>内容库 →</button>
          </div>
          {recent.length === 0 && <div className="dash-empty">还没有产物，去对话生成第一条吧</div>}
          {recent.map((g) => (
            <div key={g.name} className="dash-output" onClick={() => onNavigate('outputs')}>
              <span className="dash-output-name">{g.meta?.title || g.name}</span>
              <span className="badge">{g.meta?.platform || (g.type === 'dir' ? `${g.fileCount ?? 0} 文件` : '单文件')}</span>
            </div>
          ))}
        </div>

        {/* 创作数据（归因层）：选平台自动拉取登录账号的粉丝/获赞/关注 + 多窗口增长 + 近7日环比 + 最新笔记 */}
        <div className="card dash-card dash-card-wide">
          <div className="dash-card-head">
            <span><IconAccounts size={16} /> 创作数据</span>
            {anaSel && anaData[anaSel] && anaData[anaSel] !== 'loading' && (
              <button className="dash-more" onClick={() => runAna(anaSel)}>刷新 →</button>
            )}
          </div>
          {(() => {
            const logged = anaPlats.filter((p) => p.loggedIn || whoamiMap[p.platform]?.loggedIn);
            if (anaPlats.length === 0) return <div className="dash-empty">账号数据暂未加载，请检查连接后重试</div>;
            if (logged.length === 0) {
              return (
                <div className="dash-empty" onClick={() => onNavigate('accounts')} style={{ cursor: 'pointer' }}>
                  去账号页登录后，这里看各平台粉丝 / 获赞 / 关注、增长趋势与最新笔记 →
                </div>
              );
            }
            const d = anaSel ? anaData[anaSel] : undefined;
            const WIN: [typeof anaWin, string][] = [
              ['last', '较上次'], ['day', '较昨日'], ['week', '较上周'], ['month', '较上月'], ['year', '较去年'],
            ];
            return (
              <>
                <div className="ana-plats">
                  {logged.map((p) => (
                    <button key={p.platform} className={`chip ${anaSel === p.platform ? 'active' : ''}`}
                      onClick={() => runAna(p.platform)}>{p.name}</button>
                  ))}
                </div>
                {!d && <div className="dash-empty">点上方平台查看该账号数据</div>}
                {d === 'loading' && (
                  <div className="loading" style={{ padding: '28px 0' }}><div className="spinner" />抓取中…（起浏览器，约数秒）</div>
                )}
                {d === 'error' && (
                  <div className="dash-empty" style={{ color: 'var(--red)' }}>抓取失败（未登录 / 需真机校准），点平台重试</div>
                )}
                {d && d !== 'loading' && d !== 'error' && (!d.loggedIn ? (
                  <div className="dash-empty" onClick={() => onNavigate('accounts')} style={{ cursor: 'pointer' }}>
                    该平台登录态已失效，去账号页重登 →
                  </div>
                ) : (
                  <div className="ana-body">
                    {/* 概览 + 增长对比 */}
                    <div className="ana-col ana-col-main">
                      <div className="ana-id">{d.nickname ? `@${d.nickname}` : d.name}</div>
                      <div className="ana-overview">
                        {([['粉丝', 'followers'], ['获赞', 'likes'], ['关注', 'following']] as const).map(([label, key]) => {
                          const w = d.growth?.[anaWin] ?? null;
                          const g = w ? growthInfo(w[key as 'followers' | 'likes']) : null;
                          return (
                            <div key={key} className="ana-stat">
                              <div className="ana-stat-val">{fmtNum(d[key])}</div>
                              <div className="ana-stat-label">{label}</div>
                              {g ? <div className="ana-stat-delta" style={{ color: g.color }}>{g.text}</div>
                                 : <div className="ana-stat-delta ana-muted">—</div>}
                            </div>
                          );
                        })}
                      </div>
                      <div className="ana-wins">
                        {WIN.map(([k, lab]) => (
                          <button key={k} className={`ana-win ${anaWin === k ? 'on' : ''}`}
                            onClick={() => setAnaWin(k)}>{lab}</button>
                        ))}
                      </div>
                      <div className="ana-wins-note">
                        {d.growth?.[anaWin]?.since_days != null
                          ? `对比 ${d.growth[anaWin]!.since_days} 天前的快照`
                          : '暂无该时段历史快照，多刷新几次即可积累对比'}
                      </div>
                    </div>

                    {/* 近7日平台指标 + 环比 */}
                    <div className="ana-col ana-col-metrics">
                      <div className="ana-sub">近 7 日 · 环比</div>
                      {(d.metrics ?? []).length === 0 ? (
                        <div className="dash-empty">该平台未提供近 7 日指标</div>
                      ) : (
                        <div className="ana-metrics">
                          {(d.metrics ?? []).map((m) => {
                            const vs = m.vs ?? '';
                            const up = vs.startsWith('+');
                            const has = vs && vs !== '-';
                            return (
                              <div key={m.label} className="ana-metric">
                                <div className="ana-metric-val">{m.value}</div>
                                <div className="ana-metric-label">{m.label}</div>
                                {has && <div className="ana-metric-vs" style={{ color: up ? 'var(--trend-up)' : 'var(--trend-down)' }}>环比{vs}</div>}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    {/* 最新笔记（可点进原文） */}
                    <div className="ana-col ana-col-notes">
                      <div className="ana-sub">最新笔记</div>
                      {(d.notes ?? []).length === 0 ? (
                        <div className="dash-empty">该账号暂无可读取的已发布笔记</div>
                      ) : (
                        <div className="ana-notes">
                          {(d.notes ?? []).slice(0, 6).map((n, i) => (
                            <a key={i} className="ana-note" href={n.url} target="_blank" rel="noreferrer" title={n.title}>
                              {n.cover
                                ? <img className="ana-note-cover" src={n.cover} alt="" referrerPolicy="no-referrer" />
                                : <span className="ana-note-cover ana-note-cover-ph">📝</span>}
                              <span className="ana-note-main">
                                <span className="ana-note-title">{n.title || '(无标题)'}</span>
                                {n.stat && <span className="ana-note-stat">{n.stat}</span>}
                              </span>
                              <span className="ana-note-go">↗</span>
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </>
            );
          })()}
        </div>
      </div>
      {showTaskForm && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="创建运营任务" onMouseDown={(e) => { if (e.target === e.currentTarget) setShowTaskForm(false); }}>
          <div className="modal ops-task-modal">
            <div className="ops-modal-head"><div><h2>创建运营任务</h2><p>选择账号与运营目标，Seal 会保存任务进度并展示当前阶段。</p></div><button className="icon-btn" onClick={() => setShowTaskForm(false)} aria-label="关闭">×</button></div>
            <label className="ops-field-label">任务名称<input className="field" value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} placeholder="例如：本周小红书内容运营" autoFocus /></label>
            <div className="ops-form-grid">
              <label className="ops-field-label">平台<select className="field" value={taskPlatform} onChange={(e) => setTaskPlatform(e.target.value)}><option value="xiaohongshu">小红书</option><option value="douyin">抖音</option><option value="bilibili">B站</option><option value="kuaishou">快手</option><option value="weixin-channels">微信视频号</option><option value="zhihu">知乎</option></select></label>
              <label className="ops-field-label">运营场景<select className="field" value={taskScenario} onChange={(e) => setTaskScenario(e.target.value)}><option value="W1">W1 持续运营</option><option value="W2">W2 方向探索</option><option value="W3">W3 新号启动</option></select></label>
            </div>
            <label className="ops-field-label">账号<select className="field" value={taskAccount} onChange={(e) => setTaskAccount(e.target.value)}><option value="">{taskScenario === 'W3' ? '暂不绑定账号（可先做启动规划）' : '请选择已登录账号'}</option>{accounts.filter((a) => a.loggedIn && a.platform === taskPlatform).map((a) => <option key={`${a.platform}-${a.name}`} value={a.name}>{a.name}</option>)}</select></label>
            <label className="ops-field-label">目标（可选）<textarea className="field" value={taskGoal} onChange={(e) => setTaskGoal(e.target.value)} placeholder="例如：提高收藏率，规划未来 7 天内容" /></label>
            {taskError && <div className="ops-task-error">{taskError}</div>}
            <div className="ops-modal-actions"><button className="btn btn-ghost" onClick={() => setShowTaskForm(false)}>取消</button><button className="btn btn-primary" disabled={taskBusy} onClick={() => void submitTask()}>{taskBusy ? '创建中…' : '创建任务'}</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
