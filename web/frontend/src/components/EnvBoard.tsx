import type { ComponentType } from 'react';
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

const GROUPS: { id: string; title: string; en: string }[] = [
  { id: 'rm', title: '视频产线套件', en: 'Remotion' },
  { id: 'pub', title: '发布链', en: '发布与读回' },
  { id: 'common', title: '常用库', en: '按需' },
];

/** 环境安装页：引擎（install_tool）的真实体检 + 后台安装 + 进度轮询。 */
export default function EnvBoard({ tools, python, loading, error, jobs, anyRunning, onRefresh, onInstall, onInstallMany }: Props) {
  const total = tools.length;
  const okCount = tools.filter((t) => t.state === 'ok').length;
  const allDone = total > 0 && okCount === total;
  const pid = python ? python.split('\\').pop() : '';

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
      <div className="panel-top">
        <span className="pill sum" aria-live="polite">{allDone ? '全就绪' : `就绪 ${okCount} / ${total}`}</span>
        <span className="desc">
          装完自动校验{pid ? ` · 目标解释器 ${pid}` : ''} · 给其他机器＝整个目录拷过去
        </span>
        <span className="spacer" />
        <button className="btn btn-sm" onClick={onRefresh} disabled={loading || anyRunning}>
          {loading ? '检测中…' : '重新检测'}
        </button>
        <button className="btn btn-sm btn-primary" onClick={runAll} disabled={anyRunning || allDone || !total}>
          全部安装
        </button>
      </div>
      <div className="env-meter" role="progressbar" aria-label="环境就绪进度">
        <i style={{ transform: `scaleX(${total ? okCount / total : 0})` }} />
      </div>
      {error ? <div className="env-error">{error}</div> : null}
      {loading && !tools.length ? (
        <div className="board"><div className="empty"><span className="spin" /> 正在体检环境…<span className="hint">（后台繁忙时可能稍慢，会自动重试）</span></div></div>
      ) : null}

      {GROUPS.map((g) => {
        const list = groupTools(g.id);
        if (!list.length) return null;
        const ok = list.filter((t) => t.state === 'ok').length;
        const pending = list.filter((t) => t.state !== 'ok' && installable(t)).length;
        return (
          <div className="grp" key={g.id}>
            <div className="grp-hd">
              <h3>{g.title} <span className="en">{g.en}</span></h3>
              <span className="grp-stat">{ok} / {list.length} 就绪</span>
              <button className="btn btn-sm" onClick={() => runGroup(g.id)} disabled={anyRunning || pending === 0}>
                整组安装
              </button>
            </div>
            <div className="grid">
              {list.map((t) => {
                const v = view(t);
                const Icon = ICONS[t.id] || IconPackage;
                const job = jobs[t.id];
                return (
                  <div className="card" key={t.id} data-tool={t.id} data-state={v.state}>
                    <div className="card-top">
                      <span className="tile"><Icon size={17} /></span>
                      <span className={`badge pill ${v.cls}`}><span className="dot" />{v.badge}</span>
                    </div>
                    <div className="card-name">{t.name}</div>
                    <div className="card-desc">{t.desc}</div>
                    <div className="card-foot">
                      {v.state === 'busy' ? (
                        <>
                          <span className="foot-status busy" title={job?.line || ''}>{job?.line || '启动中…'}</span>
                          <div className="prog">
                            <div className="bar"><i /></div>
                            <span className="spin" />
                          </div>
                          <button className="btn btn-sm" disabled>安装中</button>
                        </>
                      ) : (
                        <>
                          <span
                            className="foot-status"
                            title={v.state === 'fail' ? (job?.detail || t.detail || '') : (t.version || '')}
                          >
                            {v.state === 'ok'
                              ? (t.version || '已就绪')
                              : v.state === 'fail'
                                ? (job?.detail || t.detail || '查看原因')
                                : v.state === 'nodir'
                                  ? '需要指定工程目录'
                                  : ''}
                          </span>
                          {v.state === 'nodir' ? (
                            <button className="btn btn-sm" disabled title="需要 --dir 工程目录（随独立版内置）">需目录</button>
                          ) : v.state === 'fail' ? (
                            <button className="btn btn-sm btn-fill" onClick={() => void onInstall(t.id)} disabled={anyRunning}>重试</button>
                          ) : (
                            <button
                              className={`btn btn-sm ${v.state === 'ok' ? '' : 'btn-fill'}`}
                              onClick={() => void onInstall(t.id)}
                              disabled={anyRunning}
                            >
                              {v.state === 'ok' ? '重装' : '安装'}
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      <div className="foot-note">装到哪：本机用户环境（Python 用户级 · PATH 自动接好）；给其他机器＝把独立版整个目录拷过去，双击即开。</div>
    </section>
  );
}
