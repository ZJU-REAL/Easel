import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { deleteOutput, fetchOutputs, mediaUrl, type OutputNode } from '../lib/api';
import { IconChevron, IconFile, IconFolder, IconImage, IconMusic, IconRefresh, IconSearch, IconTrash, IconVideo } from './icons';
import OutputPreview, { fileLabel, sizeLabel } from './OutputPreview';

const formats = [['all','全部类型'],['text','文档与网页'],['image','图片'],['video','视频'],['audio','音频'],['binary','其他文件']];
const statusLabels: Record<string,string> = { draft: '草稿', ready: '待发布', published: '已发布' };
const projectTypes: Record<string,string> = { article: '文章', 'xhs-note': '小红书笔记', video: '视频', cards: '卡片', poster: '海报', audio: '音频', other: '其他' };
const newer = (a: OutputNode,b: OutputNode) => (b.mtime || 0) - (a.mtime || 0);
const title = (n: OutputNode) => n.meta?.title || n.name;
const parentOf = (path: string) => path.slice(0, Math.max(0,path.lastIndexOf('/')));
const within = (path: string, folder: string) => !folder || path.startsWith(folder + '/');

function indexTree(roots: OutputNode[]) {
  const nodes = new Map<string, OutputNode>();
  const covers = new Map<string,string>();
  function visit(node: OutputNode): string {
    nodes.set(node.path,node);
    let cover = node.meta?.cover || (node.kind === 'image' || node.kind === 'video' ? node.path : '');
    for (const child of node.children || []) {
      const nested = visit(child);
      if (!cover) cover = nested;
    }
    if (cover) covers.set(node.path,cover);
    return cover;
  }
  roots.forEach(visit);
  const files = [...nodes.values()].filter(n => n.type === 'file').sort(newer);
  return { nodes, covers, files };
}

function EntryIcon({ node, cover }: { node: OutputNode; cover?: string }) {
  const Icon = node.type === 'dir' ? IconFolder : node.kind === 'audio' ? IconMusic : node.kind === 'video' ? IconVideo : node.kind === 'image' ? IconImage : IconFile;
  return <span className={'lib-entry-icon' + (node.type === 'dir' ? ' is-folder' : '')}>
    {cover ? /\.(mp4|webm|mov|mkv)$/i.test(cover) ? <video src={mediaUrl(cover)} muted preload="metadata" aria-hidden="true" /> : <img src={mediaUrl(cover)} loading="lazy" alt=""/> : <Icon size={18}/>}
  </span>;
}

interface OutputsPageProps { jumpPath?: string; onJumpHandled?: () => void }

