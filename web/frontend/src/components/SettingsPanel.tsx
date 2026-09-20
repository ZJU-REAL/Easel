import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import EnvBoard from './EnvBoard';
import type { JobView } from './EnvBoard';
import {
  fetchEnvTools, startEnvInstall, fetchEnvJob,
  fetchModelChannels, runChannelSelftest, saveModelConfig,
} from '../lib/api';
import type { EnvTool, ModelRow, SelftestResult } from '../lib/api';
import { IconSlidersHorizontal, IconPackage, IconEllipsis } from './settingsIcons';

interface Props { onClose: () => void; }

type Sec = 'model' | 'env' | 'more';
type Chan = 'chat' | 'transcribe' | 'speech' | 'image' | 'video' | 'music';

const CHANNELS: { id: Chan; label: string }[] = [
  { id: 'chat', label: '对话与脚本' },
  { id: 'transcribe', label: '语音转写' },
  { id: 'speech', label: '配音' },
  { id: 'image', label: '生图' },
  { id: 'video', label: '视频' },
  { id: 'music', label: '音乐' },
];

/** 后台繁忙（整机高负载）时的抗抖动取数：单次超时即重试，撑过多秒级接口延迟。 */
async function fetchWithRetry<T>(fn: () => Promise<T>, tries = 4, timeoutMs = 18000): Promise<T> {
  let lastErr: unknown = new Error('取数失败');
  for (let i = 0; i < tries; i += 1) {
    try {
      // eslint-disable-next-line no-await-in-loop
      return await new Promise<T>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('请求超时')), timeoutMs);
        fn().then(
          (v) => { clearTimeout(timer); resolve(v); },
          (e) => { clearTimeout(timer); reject(e); },
        );
      });
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr;
}

/** 后端放在 model/baseUrl 里的展示占位串——提交前要清掉，它们不是真实配置值。 */
const PLACEHOLDERS = new Set(['—', '官方', '（未配置）', '本机', '内建默认']);

