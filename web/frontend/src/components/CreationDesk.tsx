import { studioTools } from './studioTools';
import { useEffect, useMemo, useState } from 'react';
import { fetchIdeas, fetchOutputs, fetchSchedule, fetchTrends } from '../lib/api';
import type { OutputNode } from '../lib/api';
import { calendarDate } from '../lib/calendarDate';
import type { ChatSession } from '../lib/store';
import type { Page } from './Sidebar';
import { IconChat, IconChevron, IconFile, IconNewChat, IconPublish, IconSkills } from './icons';

export interface CreationDeskProps {
  persona: string;
  session?: ChatSession;
  onResume: (id: string) => void;
  onNavigate: (page: Page) => void;
  onOpenDate: (date: string) => void;
  onNewChat: () => void;
  onUseTopic: (title: string) => void;
}

const loadTrends = () => fetchTrends(undefined, 6).then(result => result.trends);
const workStatus: Record<string, string> = { draft: '草稿', ready: '待发布', published: '已发布' };
const shortDate = new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' });
const weekDay = new Intl.DateTimeFormat('zh-CN', { weekday: 'short' });

function recentFiles(roots: OutputNode[]) {
  const files: { file: OutputNode; project: string }[] = [];
  function visit(node: OutputNode, project: string) {
    if (node.type === 'file') files.push({ file: node, project });
    else node.children?.forEach(child => visit(child, project));
  }
  roots.forEach(root => visit(root, root.type === 'dir' ? root.meta?.title || root.name : ''));
  return files.sort((a,b) => (b.file.mtime || 0) - (a.file.mtime || 0));
}

function useDeskList<T>(read: () => Promise<T[]>) {
  const [items, setItems] = useState<T[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let current = true;
    read().then(rows => { if (current) setItems(rows); }).catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, [read, revision]);
  const retry = () => { setFailed(false); setRevision(value => value + 1); };
  return { items: items ?? [], ready: items !== null, failed, retry };
}

function ListNotice({ ready, failed, retry, empty }: { ready: boolean; failed: boolean; retry: () => void; empty: string }) {
  return <div className="desk-notice" role="status">{failed ? <>读取失败 <button className="desk-link" onClick={retry}>重试</button></> : ready ? empty : '正在读取…'}</div>;
}

