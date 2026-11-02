import { useEffect, useRef, useState } from 'react';
import { createSchedule, executeSkill, exportManualPackage, fetchOutputs, mediaUrl, runAgent, streamChat } from '../lib/api';
import type { OutputFile } from '../lib/api';
import { loadPublishDraft, savePublishDraft } from '../lib/store';
import { renderMarkdown } from '../lib/sanitize';
import { IconCalendar, IconCheck, IconCopy, IconEdit, IconPublish, IconSkills, IconStop, IconTrash } from './icons';

const PLATFORMS = [
  { key: 'xiaohongshu', label: '小红书', titleLimit: 20, bodyLimit: 1000, url: 'https://creator.xiaohongshu.com/publish/publish?source=official', hint: '在官方创作平台选择图文或视频，核对封面与话题。' },
  { key: 'douyin', label: '抖音', titleLimit: 55, bodyLimit: 55, url: 'https://creator.douyin.com/', hint: '进入官方创作者中心，选择发布体裁并上传素材。' },
  { key: 'kuaishou', label: '快手', titleLimit: 30, bodyLimit: 1000, url: 'https://cp.kuaishou.com/article/publish/video', hint: '在官方发布页核对描述、封面与素材。' },
  { key: 'weixin-channels', label: '视频号', titleLimit: 0, bodyLimit: 1000, url: 'https://channels.weixin.qq.com/platform/post/create', hint: '在视频号助手登录，上传视频并检查预览。' },
  { key: 'zhihu', label: '知乎', titleLimit: 0, bodyLimit: 5000, url: 'https://zhuanlan.zhihu.com/write', hint: '打开官方文章编辑器，粘贴正文后检查排版。' },
  { key: 'juejin', label: '掘金', titleLimit: 100, bodyLimit: 20000, url: 'https://juejin.cn/editor/drafts/new?v=2', hint: '在官方编辑器粘贴 Markdown，选择分类与标签，检查摘要后发布。' },
  { key: 'twitter-x', label: '推特 X', titleLimit: 0, bodyLimit: 280, url: 'https://x.com/compose/post', hint: '将标题与正文合并到官方发帖框，按平台计数检查长度后亲自发布。' },
  { key: 'bilibili', label: 'B站', titleLimit: 80, bodyLimit: 2000, url: 'https://member.bilibili.com/', hint: '进入官方创作中心投稿，核对分区、简介和封面。' },
  { key: 'wechat-oa', label: '公众号', titleLimit: 64, bodyLimit: 20000, url: 'https://mp.weixin.qq.com/', hint: '在官方后台新建草稿，上传图片并检查手机版预览。' },
];

