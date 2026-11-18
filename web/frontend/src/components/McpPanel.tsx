import { useCallback, useEffect, useState } from 'react';
import { IconHexagon } from './settingsIcons';
import {
  fetchMcpServers, addMcpServer, deleteMcpServer, toggleMcpServer, probeMcpServer,
} from '../lib/api';
import type { McpServerRow, McpToolInfo } from '../lib/api';

/** 设置 → MCP 节点：通讯录（增删/启停）+ 工具总览（实时探测）。
 *  变更会重启 OpenClaw gateway（约 20s），agent 下轮对话即见新工具架。 */
export default function McpPanel() {
  const [servers, setServers] = useState<McpServerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [applying, setApplying] = useState(false);
  const [distLine, setDistLine] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, McpToolInfo[] | 'loading' | 'error'>>({});
  const [fName, setFName] = useState('');
  const [fTransport, setFTransport] = useState<'stdio' | 'streamable-http'>('streamable-http');
  const [fUrl, setFUrl] = useState('');
  const [fCommand, setFCommand] = useState('');
  const [fArgs, setFArgs] = useState('');
  const [fEnv, setFEnv] = useState('');

  const load = useCallback(async () => {
    try {
      const d = await fetchMcpServers();
      setServers(d.servers);
      setError('');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const apply = useCallback(async (action: () => Promise<unknown>) => {
    setApplying(true);
    setError('');
    setDistLine('');
    try {
      const d = await action() as { distribution?: { runtime: string; status: string }[] };
      if (d?.distribution?.length) {
        setDistLine('分发：' + d.distribution
          .map((r) => `${r.runtime} ${r.status.startsWith('applied') ? '✓' : r.status.startsWith('skipped') ? '—' : '✗'}`)
          .join(' · '));
      }
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setApplying(false);
    }
  }, [load]);

  const doAdd = useCallback(() => {
    const env: Record<string, string> = {};
    fEnv.split('\n').forEach((line) => {
      const lineTrim = line.trim();
      if (!lineTrim || lineTrim.startsWith('#')) return;
      const eq = lineTrim.indexOf('=');
      if (eq > 0) env[lineTrim.slice(0, eq).trim()] = lineTrim.slice(eq + 1).trim();
    });
    void apply(() => addMcpServer({
      name: fName.trim(),
      transport: fTransport,
      command: fTransport === 'stdio' ? fCommand.trim() : undefined,
      args: fTransport === 'stdio' ? fArgs.split(/\s+/).filter(Boolean) : undefined,
      env: fTransport === 'stdio' ? env : undefined,
      url: fTransport === 'streamable-http' ? fUrl.trim() : undefined,
    })).then(() => { setShowAdd(false); setFName(''); setFUrl(''); setFCommand(''); setFArgs(''); setFEnv(''); });
  }, [apply, fName, fTransport, fUrl, fCommand, fArgs, fEnv]);

  const doProbe = useCallback(async (name: string) => {
    setExpanded((s) => ({ ...s, [name]: 'loading' }));
    try {
      const r = await probeMcpServer(name);
      setExpanded((s) => ({ ...s, [name]: r.tools }));
    } catch (e) {
      setError(`${name} 探测失败：${String(e)}`);
      setExpanded((s) => ({ ...s, [name]: 'error' }));
    }
  }, []);

  return (
    <div className="st-env">
      <div className="panel-top">
        <span className="desc">全部工具对 agent 可见，agent 按任务自主调用。变更会短暂重启网关（约 20 秒），进行中的会话会中断。</span>
        <span className="spacer" />
        <button className="btn btn-sm btn-primary" disabled={applying || showAdd}
                onClick={() => setShowAdd(true)}>＋ 新增节点</button>
      </div>
      {error && <div className="desc" style={{ color: 'var(--red)', margin: '8px 0' }}>{error}</div>}
      {loading && <div className="desc">加载中……</div>}
      {!loading && servers.length === 0 && <div className="desc">还没有任何 MCP 节点，点「新增节点」添加。</div>}
      {applying && <div className="desc" style={{ margin: '8px 0' }}>应用中（网关重启约 20 秒）……</div>}
      {distLine && !applying && <div className="desc" style={{ margin: '8px 0' }}>{distLine}</div>}

      {showAdd && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-name">新增 MCP 节点</div>
          <label className="field-label" style={{ display: 'block', marginTop: 8 }}>名称</label>
          <input className="field" value={fName} onChange={(e) => setFName(e.target.value)}
                 placeholder="如 shotvideo-mcp" style={{ width: '100%', boxSizing: 'border-box' }} />
          <label className="field-label" style={{ display: 'block', marginTop: 8 }}>类型</label>
          <select className="field" value={fTransport}
                  onChange={(e) => setFTransport(e.target.value as 'stdio' | 'streamable-http')}
                  style={{ width: '100%', boxSizing: 'border-box' }}>
            <option value="streamable-http">HTTP（远程 URL）</option>
            <option value="stdio">本地进程（command）</option>
          </select>
          {fTransport === 'streamable-http' ? (
            <>
              <label className="field-label" style={{ display: 'block', marginTop: 8 }}>URL</label>
              <input className="field" value={fUrl} onChange={(e) => setFUrl(e.target.value)}
                     placeholder="https://host/mcp" style={{ width: '100%', boxSizing: 'border-box' }} />
            </>
          ) : (
            <>
              <label className="field-label" style={{ display: 'block', marginTop: 8 }}>命令</label>
              <input className="field" value={fCommand} onChange={(e) => setFCommand(e.target.value)}
                     placeholder="node / 可执行脚本" style={{ width: '100%', boxSizing: 'border-box' }} />
              <label className="field-label" style={{ display: 'block', marginTop: 8 }}>参数（空格分隔）</label>
              <input className="field" value={fArgs} onChange={(e) => setFArgs(e.target.value)}
                     placeholder="server.js --port 8080" style={{ width: '100%', boxSizing: 'border-box' }} />
              <label className="field-label" style={{ display: 'block', marginTop: 8 }}>环境变量（每行 KEY=VALUE）</label>
              <textarea className="field" value={fEnv} onChange={(e) => setFEnv(e.target.value)} rows={3}
                        style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical' }} />
            </>
          )}
          <div className="card-foot" style={{ marginTop: 12 }}>
            <button className="btn btn-sm btn-primary" disabled={!fName.trim() || applying}
                    onClick={doAdd}>保存并应用</button>
            <button className="btn btn-sm" onClick={() => setShowAdd(false)}>取消</button>
          </div>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', marginTop: 12 }}>
        {servers.map((s) => {
          const tools = expanded[s.name];
          return (
            <div className="card" key={s.name} data-state={s.disabled ? 'nodir' : 'ok'}>
              <div className="card-top">
                <span className="tile"><IconHexagon size={17} /></span>
                <span className={`badge pill ${s.disabled ? 'off' : 'ok'}`}>
                  <span className="dot" />{s.disabled ? '停用' : '启用'}
                </span>
              </div>
              <div className="card-name">{s.name}</div>
              <div className="card-desc">
                {s.transport === 'streamable-http'
                  ? `HTTP · ${s.target}`
                  : `stdio · ${s.target}${s.args.length ? ` ${s.args.join(' ')}` : ''}`}
                {s.hasEnv ? ' · env' : ''}{s.hasHeaders ? ' · headers' : ''}
              </div>
              <div className="card-foot">
                <button className="btn" disabled={applying}
                        onClick={() => void apply(() => toggleMcpServer(s.name))}>
                  {s.disabled ? '启用' : '停用'}
                </button>
                <button className="btn" disabled={applying || s.disabled}
                        onClick={() => void doProbe(s.name)}>
                  {tools === 'loading' ? '探测中……'
                    : Array.isArray(tools) ? `工具 ×${tools.length}` : '工具清单'}
                </button>
                <button className="btn" disabled={applying}
                        onClick={() => { if (window.confirm(`删除节点 ${s.name}？`)) void apply(() => deleteMcpServer(s.name)); }}>
                  删除
                </button>
              </div>
              {Array.isArray(tools) && tools.length > 0 && (
                <div style={{ border: '1px solid var(--border)', borderRadius: 8, maxHeight: 170,
                              overflowY: 'auto', padding: '6px 9px', background: 'var(--surface-hover)' }}>
                  {tools.map((t) => (
                    <div key={t.name} style={{ margin: '3px 0', fontSize: 12, lineHeight: 1.45 }}>
                      <code style={{ fontWeight: 650 }}>{t.name}</code>
                      <span style={{ color: 'var(--text-tertiary)' }}> — {t.description || '(无描述)'}</span>
                    </div>
                  ))}
                </div>
              )}
              {tools === 'error' && (
                <div className="card-desc" style={{ color: 'var(--red)' }}>探测失败，详见顶部错误信息</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
