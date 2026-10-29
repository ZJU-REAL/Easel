import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { fetchTrendManagement, updateTrendSource } from '../lib/api';
import type { TrendManagedSource } from '../lib/api';
import SettingsSelect from './SettingsSelect';

export default function TrendSourcesDialog({ onClose, onChanged }: { onClose: () => void; onChanged: (addedId?: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const errorBox = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const [sources, setSources] = useState<TrendManagedSource[]>([]);
  const [template, setTemplate] = useState('');
  const [scriptCode, setScriptCode] = useState('');
  const [scriptName, setScriptName] = useState('collector.py');
  const [maxScriptBytes, setMaxScriptBytes] = useState(65536);
  const fileInput = useRef<HTMLInputElement>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [removing, setRemoving] = useState('');
  const [kind, setKind] = useState('rss');
  const [label, setLabel] = useState('');
  const [url, setUrl] = useState('');
  const [method, setMethod] = useState('GET');
  const [headers, setHeaders] = useState('{}');
  const [body, setBody] = useState('{}');
  const [refresh, setRefresh] = useState(300);

  const reload = useCallback(async () => {
    const result = await fetchTrendManagement();
    if (!alive.current) return;
    setSources(result.sources); setWarnings(result.warnings);
    setTemplate(result.python_template); setMaxScriptBytes(result.script_max_bytes);
    setScriptCode(prev => prev || result.python_template);
  }, []);
  useEffect(() => {
    alive.current = true;
    const element = dialog.current;
    element?.showModal();
    void reload().catch((e: unknown) => {
      if (alive.current) setError(e instanceof Error ? e.message : '无法读取数据源。');
    }).finally(() => { if (alive.current) setLoading(false); });
    return () => { alive.current = false; element?.close(); };
  }, [reload]);
  useEffect(() => { if (error) errorBox.current?.focus(); }, [error]);

  const mutate = async (value: Record<string, unknown>, added = false) => {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await updateTrendSource(value);
      onChanged(added ? result.id : undefined);
      if (alive.current) {
        if (added) { setLabel(''); setUrl(''); }
        setRemoving(''); setNotice(added ? '已添加，热点雷达会自动选中这个来源。' : '已保存。');
        await reload();
      }
    } catch (e: unknown) {
      if (alive.current) setError(e instanceof Error ? e.message : '保存失败，请稍后重试。');
    } finally { if (alive.current) setBusy(false); }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    try {
      const value: Record<string, unknown> = { action: 'add', label: label.trim(), type: kind, refresh_seconds: refresh };
      if (kind === 'python') {
        if (!scriptCode.trim() || new TextEncoder().encode(scriptCode).length > maxScriptBytes) throw new Error('请填写采集代码，UTF-8 脚本上限为 64 KiB。');
        value.script_name = scriptName;
        value.script_code = scriptCode;
      }
      else {
        value.url = url.trim();
        const parsed: unknown = JSON.parse(headers);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object' || Object.values(parsed).some(v => typeof v !== 'string')) throw new Error('请求头需要填写 JSON 字符串映射，例如 {"Authorization":"Bearer ${TOKEN}"}。');
        value.headers = parsed;
        if (kind === 'http') {
          value.method = method;
          if (method === 'POST') value.body = JSON.parse(body);
        }
      }
      void mutate(value, true);
    } catch (e: unknown) { setError(e instanceof Error ? e.message : '高级设置中的 JSON 格式无效。'); }
  };

  return <dialog ref={dialog} className="trend-manager" aria-labelledby="trend-manager-title" onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="trend-manager-head"><div><h2 id="trend-manager-title">数据源</h2><p>订阅你关心的内容，或接入自己的采集服务。</p></div><button className="btn btn-sm" onClick={onClose}>关闭</button></div>
    {error && <div ref={errorBox} tabIndex={-1} className="trend-manager-error" role="alert">{error}</div>}
    {notice && <div className="trend-manager-notice" role="status">{notice}</div>}
    {warnings.map((warning, i) => <p className="trend-manager-error" key={i}>{warning}</p>)}
    {loading ? <p role="status">正在加载数据源…</p> : <>
      <section className="trend-manager-list" aria-label="已配置来源">
        {sources.map(source => <div key={source.id} className="trend-manager-row">
          <div><strong>{source.label}</strong><span>{source.builtin ? '内置' : '自定义'} · {source.enabled ? '已启用' : '已停用'}</span></div>
          <button className="btn btn-sm" disabled={busy} aria-label={`${source.enabled ? '停用' : '启用'}${source.label}`} onClick={() => { void mutate({ action: 'toggle', id: source.id, enabled: !source.enabled }); }}>{source.enabled ? '停用' : '启用'}</button>
          {!source.builtin && (removing === source.id ? <><button className="btn btn-sm btn-danger" disabled={busy} onClick={() => { void mutate({ action: 'delete', id: source.id }); }}>确认删除</button><button className="btn btn-sm" onClick={() => setRemoving('')}>取消</button></> : <button className="btn btn-sm" disabled={busy} aria-label={`删除${source.label}`} onClick={() => setRemoving(source.id)}>删除</button>)}
        </div>)}
      </section>
      <form onSubmit={submit} className="trend-manager-form" aria-busy={busy}>
        <h3>添加来源</h3>
        <div className="trend-manager-fields">
          <label>名称<input className="field" required maxLength={80} value={label} onChange={e => setLabel(e.target.value)} placeholder="例如：行业资讯" /></label>
          <div><span className="field-label">接入方式</span><SettingsSelect label="接入方式" value={kind} disabled={busy} options={[{value:'rss',label:'RSS / Atom 订阅'},{value:'http',label:'HTTP 接口'},{value:'python',label:'Python 脚本'}]} onChange={next => { setKind(next); if (next === 'python' && !scriptCode) setScriptCode(template); }} /></div>
        </div>
        {kind === 'python' ? <>
          <div className="trend-script-toolbar"><span>{scriptName}</span><button className="btn btn-sm" type="button" disabled={busy} onClick={() => fileInput.current?.click()}>选择 .py 文件</button><button className="btn btn-sm" type="button" disabled={busy || !template} onClick={() => { setScriptCode(template); setScriptName('collector.py'); }}>恢复示例</button></div>
          <input ref={fileInput} type="file" accept=".py" hidden aria-label="选择 Python 脚本" onChange={async event => {
            const file = event.currentTarget.files?.[0]; event.currentTarget.value = '';
            if (!file) return;
            try {
              if (!/\.py$/i.test(file.name) || file.size > maxScriptBytes) throw new Error('请选择不超过 64 KiB 的 UTF-8 .py 文件。');
              const code = new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer());
              if (!alive.current) return;
              setScriptCode(code); setScriptName(file.name); setError('');
              setLabel(prev => prev || file.name.replace(/\.py$/i,'').slice(0,80));
            } catch { if (alive.current) setError('无法读取脚本，请选择不超过 64 KiB 的 UTF-8 .py 文件。'); }
          }} />
          <label>Python 采集代码<textarea className="field trend-code-editor" aria-label="Python 采集代码" required spellCheck={false} rows={12} wrap="off" maxLength={65536} value={scriptCode} onChange={e => setScriptCode(e.target.value)} /></label>
          <p className="trend-manager-hint">保存前仅在受限进程中校验语法；保存并启用后将以服务账号运行代码。未知脚本建议部署为隔离的 HTTP 服务。</p>
        </> : <label>{kind === 'rss' ? '订阅地址' : '接口地址'}<input className="field" type="url" required maxLength={8192} value={url} onChange={e => setUrl(e.target.value)} placeholder="https://…" /></label>}
        <details><summary>高级设置</summary>
          <label>刷新间隔（秒）<input className="field" type="number" min={1} max={86400} required value={refresh} onChange={e => setRefresh(Number(e.target.value))} /></label>
          {kind === 'http' && <div><span className="field-label">请求方式</span><SettingsSelect label="请求方式" value={method} disabled={busy} options={[{value:'GET',label:'GET'},{value:'POST',label:'POST'}]} onChange={setMethod} /></div>}
          {kind !== 'python' && <label>请求头（JSON，可用环境变量引用）<textarea className="field" aria-label="请求头" rows={3} maxLength={8192} value={headers} onChange={e => setHeaders(e.target.value)} /></label>}
          {kind === 'http' && method === 'POST' && <label>请求正文（JSON）<textarea className="field" aria-label="请求正文" rows={3} maxLength={8192} value={body} onChange={e => setBody(e.target.value)} /></label>}
        </details>
        <div className="trend-manager-footer"><span>保存后立即生效。</span><button className="btn btn-primary" type="submit" disabled={busy || (kind === 'python' && !scriptCode.trim())}>{busy ? '保存中…' : kind === 'python' ? '保存并启用' : '添加来源'}</button></div>
      </form>
    </>}
  </dialog>;
}
