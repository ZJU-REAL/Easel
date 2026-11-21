import '../styles/studio.css';
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { IconChevron, IconLayers } from './icons';
import { getAccess, saveAccess, type Access } from '../lib/access';

const hints: Record<string, string> = {
  easel: '控制从画板界面发起的工具操作。聊天中的工具由对应 Agent 管理。',
  api: '此模式仅调用模型，支持文字和附件分析。',
  openclaw: '新任务启动前，画板会让网关确认所选会话权限。实际执行仍受网关策略约束。',
  codex: '访问范围与审批方式分别生效。设置从下一次任务开始使用。',
};
const acpHint = '此策略处理 Agent 通过 ACP 提交的授权请求。原生进程自行执行的工具由该 Agent 管理。';

export default function AccessControls({ compact = false, onEngine, session, current }: {
  compact?: boolean; onEngine?: (runtime: string) => void; session?: string; current?: string;
}) {
  const radioId = useId();
  const [target, setTarget] = useState('');
  const [value, setValue] = useState<Access | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  useEffect(() => {
    let live = true;
    setValue(null); setError('');
    const reload = () => {
      const id = ++generation.current;
      void getAccess(target, session).then(result => {
        if (live && id === generation.current) setValue(result);
      }).catch(e => { if (live && id === generation.current) setError(e.message); });
    };
    reload();
    window.addEventListener('easel-access', reload);
    return () => { live = false; window.removeEventListener('easel-access', reload); };
  }, [target, session, current]);
  async function change(scope: string, approval: string) {
    if (!value || busy) return;
    const id = generation.current;
    setBusy(true); setError('');
    try {
      const result = await saveAccess(scope, approval, value);
      if (generation.current === id) setValue(result);
      window.dispatchEvent(new Event('easel-access'));
    } catch (e) {
      if (generation.current === id) setError((e as Error).message);
      window.dispatchEvent(new Event('easel-access'));
    } finally { setBusy(false); }
  }
  if (!value) return <small role="status">{error || '读取权限…'}</small>;
  const { scopes, approvals, runtime, targets, localFull } = value;
  const engine = targets[runtime];
  const groups = [
    { id: 'scope', name: runtime === 'openclaw' ? '会话权限' : '访问范围', options: scopes, active: value.scope,
      pick: (id: string) => void change(id, value.approval) },
    { id: 'approval', name: '审批方式', options: approvals, active: value.approval,
      pick: (id: string) => void change(value.scope, id) },
  ].filter(group => group.options.length > 1);
  const fields = <div className="access-fields">{groups.map(g => <fieldset key={g.id} disabled={busy || (runtime === 'easel' && g.id === 'approval' && value.scope === 'read-only')}><legend>{g.name}</legend>
      <div className="access-options">{g.options.map(([id, name, note]) => <label key={id}>
        <input type="radio" name={radioId + '-' + g.id} value={id} checked={id === g.active}
          disabled={id === 'full' && !localFull} onChange={() => g.pick(id)} />
        <span><strong>{name}</strong><small>{id === 'full' && !localFull ? '使用 easel web --local 启动后可选。' : note}</small></span>
      </label>)}</div></fieldset>)}</div>;
  if (compact) {
    const summary = groups.map(g => g.options.find(([id]) => id === g.active)?.[1]).filter(Boolean).join(' · ');
    return <ComposerAccess engine={engine} summary={summary} onEngine={() => onEngine?.(runtime)} error={error}>
      {fields}
      <p className="permission-footnote" role="status">{busy ? '正在保存…' : '设置自动保存，应用于该引擎的新任务。'}</p>
    </ComposerAccess>;
  }
  return <section className="studio-access">
    <div className="studio-intro access-title"><div><h3>访问权限</h3><p>{hints[runtime] || acpHint}</p></div>
      <label className="access-target">权限对象<select aria-label="权限对象" value={runtime} disabled={busy}
        onChange={e => setTarget(e.target.value)}>{Object.entries(targets).map(([id, label]) =>
          <option value={id} key={id}>{label}</option>)}</select></label>
    </div>
    {fields}
    {runtime === 'api' && <div className="access-static"><strong>仅对话</strong><p>文件读写、运行命令和平台发布均不可用。</p></div>}
    {groups.length > 0 && <p className="studio-note" role="status">{error || (busy ? '保存中…' :
      value.scope === 'full' ? '已选择完整访问。新任务按该引擎的本机权限运行。' : '选择后自动保存，仅应用于此对象。')}</p>}
  </section>;
}

function ComposerAccess({ engine, summary, children, error, onEngine }: {
  engine: string; summary: string; children: ReactNode; error: string; onEngine?: () => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  // Keep the native popover in view for both the welcome composer and the bottom composer.
  useLayoutEffect(() => {
    if (!open || !panel.current || !trigger.current) return;
    const place = () => {
      const box = trigger.current!.getBoundingClientRect();
      const elem = panel.current!;
      const gap = 8;
      const margin = 12;
      const below = window.innerHeight - box.bottom - margin - gap;
      const above = box.top - margin - gap;
      const down = below >= Math.min(elem.scrollHeight, 380) || below > above;
      elem.style.left = Math.max(margin, Math.min(box.left, window.innerWidth - elem.offsetWidth - margin)) + 'px';
      elem.style.top = down ? box.bottom + gap + 'px' : 'auto';
      elem.style.bottom = down ? 'auto' : window.innerHeight - box.top + gap + 'px';
      elem.style.maxHeight = Math.max(0, down ? below : above) + 'px';
    };
    place();
    const observer = new ResizeObserver(place);
    observer.observe(trigger.current);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open]);

  return <div className="access-inline composer-tools">
    <button className="tool-engine" type="button" onClick={onEngine} title="设置执行引擎">
      <IconLayers size={14} /><span>{engine}</span><IconChevron size={11} />
    </button>
    {summary && <>
      <span className="tool-separator" aria-hidden="true" />
      <button className="tool-permissions" type="button" ref={trigger} popoverTarget={id} aria-expanded={open}
        aria-haspopup="dialog" aria-label={'访问权限，' + summary} title={'访问权限 · ' + summary}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="M12 3 4.5 6v5.7c0 4.1 3 7.9 7.5 9.3 4.5-1.4 7.5-5.2 7.5-9.3V6Z"/><path d="m8.7 12.1 2.1 2.1 4.5-4.6"/></svg>
        <span>{summary}</span><IconChevron size={11} />
      </button>
      <div id={id} ref={panel} popover="auto" role="dialog" aria-label={engine + ' 访问权限'}
        className="permission-popover" onToggle={event => setOpen(event.currentTarget.matches(':popover-open'))}>
        <div className="permission-head"><h3>访问权限</h3><span>{engine}</span>
          <button type="button" popoverTarget={id} popoverTargetAction="hide" aria-label="关闭权限面板">×</button>
        </div>
        {open && children}
        {error && <p role="alert">{error}</p>}
      </div>
    </>}
    {error && !open && <span role="alert">{error}</span>}
  </div>;
}
