import { useEffect, useRef, useState } from 'react';
import { artifactFromUrl, fitArtifact, mergeArtifacts } from '../lib/artifacts';
import { fetchArtifactArchive, mediaUrl } from '../lib/api';
import type { Artifact } from '../lib/artifacts';
import { IconChevron, IconOutputs } from './icons';

function HtmlArtifact({ artifact }: { artifact: Artifact }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [source, setSource] = useState('');
  const [error, setError] = useState(false);
  const [bounds, setBounds] = useState({ width: 800, height: 600 });
  const [available, setAvailable] = useState({ width: 640, height: 480 });
  const token = useRef(crypto.randomUUID());
  useEffect(() => {
    const controller = new AbortController();
    void fetch(artifact.url, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('preview');
      const html = await response.text();
      const base = new URL('.', new URL(artifact.url, window.location.origin)).href;
      const document = new DOMParser().parseFromString(html, 'text/html');
      document.querySelectorAll('base').forEach(element => element.remove());
      const baseElement = document.createElement('base');
      baseElement.href = base;
      document.head.prepend(baseElement);
      const script = document.createElement('script');
      script.textContent = `(() => {
        const report = () => parent.postMessage({type:'easel-artifact-size',token:${JSON.stringify(token.current)},
          width:Math.max(document.documentElement.scrollWidth,document.body.scrollWidth),
          height:Math.max(document.documentElement.scrollHeight,document.body.scrollHeight)}, '*');
        addEventListener('load', report);
        new ResizeObserver(report).observe(document.body);
        document.fonts?.ready.then(report);
        report();
      })();`;
      document.body.append(script);
      if (!controller.signal.aborted) setSource('<!doctype html>' + document.documentElement.outerHTML);
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => controller.abort();
  }, [artifact.url]);
  useEffect(() => {
    const observer = new ResizeObserver(entries => {
      const rect = entries[0].contentRect;
      setAvailable({ width: rect.width, height: rect.height });
    });
    if (stage.current) observer.observe(stage.current);
    const resize = (event: MessageEvent) => {
      const data = event.data;
      if (event.source !== frame.current?.contentWindow || data?.type !== 'easel-artifact-size'
          || data.token !== token.current || !Number.isFinite(data.width) || !Number.isFinite(data.height)
          || data.width <= 0 || data.height <= 0 || data.width > 20000 || data.height > 50000) return;
      setBounds(previous => previous.width === data.width && previous.height === data.height
        ? previous : { width: data.width, height: data.height });
    };
    window.addEventListener('message', resize);
    return () => { observer.disconnect(); window.removeEventListener('message', resize); };
  }, []);
  const fitted = fitArtifact(bounds.width, bounds.height, available.width - 24, available.height - 24);
  return (
    <div className="artifact-html-stage" ref={stage}>
      {error ? <span className="artifact-hint">预览加载失败，可在新标签打开原文件</span>
        : !source ? <span className="artifact-hint">正在加载预览…</span>
        : <div className="artifact-html-fit" style={{ width: fitted.width, height: fitted.height }}>
          <iframe ref={frame} srcDoc={source} title={artifact.name} sandbox="allow-scripts" allow="clipboard-write"
            style={{ width: bounds.width, height: bounds.height, transform: `scale(${fitted.scale})` }} />
        </div>}
    </div>
  );
}

function ArtifactPreview({ artifact }: { artifact: Artifact }) {
  const [error, setError] = useState(false);
  if (error) return <div className="artifact-hint">预览加载失败，可打开或下载原文件</div>;
  if (artifact.kind === 'html') return <HtmlArtifact artifact={artifact} />;
  if (artifact.kind === 'image') return <img src={artifact.url} alt={artifact.name} onError={() => setError(true)} />;
  if (artifact.kind === 'video') return <video src={artifact.url} controls preload="metadata" onError={() => setError(true)} />;
  if (artifact.kind === 'audio') return <audio src={artifact.url} controls preload="metadata" onError={() => setError(true)} />;
  return <iframe src={artifact.url} title={artifact.name} sandbox="" />;
}

export default function ArtifactGallery({ artifacts, archives }: { artifacts: Artifact[]; archives?: string[] }) {
  const [index, setIndex] = useState(0);
  const [archiveArtifacts, setArchiveArtifacts] = useState<Artifact[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    setArchiveArtifacts([]);
    if (archives?.length) {
      void Promise.all(archives.slice(0, 8).map(path =>
        fetchArtifactArchive(path, controller.signal).then(result =>
          result.paths.map(path => artifactFromUrl(mediaUrl(path))).filter((artifact): artifact is Artifact => !!artifact),
        ).catch(() => []),
      )).then(groups => {
        if (!controller.signal.aborted) setArchiveArtifacts(mergeArtifacts(...groups));
      });
    }
    return () => controller.abort();
  }, [archives]);
  const items = mergeArtifacts(artifacts, archiveArtifacts);
  const current = Math.min(index, items.length - 1);
  const artifact = items[current];
  if (!artifact) return null;
  const move = (direction: number) => setIndex((current + direction + items.length) % items.length);
  return (
    <section className="artifact-gallery" aria-label="对话产物预览" aria-roledescription="轮播"
      tabIndex={items.length > 1 ? 0 : undefined}
      onKeyDown={event => {
        if (event.target !== event.currentTarget || items.length < 2) return;
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
          event.preventDefault();
          move(event.key === 'ArrowLeft' ? -1 : 1);
        }
      }}>
      <div className="artifact-header"><IconOutputs size={16} /><span>创作产物</span>
        <span className="artifact-count" aria-live="polite">{current + 1} / {items.length}</span></div>
      <div className="artifact-stage">
        <ArtifactPreview key={artifact.url} artifact={artifact} />
        {items.length > 1 && <>
          <button type="button" className="artifact-arrow previous" aria-label="上一个产物" onClick={() => move(-1)}>
            <IconChevron size={20} /></button>
          <button type="button" className="artifact-arrow next" aria-label="下一个产物" onClick={() => move(1)}>
            <IconChevron size={20} /></button>
        </>}
      </div>
      <div className="artifact-footer">
        <span className="artifact-name" title={artifact.name}>{artifact.name}</span>
        <a href={artifact.url} target="_blank" rel="noreferrer">打开 ↗</a>
        <a href={artifact.url} download={artifact.name}>下载</a>
      </div>
    </section>
  );
}
