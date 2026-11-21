import { useEffect, useRef, useState } from 'react';
import { fetchChatRun, updateChatRun, type ChatRun } from '../lib/api';

const labels: Record<ChatRun['state'], string> = {
  queued: '等待执行', running: '上次记录为执行中', succeeded: '已完成',
  failed: '执行失败', cancelled: '已取消', interrupted: '已中断', unknown: '结果未知',
};

type RecoveryState = { turnId: string; run: ChatRun | null; busy: boolean; error: string };

/** Recovery reads saved state; no action here sends the original prompt again. */
export default function RunRecovery({ turnId }: { turnId: string }) {
  const [snapshot, setSnapshot] = useState<RecoveryState>({ turnId, run: null, busy: true, error: '' });
  const generation = useRef(0);
  const { run, busy, error } = snapshot.turnId === turnId
    ? snapshot : { run: null, busy: true, error: '' };

  useEffect(() => {
    const epoch = ++generation.current;
    const controller = new AbortController();
    void fetchChatRun(turnId, controller.signal).then(value => {
      if (generation.current === epoch && !controller.signal.aborted) {
        setSnapshot({ turnId, run: value, busy: false, error: '' });
      }
    }).catch((e: Error) => {
      if (generation.current === epoch && !controller.signal.aborted) {
        setSnapshot({ turnId, run: null, busy: false, error: e.message });
      }
    });
    return () => { ++generation.current; controller.abort(); };
  }, [turnId]);

  const inspect = async (action?: 'reconcile' | 'cancel-queued') => {
    if (busy) return;
    const epoch = generation.current;
    const current = () => generation.current === epoch;
    setSnapshot({ turnId, run, busy: true, error: '' });
    try {
      const value = action && run?.tracking === 'persisted' && run.version
        ? await updateChatRun(turnId, action, run.version)
        : await fetchChatRun(turnId);
      if (current()) setSnapshot({ turnId, run: value, busy: false, error: '' });
    } catch (e) {
      if (!current()) return;
      const message = e instanceof Error ? e.message : '任务状态暂不可读取';
      let value = run;
      // Refresh stale revisions, but never retry a mutation automatically.
      try { value = await fetchChatRun(turnId); } catch { /* keep last known state */ }
      if (current()) setSnapshot({ turnId, run: value, busy: false, error: message });
    }
  };

  return <section className="studio-recovery" aria-label="任务恢复" aria-busy={busy}>
    <div className="recovery-line"><span aria-hidden="true" className="recovery-dot" />
      <strong role="status">{run ? labels[run.state] : '正在读取任务记录'}</strong>
      <button type="button" disabled={busy} onClick={() => void inspect()}>刷新状态</button>
    {run?.tracking === 'persisted' && run.state === 'running' &&
      <button type="button" disabled={busy} onClick={() => void inspect('reconcile')}>核验执行状态</button>}
    {run?.tracking === 'persisted' && run.state === 'queued' &&
      <button type="button" disabled={busy} onClick={() => void inspect('cancel-queued')}>取消排队</button>}
    </div>
    {run && <details><summary>任务记录说明</summary><p>{run.tracking === 'legacy' ? '旧任务仅保存了回放记录。' :
      run.state === 'running' ? '核验本地执行锁后更新状态。远端工具可能仍在运行，请先检查已有结果。' :
      run.state === 'queued' ? '任务仍在队列中，可以撤回。' : '此处显示上次保存的执行结果。'}</p></details>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