export default function CreationDesk({ persona, session, onResume, onNavigate, onOpenDate, onNewChat, onUseTopic }: CreationDeskProps) {
  const works = useDeskList(fetchOutputs);
  const ideas = useDeskList(fetchIdeas);
  const agenda = useDeskList(fetchSchedule);
  const trends = useDeskList(loadTrends);
  const [shelf, setShelf] = useState<'works' | 'ideas'>('works');
  const topicList = ideas.items.filter(i => i.status === 'pending');
  const today = new Date();
  const todayKey = calendarDate(today);
  const days = Array.from({ length: 7 }, (_, n) => new Date(today.getFullYear(), today.getMonth(), today.getDate() + n));
  const upcoming = agenda.items.filter(it => it.date >= todayKey && it.status !== 'published')
    .sort((a,b) => a.date.localeCompare(b.date) || (a.time || '').localeCompare(b.time || ''));
  const project = works.items[0];
  const files = useMemo(() => recentFiles(works.items), [works.items]);
  const title = session?.title || project?.meta?.title || project?.name;
  const workHref = (path: string) => '#/outputs/' + encodeURIComponent(path);
  const studioPersona = session ? session.persona : persona;
  const sources = trends.items.filter(group => group.items.length > 0);
  const showWorks = shelf === 'works';
  const library = showWorks ? works : ideas;

  return <>
    <nav className="desk-toolstrip" aria-label="创作快捷入口">
      {studioTools.map(({page, Icon, label, action}) => <button key={page} onClick={() => onNavigate(page)}>
        <span className="desk-tool-mark"><Icon size={17}/></span>
        <span><strong>{label}</strong><small>{action}</small></span><IconChevron size={12}/>
      </button>)}
    </nav>
    <div className="desk-columns">

      <section className="desk-focus" aria-label="当前创作">
        <div className="dash-cover-copy">
          <div className="desk-focus-label">{session ? <IconChat size={15} /> : <IconFile size={15} />}
            {session ? '上次的创作对话' : project ? '最近编辑的作品' : '开始创作'}
          </div>
          <h2>{title || (works.ready || works.failed ? '想写点什么？' : '正在读取作品…')}</h2>
          {(title || studioPersona) && <p className="desk-focus-meta">{[
            studioPersona, session ? session.messages.length + ' 条对话消息' : project?.meta?.platform,
            !session && project?.meta?.status ? workStatus[project.meta.status] || project.meta.status : '',
            !session && project?.mtime ? shortDate.format(project.mtime * 1000) + '更新' : '',
          ].filter(Boolean).join(' · ')}</p>}
          <div className="dash-cover-actions">
            {session ? <button className="studio-start" onClick={() => onResume(session.id)}>继续对话 <IconChevron size={14} /></button>
              : project ? <a className="studio-start" href={workHref(project.path)}>打开作品 <IconChevron size={14} /></a> : null}
            <button className={title ? 'studio-link' : 'studio-start'} onClick={onNewChat}><IconNewChat size={15} />新建创作</button>
          </div>
        </div>
        <div className="studio-art" aria-hidden="true"><img src="./static/studio-still-life.webp" alt="" /></div>
      </section>

      <section className="desk-section desk-agenda">
        <header className="desk-section-head"><h2>发布日程</h2><button className="desk-link" onClick={() => onNavigate('calendar')}>内容日历 <IconChevron size={12}/></button></header>
        <div className="desk-week" role="group" aria-label="未来七天的日历">
          {days.map((date, index) => {
            const key = calendarDate(date);
            const count = agenda.items.filter(it => it.date === key).length;
            return <button key={key} className={index === 0 ? 'is-today' : ''} aria-current={index === 0 ? 'date' : undefined}
              aria-label={key + (count ? '，' + count + ' 项安排' : '，查看日历')} onClick={() => onOpenDate(key)}>
              <small>{index === 0 ? '今天' : weekDay.format(date).replace('周','')}</small>
              <strong>{date.getDate()}</strong><i className={count ? 'has-items' : ''} aria-hidden="true" />
            </button>;
          })}
        </div>
        {upcoming.slice(0,3).map(it => <button key={it.id} className="desk-item desk-agenda-row" onClick={() => onOpenDate(it.date)}>
          <time dateTime={it.date}>{it.date === todayKey ? '今天' : it.date.slice(5).replace('-','/')}</time>
          <span className="desk-row-text"><strong>{it.title}</strong><small>{[it.time,it.platform,it.kind === 'event' ? '平台活动' : ''].filter(Boolean).join(' · ')}</small></span>
        </button>)}
        {!upcoming.length && <ListNotice {...agenda} empty="近期没有待发布的内容。"/>}
        <button className="desk-publish" onClick={() => onNavigate('publish')}><IconPublish size={15}/>进入发布中心 <IconChevron size={12}/></button>
      </section>

      <section className="desk-section desk-inspiration">
        <header className="desk-section-head"><h2>选题灵感</h2><button className="desk-link" onClick={() => onNavigate('trends')}>热点雷达 <IconChevron size={12}/></button></header>
        <div className="desk-feeds">{sources.map(source => <section className="desk-feed" key={source.platform}>
          <h3>{source.label}{source.stale && <small>缓存</small>}</h3>
          {source.items.slice(0,6).map(item => <button className="desk-headline" key={item.id}
            onClick={() => onUseTopic(item.title)} aria-label={'用这个热点写初稿：' + item.title}>
            <strong>{item.title}</strong><span className="desk-headline-action">写初稿</span>
          </button>)}
        </section>)}</div>
        {!sources.length && <ListNotice {...trends} empty={trends.items.some(g => g.error) ? '数据源暂不可用，可到热点雷达查看。' : '暂无可用热点。'}/>}
        <button className="desk-link desk-breakdown" onClick={() => onNavigate('breakdown')}><IconSkills size={14}/>拆解参考文案 <IconChevron size={12}/></button>
      </section>

      <section className="desk-section desk-library" aria-label="最近文件与待做选题">
        <header className="desk-section-head">
          <div className="desk-shelf-switch" role="group" aria-label="查看创作资料">
            <button aria-pressed={showWorks} onClick={() => setShelf('works')}>最近文件{works.ready && <small>{files.length}</small>}</button>
            <button aria-pressed={!showWorks} onClick={() => setShelf('ideas')}>待做选题{ideas.ready && <small>{topicList.length}</small>}</button>
          </div>
          <button className="desk-link" onClick={() => onNavigate(showWorks ? 'outputs' : 'ideas')}>{showWorks ? '内容库' : '选题库'} <IconChevron size={12}/></button>
        </header>
        {showWorks ? files.slice(0,5).map(({file,project: projectName}) => <a key={file.path} className="desk-item dash-output" href={workHref(file.path)}>
          <span className="desk-file"><IconFile size={16}/></span>
          <span className="desk-row-text"><strong>{file.name}</strong>{projectName && <small>{projectName}</small>}</span>
          <IconChevron size={12}/>
        </a>) : topicList.slice(0,5).map(idea => <button key={idea.id} className="desk-item" onClick={() => onUseTopic(idea.title)}>
          <span className="desk-row-text"><strong>{idea.title}</strong>{idea.source && <small>{idea.source}</small>}</span><span className="desk-row-action">开始写</span>
        </button>)}
        {!(showWorks ? files : topicList).length && <ListNotice {...library} empty={showWorks ? '还没有创作文件。' : '还没有待做选题。可以从热点中挑一个。'}/>}
      </section>
  </div></>;
}