export default function OutputsPage({ jumpPath, onJumpHandled }: OutputsPageProps) {
  const [roots, setRoots] = useState<OutputNode[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [treeError, setTreeError] = useState('');
  const [folder, setFolder] = useState('');
  const [picked, setPicked] = useState('');
  const [query, setQuery] = useState('');
  const [format, setFormat] = useState('all');
  const [reading, setReading] = useState(false);
  const seq = useRef(0);
  const shell = useRef<HTMLDivElement>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const load = useCallback(async () => {
    const id = ++seq.current;
    setBusy(true); setTreeError('');
    try {
      const rows = await fetchOutputs();
      if (id === seq.current) { setRoots(rows); setLoaded(true); }
    } catch { if (id === seq.current) setTreeError('内容库读取失败，请刷新重试。'); }
    finally { if (id === seq.current) setBusy(false); }
  }, []);
  useEffect(() => { void load(); return () => { seq.current++; }; }, [load]);
  const index = useMemo(() => indexTree(roots), [roots]);
  let current = folder;
  while (current && index.nodes.get(current)?.type !== 'dir') current = parentOf(current);
  const directory = index.nodes.get(current);
  const crumbs = current ? current.split('/').map((_,i,parts) => parts.slice(0,i+1).join('/')) : [];
  const files = useMemo(() => index.files.filter(n => within(n.path,current)), [current,index]);
  const children = directory?.children || roots;
  const folders = children.filter(n => n.type === 'dir').sort(newer);
  const directFiles = children.filter(n => n.type === 'file').sort(newer);
  const declared = directory?.meta?.deliverablePaths || [];
  const finals = declared.map(path => index.nodes.get(path)).filter((n): n is OutputNode => !!n && n.type === 'file');
  const finalPaths = new Set(finals.map(n => n.path));
  const keyword = query.trim().toLocaleLowerCase();
  const searching = !!keyword || format !== 'all';
  const matches = useMemo(() => {
    if (!searching) return [];
    return [...index.nodes.values()].filter(n => within(n.path,current)
      && (format === 'all' || (n.type === 'file' && n.kind === format))
      && (!keyword || [n.path,title(n),n.meta?.platform,n.meta?.summary,...(n.meta?.tags || [])].join(' ').toLocaleLowerCase().includes(keyword))
    ).sort(newer);
  }, [index,current,keyword,format,searching]);
  const preferred = (node?: OutputNode) => {
    if (!node || node.type === 'file') return node;
    const deliverable = node.meta?.deliverablePaths?.map(path => index.nodes.get(path)).find(n => n?.type === 'file');
    return deliverable || index.files.find(n => within(n.path,node.path));
  };
  const selection = index.nodes.get(picked);
  const selected = selection?.type === 'file' && within(selection.path,current) && (!searching || matches.some(n => n.path === picked))
    ? selection : searching ? preferred(matches[0]) : (finals[0] || (current ? files[0] : preferred([...roots].sort(newer)[0]) || files[0]));
  const focusMode = reading && !!selected;
  const clearFilters = () => { setQuery(''); setFormat('all'); };
  const navigate = (path: string, file = '') => { setFolder(path); setPicked(file); clearFilters(); setReading(false); };
  const leaveReading = useCallback(() => {
    setReading(false);
    requestAnimationFrame(() => {
      const target = lastTrigger.current;
      if (target?.isConnected) target.focus(); else shell.current?.querySelector<HTMLButtonElement>('[data-reader-toggle]')?.focus();
    });
  }, []);
  useEffect(() => {
    if (!focusMode) return;
    shell.current?.querySelector<HTMLButtonElement>('[data-reader-toggle]')?.focus();
    const escape = (e: KeyboardEvent) => { if (e.key === 'Escape') leaveReading(); };
    window.addEventListener('keydown',escape);
    return () => window.removeEventListener('keydown',escape);
  }, [focusMode,leaveReading]);
  useEffect(() => {
    if (!jumpPath || !loaded) return;
    const node = index.nodes.get(jumpPath);
    let parent = node?.type === 'dir' ? node.path : parentOf(jumpPath);
    while (parent && !index.nodes.has(parent)) parent = parentOf(parent);
    setFolder(parent); setQuery(''); setFormat('all');
    setPicked(node?.type === 'file' ? node.path : '');
    setReading(node?.type === 'file' && (shell.current?.clientWidth || 0) <= 700);
    onJumpHandled?.();
  }, [jumpPath,loaded,index,onJumpHandled]);
  const open = (node: OutputNode, trigger: HTMLElement) => {
    if (node.type === 'dir') { navigate(node.path); return; }
    lastTrigger.current = trigger; setPicked(node.path);
    if ((shell.current?.clientWidth || 0) <= 700) setReading(true);
  };
  const remove = async (node: OutputNode) => {
    const name = node.type === 'dir' ? '文件夹「' + title(node) + '」及其中所有文件' : '文件「' + node.name + '」';
    if (!window.confirm('确定删除' + name + '？此操作不可恢复。')) return;
    try { await deleteOutput(node.path); await load(); }
    catch { setTreeError('删除失败，请刷新后重试。'); }
  };
  const entry = (node: OutputNode, showPath = false) => {
    const dir = node.type === 'dir';
    const location = parentOf(node.path);
    const details = dir ? [node.fileCount !== undefined ? node.fileCount + ' 个文件' : '文件夹', node.meta?.platform,
      node.meta?.status ? statusLabels[node.meta.status] || node.meta.status : '', node.meta?.kind ? projectTypes[node.meta.kind] : '']
      : [fileLabel(node), showPath && location ? location : sizeLabel(node.size)];
    return <li key={node.path} className={'lib-entry' + (selected && (selected.path === node.path || (!current && dir && within(selected.path,node.path))) ? ' is-selected' : '')}>
      <button className="lib-open" onClick={e => open(node,e.currentTarget)} title={node.path}>
        <EntryIcon node={node} cover={index.covers.get(node.path)}/>
        <span className="lib-entry-text"><strong>{title(node)}</strong><small>{details.filter(Boolean).join(' · ')}</small></span>
        {dir && <IconChevron size={12}/>}
      </button>
      <button className="lib-delete" aria-label={'删除 ' + title(node)} title="删除" onClick={() => void remove(node)}><IconTrash size={13}/></button>
    </li>;
  };
  const group = (label: string, list: OutputNode[], paths = false) => list.length > 0 && <section className="lib-group">
    <h2>{label}<small>{list.length}</small></h2><ul>{list.map(n => entry(n,paths))}</ul>
  </section>;
  return <div className="gallery-page library-page">
    <div className={'lib-shell' + (focusMode ? ' is-reading' : '')} ref={shell}>
      <header className="lib-mast">
        <div><h1 className="page-title">内容库</h1><p>{roots.filter(n => n.type === 'dir').length} 个项目 · {index.files.length} 个文件</p></div>
        <button className="lib-refresh" disabled={busy} onClick={() => void load()}><IconRefresh size={14}/>{busy ? '刷新中…' : '刷新'}</button>
      </header>
      {treeError && <p className="lib-error" role="alert">{treeError}</p>}
      <div className="lib-layout">
        <section className="lib-browser" aria-label="浏览项目和文件">
          <nav className="lib-crumbs gallery-breadcrumb" aria-label="内容库路径"><button onClick={() => navigate('')} aria-current={!current ? 'page' : undefined}>全部项目</button>
            {crumbs.map(path => <span key={path}><IconChevron size={11}/><button aria-current={path === current ? 'page' : undefined}
              onClick={() => navigate(path)}>{title(index.nodes.get(path)!)}</button></span>)}</nav>
          {directory?.meta?.summary && <p className="lib-description">{directory.meta.summary}</p>}
          {!!directory?.meta?.tags?.length && <p className="lib-tags">{directory.meta.tags.map(t => <span key={t}>#{t}</span>)}</p>}
          <div className="lib-filters">
            <label className="lib-search"><IconSearch size={15}/><input type="search" aria-label="搜索项目或文件" value={query} placeholder={current ? '搜索此目录' : '搜索项目或文件'} onChange={e => { setQuery(e.target.value); setPicked(''); }}/></label>
            <select aria-label="文件类型" value={format} onChange={e => { setFormat(e.target.value); setPicked(''); }}>
              {formats.map(([key,label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </div>
          <div className="lib-list">
            {searching ? group('搜索结果',matches,true) : <>
              {group(current ? '子文件夹' : '项目目录',folders)}
              {group('成品',finals,true)}
              {group(finals.length ? '其他文件' : '文件',directFiles.filter(n => !finalPaths.has(n.path)))}
              {!current && group('最近文件',index.files.filter(n => parentOf(n.path)).slice(0,5),true)}
            </>}
            {!loaded && !treeError && <p className="lib-empty" role="status">正在读取内容库…</p>}
            {loaded && searching && !matches.length && <div className="lib-empty">没有匹配的项目或文件。<button className="lib-link" onClick={clearFilters}>清除筛选</button></div>}
            {loaded && !searching && !children.length && <p className="lib-empty">{current ? '这个文件夹还是空的。' : '创作生成的项目会出现在这里。'}</p>}
          </div>
        </section>
        {selected ? <OutputPreview key={selected.path + ':' + selected.mtime} file={selected} location={parentOf(selected.path)}
          onLocate={() => navigate(parentOf(selected.path),selected.path)} onRemove={() => void remove(selected)} reading={focusMode}
          onToggleReading={() => { if (focusMode) leaveReading(); else { lastTrigger.current = document.activeElement as HTMLElement; setReading(true); } }}/>
          : <section className="lib-reader lib-blank"><IconFile size={24}/><h2>文件预览</h2><p>{searching ? '选择匹配的文件即可预览。' : '打开有文件的项目后，即可在这里查看内容。'}</p></section>}
      </div>
    </div>
  </div>;
}
