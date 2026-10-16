import { useState, useEffect } from 'react';
import { fetchPersonas, fetchPersonaFiles, savePersonaFile, deletePersona, fetchAccountAnalytics } from '../lib/api';
import type { PersonaItem, PersonaFile, AccountAnalytics } from '../lib/api';
import { renderMarkdown } from '../lib/sanitize';
import { IconProfile, IconPlus } from './icons';

// 粉丝量级：把粉丝数映射成人话档位（画像里“粉丝量级”一栏要的是量级而非精确值）
function fanTier(n: number): string {
  if (n <= 0) return '新号 / 0';
  if (n < 500) return '冷启动 <500';
  if (n < 1000) return '数百';
  if (n < 5000) return '千级';
  if (n < 10000) return '数千';
  if (n < 100000) return '万级';
  if (n < 1000000) return '十万级';
  return '百万+';
}

// 用注释围栏包住自动抓取段，重复抓取只替换该段、不动用户手写内容（幂等）
const WX_START = '<!-- wechat-oa:auto:start -->';
const WX_END = '<!-- wechat-oa:auto:end -->';

function buildWechatBlock(a: AccountAnalytics): string {
  const fans = a.followers ?? 0;
  const posts = a.posts ?? 0;
  const reads = a.likes ?? 0;
  const tops = [...new Set(a.notes.map((n) => n.title).filter(Boolean))].slice(0, 3);
  const stamp = new Date().toLocaleString('zh-CN', { hour12: false });
  const lines = [
    `### 微信公众号（自动抓取 · ${stamp}）`,
    '',
    `- **粉丝量级**：${fans}（${fanTier(fans)}）`,
    `- **内容形式**：图文推文（公众号文章）；已发表 ${posts} 篇${reads ? `，累计阅读 ${reads}` : ''}`,
  ];
  if (a.metrics?.length) {
    lines.push(`- **后台数据**：${a.metrics.map((m) => `${m.label} ${m.value}`).join(' · ')}`);
  }
  if (tops.length) lines.push(`- **代表内容**：${tops.join('｜')}`);
  return lines.join('\n');
}

function mergeWechatBlock(existing: string, block: string): string {
  const wrapped = `${WX_START}\n${block}\n${WX_END}`;
  const s = existing.indexOf(WX_START);
  const e = existing.indexOf(WX_END);
  if (s !== -1 && e !== -1 && e > s) {
    return existing.slice(0, s) + wrapped + existing.slice(e + WX_END.length);
  }
  const head = existing.replace(/\s+$/, '');
  return head ? `${head}\n\n${wrapped}` : wrapped;
}

interface ProfilePageProps {
  persona: string;
  onUsePersona: (name: string) => void;
  onNewProfile: () => void;
  onDeleted: (name: string) => void;
}

const DIM_META: Record<string, { label: string; icon: string }> = {
  'identity.md': { label: '身份定位', icon: '🪪' },
  'style.md': { label: '内容风格', icon: '🎨' },
  'audience.md': { label: '目标受众', icon: '👥' },
  'platforms.md': { label: '平台运营', icon: '📱' },
  'preferences.md': { label: '偏好与红线', icon: '⚖️' },
  'memory.md': { label: '经验沉淀', icon: '🧠' },
};

