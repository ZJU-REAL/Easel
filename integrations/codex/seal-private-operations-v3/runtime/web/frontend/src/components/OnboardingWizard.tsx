import { useState, useEffect } from 'react';
import { buildProfile, profileBuildStatus } from '../lib/api';

const PLATFORMS = ['小红书', '抖音', 'B站', '视频号', '公众号', '微博', '知乎'];
const TONES = ['专业严谨', '轻松幽默', '亲切日常', '犀利吐槽', '治愈温暖', '干货实用'];

interface OnboardingWizardProps {
  onClose: () => void;
  onCreated: (name: string) => void;
}

interface FormState {
  name: string;
  platforms: string[];
  accountStage: string;
  links: Record<string, string>;
  direction: string;
  reason: string;
  goal: string;
  formats: string;
  likes: string;
  tone: string;
  avoid: string;
}

const EMPTY: FormState = {
  name: '', platforms: [], accountStage: '全新起号', links: {},
  direction: '', reason: '', goal: '', formats: '', likes: '', tone: '', avoid: '',
};

const STEPS = ['基础信息', '社媒链接', '运营意图', '偏好与红线'];

export default function OnboardingWizard({ onClose, onCreated }: OnboardingWizardProps) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState<'form' | 'enhancing'>('form');
  const [error, setError] = useState('');

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const togglePlatform = (p: string) =>
    setForm((f) => ({
      ...f,
      platforms: f.platforms.includes(p)
        ? f.platforms.filter((x) => x !== p)
        : [...f.platforms, p],
    }));

  const canNext =
    (step === 0 && form.name.trim() !== '') ||
    (step === 2 && form.direction.trim() !== '') ||
    step === 1 || step === 3;

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      // 后端异步：立即返回（基线已写、画像可用），不再长阻塞被代理超时掐断
      const res = await buildProfile(form.name.trim(), form as unknown as Record<string, unknown>);
      if (res.created) {
        setSubmitting(false);
        setPhase('enhancing'); // 进入后台增强等待（可跳过）
      } else {
        setError('画像创建失败，请重试');
        setSubmitting(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败');
      setSubmitting(false);
    }
  };

  // 增强阶段：轮询后台 AI 增强进度；完成/失败即进入画像（基线已可用）
  useEffect(() => {
    if (phase !== 'enhancing') return;
    let alive = true;
    const name = form.name.trim();
    const tick = async () => {
      try {
        const st = await profileBuildStatus(name);
        if (!alive) return;
        if (st.state === 'done' || st.state === 'failed' || st.state === 'unknown') {
          onCreated(name);
          return;
        }
      } catch {
        /* 轮询失败忽略，继续 */
      }
      if (alive) setTimeout(tick, 5000);
    };
    const t = setTimeout(tick, 4000);
    return () => { alive = false; clearTimeout(t); };
  }, [phase]); // eslint-disable-line react-hooks/exhaustive-deps

  const box: React.CSSProperties = {
    width: '100%', padding: '10px 12px', marginTop: 6, borderRadius: 'var(--radius)',
    border: '1px solid var(--border)', background: 'var(--bg-elev)', color: 'var(--text)',
    fontSize: 14, fontFamily: 'inherit',
  };
  const label: React.CSSProperties = { display: 'block', marginTop: 16, fontSize: 13, color: 'var(--text-secondary)' };

  const chip = (active: boolean): React.CSSProperties => ({
    padding: '6px 13px', borderRadius: 999, fontSize: 13, cursor: 'pointer',
    border: '1px solid var(--border)',
    background: active ? 'var(--accent-gradient)' : 'var(--bg-elev)',
    color: active ? '#fff' : 'var(--text)',
  });

  return (
    <div className="overlay">
      <div className="modal" style={{ width: 560, maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto' }}>
        {/* 头部 + 进度 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>配置账号画像</h2>
          <button onClick={onClose} disabled={submitting}
            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', fontSize: 22, cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ display: 'flex', gap: 6, margin: '16px 0 4px' }}>
          {STEPS.map((s, i) => (
            <div key={s} style={{ flex: 1 }}>
              <div style={{ height: 4, borderRadius: 2, background: i <= step ? 'var(--accent-start)' : 'var(--border)' }} />
              <div style={{ fontSize: 11, color: i === step ? 'var(--text)' : 'var(--text-secondary)', marginTop: 4 }}>{s}</div>
            </div>
          ))}
        </div>

        {submitting ? (
          <div style={{ padding: '48px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div className="spinner" style={{ margin: '0 auto 16px' }} />
            正在创建画像基线…
          </div>
        ) : phase === 'enhancing' ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div className="spinner" style={{ margin: '0 auto 16px' }} />
            <div style={{ color: 'var(--text)', fontSize: 15, marginBottom: 6 }}>画像已创建 ✓　AI 正在后台增强…</div>
            <span style={{ fontSize: 12 }}>
              正在尝试抓取社媒链接并完善各维度，可能需要 1-2 分钟。<br />
              也可以现在就进去用，增强会在后台继续。
            </span>
            <div style={{ marginTop: 20 }}>
              <button className="btn btn-primary" onClick={() => onCreated(form.name.trim())}>先进去用</button>
            </div>
          </div>
        ) : (
          <div style={{ minHeight: 240 }}>
            {step === 0 && (
              <>
                <label style={label}>画像名 *（一个人设 = 一个画像，可跨多平台）</label>
                <input style={box} value={form.name} placeholder="如：科技数码达人"
                  onChange={(e) => set('name', e.target.value)} />
                <label style={label}>运营平台（可多选）</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
                  {PLATFORMS.map((p) => (
                    <button key={p} onClick={() => togglePlatform(p)} style={chip(form.platforms.includes(p))}>{p}</button>
                  ))}
                </div>
                <label style={label}>起号状态</label>
                <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                  {['全新起号', '已有账号'].map((s) => (
                    <button key={s} onClick={() => set('accountStage', s)} style={chip(form.accountStage === s)}>{s}</button>
                  ))}
                </div>
              </>
            )}

            {step === 1 && (
              <>
                <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 12 }}>
                  贴上各平台主页链接，AI 会尽力分析你已发的内容和风格（抓不到会跳过，可留空）。
                </p>
                {form.platforms.length === 0 && (
                  <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>（未选平台，可直接下一步）</p>
                )}
                {form.platforms.map((p) => (
                  <div key={p}>
                    <label style={label}>{p} 主页链接</label>
                    <input style={box} value={form.links[p] || ''} placeholder={`https://…`}
                      onChange={(e) => set('links', { ...form.links, [p]: e.target.value })} />
                  </div>
                ))}
              </>
            )}

            {step === 2 && (
              <>
                <label style={label}>想做什么方向的内容 *（越具体越好）</label>
                <input style={box} value={form.direction} placeholder="如：平价护肤测评"
                  onChange={(e) => set('direction', e.target.value)} />
                <label style={label}>为什么做这个 / 你的优势·独特经历</label>
                <textarea style={{ ...box, minHeight: 60, resize: 'vertical' }} value={form.reason}
                  onChange={(e) => set('reason', e.target.value)} />
                <label style={label}>运营目标</label>
                <input style={box} value={form.goal} placeholder="涨粉 / 变现 / 个人品牌 / 引流私域"
                  onChange={(e) => set('goal', e.target.value)} />
                <label style={label}>想产出的形式</label>
                <input style={box} value={form.formats} placeholder="图文 / 短视频 / 中长视频 / 长文"
                  onChange={(e) => set('formats', e.target.value)} />
              </>
            )}

            {step === 3 && (
              <>
                <label style={label}>喜欢看的内容 / 对标账号</label>
                <textarea style={{ ...box, minHeight: 60, resize: 'vertical' }} value={form.likes}
                  onChange={(e) => set('likes', e.target.value)} />
                <label style={label}>期望调性</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
                  {TONES.map((t) => (
                    <button key={t} onClick={() => set('tone', form.tone === t ? '' : t)} style={chip(form.tone === t)}>{t}</button>
                  ))}
                </div>
                <label style={label}>不做的内容 / 合规红线</label>
                <textarea style={{ ...box, minHeight: 60, resize: 'vertical' }} value={form.avoid}
                  placeholder="如：不接医疗功效、不做虚假宣传"
                  onChange={(e) => set('avoid', e.target.value)} />
              </>
            )}

            {error && <div style={{ color: 'var(--red)', fontSize: 13, marginTop: 12 }}>{error}</div>}
          </div>
        )}

        {/* 底部按钮 */}
        {phase === 'form' && !submitting && (
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20 }}>
            <button className="btn" onClick={() => (step === 0 ? onClose() : setStep(step - 1))}>
              {step === 0 ? '取消' : '上一步'}
            </button>
            {step < STEPS.length - 1 ? (
              <button className="btn btn-primary" onClick={() => canNext && setStep(step + 1)} disabled={!canNext}>
                下一步
              </button>
            ) : (
              <button className="btn btn-primary" onClick={submit} disabled={!form.name.trim() || !form.direction.trim()}>
                生成画像
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