const hhmm = (ts: number) => {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

/** 设置（统一入口）：竖＝功能分类（模型配置 / 环境安装 / 更多设置），横＝模型六通道。 */
export default function SettingsPanel({ onClose }: Props) {
  const [sec, setSec] = useState<Sec>('model');
  const [chan, setChan] = useState<Chan>('chat');

  // ── 环境安装（引擎真实数据） ──────────────────────────────
  const [tools, setTools] = useState<EnvTool[]>([]);
  const [python, setPython] = useState('');
  const [envLoading, setEnvLoading] = useState(true);
  const [envError, setEnvError] = useState('');
  const [jobs, setJobs] = useState<Record<string, JobView>>({});
  const runningRef = useRef(false);

  const refreshEnv = useCallback(async (force = false) => {
    setEnvLoading(true);
    setEnvError('');
    try {
      const d = await fetchWithRetry(() => fetchEnvTools(force));
      setTools(d.tools || []);
      setPython(d.python || '');
    } catch (e) {
      setEnvError(e instanceof Error ? `环境体检失败：${e.message}` : '环境体检失败');
    } finally {
      setEnvLoading(false);
    }
  }, []);

  useEffect(() => { void refreshEnv(); }, [refreshEnv]);

  const batchMode = useRef(false);

  // 装完统一收尾：刷新体检（期间卡片显示「校验中」），然后清掉成功的 job 记录、保留失败（带原因）
  const settleJobs = useCallback(async () => {
    await refreshEnv(true);
    setJobs((j) => {
      const n: Record<string, JobView> = {};
      Object.entries(j).forEach(([k, v]) => { if (v.state === 'fail') n[k] = v; });
      return n;
    });
  }, [refreshEnv]);

  const pollJob = useCallback((id: string, jobId: string) => new Promise<void>((resolve) => {
    let fails = 0;
    const timer = setInterval(async () => {
      try {
        const st = await fetchEnvJob(jobId);
        const last = (st.lines || [])[st.lines.length - 1] || '';
        setJobs((j) => ({
          ...j,
          [id]: { state: st.state, line: last.trim().slice(0, 140), detail: st.result?.detail || null },
        }));
        if (st.state !== 'running') { clearInterval(timer); resolve(); }
      } catch {
        fails += 1;
        if (fails >= 3) { clearInterval(timer); resolve(); }   // 服务重启/任务丢失：放弃轮询
      }
    }, 1500);
  }), []);

  const installOne = useCallback(async (id: string) => {
    setJobs((j) => ({ ...j, [id]: { state: 'running', line: '启动中…' } }));
    try {
      const { jobId } = await startEnvInstall(id);
      await pollJob(id, jobId);
    } catch (e) {
      setJobs((j) => ({ ...j, [id]: { state: 'fail', line: '', detail: e instanceof Error ? e.message : '启动失败' } }));
    }
    if (!batchMode.current) await settleJobs();   // 单卡装完立即收尾刷新
  }, [pollJob, settleJobs]);

  const installMany = useCallback(async (ids: string[]) => {
    runningRef.current = true;
    batchMode.current = true;
    setJobs((j) => {
      const n = { ...j };
      ids.forEach((id) => { n[id] = { state: 'running', line: '排队中…' }; });
      return n;
    });
    for (const id of ids) {
      // eslint-disable-next-line no-await-in-loop
      await installOne(id);
    }
    batchMode.current = false;
    runningRef.current = false;
    await settleJobs();
  }, [installOne, settleJobs]);

  const anyRunning = runningRef.current || Object.values(jobs).some((j) => j.state === 'running');
  const okCount = tools.filter((t) => t.state === 'ok').length;
  const total = tools.length;

  // ── 模型配置（真值只读 + 真自测） ────────────────────────
  const [chatRows, setChatRows] = useState<ModelRow[]>([]);
  const [transRows, setTransRows] = useState<ModelRow[]>([]);
  const [mediaRows, setMediaRows] = useState<Record<string, ModelRow[]>>({});
  const [modelLoading, setModelLoading] = useState(true);
  const [modelErr, setModelErr] = useState('');
  const [selftest, setSelftest] = useState<{ testedAt: number; byBase: Record<string, SelftestResult> } | null>(null);
  const [testing, setTesting] = useState(false);
  const [selftestNote, setSelftestNote] = useState('');

  useEffect(() => {
    let alive = true;
    fetchWithRetry(() => fetchModelChannels(), 5, 15000)
      .then((d) => {
        if (!alive) return;
        setChatRows(d.channels.chat.rows || []);
        setTransRows(d.channels.transcribe.rows || []);
        setMediaRows({
          image: d.channels.image?.rows || [],
          video: d.channels.video?.rows || [],
          music: d.channels.music?.rows || [],
          speech: d.channels.speech?.rows || [],
        });
        setModelErr('');
      })
      .catch((e) => { if (alive) setModelErr(e instanceof Error ? e.message : '模型配置读取失败'); })
      .finally(() => { if (alive) setModelLoading(false); });
    return () => { alive = false; };
  }, []);

  const doSelftest = useCallback(async (channel: string) => {
    setTesting(true);
    setSelftestNote('');
    try {
      const r = await runChannelSelftest(channel);
      const byBase: Record<string, SelftestResult> = {};
      r.results.forEach((x) => { byBase[x.baseUrl] = x; });
      setSelftest({ testedAt: r.testedAt, byBase });
      if (!r.results.length) setSelftestNote('没有可自测的通道（未配置 key）');
      void refreshEnv();
    } catch (e) {
      setSelftestNote(e instanceof Error ? `自测失败：${e.message}` : '自测失败');
    } finally {
      setTesting(false);
    }
  }, [refreshEnv]);

  // ── 模型配置可编辑（v2）：保存到 .env / openclaw ──────────
  const [saving, setSaving] = useState(false);
  const [savedNote, setSavedNote] = useState('');

  const saveCurrent = useCallback(async () => {
    const rows = chan === 'chat' ? chatRows : chan === 'transcribe' ? transRows : (mediaRows[chan] || []);
    const payload = rows
      .filter((r) => r.slot)
      .map((r) => ({
        slot: r.slot as string,
        name: r.slot === 'custom' ? r.name.trim().toLowerCase() : '',
        // 后端在这些字段里塞的是展示占位（'官方'/'（未配置）'/'本机'/'—'），不是真值：
        // 原样回传会被后端的 Base URL 校验打成 400，导致该行永远保存不了。
        model: PLACEHOLDERS.has(r.model) ? '' : r.model,
        baseUrl: PLACEHOLDERS.has(r.baseUrl) ? '' : r.baseUrl,
        key: r.keyNew || '',
        key2: r.keyNew2 || '',
        primary: r.role === '主',
      }));
    if (!payload.length) {
      setSavedNote('当前通道没有可保存的配置');
      return;
    }
    setSaving(true);
    setSavedNote('');
    try {
      const d = await fetchWithRetry(() => saveModelConfig(chan, payload), 3, 20000);
      setChatRows(d.channels.chat.rows || []);
      setTransRows(d.channels.transcribe.rows || []);
      setMediaRows({
        image: d.channels.image?.rows || [],
        video: d.channels.video?.rows || [],
        music: d.channels.music?.rows || [],
        speech: d.channels.speech?.rows || [],
      });
      setSavedNote(d.note ? `✓ 已保存（${d.note}）` : '✓ 已保存');
      void refreshEnv();
    } catch (e) {
      setSavedNote(e instanceof Error ? `保存失败：${e.message}` : '保存失败');
    } finally {
      setSaving(false);
      setTimeout(() => setSavedNote(''), 6000);
    }
  }, [chan, chatRows, transRows, mediaRows, refreshEnv]);

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // 本地兜底 whisper：从环境工具状态推出来（fw + 模型都在才算就绪）
  const fw = tools.find((t) => t.id === 'fw');
  const modelTool = tools.find((t) => t.id === 'model');
  const localReady = fw?.state === 'ok' && modelTool?.state === 'ok';
  const localRow: ModelRow = {
    order: 2, name: 'local-whisper', sub: '本机兜底 · 免 key', type: 'local',
    model: 'faster-whisper', baseUrl: '本机', keyMasked: '—', role: '备',
    result: localReady ? '✓ 已就绪' : (tools.length ? '未装（去环境安装）' : '检测中…'),
  };

  const resultText = (row: ModelRow): { text: string; cls: string } => {
    const st = row.baseUrl && row.baseUrl !== '—' ? selftest?.byBase[row.baseUrl] : undefined;
    if (st) return st.ok ? { text: `✓ ${st.ms}ms`, cls: 'good' } : { text: `✗ ${(st.detail || '失败').slice(0, 42)}`, cls: 'bad' };
    if (row.result.includes('已就绪') || row.result.includes('已配置')) return { text: row.result, cls: 'good' };
    if (row.result.includes('缺') || row.result.includes('未装')) return { text: row.result, cls: 'warn-text' };
    return { text: row.result, cls: '' };
  };

  const SLOT_EDIT: Record<string, { model: boolean; base: boolean }> = {
    openai: { model: true, base: true },
    relay: { model: true, base: true },
    anthropic: { model: true, base: false },
    siliconflow: { model: false, base: true },
    custom: { model: true, base: true },
  };

  const addProvider = () => {
    setChatRows((rs) => [...rs, {
      slot: 'custom', order: 0, name: '', sub: '自定义', type: 'openai',
      model: '', baseUrl: '', keyMasked: '', role: '备', result: '待保存',
    }]);
  };

  const setPrimaryRow = (i: number) =>
    setChatRows((rs) => rs.map((r, j) => (r.slot ? { ...r, role: j === i ? '主' : '备' } : r)));

  const removeRow = (i: number) =>
    setChatRows((rs) => {
      const gone = rs[i];
      const left = rs.filter((_, j) => j !== i);
      if (gone && gone.role === '主') {
        const first = left.findIndex((r) => r.slot);
        if (first >= 0) left[first] = { ...left[first], role: '主' };
      }
      return left;
    });

  const updateRow = (
    setRows: Dispatch<SetStateAction<ModelRow[]>>,
    i: number,
    patch: Partial<ModelRow>,
  ) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const updateMediaRow = (ch: string, i: number, patch: Partial<ModelRow>) =>
    setMediaRows((m) => ({ ...m, [ch]: (m[ch] || []).map((r, j) => (j === i ? { ...r, ...patch } : r)) }));

  const setMediaPrimary = (ch: string, i: number) =>
    setMediaRows((m) => ({ ...m, [ch]: (m[ch] || []).map((r, j) => ({ ...r, role: j === i ? '主' : '备' })) }));

  const mediaOk = (ch: string) => (mediaRows[ch] || []).some((r) => r.result === '已配置');

  const renderBoard = (
    rows: ModelRow[],
    ops?: { onRow?: (i: number, patch: Partial<ModelRow>) => void; onPrimary?: (i: number) => void; onRemove?: (i: number) => void; media?: boolean },
  ) => (
    modelLoading && rows.length === 0 ? (
      <div className="board"><div className="empty"><span className="spin" /> 正在读取配置…<span className="hint">（后台繁忙时可能稍慢，会自动重试）</span></div></div>
    ) : rows.length === 0 ? (
      <div className="board"><div className="empty">还没有配置。<span className="hint">可在「环境安装」先补齐本地能力。</span></div></div>
    ) : (
      <div className="board">
        <div className="prow head">
          <span>顺序</span><span>供应商</span><span>类型</span><span>模型</span>
          <span>Base URL</span><span>API Key</span><span>角色</span><span>上次结果</span>
          <span />
        </div>
        {rows.map((r, i) => {
          const rt = resultText(r);
          const ed = SLOT_EDIT[r.slot || '']
            || (ops?.media && r.slot
              ? { model: r.modelEditable !== false, base: r.baseEditable !== false }
              : undefined);
          const isCustom = r.slot === 'custom';
          return (
            <div className="prow" key={i}>
              <span className={`step${r.order === 0 ? ' ghost' : ''}`}>{isCustom ? i + 1 : r.order}</span>
              {isCustom ? (
                <span className="pname">
                  <input
                    className="mock"
                    value={r.name}
                    placeholder="名称"
                    onChange={(e) => ops?.onRow?.(i, { name: e.target.value.toLowerCase() })}
                  />
                </span>
              ) : (
                <span className="pname">{r.name}<small>{r.sub}</small></span>
              )}
              <span>{r.type}</span>
              {ed && ed.model && (!ops?.media || r.adv) ? (
                <input className="mock" value={r.model} placeholder={isCustom ? '模型名' : ''} onChange={(e) => ops?.onRow?.(i, { model: e.target.value })} />
              ) : (
                <span className={`cell-text${ops?.media && !r.model ? ' dim' : ''}`} title={r.model || '内建默认'}>
                  {r.model || (ops?.media ? '默认（内建）' : '')}
                </span>
              )}
              {ed && ed.base && (!ops?.media || r.adv) ? (
                <input className="mock" value={r.baseUrl} placeholder="https://…" onChange={(e) => ops?.onRow?.(i, { baseUrl: e.target.value })} />
              ) : (
                <span className={`cell-text${ops?.media && !r.baseUrl ? ' dim' : ''}`} title={r.baseUrl || '内建默认'}>
                  {r.baseUrl
                    || (ops?.media
                      ? r.baseOptional === false
                        ? '需填写（点「高级」）'
                        : '默认（内建）'
                      : '')}
                </span>
              )}
              {ed ? (
                r.key2Label ? (
                  <span className="key-stack">
                    <input
                      className="mock key-input"
                      type="password"
                      value={r.keyNew || ''}
                      placeholder={r.keyMasked || 'Key'}
                      onChange={(e) => ops?.onRow?.(i, { keyNew: e.target.value })}
                    />
                    <input
                      className="mock key-input"
                      type="password"
                      value={r.keyNew2 || ''}
                      placeholder={r.key2Masked || r.key2Label}
                      onChange={(e) => ops?.onRow?.(i, { keyNew2: e.target.value })}
                    />
                  </span>
                ) : (
                  <input
                    className="mock key-input"
                    type="password"
                    value={r.keyNew || ''}
                    placeholder={r.keyMasked || '粘贴 Key'}
                    onChange={(e) => ops?.onRow?.(i, { keyNew: e.target.value })}
                  />
                )
              ) : (
                <span className="cell-text key-mask" title="密钥不显示明文">{r.keyMasked || '—'}</span>
              )}
              {r.slot && ops?.onPrimary ? (
                <button
                  className={`tag ${r.role === '主' ? 'main' : 'backup'}`}
                  onClick={() => ops.onPrimary?.(i)}
                  title="设为主通道"
                >
                  {r.role}
                </button>
              ) : (
                <span className={`tag ${r.role === '主' ? 'main' : 'backup'}`}>{r.role}</span>
              )}
              <span className={`stt ${rt.cls}`}>{rt.text}</span>
              {isCustom && ops?.onRemove ? (
                <button className="row-del" onClick={() => ops.onRemove?.(i)} title="删除该供应商">✕</button>
              ) : ops?.media && r.slot ? (
                <button className="adv-btn" onClick={() => ops?.onRow?.(i, { adv: !r.adv })}>
                  {r.adv ? '收起' : '高级'}
                </button>
              ) : (
                <span />
              )}
            </div>
          );
        })}
      </div>
    )
  );

  const chatOk = chatRows.length > 0 && !chatRows[0].result.includes('缺');
  const transOk = transRows.length > 1 && transRows[1].result.includes('已配置');

  return (
    <div
      className="settings-overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="settings-panel" role="dialog" aria-modal="true" aria-label="设置">
        <div className="settings-head">
          <div>
            <h2 className="settings-title">设置</h2>
            <div className="settings-sub">模型配置 · 环境安装 · 更多设置</div>
          </div>
          <div className="settings-actions">
            <button
              className="btn btn-sm btn-primary"
              onClick={() => void saveCurrent()}
              disabled={saving || sec !== 'model'}
            >
              {saving ? '保存中…' : '保存配置'}
            </button>
            <button
              className="btn btn-sm"
              onClick={() => void doSelftest(sec === 'model' ? chan : 'all')}
              disabled={testing}
            >
              {testing ? '自测中…' : '全部自测'}
            </button>
            <button className="settings-close" onClick={onClose} title="关闭（Esc）">✕</button>
          </div>
        </div>

        <div className="settings-body">
          <nav className="settings-nav">
            <button className={`snav${sec === 'model' ? ' active' : ''}`} onClick={() => setSec('model')}>
              <IconSlidersHorizontal size={16} />模型配置<small>六个通道</small>
            </button>
            <button className={`snav${sec === 'env' ? ' active' : ''}`} onClick={() => setSec('env')}>
              <IconPackage size={16} />环境安装<small>{total ? (okCount === total ? '全就绪' : `${okCount}/${total}`) : '…'}</small>
            </button>
            <button className={`snav${sec === 'more' ? ' active' : ''}`} onClick={() => setSec('more')}>
              <IconEllipsis size={16} />更多设置
            </button>
          </nav>

          <div className="settings-main">
            {sec === 'model' && (
              <section className="st-sec active">
                <div className="tabbar">
                  {CHANNELS.map((c) => (
                    <button key={c.id} className={`tab${chan === c.id ? ' active' : ''}`} onClick={() => setChan(c.id)}>
                      <span className="cdot" />{c.label}
                    </button>
                  ))}
                </div>
                {savedNote ? <div className={`save-note${savedNote.startsWith('保存失败') || savedNote.startsWith('没有') ? ' err' : ''}`}>{savedNote}</div> : null}

                {chan === 'chat' && (
                  <section className="st-panel active">
                    <div className="panel-top">
                      <span className={`pill ${chatOk ? 'ok' : 'off'}`}><span className="dot" />{chatOk ? '主通道在线' : '未配置'}</span>
                      <span className="desc">经本地网关路由（主备自动降级）</span>
                      {selftest && <span className="desc">上次自测 {hhmm(selftest.testedAt)}</span>}
                      <span className="spacer" />
                      <button className="btn btn-sm" onClick={() => void doSelftest('chat')} disabled={testing}>自测本通道</button>
                    </div>
                    {renderBoard(chatRows, { onRow: (i, p) => updateRow(setChatRows, i, p), onPrimary: setPrimaryRow, onRemove: removeRow })}
                    <div className="add-row" onClick={addProvider}>＋ 添加供应商（填名称 / 模型 / Base URL / Key；点「设为主」切换生效通道）</div>
                    <div className="foot-note">改完点右上角「保存配置」（key 留空=不改）；自动降级链随统一网关接入开放。</div>
                  </section>
                )}

                {chan === 'transcribe' && (
                  <section className="st-panel active">
                    <div className="panel-top">
                      <span className={`pill ${transOk ? 'ok' : 'warn'}`}><span className="dot" />{transOk ? '主通道在线' : (localReady ? '本地兜底生效' : '备用待安装')}</span>
                      <span className="desc">三级链：自带字幕 → API → 本地兜底</span>
                      <span className="spacer" />
                      <button className="btn btn-sm" onClick={() => void doSelftest('transcribe')} disabled={testing}>自测本通道</button>
                    </div>
                    {renderBoard([...transRows, localRow], { onRow: (i, p) => updateRow(setTransRows, i, p) })}
                    <div className="foot-note">有字幕不下模型；API 通道缺 key 自动落到本地 whisper（本地组件在「环境安装」页装）。保存即写入 .env 生效。</div>
                  </section>
                )}

                {chan === 'speech' && (
                  <section className="st-panel active">
                    <div className="panel-top">
                      <span className={`pill ${mediaOk('speech') ? 'ok' : 'off'}`}><span className="dot" />{mediaOk('speech') ? '有可用提供商' : '未配置'}</span>
                      <span className="desc">只填 Key 即用（地址/模型内建）；「主/备」= 默认</span>
                      <span className="spacer" />
                    </div>
                    {renderBoard(mediaRows.speech || [], { onRow: (i, p) => updateMediaRow('speech', i, p), onPrimary: (i) => setMediaPrimary('speech', i), media: true })}
                    <div className="foot-note">配音脚本按「主」provider 合成；本地 VoxCPM / edge-tts 在视频产线里可直接替代。</div>
                  </section>
                )}

                {chan === 'image' && (
                  <section className="st-panel active">
                    <div className="panel-top">
                      <span className={`pill ${mediaOk('image') ? 'ok' : 'off'}`}><span className="dot" />{mediaOk('image') ? '已配置' : '未配置'}</span>
                      <span className="desc">只填 Key 即用（地址/模型内建，点「高级」可覆盖）</span>
                      <span className="spacer" />
                    </div>
                    {renderBoard(mediaRows.image || [], { onRow: (i, p) => updateMediaRow('image', i, p), media: true })}
                    <div className="foot-note">按 Base URL 自动选同步 / 异步（apimart）模式；模型名留空用服务端默认。</div>
                  </section>
                )}

                {chan === 'video' && (
                  <section className="st-panel active">
                    <div className="panel-top">
                      <span className={`pill ${mediaOk('video') ? 'ok' : 'off'}`}><span className="dot" />{mediaOk('video') ? '有可用提供商' : '未配置'}</span>
                      <span className="desc">只填 Key 即用（地址/模型内建，点「高级」可覆盖）；「主/备」= 默认</span>
                      <span className="spacer" />
                    </div>
                    {renderBoard(mediaRows.video || [], { onRow: (i, p) => updateMediaRow('video', i, p), onPrimary: (i) => setMediaPrimary('video', i), media: true })}
                    <div className="foot-note">脚本按「主」provider 出片；同类多家的自动降级随统一网关接入开放。</div>
                  </section>
                )}

                {chan === 'music' && (
                  <section className="st-panel active">
                    <div className="panel-top">
                      <span className={`pill ${mediaOk('music') ? 'ok' : 'off'}`}><span className="dot" />{mediaOk('music') ? '有可用提供商' : '未配置'}</span>
                      <span className="desc">只填 Key 即用；「主/备」= 默认</span>
                      <span className="spacer" />
                    </div>
                    {renderBoard(mediaRows.music || [], { onRow: (i, p) => updateMediaRow('music', i, p), onPrimary: (i) => setMediaPrimary('music', i), media: true })}
                  </section>
                )}

                {modelErr && <div className="env-error">{modelErr}</div>}
                {selftestNote && <div className="foot-note">{selftestNote}</div>}
              </section>
            )}

            {sec === 'env' && (
              <section className="st-sec active">
                <EnvBoard
                  tools={tools}
                  python={python}
                  loading={envLoading}
                  error={envError}
                  jobs={jobs}
                  anyRunning={anyRunning}
                  onRefresh={() => void refreshEnv(true)}
                  onInstall={installOne}
                  onInstallMany={installMany}
                />
              </section>
            )}

            {sec === 'more' && (
              <section className="st-sec active">
                <div className="panel-top">
                  <span className="pill off"><span className="dot" />可扩展位</span>
                  <span className="desc">同一个面板，以后放更多设置</span>
                </div>
                <div className="board">
                  <div className="stub-row"><span className="tag2">预留</span>网关参数（端口 / 绑定 / 会话）<span className="future">就挂在这页旁边</span></div>
                  <div className="stub-row"><span className="tag2">预留</span>通用设置（语言 / 更新 / 数据目录）<span className="future">按需加</span></div>
                </div>
                <div className="foot-note">扩展方式：在这个面板里加标签即可——模型、环境已各就位，其余按需加。</div>
              </section>
            )}
          </div>
        </div>

        <div className="settings-foot">
          ⓘ 环境安装在后台执行，装完自动回写状态；模型配置保存写入 .env（对话经本地网关路由，主备自动降级）。
        </div>
      </div>
    </div>
  );
}