export default function ProfilePage(props: ProfilePageProps) {
  const [viewedPersona, setViewedPersona] = useState(props.persona);
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);

  useEffect(() => { setViewedPersona(props.persona); }, [props.persona]);
  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError('');
    fetchPersonas().then((list) => {
      if (!ignore) setPersonas(list);
    }).catch(() => {
      if (!ignore) setError('加载画像列表失败，请重试。');
    }).finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [revision]);

  if (viewedPersona) {
    return <ProfileDetail key={viewedPersona} {...props} persona={viewedPersona}
      inUse={viewedPersona === props.persona}
      onBack={() => { setViewedPersona(''); setRevision((n) => n + 1); }}
      onDeleted={(name) => {
        setPersonas((list) => list.filter((p) => p.name !== name));
        setViewedPersona('');
        setRevision((n) => n + 1);
        props.onDeleted(name);
      }} />;
  }

  return (
    <div className="profile-page">
      <div className="profile-head">
        <div>
          <h1 className="page-title">用户画像 <span className="profile-title-en">Profile</span></h1>
          <p className="page-subtitle">管理你的定位、风格与受众，为每一种创作找到合适的身份。</p>
        </div>
        <button className="btn btn-primary" onClick={props.onNewProfile}><IconPlus size={15} /> 新建画像</button>
      </div>
      <div className="profile-mode-note">
        <IconProfile size={18} />
        <span>{props.persona ? `当前对话使用「${props.persona}」` : '当前对话为通用模式'}<small>查看和编辑画像不会切换对话身份。</small></span>
      </div>
      {loading ? <div className="loading"><div className="spinner" />加载画像…</div>
        : error ? <div className="empty-state"><p role="alert">{error}</p><button className="btn" onClick={() => setRevision((n) => n + 1)}>重新加载</button></div>
        : personas.length === 0 ? <div className="empty-state profile-empty">
          <div className="profile-avatar"><IconProfile size={28} /></div>
          <h3>创建你的第一个画像</h3>
          <p>记录账号定位、内容风格和偏好，让每次创作都更贴合你。</p>
          <button className="btn btn-primary" onClick={props.onNewProfile}><IconPlus size={15} /> 新建画像</button>
        </div> : <>
          <div className="section-title">我的画像 · {personas.length}</div>
          <div className="profile-grid">
            {personas.map((p) => <article className="card profile-summary" key={p.name}>
              <div className="profile-summary-head">
                <div className="profile-avatar"><IconProfile size={22} /></div>
                {p.name === props.persona && <span className="badge badge-accent">当前使用</span>}
              </div>
              <h2>{p.name}</h2>
              <p className="profile-summary-description">{p.description || '还没有定位简介，打开画像完善你的创作方向。'}</p>
              <div className="profile-summary-actions">
                <button className="btn" onClick={() => setViewedPersona(p.name)}>查看 / 编辑</button>
                <button className="btn btn-primary" onClick={() => props.onUsePersona(p.name)}>切换画像</button>
              </div>
            </article>)}
          </div>
        </>}
    </div>
  );
}

