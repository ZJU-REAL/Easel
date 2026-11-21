import { useEffect, useRef, useState } from 'react';
import { fetchCodexStatus, probeCodex } from '../lib/api';
import type { CodexStatus } from '../lib/api';
import CodexLogin from './CodexLogin';

export default function CodexConnection({ model, effort, disabled }: {
  model: string; effort: string; disabled: boolean;
}) {
  const [status, setStatus] = useState<CodexStatus | null>(null);
  const [reading, setReading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [result, setResult] = useState('');
  const [refresh, setRefresh] = useState(0);
  const sequence = useRef(0);
  useEffect(() => {
    let alive = true;
    if (disabled) return;
    setReading(true);
    setStatusError('');
    fetchCodexStatus().then(value => { if (alive) setStatus(value); })
      .catch(error => {
        if (alive) { setStatus(null); setStatusError(error instanceof Error ? error.message : String(error)); }
      })
      .finally(() => { if (alive) setReading(false); });
    return () => { alive = false; };
  }, [disabled, refresh]);
  useEffect(() => {
    sequence.current += 1;
    setResult('');
    return () => { sequence.current += 1; };
  }, [model, effort]);
  const test = async () => {
    const current = sequence.current;
    setTesting(true);
    setResult('');
    try {
      const value = await probeCodex(model, effort);
      if (current === sequence.current) {
        setResult(value.ok ? `连接成功：${value.model} · ${((value.elapsedMs || 0) / 1000).toFixed(1)} 秒`
          : value.error?.message || '连接测试失败，请检查 Codex 配置。');
        setRefresh(previous => previous + 1);
      }
    } catch (error) {
      if (current === sequence.current) setResult(`测试失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setTesting(false);
    }
  };
  const label = status?.state === 'authenticated' ? `已登录（${status.authType || '原生账号'}）`
    : status?.state === 'external' ? '使用原生自定义供应商，请测试连接'
    : status?.state === 'unauthenticated' ? '尚未登录，点击下方按钮连接你的账号'
    : '登录状态暂未确认';
  const authenticated = status?.state === 'authenticated';
  const loginControls = <CodexLogin disabled={disabled || testing} authenticated={authenticated}
    onConnected={() => { setResult(''); setRefresh(previous => previous + 1); }} />;
  return <section className="engine-connection" aria-label="Codex 连接">
    <div className="connection-head">
      <h3>账号与连接</h3>
      <span className={'connection-state' + (authenticated ? ' connected' : '')} role="status">
        {disabled ? '引擎未就绪' : reading ? '读取状态中…' : label}
      </span>
    </div>
    {(statusError || status?.error) && <p className="engine-notice" role="status">{statusError || status?.error?.message}</p>}
    {status && status.windows.length > 0 && <div className="quota-windows">
      {status.windows.map((window, index) => <div className="quota-window" key={window.window + '-' + index}>
        <div><span>{window.windowDurationMins ? (window.windowDurationMins % 1440 === 0
          ? window.windowDurationMins / 1440 + ' 天' : window.windowDurationMins % 60 === 0
          ? window.windowDurationMins / 60 + ' 小时' : window.windowDurationMins + ' 分钟') + '用量' : '额度窗口 ' + (index + 1)}</span>
          <strong>已用 {window.usedPercent}%</strong></div>
        <progress aria-label="额度已用百分比" value={window.usedPercent} max={100} />
        {window.resetsAt ? <small>{new Date(window.resetsAt * 1000).toLocaleString()} 重置</small> : null}
      </div>)}
    </div>}
    <div className="connection-actions">
      <button className="btn btn-sm" disabled={disabled || testing} onClick={() => void test()}>{testing ? '测试连接中…' : '测试连接'}</button>
      <button className="btn btn-sm" disabled={disabled || reading || testing} onClick={() => setRefresh(previous => previous + 1)}>刷新状态</button>
    </div>
    <p className="engine-note">测试会向所选模型发送一次简短请求，消耗少量用量。</p>
    {result && <p className="engine-notice" role="status">{result}</p>}
    <details className="engine-details" hidden={disabled} open={status?.state === 'unauthenticated'}>
      <summary>{authenticated ? '管理登录账号' : '登录账号'}</summary>
      {loginControls}
    </details>
    {!reading && status && !status.windows.length && <p className="engine-note">{status.quotaNote || '未提供额度窗口；不代表额度为零。'}</p>}
  </section>;
}