function sections(text: string): Record<string, string> {
  const parts = text.split(/^\s*={2,}\s*(.+?)\s*={2,}\s*$/m);
  return Object.fromEntries(Array.from({ length: Math.floor((parts.length - 1) / 2) }, (_, i) => [parts[2 * i + 1].trim(), (parts[2 * i + 2] || '').trim()]));
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export default function ManualPublishPage({ persona }: { persona: string }) {
  const initial = useRef(loadPublishDraft()).current;
  const [title, setTitle] = useState(initial.title);
  const [body, setBody] = useState(initial.body);
  const [platforms, setPlatforms] = useState<string[]>(initial.platforms);
  const [overrides, setOverrides] = useState<Record<string, string>>(initial.overrides);
  const [tags, setTags] = useState(initial.tags || '');
  const [mediaFiles, setMediaFiles] = useState<OutputFile[]>([]);
  const [selectedMedia, setSelectedMedia] = useState<string[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState<Record<string, string>>({});
  const [links, setLinks] = useState<Record<string, string>>({});
  const [recorded, setRecorded] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState('');
  const [toast, setToast] = useState('');
  const [adapting, setAdapting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState('');
  const [exporting, setExporting] = useState('');
  const [saving, setSaving] = useState(false);
  const ctl = useRef<AbortController | null>(null);

  useEffect(() => { savePublishDraft({ title, body, platforms, overrides, tags }); }, [title, body, platforms, overrides, tags]);
  useEffect(() => () => ctl.current?.abort(), []);
  useEffect(() => {
    fetchOutputs().then((roots) => {
      const files: OutputFile[] = [];
      const walk = (node: OutputFile) => {
        if (node.type === 'file') { if (node.kind === 'image' || node.kind === 'video') files.push(node); }
        else (node.children || []).forEach(walk);
      };
      roots.forEach(walk);
      setMediaFiles(files.sort((a, b) => (b.mtime || 0) - (a.mtime || 0)));
    }).catch(() => setToast('内容库暂时无法读取，仍可编辑和复制文案'));
  }, []);

  const effective = (key: string) => overrides[key] ?? body;
  const snapshot = (key: string) => JSON.stringify([title, effective(key), tags, selectedMedia]);
  const approved = (key: string) => reviewed[key] === snapshot(key) && !adapting;
  const empty = !title.trim() && !body.trim() && !Object.values(overrides).some((text) => text.trim());
  const showToast = (text: string) => { setToast(text); window.setTimeout(() => setToast(''), 4000); };
  const toggle = (key: string) => setPlatforms((prev) => prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]);
  const toggleMedia = (path: string) => setSelectedMedia((prev) => prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]);
  const bodyWithTags = (key: string) => {
    const text = effective(key);
    const extra = tags.split(/[,，]/).map((t) => t.trim().replace(/^#+/, '')).filter((t) => t && !text.includes(`#${t}`));
    return text + (extra.length ? `\n\n${extra.map((t) => `#${t}`).join(' ')}` : '');
  };

  const adapt = () => {
    if (empty || !platforms.length || adapting) return;
    const selected = PLATFORMS.filter((p) => platforms.includes(p.key));
    const prompt = `仅改写和排版以下稿件，不执行工具、发布脚本或平台接口。按当前画像适配：${selected.map((p) => p.label).join('、')}。\n`
      + '保持事实，不新增未经核实的数据。各段只返回正文，不重复标题。公众号用清晰的 Markdown 小标题、短段落和列表；其他平台输出可直接粘贴的纯文本与自然换行。不要输出 HTML。\n'
      + '严格按以下格式返回，每个平台一段，不加额外说明：\n'
      + selected.map((p) => `===${p.label}===\n<排版后的正文>`).join('\n')
      + `\n\n标题：${title}\n正文：${body}`;
    let acc = '';
    const base = { ...overrides };
    setAdapting(true);
    ctl.current = streamChat(prompt, persona, `manual-adapt-${Date.now()}`, (chunk) => {
      acc += chunk;
      const parsed = sections(acc);
      const next = { ...base };
      selected.forEach((p) => { if (parsed[p.label] != null) next[p.key] = parsed[p.label]; });
      setOverrides(next);
    }, () => { setAdapting(false); showToast(Object.keys(sections(acc)).length ? 'AI 排版完成，请逐个平台人工审核' : '未解析到平台正文，请重试'); },
    (error) => { setAdapting(false); showToast(error.message || '排版失败，请重试'); });
  };

  const check = async () => {
    if (empty || checking || adapting) return;
    setChecking(true);
    const content = `标题：${title}\n${PLATFORMS.filter((p) => platforms.includes(p.key)).map((p) => `${p.label}：${effective(p.key)}`).join('\n\n')}\n话题：${tags}`;
    try {
      const [general, consistency] = await Promise.all([
        runAgent(`仅给审核建议，不发布、不调用发布脚本。检查内容中的事实依据、夸大表述、版权和标题正文一致性，给出修改建议；不能确认的事项明确列出，不能保证平台审核结果。\n${content}`),
        persona ? executeSkill('persona-check', content, persona) : Promise.resolve(null),
      ]);
      setCheckResult(general.response + (consistency ? `\n\n## 人设一致性\n${consistency.response}` : ''));
    } catch (error) { setCheckResult(`检查未完成：${error instanceof Error ? error.message : '请稍后重试'}`); }
    finally { setChecking(false); }
  };

  const copyFor = async (key: string, part: 'title' | 'body' | 'all') => {
    if (!approved(key)) return;
    try {
      await navigator.clipboard.writeText(part === 'title' ? title : part === 'body' ? bodyWithTags(key) : `${title}\n\n${bodyWithTags(key)}`.trim());
      setCopied(`${key}:${part}`);
      window.setTimeout(() => setCopied(''), 1600);
    } catch { showToast('复制未成功，请手动选择文字，或导出稿件包'); }
  };

  const exportFor = async (key: string) => {
    if (!approved(key) || exporting) return;
    setExporting(key);
    try {
      const result = await exportManualPackage(key, { title, body: effective(key), tags, media: [...selectedMedia], reviewed: true });
      const a = document.createElement('a');
      a.href = mediaUrl(result.path); a.download = result.filename;
      document.body.appendChild(a); a.click(); a.remove();
      showToast('已生成稿件包并发起下载；尚未上传或发布');
    } catch (error) { showToast(error instanceof Error ? error.message : '导出失败'); }
    finally { setExporting(''); }
  };

  const copyRichText = async () => {
    if (!approved('wechat-oa')) return;
    try {
      const heading = document.createElement('h1');
      heading.textContent = title;
      const content = `<article style="font-size:16px;line-height:1.9">${heading.outerHTML}${renderMarkdown(effective('wechat-oa'))}</article>`;
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([content], { type: 'text/html' }),
        'text/plain': new Blob([`${title}\n\n${effective('wechat-oa')}`], { type: 'text/plain' }),
      })]);
      showToast('已复制公众号排版；请在官方编辑器中粘贴并检查实际效果');
    } catch { showToast('当前浏览器未允许复制富文本，请导出稿件包并打开 article.html'); }
  };

  const addToCalendar = async (key: string, published = false) => {
    if (saving || empty || (published && !approved(key))) return;
    let link = '';
    if (published) {
      try {
        const url = new URL(links[key] || '');
        if (url.protocol !== 'https:') throw new Error();
        link = url.href;
      } catch { showToast('请粘贴官方平台上已发布作品的 HTTPS 链接'); return; }
    }
    setSaving(true);
    const version = snapshot(key);
    try {
      await createSchedule({ title: title.trim() || effective(key).slice(0, 20), date: today(), time: '',
        platform: PLATFORMS.find((p) => p.key === key)?.label || '', status: published ? 'published' : 'draft',
        note: published ? `【人工确认已发布，未自动验证平台状态】\n${link}\n\n${effective(key)}` : effective(key) });
      if (published) setRecorded((prev) => ({ ...prev, [key]: version + (links[key] || '') }));
      showToast(published ? '已按你的确认记录到日历，未自动校验平台结果' : '已保存为日历草稿，不会自动发布');
    } catch (error) { showToast(error instanceof Error ? error.message : '保存失败'); }
    finally { setSaving(false); }
  };

  return <div className="publish-page">
    <div className="publish-editor">
      <h1 className="page-title"><IconPublish size={21} /> 发布中心 · 人工发布</h1>
      <p className="page-subtitle">AI 排版 → 人工审核 → 复制 / 导出 → 在官方发布页亲自提交。</p>
      <div className="panel" style={{ marginBottom: 16, fontSize: 13 }}>
        <strong>最终提交由你完成。</strong> 本页不自动登录、上传或点击发布。官方页面的登录与 Easel 账号页相互独立。
      </div>
      <label className="field-label" htmlFor="manual-title">标题</label>
      <input id="manual-title" className="field" value={title} placeholder="请输入标题" onChange={(e) => setTitle(e.target.value)} />
      <label className="field-label" htmlFor="manual-body">正文（母版）</label>
      <textarea id="manual-body" className="field" style={{ minHeight: 180 }} value={body} placeholder="输入文案，选择平台后让 AI 排版，也可以自行编辑。" onChange={(e) => setBody(e.target.value)} />
      <label className="field-label" htmlFor="manual-tags">话题标签（逗号分隔）</label>
      <input id="manual-tags" className="field" value={tags} placeholder="AI,职场,干货" onChange={(e) => setTags(e.target.value)} />
      <label className="field-label">目标平台</label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{PLATFORMS.map((p) => <button key={p.key} className={`chip ${platforms.includes(p.key) ? 'active' : ''}`} onClick={() => toggle(p.key)}>{p.label}</button>)}</div>
      <label className="field-label" style={{ marginTop: 16 }}>媒体素材 · 已选 {selectedMedia.length} 个</label>
      <p className="pv-hint">从内容库选择图片 / 视频打包导出，也可稍后在官方页面手动选择电脑上的文件。</p>
      <button className="btn btn-sm" onClick={() => setShowPicker((v) => !v)}>{showPicker ? '收起素材' : '选择媒体'}</button>
      {selectedMedia.length > 0 && <ul style={{ fontSize: 12 }}>{selectedMedia.map((path) => <li key={path}><button className="pv-copy" onClick={() => toggleMedia(path)} title="移除素材">×</button> {path.split('/').pop()}</li>)}</ul>}
      {showPicker && <div className="media-grid">
        {!mediaFiles.length && <p className="dash-empty">内容库暂无图片或视频，可先导出文案。</p>}
        {mediaFiles.slice(0, 80).map((f) => <button type="button" key={f.path} className={`media-cell ${selectedMedia.includes(f.path) ? 'sel' : ''}`} onClick={() => toggleMedia(f.path)} title={f.path}>
          {f.kind === 'image' ? <img src={mediaUrl(f.path)} alt={f.name} loading="lazy" /> : <span className="media-vid">视频 · {f.name}</span>}
          {selectedMedia.includes(f.path) && <span className="media-check">✓</span>}
        </button>)}
      </div>}
      <div className="publish-actions">
        {adapting ? <button className="btn btn-sm" onClick={() => { ctl.current?.abort(); setAdapting(false); }}><IconStop size={13} /> 停止排版</button>
          : <button className="btn btn-sm btn-primary" disabled={empty || !platforms.length} onClick={adapt}><IconSkills size={14} /> AI 排版 / 适配</button>}
        <button className="btn btn-sm" disabled={empty || checking || adapting} onClick={check}><IconCheck size={14} />{checking ? '检查中…' : 'AI 辅助检查'}</button>
        <button className="btn btn-sm" disabled={empty || saving || adapting} onClick={() => addToCalendar(platforms[0] || 'xiaohongshu')}><IconCalendar size={14} /> 存草稿并排期</button>
        <button className="btn btn-sm btn-ghost" disabled={empty || adapting} onClick={() => { setTitle(''); setBody(''); setTags(''); setOverrides({}); setReviewed({}); setCheckResult(''); }}><IconTrash size={13} /> 清空文案</button>
      </div>
      <p className="publish-saved-note">文案自动保存到当前浏览器。审核只针对当前版本；修改标题、正文、标签或素材后，需重新审核。AI 检查仅作参考。</p>
      {checkResult && <div className="panel"><div className="panel-title">AI 辅助检查</div><div className="skill-body-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(checkResult) }} /></div>}
    </div>
    <div className="publish-previews">
      {!platforms.length && <div className="dash-empty">选择目标平台，在这里预览和审核。</div>}
      {PLATFORMS.filter((p) => platforms.includes(p.key)).map((p) => {
        const text = effective(p.key);
        const ready = approved(p.key) && !!(title.trim() || text.trim());
        const isEdit = editing === p.key;
        const hasRecorded = recorded[p.key] === snapshot(p.key) + (links[p.key] || '');
        return <div key={p.key} className={`card pv-card pv-${p.key}`}>
          <div className="pv-head"><span className="pv-plat">{p.label}<span className={`pv-badge ${ready ? 'pv-badge-ok' : ''}`}>{ready ? '已人工审核' : '待人工审核'}</span></span><span className={`pv-count ${text.length > p.bodyLimit ? 'over' : ''}`}>{text.length} 字</span></div>
          <div className="pv-body">
            <div className={`pv-title ${p.titleLimit && title.length > p.titleLimit ? 'over' : ''}`}>{title || <span className="pv-ph">标题预览</span>}</div>
            {isEdit ? <textarea className="field" aria-label={`${p.label}正文`} style={{ minHeight: 140 }} value={text} onChange={(e) => setOverrides((old) => ({ ...old, [p.key]: e.target.value }))} />
              : p.key === 'wechat-oa' ? <div className="skill-body-md" dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} /> : <div className="pv-text">{text || '正文预览'}</div>}
            <p className="pv-hint" style={{ marginTop: 12 }}>{p.hint} 字数和格式以官方页面为准。</p>
            <button className="pv-copy" onClick={() => setEditing(isEdit ? null : p.key)}><IconEdit size={13} />{isEdit ? '完成编辑' : '编辑此平台版本'}</button>
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, margin: '16px 0', fontSize: 13 }}>
              <input type="checkbox" aria-label={`${p.label}人工审核`} disabled={adapting || isEdit || !(title.trim() || text.trim())} checked={ready} onChange={(e) => setReviewed((old) => ({ ...old, [p.key]: e.target.checked ? snapshot(p.key) : '' }))} />
              我已核对当前版本的事实、标题正文、话题、素材及使用授权，准备到官方页面发布。
            </label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(['title', 'body', 'all'] as const).map((part) => <button key={part} className="btn btn-sm" disabled={!ready} onClick={() => copyFor(p.key, part)}><IconCopy size={13} />{copied === `${p.key}:${part}` ? '已复制' : part === 'title' ? '复制标题' : part === 'body' ? '复制正文' : '复制全文'}</button>)}
              {p.key === 'wechat-oa' && <button className="btn btn-sm" disabled={!ready} onClick={copyRichText}>复制公众号排版</button>}
              <button className="btn btn-sm" disabled={!ready || !!exporting} onClick={() => exportFor(p.key)}>{exporting === p.key ? '打包中…' : '导出稿件和素材 ZIP'}</button>
              {ready ? <a className="btn btn-sm btn-primary" href={p.url} target="_blank" rel="noopener noreferrer">打开官方发布页 ↗</a> : <button className="btn btn-sm" disabled>审核后打开官方发布页</button>}
            </div>
            <p className="pv-hint" style={{ margin: '14px 0' }}>导出不代表已发布。请解压 ZIP，在官方页面粘贴稿件、上传素材、检查预览，并按平台要求标注 AI 辅助创作，最后由你点击发布。</p>
            <details><summary style={{ cursor: 'pointer', fontSize: 13 }}>发布后，回填作品链接</summary>
              <input className="field" aria-label={`${p.label}作品链接`} placeholder="粘贴已发布作品的 https:// 链接" value={links[p.key] || ''} onChange={(e) => setLinks((old) => ({ ...old, [p.key]: e.target.value }))} style={{ margin: '10px 0' }} />
              <button className="btn btn-sm" disabled={!ready || saving || !links[p.key]?.trim() || hasRecorded} onClick={() => addToCalendar(p.key, true)}>{hasRecorded ? '已记录人工确认' : '我已在官方平台发布，记录到日历'}</button>
              <p className="pv-hint">按你的确认记录，不自动检查平台状态。</p>
            </details>
          </div>
        </div>;
      })}
    </div>
    {toast && <div className="toast" role="status">{toast}</div>}
  </div>;
}
