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
  return <div className="settings-field">
    <span className="settings-field-label">Codex 连接</span>
    <div className="settings-field-body">
      <p className="desc" role="status">{reading ? '读取登录与额度状态…' : label}</p>
      <CodexLogin disabled={disabled || testing} authenticated={status?.state === 'authenticated'}
        onConnected={() => { setResult(''); setRefresh(previous => previous + 1); }} />
      {status?.windows.map((window, index) => <p className="desc" key={`${window.window}-${index}`}>
        {window.windowDurationMins ? `${window.windowDurationMins % 1440 === 0
          ? `${window.windowDurationMins / 1440} 天` : window.windowDurationMins % 60 === 0
            ? `${window.windowDurationMins / 60} 小时` : `${window.windowDurationMins} 分钟`}窗口` : `额度窗口 ${index + 1}`}：
        已使用 {window.usedPercent}%
        {window.resetsAt ? ` · 重置于 ${new Date(window.resetsAt * 1000).toLocaleString()}` : ''}
      </p>)}
      {!reading && status && !status.windows.length && <p className="desc">{status.quotaNote || '未提供额度窗口；不代表额度为零。'}</p>}
      {(statusError || status?.error) && <p className="desc" role="status">{statusError || status?.error?.message}</p>}
      <div className="settings-native-models">
        <button className="btn btn-sm" disabled={disabled || reading || testing}
          onClick={() => setRefresh(previous => previous + 1)}>刷新状态</button>
        <button className="btn btn-sm" disabled={disabled || testing}
          onClick={() => void test()}>{testing ? '测试连接中…' : '测试连接'}</button>
      </div>
      <p className="desc">测试使用当前选择的模型和推理强度，发起一次简短请求，会消耗少量用量；不保存设置或创建 Easel 对话。</p>
      {result && <p className="desc" role="status">{result}</p>}
    </div>
  </div>;
}
