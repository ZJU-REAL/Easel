import { Component, useState, useEffect, useCallback, useRef } from 'react';
import type { ReactNode } from 'react';
import { fetchTrendSources, fetchTrends, createIdea } from '../lib/api';
import type { TrendGroup, TrendSource } from '../lib/api';
import { IconFire, IconRefresh, IconBookmark, IconCheck } from './icons';
import TrendSourcesDialog from './TrendSourcesDialog';

interface TrendsPageProps {
  onUseTopic: (title: string) => void;   // 一键做成内容 → 跳 chat
}

class TrendBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <div className="page-scroll trends-page"><div className="notice-error" role="alert">热点页面暂时无法显示，其他工作台功能仍可使用。<button className="btn btn-sm" onClick={() => this.setState({ failed: false })}>重新加载热点</button></div></div> : this.props.children;
  }
}

export default function TrendsPage(props: TrendsPageProps) {
  return <TrendBoundary><TrendsPanel {...props} /></TrendBoundary>;
}

function TrendsPanel({ onUseTopic }: TrendsPageProps) {
  const [sources, setSources] = useState<TrendSource[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [groups, setGroups] = useState<TrendGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState(0);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [managerOpen, setManagerOpen] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [saveError, setSaveError] = useState('');
  const requestId = useRef(0);
  const discoveryId = useRef(0);
  const initialized = useRef(false);

  const save = async (key: string, title: string, source: string) => {
    if (saved.has(key)) return;
    try {
      await createIdea({ title, source, status: 'pending' });
      setSaved((prev) => new Set(prev).add(key));
    } catch { setSaveError('收藏失败，请稍后重试。'); }
  };

  const load = useCallback((pfs: string[]) => {
    const id = ++requestId.current;
    if (pfs.length === 0) { setGroups([]); setLoading(false); setError(''); return; }
    setGroups((prev) => prev.filter((g) => pfs.includes(g.platform)));
    setLoading(true);
    setError('');
    fetchTrends(pfs.join(','), 15)
      .then((d) => { if (requestId.current === id) { setGroups(d.trends); setUpdated(d.updated); setWarnings(d.warnings); } })
      .catch((e: unknown) => {
        if (requestId.current === id) setError(e instanceof Error ? e.message : '热点拉取失败，请稍后重试。');
      })
      .finally(() => { if (requestId.current === id) setLoading(false); });
  }, []);

  const discover = useCallback(() => {
    const id = ++discoveryId.current;
    requestId.current++;
    setReady(false);
    setLoading(false);
    setError('');
    return fetchTrendSources().then((d) => {
      if (discoveryId.current !== id) return;
      setSources(d.sources);
      setWarnings(d.warnings);
      const first = !initialized.current;
      initialized.current = true;
      setSelected((prev) => first ? d.sources.filter((s) => s.default).map((s) => s.id)
        : d.sources.filter((s) => prev.includes(s.id)).map((s) => s.id));
      setGroups((prev) => prev.filter((g) => d.sources.some((s) => s.id === g.platform)));
      setReady(true);
    }).catch((e: unknown) => {
      if (discoveryId.current === id) {
        setGroups([]);
        setSources([]);
        setError(e instanceof Error ? e.message : '无法加载热点数据源。');
      }
    });
  }, []);

  const invalidate = useCallback(() => { requestId.current++; discoveryId.current++; }, []);
  useEffect(() => { void discover(); return invalidate; }, [discover, invalidate]);
  useEffect(() => { if (ready) load(selected); }, [load, selected, ready]);
  useEffect(() => {
    if (!groups.some(group => group.error?.code === 'busy')) return;
    const timer = window.setTimeout(() => load(selected), 1500);
    return () => window.clearTimeout(timer);
  }, [groups, selected, load]);

  const toggle = (k: string) =>
    setSelected((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]);

  return (
    <div className="page-scroll trends-page" aria-busy={loading}>
      <div className="page-head">
        <div>
          <h1 className="page-title"><IconFire size={22} /> 热点雷达</h1>
          <p className="page-subtitle">
            汇集平台热搜与自定义数据源，挑选题，一键交给 AI 做成你的内容。
            {updated > 0 && <span style={{ color: 'var(--text-tertiary)' }}> · {new Date(updated * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 查询</span>}
          </p>
        </div>
        <div className="trend-actions"><button className="btn btn-sm" onClick={() => setManagerOpen(true)}>数据源</button>
        <button className="btn btn-sm" onClick={() => { void discover(); }} disabled={loading}>
          <IconRefresh size={14} /> {loading ? '刷新中…' : '刷新'}
        </button></div>
      </div>

      <div className="trend-platforms">
        {sources.map((p) => (
          <button key={p.id} className={`chip ${selected.includes(p.id) ? 'active' : ''}`}
            aria-pressed={selected.includes(p.id)} onClick={() => toggle(p.id)}>{p.label}</button>
        ))}
      </div>

      {error && <div className="notice-error" role="alert">{error}</div>}
      {saveError && <div className="notice-error" role="alert">{saveError}</div>}
      {warnings.map((warning, i) => <div className="notice-error" role="status" key={i}>{warning}</div>)}
      {!ready && !error && <div className="trend-platforms" role="status">正在加载数据源…</div>}
      {ready && sources.length === 0 && <div className="trend-platforms">尚未启用数据源，请在本地热点数据源配置中添加或启用。</div>}
      {ready && sources.length > 0 && selected.length === 0 && <div className="trend-platforms">请选择上方的数据源查看热点。</div>}
      {loading && <div className="trend-platforms" role="status">正在获取热点…</div>}

      <div className="trend-grid">
        {groups.map((g) => (
          <div key={g.platform} className="card trend-col">
            <div className="trend-col-head">{g.label}<span className="trend-count">{g.items.length}</span></div>
            <div className="trend-source-status">
              {g.fetched_at && <span>采集于 {new Date(g.fetched_at).toLocaleString('zh-CN')}</span>}
              {g.stale && <span> · 缓存已过期</span>}
              {g.error && <div role="status">{g.error.message}{g.stale ? '，暂用上次结果' : ''}</div>}
            </div>
            <div className="trend-list">
              {g.items.length === 0 && !loading && (
                <div className="trend-empty">
                  {!g.ok ? '该数据源暂时不可用' : '采集成功，暂无热点'}
                </div>
              )}
              {g.items.map((it, i) => (
                <div key={it.id} className="trend-item">
                  <span className={`trend-rank ${i < 3 ? 'top' : ''}`}>{i + 1}</span>
                  <div className="trend-main">
                    <a className="trend-title" href={it.url || undefined} target="_blank" rel="noreferrer"
                      title={it.title}>{it.title}</a>
                    {it.hot && <span className="trend-hot">{it.hot}</span>}
                  </div>
                  <button className="trend-save" title={saved.has(`${g.platform}:${it.id}`) ? '已收藏到选题库' : '收藏到选题库'}
                    aria-label={`收藏选题：${it.title}`}
                    onClick={() => save(`${g.platform}:${it.id}`, it.title, g.label)}>
                    {saved.has(`${g.platform}:${it.id}`) ? <IconCheck size={14} /> : <IconBookmark size={14} />}
                  </button>
                  <button className="trend-use" title="做成内容"
                    onClick={() => onUseTopic(it.title)}>做内容</button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      {managerOpen && <TrendSourcesDialog onClose={() => setManagerOpen(false)} onChanged={addedId => {
        void discover().then(() => { if (addedId) setSelected(prev => [...new Set([...prev, addedId])]); });
      }} />}
    </div>
  );
}
