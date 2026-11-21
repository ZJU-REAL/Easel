import { useEffect, useRef, useState } from 'react';
import { getRemotion, selectRemotion, probeRemotion, type RemotionState } from '../lib/remotion';

export default function RemotionProject({ revision, onChange }: { revision: number; onChange: () => void }) {
  const [data, setData] = useState<RemotionState | null>(null);
  const [editing, setEditing] = useState(false);
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const generation = useRef(0);
  useEffect(() => {
    const id = ++generation.current;
    let mounted = true;
    getRemotion().then(d => { if (mounted && generation.current === id) { setData(d); setError(""); } }).catch(e => { if (mounted && generation.current === id) setError(e.message); });
    return () => { mounted = false; };
  }, [revision]);
  const apply = async (path: string) => {
    generation.current++;
    setBusy('save'); setError('');
    try { setData(await selectRemotion(path)); setEditing(false); onChange(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  };
  const test = async () => {
    generation.current++;
    setBusy('test'); setError('');
    setData(previous => previous && { ...previous, probe: null });
    try { await probeRemotion(); setData(await getRemotion()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  };
  const project = data?.selected;
  return <section className="remotion-project">
    <div className="remotion-top"><span className="remotion-symbol" aria-hidden="true">▸</span>
      <div><h4>本机 Remotion</h4><p>{project?.ready ? '当前渲染工程' : project ? '工程依赖待检查' : '选择已有的视频工程'}</p></div>
      {project?.version && <span className="studio-version">v{project.version}</span>}
    </div>
    {project && <code className="project-path">{project.path}</code>}
    {project?.detail && <p className="studio-note">{project.detail}</p>}
    <div className="project-actions">
      <button type="button" className="studio-button" disabled={!!busy}
        onClick={() => { setEditing(!editing); setPath(project?.path || data?.projects[0]?.path || ''); setError(''); }}>
        {editing ? '取消' : project ? '更换工程' : '选择工程'}</button>
      {project?.ready && <button type="button" disabled={!!busy} className="studio-button" onClick={() => void test()}>
        {busy === 'test' ? '正在渲染…' : '测试渲染一帧'}</button>}
      {project && <small role="status">{busy === 'test' ? '正在验证本机渲染器…' : data?.probe ? '已通过单帧渲染 · ' + data.probe.size : '尚未验证渲染'}</small>}
    </div>
    {editing && <form className="project-picker" onSubmit={e => { e.preventDefault(); if (path.trim()) void apply(path); }}>
      <label htmlFor="remotion-project-dir">含 package.json 和 node_modules 的工程目录</label>
      <div><input id="remotion-project-dir" list="remotion-locations" value={path} onChange={e => setPath(e.target.value)}
        placeholder="输入本机工程的完整路径" autoFocus /><button className="studio-primary" disabled={!!busy || !path.trim()}>使用此工程</button></div>
      <datalist id="remotion-locations">{data?.projects.map(p => <option key={p.path} value={p.path} />)}</datalist>
      {project && <button type="button" className="studio-link" disabled={!!busy} onClick={() => void apply('')}>解除关联</button>}
    </form>}
    {error && <p className="studio-error" role="alert">{error}</p>}
  </section>;
}