function ProfileDetail({ persona, onDeleted, onBack, onUsePersona, inUse }: ProfilePageProps & {
  onBack: () => void;
  inUse: boolean;
}) {  const [files, setFiles] = useState<PersonaFile[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [savingFile, setSavingFile] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [toast, setToast] = useState('');
  const [fetchingWx, setFetchingWx] = useState(false);

  useEffect(() => {
    if (!persona) { setFiles([]); return; }
    let ignore = false;   // 切 persona 丢弃旧请求（F2）
    setLoading(true);
    setError('');
    setEditing(false);
    fetchPersonaFiles(persona)
      .then((d) => {
        if (ignore) return;
        setFiles(d.files);
        setDrafts(Object.fromEntries(d.files.map((f) => [f.filename, f.content])));
      })
      .catch(() => { if (!ignore) setError('加载画像失败'); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [persona]);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 2500); };

  const handleSave = async (filename: string) => {
    setSavingFile(filename);
    try {
      await savePersonaFile(persona, filename, drafts[filename] ?? '');
      setFiles((prev) => prev.map((f) => f.filename === filename ? { ...f, content: drafts[filename] ?? '' } : f));
      showToast(`已保存 ${DIM_META[filename]?.label || filename} ✓`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSavingFile('');
    }
  };

  // 「平台运营」一键抓取公众号数据：复用数据中心同一个 mp 后台会话接口，把粉丝量级/内容形式
  // 抓完“直接落盘”并刷新视图——不进编辑态、不用用户点保存（否则会露出原始 markdown 破坏观感）。
  const handleFetchWechat = async (filename: string) => {
    setFetchingWx(true);
    try {
      const a = await fetchAccountAnalytics('wechat-oa');
      if (!a.loggedIn) {
        showToast('公众号后台未登录：请先到「账号」页扫码登录后再抓取');
        return;
      }
      const base = files.find((f) => f.filename === filename)?.content ?? '';
      const merged = mergeWechatBlock(base, buildWechatBlock(a));
      await savePersonaFile(persona, filename, merged);
      // 同步更新 files（视图）与 drafts（若正在编辑也一致），无需手动保存
      setFiles((prev) => prev.map((f) => f.filename === filename ? { ...f, content: merged } : f));
      setDrafts((p) => ({ ...p, [filename]: merged }));
      showToast(`已抓取并更新画像（粉丝 ${a.followers ?? 0}，已发表 ${a.posts ?? 0} 篇）✓`);
    } catch (e) {
      showToast(e instanceof Error ? `抓取失败：${e.message}` : '抓取失败（可能未登录或平台改版）');
    } finally {
      setFetchingWx(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`确定删除画像「${persona}」吗？\n此操作不可恢复，将删除该画像的全部六维文件。`)) return;
    setDeleting(true);
    try {
      await deletePersona(persona);
      onDeleted(persona);
      showToast(`已删除画像「${persona}」`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };


  return (
    <div className="profile-page">
      <div className="profile-detail-nav">
        <button className="btn btn-sm" disabled={!!savingFile || fetchingWx || deleting} onClick={() => {
          if (files.some((f) => (drafts[f.filename] ?? '') !== f.content)
              && !window.confirm('还有未保存的修改，确定返回画像列表吗？')) return;
          onBack();
        }}>← 全部画像</button>
        {inUse ? <span className="badge badge-accent">当前对话使用中</span>
          : <button className="btn btn-sm" onClick={() => onUsePersona(persona)}>切换画像</button>}
      </div>
      <div className="profile-head">
        <div>
          <h1 className="page-title">{persona}</h1>
          <p className="page-subtitle">六个维度构成一个完整人设，可随时编辑保存。</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={`btn ${editing ? 'btn-primary' : ''}`} onClick={() => setEditing((v) => !v)}>
            {editing ? '完成编辑' : '✏️ 编辑资料'}
          </button>
          <button className="btn" style={{ color: 'var(--red)', borderColor: 'var(--red)' }}
            disabled={deleting} onClick={handleDelete}>
            {deleting ? '删除中…' : '🗑 删除画像'}
          </button>
        </div>
      </div>

      {error && <div style={{ color: 'var(--red)', fontSize: 14, marginTop: 12 }}>{error}</div>}

      {loading ? (
        <div className="loading"><div className="spinner" />加载中…</div>
      ) : (
        files.map((f) => {
          const meta = DIM_META[f.filename] || { label: f.filename, icon: '📄' };
          const dirty = editing && (drafts[f.filename] ?? '') !== f.content;
          return (
            <div key={f.filename} className="profile-dim">
              <div className="profile-dim-head">
                <div className="profile-dim-title">{meta.icon} {meta.label}</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {f.filename === 'platforms.md' && (
                    <button className="btn btn-sm" disabled={fetchingWx}
                      title="用已登录的公众号后台会话抓取粉丝/内容数据，写入本栏（与数据中心同源）"
                      onClick={() => handleFetchWechat(f.filename)}>
                      {fetchingWx ? '抓取中…' : '📊 抓取公众号数据'}
                    </button>
                  )}
                  {editing && (
                    <button className="btn btn-sm btn-primary" disabled={!dirty || savingFile === f.filename}
                      onClick={() => handleSave(f.filename)}>
                      {savingFile === f.filename ? '保存中…' : dirty ? '保存' : '已保存'}
                    </button>
                  )}
                </div>
              </div>
              {editing ? (
                <textarea
                  className="field"
                  style={{ minHeight: 150, fontFamily: "'SF Mono','Consolas',monospace", fontSize: 13 }}
                  value={drafts[f.filename] ?? ''}
                  onChange={(e) => setDrafts((p) => ({ ...p, [f.filename]: e.target.value }))}
                />
              ) : (
                <div className="card" style={{ padding: '14px 18px' }}>
                  <div className="profile-content"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(f.content || '_（空）_') }} />
                </div>
              )}
            </div>
          );
        })
      )}

      {toast && <div className="toast ok"><span className="toast-icon">✓</span>{toast}</div>}
    </div>
  );
}
