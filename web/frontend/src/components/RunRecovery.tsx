import { useEffect, useState } from 'react';
import { fetchChatRun, updateChatRun, type ChatRun } from '../lib/api';

const labels: Record<ChatRun['state'], string> = {
  queued: '等待执行', running: '上次记录为执行中', succeeded: '已完成',
  failed: '执行失败', cancelled: '已取消', interrupted: '已中断', unknown: '结果未知',
};

/** Recovery reads saved state; no action here sends the original prompt again. */
export default function RunRecovery({ turnId }: { turnId: string }) {
  const [run, setRun] = useState<ChatRun | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void fetchChatRun(turnId, controller.signal).then(setRun).catch((e: Error) => {
      if (!controller.signal.aborted) setError(e.message);
    }).finally(() => {
      if (!controller.signal.aborted) setBusy(false);
    });
    return () => controller.abort();
  }, [turnId]);

  const inspect = async (action?: 'reconcile' | 'cancel-queued') => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      if (action && run?.tracking === 'persisted' && run.version) {
        setRun(await updateChatRun(turnId, action, run.version));
      } else {
        setRun(await fetchChatRun(turnId));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '任务状态暂不可读取');
      // Refresh stale revisions, but never retry a mutation automatically.
      try { setRun(await fetchChatRun(turnId)); } catch { /* keep last known state */ }
    } finally {
      setBusy(false);
    }
  };

  return <section className="card" style={{ padding: '16px', marginBlock: '12px' }} aria-label="任务恢复" aria-busy={busy}>
    <p role="status">任务状态：{run ? labels[run.state] : '尚未读取'}</p>
    <p>这里显示上次保存的状态。接回结果不会重新执行任务。</p>
    {run?.state === 'running' && <p>若服务曾重启或长时间没有进展，可核验执行状态；无法确认的远端结果会标记为未知。</p>}
    {run?.state === 'queued' && <p>取消排队会撤回尚未开始的请求，包括服务重启后遗留的排队记录。</p>}
    {run?.state === 'unknown' && <p>请先检查已有结果及外部操作记录，再决定是否发起新任务。</p>}
    {run?.tracking === 'legacy' && <p>此旧任务只有回放记录，暂不支持状态核验。</p>}
    {error && <p role="alert">{error}</p>}
    <button type="button" disabled={busy} onClick={() => void inspect()}>刷新状态</button>
    {run?.tracking === 'persisted' && run.backend === 'direct_api' && run.state === 'running' &&
      <button type="button" disabled={busy} onClick={() => void inspect('reconcile')}>核验执行状态</button>}
    {run?.tracking === 'persisted' && run.backend === 'direct_api' && run.state === 'queued' &&
      <button type="button" disabled={busy} onClick={() => void inspect('cancel-queued')}>取消排队</button>}
  </section>;
}
