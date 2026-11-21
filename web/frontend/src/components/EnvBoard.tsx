import '../styles/environment.css';
import { statusText } from '../lib/statusText';
import { useState, type ComponentType } from 'react';
import RemotionProject from './RemotionProject';
import type { EnvTool } from '../lib/api';
import {
  IconHexagon, IconFilm, IconFileCode, IconAudioWaveform, IconDatabase,
  IconPackage, IconMonitor, IconTv, IconGlobe, IconCompass, IconLibrary,
} from './settingsIcons';

export interface JobView {
  state: 'running' | 'ok' | 'fail';
  line: string;
  detail?: string | null;
}

interface Props {
  tools: EnvTool[];
  python: string;
  loading: boolean;
  error: string;
  jobs: Record<string, JobView>;
  anyRunning: boolean;
  onRefresh: () => void;
  onInstall: (id: string) => Promise<void>;
  onInstallMany: (ids: string[]) => Promise<void>;
}

const ICONS: Record<string, ComponentType<{ size?: number }>> = {
  node: IconHexagon, ffmpeg: IconFilm, python: IconFileCode, fw: IconAudioWaveform,
  model: IconDatabase, rmdeps: IconPackage, shell: IconMonitor, biliup: IconTv,
  pw: IconGlobe, cft: IconCompass, pylibs: IconLibrary,
};

const GROUPS: { id: string; title: string }[] = [
  { id: 'rm', title: '视频制作' },
  { id: 'pub', title: '平台发布' },
  { id: 'common', title: '基础工具' },
];

/** 环境安装页：引擎（install_tool）的真实体检 + 后台安装 + 进度轮询。 */
export default function EnvBoard({ tools, python, loading, error, jobs, anyRunning, onRefresh, onInstall, onInstallMany }: Props) {
  const total = tools.length;
  const okCount = tools.filter((t) => t.state === 'ok').length;
  const allDone = total > 0 && okCount === total;
  const [showReady, setShowReady] = useState(false);
  const [revision, setRevision] = useState(0);
  const refresh = () => { setRevision(v => v + 1); onRefresh(); };

  const groupTools = (gid: string) => tools.filter((t) => t.group === gid);
  const installable = (t: EnvTool) => t.state !== 'no_dir';

  const runAll = () => {
    const ids = tools.filter((t) => t.state !== 'ok' && installable(t)).map((t) => t.id);
    if (ids.length) void onInstallMany(ids);
  };
  const runGroup = (gid: string) => {
    const ids = groupTools(gid).filter((t) => t.state !== 'ok' && installable(t)).map((t) => t.id);
    if (ids.length) void onInstallMany(ids);
  };

  const view = (t: EnvTool): { state: 'ok' | 'missing' | 'busy' | 'fail' | 'nodir'; badge: string; cls: string } => {
    const job = jobs[t.id];
    if (job?.state === 'running') return { state: 'busy', badge: '安装中', cls: 'warn' };
    if (t.state === 'ok') return { state: 'ok', badge: '已装', cls: 'ok' };
    // 刚装完、面板还在重新体检的过渡窗口：显示「校验中」，别闪回「未装」
    if (job?.state === 'ok') return { state: 'busy', badge: '校验中', cls: 'warn' };
    if (job?.state === 'fail') return { state: 'fail', badge: '失败', cls: 'fail' };
    if (t.state === 'no_dir') return { state: 'nodir', badge: '需目录', cls: 'warn' };
    if (t.state === 'fail') return { state: 'fail', badge: '异常', cls: 'fail' };
    return { state: 'missing', badge: '未装', cls: 'off' };
  };

  return (
    <section className="st-env">
      <div className="studio-intro env-intro"><div><h3>运行环境</h3>
        <p>{loading ? '正在检测本机工具…' : total ? total + ' 项工具 · ' + okCount + ' 项就绪' : '工具检测'}</p></div>
        <div className="env-actions"><button className="studio-button" onClick={refresh} disabled={loading || anyRunning}>重新检测</button>
        <button className="studio-primary" onClick={runAll} disabled={anyRunning || allDone || !total}>安装缺失项</button></div>
      </div>
      <RemotionProject revision={revision} onChange={onRefresh} />
      <div className="env-filters"><label><input type="checkbox" checked={showReady} onChange={e => setShowReady(e.target.checked)} />显示已就绪工具</label>
        {python && <details><summary>检测解释器</summary><code>{python}</code></details>}</div>
      {error ? <div className="env-error">{error}</div> : null}
      {loading && !tools.length ? (
        <div className="board"><div className="empty"><span className="spin" /> 正在体检环境…<span className="hint">（后台繁忙时可能稍慢，会自动重试）</span></div></div>
      ) : null}

      {GROUPS.map((g) => {
        const list = groupTools(g.id);
        if (!list.length) return null;
        const ok = list.filter((t) => t.state === 'ok').length;
        const pending = list.filter((t) => t.state !== 'ok' && installable(t)).length;
        const visible = list.filter(t => showReady || view(t).state !== 'ok');
        if (!visible.length) return null;
        return (
          <div className="grp" key={g.id}>
            <div className="grp-hd">
              <h3>{g.title}</h3>
              <span className="grp-stat">{ok} / {list.length} 就绪</span>
              <button className="btn btn-sm" onClick={() => runGroup(g.id)} disabled={anyRunning || pending === 0}>
                安装本组缺失项
              </button>
            </div>
            <div className="env-list">
              {visible.map((t) => {
                const v = view(t);
                const Icon = ICONS[t.id] || IconPackage;
                const job = jobs[t.id];
                const detail = job?.detail || t.detail;
                return <div className="env-row" key={t.id} data-tool={t.id}>
                  <span className="env-icon"><Icon size={17}/></span>
                  <div className="env-name"><strong>{t.name}</strong>
                    <small>{v.state === 'busy' ? statusText(job?.line || '') || '正在校验…' : t.desc}</small>
                    {(detail || t.location) && <details><summary>检测详情</summary>
                      {t.location && <code>{t.location}</code>}{detail && <p>{statusText(detail)}</p>}</details>}
                  </div>
                  <span className={'env-state ' + v.cls}>{v.state === 'ok' ? t.version || '就绪' : v.badge}</span>
                  {v.state !== 'ok' && <button className="studio-button" disabled={anyRunning || !installable(t) || v.state === 'busy'}
                    onClick={() => void onInstall(t.id)}>{v.state === 'fail' ? '修复' : '安装'}</button>}
                </div>;
              })}
            </div>
          </div>
        );
      })}


    </section>
  );
}
