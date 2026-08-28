import { useState, useEffect } from 'react';
import { fetchPersonaFiles, savePersonaFile, deletePersona } from '../lib/api';
import type { PersonaFile } from '../lib/api';
import { renderMarkdown } from '../lib/sanitize';

interface ProfilePageProps {
  persona: string;
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

export default function ProfilePage({ persona, onNewProfile, onDeleted }: ProfilePageProps) {
  const [files, setFiles] = useState<PersonaFile[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [savingFile, setSavingFile] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [toast, setToast] = useState('');

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

  if (!persona) {
    return (
      <div className="profile-page">
        <h1 className="page-title">用户画像 Profile</h1>
        <div className="empty-state" style={{ height: '70%' }}>
          <div className="empty-icon">👤</div>
          <h3>还没有选择画像</h3>
          <p>画像沉淀你的定位、风格、受众与红线，生成内容会更贴合你的人设。</p>
          <button className="btn btn-primary" onClick={onNewProfile}>+ 新建画像</button>
        </div>
      </div>
    );
  }

  return (
    <div className="profile-page">
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
                {editing && (
                  <button className="btn btn-sm btn-primary" disabled={!dirty || savingFile === f.filename}
                    onClick={() => handleSave(f.filename)}>
                    {savingFile === f.filename ? '保存中…' : dirty ? '保存' : '已保存'}
                  </button>
                )}
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
