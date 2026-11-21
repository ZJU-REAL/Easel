import { useEffect, useMemo, useState } from 'react';
import { fetchOutputContent, mediaUrl, type OutputNode } from '../lib/api';
import { renderMarkdown } from '../lib/sanitize';
import { IconCopy, IconLayout, IconTrash } from './icons';

export function fileLabel(file: OutputNode) {
  if (file.kind === 'text') return /\.html?$/i.test(file.name) ? '网页' : '文档';
  return ({ image: '图片', video: '视频', audio: '音频', binary: '文件' } as const)[file.kind || 'binary'];
}

export function sizeLabel(bytes?: number) {
  if (bytes === undefined) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return Math.round(bytes / 102.4) / 10 + ' KB';
  return Math.round(bytes / 1024 / 102.4) / 10 + ' MB';
}

const dateFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' });
interface Props {
  file: OutputNode;
  location: string;
  onLocate: () => void;
  onRemove: () => void;
  reading: boolean;
  onToggleReading: () => void;
}

export default function OutputPreview({ file, location, onLocate, onRemove, reading, onToggleReading }: Props) {
  const html = file.kind === 'text' && /\.html?$/i.test(file.name);
  const textFile = file.kind === 'text' && !html;
  const markdown = /\.(?:md|markdown)$/i.test(file.name);
  const [text, setText] = useState<string | null>(null);
  const [binary, setBinary] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [htmlOpen, setHtmlOpen] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const url = mediaUrl(file.path);
  useEffect(() => {
    if (!textFile) return;
    let active = true;
    fetchOutputContent(file.path).then(result => {
      if (active) { setText(result.content); setBinary(result.isBinary); }
    }).catch(() => { if (active) setError('文件内容读取失败。'); });
    return () => { active = false; };
  }, [file.path, textFile, attempt]);
  useEffect(() => {
    if (copyState === 'idle') return;
    const timeout = window.setTimeout(() => setCopyState('idle'), 2600);
    return () => window.clearTimeout(timeout);
  }, [copyState]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text || ''); setCopyState('copied'); }
    catch { setCopyState('error'); }
  };
  const rendered = useMemo(() => markdown && text ? renderMarkdown(text) : '', [markdown,text]);
  const preview = () => {
    if (file.kind === 'image') return <img className="lib-photo" src={url} alt={file.name}/>;
    if (file.kind === 'video') return <video className="lib-video" src={url} controls preload="metadata" />;
    if (file.kind === 'audio') return <audio src={url} controls preload="metadata" aria-label={file.name}/>;
    if (html) return htmlOpen
      ? <iframe className="lib-web" src={url + '?v=' + (file.mtime ?? 0)} title={file.name} sandbox="allow-scripts" allow="clipboard-write" />
      : <button className="btn btn-sm" onClick={() => setHtmlOpen(true)}>加载网页预览</button>;
    if (!textFile || binary) return <p>此文件可下载后查看。</p>;
    if (error) return <div role="alert">{error} <button className="lib-link" onClick={() => { setError(''); setAttempt(n => n + 1); }}>重试</button></div>;
    if (text === null) return <p role="status">正在读取原文…</p>;
    if (!text.trim()) return <p>这是一个空文档。</p>;
    return markdown
      ? <article className="lib-paper outputs-viewer-content" dangerouslySetInnerHTML={{ __html: rendered }} />
      : <article className="lib-paper"><pre className="lib-plain">{text}</pre></article>;
  };
  return <section className="lib-reader" aria-labelledby="lib-reader-title">
    <header className="lib-reader-head">
      <div className="lib-file-location">{location && <><button onClick={onLocate} title="打开所在目录">{location}</button><span aria-hidden="true">/</span></>}{fileLabel(file)}</div>
      <div className="lib-reader-title"><h2 id="lib-reader-title">{file.name}</h2>
        <button className="lib-reader-mode" data-reader-toggle onClick={onToggleReading} aria-pressed={reading}><IconLayout size={14}/>{reading ? '退出阅读' : '阅读模式'}</button>
      </div>
      <div className="lib-reader-bar">
        <small>{[sizeLabel(file.size), file.mtime ? dateFormat.format(file.mtime * 1000) + '更新' : ''].filter(Boolean).join(' · ')}</small>
        <div className="lib-actions">
          {textFile && !binary && <button className="lib-link" disabled={text === null || !!error} onClick={() => void copy()}><IconCopy size={13}/>{copyState === 'copied' ? '已复制' : '复制原文'}</button>}
          {html && <a className="lib-link" href={url} target="_blank" rel="noreferrer">新标签打开</a>}
          <a className="lib-link" href={url} download={file.name}>下载</a>
          <button className="lib-delete" aria-label="删除此文件" title="删除此文件" onClick={onRemove}><IconTrash size={13}/></button>
        </div>
      </div>
      <span role="status" className={copyState === 'error' ? 'lib-error' : 'lib-sr'}>{copyState === 'error' ? '复制失败，请选中原文复制。' : copyState === 'copied' ? '已复制原文' : ''}</span>
    </header>
    <div className={'lib-stage ' + (textFile ? 'is-document' : 'is-media')} tabIndex={0} aria-label="文件内容">{preview()}</div>
  </section>;
}
