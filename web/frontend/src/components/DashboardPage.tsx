import { useState, useEffect, useRef } from 'react';
import { fetchAccounts, fetchAnalyticsPlatforms, fetchAccountAnalytics } from '../lib/api';
import type { AccountItem, AnalyticsPlatform, AccountAnalytics, AccountWhoami } from '../lib/api';
import { getWhoamiCache, verifyStale } from '../lib/whoami';
import { calendarDate } from '../lib/calendarDate';
import CreationDesk, { type CreationDeskProps } from './CreationDesk';
import ContentPanel from './ContentPanel';
import { IconAccounts, IconFile, IconLayout, IconChart } from './icons';

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

export default function DashboardPage(props: CreationDeskProps) {
  const { onNavigate } = props;
  const [view, setView] = useState<'desk' | 'review'>('desk');
  const [reviewOpened, setReviewOpened] = useState(false);
  const [accounts, setAccounts] = useState<AccountItem[] | null>(null);
  const [platformState, setPlatformState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [revision, setRevision] = useState(0);
  // 归因层：账号创作数据
  const [anaPlats, setAnaPlats] = useState<AnalyticsPlatform[]>([]);
  const [anaSel, setAnaSel] = useState('');
  const [anaData, setAnaData] = useState<Record<string, AccountAnalytics | 'loading' | 'error'>>(() => {
    try {
      const cache = JSON.parse(localStorage.getItem('easel_analytics') || '{}') as Record<string, AccountAnalytics | 'loading' | 'error'>;
      return Object.fromEntries(Object.entries(cache).filter(([platform, value]) =>
        value && typeof value === 'object' && value.platform === platform
        && typeof value.loggedIn === 'boolean'));
    } catch { return {}; }
  });
  const anaPending = useRef(new Set<string>());
  const [anaErrors, setAnaErrors] = useState<Record<string, string>>({});
  const [anaWin, setAnaWin] = useState<'last' | 'day' | 'week' | 'month' | 'year'>('week');
  // whoami 自愈：登录态以真实 profile 为准（与账号页共享 localStorage 缓存）
  const [whoamiMap, setWhoamiMap] = useState<Record<string, AccountWhoami>>(() => getWhoamiCache());
  useEffect(() => {
    if (!reviewOpened) return;
    let current = true;
    fetchAccounts().then(rows => { if (current) setAccounts(rows); }).catch(() => {});
    fetchAnalyticsPlatforms().then((ps) => {
      if (!current) return;
      setPlatformState('ready');
      setAnaPlats(ps);
      const cache = getWhoamiCache();
      const isLog = (p: AnalyticsPlatform) => p.loggedIn || !!cache[p.platform]?.loggedIn;
      const first = ps.find(isLog);
      if (first) setAnaSel((s) => s || first.platform);
      // 开页后台自愈：对非 API 式的归因平台真校验（whoami），刷新登录态；
      // B 站走 cookie、公众号走凭证/官方 API 判定，都不起浏览器。
      const API_BASED = new Set(['bilibili', 'wechat-oa']);
      verifyStale(ps.filter((p) => !API_BASED.has(p.platform)).map((p) => p.platform), {
        alive: () => current,
        onUpdate: (platform, r) => {
          setWhoamiMap((m) => ({ ...m, [platform]: r }));
          if (r.loggedIn) setAnaSel((s) => s || platform);
        },
      });
    }).catch(() => { if (current) setPlatformState('error'); });
    return () => { current = false; };
  }, [reviewOpened, revision]);

  const runAna = (platform: string) => {
    setAnaSel(platform);
    if (anaPending.current.has(platform)) return;
    anaPending.current.add(platform);
    setAnaErrors((errors) => ({ ...errors, [platform]: '' }));
    setAnaData((d) => ({ ...d, [platform]: 'loading' }));
    fetchAccountAnalytics(platform)
      .then((r) => setAnaData((d) => {
        const next = { ...d, [platform]: r };
        const cache = Object.fromEntries(Object.entries(next).filter(([, value]) =>
          value && typeof value === 'object'));
        try { localStorage.setItem('easel_analytics', JSON.stringify(cache)); } catch { /* quota */ }
        return next;
      }))
      .catch((error: unknown) => {
        setAnaErrors((errors) => ({ ...errors, [platform]: error instanceof Error
          ? error.message : '抓取失败，请稍后重试' }));
        setAnaData((d) => ({ ...d, [platform]: 'error' as const }));
      })
      .finally(() => anaPending.current.delete(platform));
  };

  const today = new Date();
  const review = view === 'review';
  return (
    <div className="page-scroll dash-page editorial-desk">
      <div className="desk-inner">
        <header className="desk-masthead">
          <div><time dateTime={calendarDate(today)}>{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(today)}</time>
            <h1 className="page-title">创作工作台</h1></div>
          <div className="desk-mode" role="group" aria-label="工作台视图">
            <button aria-pressed={!review} onClick={() => setView('desk')}><IconLayout size={15}/>创作</button>
            <button aria-pressed={review} onClick={() => { setReviewOpened(true); setView('review'); }}><IconChart size={15}/>数据复盘</button>
          </div>
        </header>

        <div hidden={review}><CreationDesk {...props}/></div>

        {review && <div className="desk-review">
          <div className="desk-review-head"><h2>账号表现</h2>
            <button className="desk-link" onClick={() => onNavigate('accounts')}>
              {accounts && <span>{accounts.filter(a => whoamiMap[a.platform]?.loggedIn ?? a.loggedIn).length} / {accounts.length} 已登录 · </span>}管理账号
            </button>
          </div>
        <ContentPanel className="dash-card dash-card-wide" label="创作数据" header={<div className="dash-card-head">
            <span><IconAccounts size={16} /> 创作数据</span>
            {anaSel && anaData[anaSel] && anaData[anaSel] !== 'loading' && (
              <button className="dash-more" onClick={() => runAna(anaSel)}>刷新 →</button>
            )}
          </div>}>
          {(() => {
            const logged = anaPlats.filter((p) => p.loggedIn || whoamiMap[p.platform]?.loggedIn);
            if (platformState === 'loading') return <div className="dash-empty" role="status">正在读取账号…</div>;
            if (platformState === 'error') return <div className="dash-empty" role="alert">账号列表读取失败 <button className="desk-link" onClick={() => { setPlatformState('loading'); setRevision(v => v + 1); }}>重试</button></div>;
            if (logged.length === 0) {
              return (
                <p className="dash-empty">登录支持数据复盘的平台后，可以查看粉丝、互动和近期作品。</p>
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
                  <div className="loading" style={{ padding: '28px 0' }}><div className="spinner" />抓取中…正在校验登录态并读取平台数据</div>
                )}
                {d === 'error' && (
                  <div className="dash-empty" style={{ color: 'var(--red)' }}>{anaErrors[anaSel] || '抓取失败，请稍后重试'}；点平台重试</div>
                )}
                {d && d !== 'loading' && d !== 'error' && (!d.loggedIn ? (
                  <button className="desk-link" onClick={() => onNavigate('accounts')}>该平台登录已失效，前往账号页重新登录</button>
                ) : (
                  <div className="ana-body">
                    {d.warning && <div className="dash-empty" role="status" style={{ gridColumn: '1 / -1' }}>{d.warning}</div>}
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
                                : <span className="ana-note-cover ana-note-cover-ph"><IconFile size={19} /></span>}
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
        </ContentPanel>
        </div>}
      </div>
    </div>
  );
}
