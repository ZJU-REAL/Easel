import { useState, useEffect, useCallback, useMemo } from 'react';
import { fetchSchedule, createSchedule, updateSchedule, deleteSchedule, fetchScheduleContext } from '../lib/api';
import type { ScheduleItem, ScheduleInput, ScheduleContext } from '../lib/api';
import { IconCalendar, IconTrash, IconChevron } from './icons';

const STATUS_META: Record<string, { label: string; color: string }> = {
  idea: { label: '选题', color: 'var(--text-tertiary)' },
  draft: { label: '草稿', color: 'var(--layer-plan)' },
  scheduled: { label: '待发', color: 'var(--layer-attribute)' },
  published: { label: '已发', color: 'var(--layer-publish)' },
};
const EVENT_COLOR = 'var(--layer-discover)';
const EVENT_TYPES = ['节日', '电商', '平台活动', '行业'];
const SOURCE_LABEL: Record<string, string> = {
  chat: '对话页', 'publish-page': '发布页', manual: '手动', scheduler: '排期',
};
const PLATFORMS = ['小红书', '抖音', 'B站', '微信视频号', '快手', '公众号', '微博', '知乎'];
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
type Filter = 'all' | 'content' | 'event';

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
const kindOf = (it: ScheduleItem) => (it.kind === 'event' ? 'event' : 'content');
const MAX_VISIBLE = 3;   // 每格最多显示几条，超出折叠成「+N 更多」→ 点开当天详情
const EMPTY: ScheduleInput = {
  title: '', date: '', platform: '', time: '', status: 'idea', note: '',
  kind: 'content', url: '', source: 'manual', event_type: '', end_date: '',
};

export default function CalendarPage() {
  const today = useMemo(() => new Date(), []);
  const [cursor, setCursor] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1));
  const [items, setItems] = useState<ScheduleItem[]>([]);
  const [editing, setEditing] = useState<ScheduleItem | null>(null);   // 现有项
  const [form, setForm] = useState<ScheduleInput | null>(null);        // 弹窗表单（null=关闭）
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [ctx, setCtx] = useState<ScheduleContext | null>(null);
  const [showSuggest, setShowSuggest] = useState(true);
  const [dayView, setDayView] = useState<string | null>(null);   // 展开查看某天全部（date，null=关闭）

  const load = useCallback(() => {
    fetchSchedule().then(setItems).catch(() => {});
    fetchScheduleContext(14).then(setCtx).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const visible = useMemo(
    () => (filter === 'all' ? items : items.filter((it) => kindOf(it) === filter)),
    [items, filter]);

  // 每格：活动（事件）在上、内容在下
  const byDate = useMemo(() => {
    const m: Record<string, { events: ScheduleItem[]; content: ScheduleItem[] }> = {};
    for (const it of visible) {
      const bucket = (m[it.date] ||= { events: [], content: [] });
      (kindOf(it) === 'event' ? bucket.events : bucket.content).push(it);
    }
    return m;
  }, [visible]);

  // 构造当月网格（周一开头）
  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const startOffset = (first.getDay() + 6) % 7;  // 周一=0
    const start = new Date(first); start.setDate(1 - startOffset);
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start); d.setDate(start.getDate() + i); return d;
    });
  }, [cursor]);

  const openNew = (date: string) => {
    setDayView(null);
    setEditing(null);
    setForm({ ...EMPTY, date, kind: filter === 'event' ? 'event' : 'content' });
  };
  const openEdit = (it: ScheduleItem) => { setDayView(null); setEditing(it); setForm({ ...EMPTY, ...it }); };
  const close = () => { setForm(null); setEditing(null); };

  // 单条 chip（活动=色条，内容=按状态上色的圆点），日历格与当天详情共用
  const renderChip = (it: ScheduleItem) => {
    if (kindOf(it) === 'event') {
      return (
        <div key={it.id} className="cal-event is-event"
          title={it.event_type ? `${it.event_type}·${it.title}` : it.title}
          style={{ ['--ev' as string]: EVENT_COLOR }}
          onClick={(e) => { e.stopPropagation(); openEdit(it); }}>
          <span className="cal-event-dot" />
          <span className="cal-event-title">{it.title}</span>
        </div>
      );
    }
    return (
      <div key={it.id} className="cal-event" title={it.title}
        style={{ ['--ev' as string]: STATUS_META[it.status]?.color || 'var(--text-tertiary)' }}
        onClick={(e) => { e.stopPropagation(); openEdit(it); }}>
        <span className="cal-event-dot" />
        <span className="cal-event-title">{it.platform ? `[${it.platform}] ` : ''}{it.title}</span>
        {it.status === 'published' && it.source && SOURCE_LABEL[it.source]
          && <span className="cal-src">{SOURCE_LABEL[it.source]}</span>}
      </div>
    );
  };

  const save = async () => {
    if (!form || !form.title.trim() || !form.date) return;
    setSaving(true);
    try {
      if (editing) await updateSchedule(editing.id, form);
      else await createSchedule(form);
      close(); load();
    } finally { setSaving(false); }
  };
  const remove = async () => {
    if (!editing) return;
    setSaving(true);
    try { await deleteSchedule(editing.id); close(); load(); } finally { setSaving(false); }
  };

  const monthLabel = `${cursor.getFullYear()} 年 ${cursor.getMonth() + 1} 月`;
  const shift = (n: number) => setCursor((c) => new Date(c.getFullYear(), c.getMonth() + n, 1));
  const todayStr = ymd(today);
  const isEvent = form?.kind === 'event';
  const suggestions = ctx?.suggestions || [];

  return (
    <div className="page-scroll calendar-page">
      <div className="page-head">
        <div>
          <h1 className="page-title"><IconCalendar size={21} /> 内容日历</h1>
          <p className="page-subtitle">每天各平台发什么一目了然——发布自动落库，可记录排期与平台活动。</p>
        </div>
        <div className="cal-nav">
          <button className="btn btn-sm" onClick={() => shift(-1)}><span style={{ transform: 'rotate(180deg)', display: 'inline-flex' }}><IconChevron size={14} /></span></button>
          <button className="btn btn-sm" onClick={() => setCursor(new Date(today.getFullYear(), today.getMonth(), 1))}>本月</button>
          <span className="cal-month">{monthLabel}</span>
          <button className="btn btn-sm" onClick={() => shift(1)}><IconChevron size={14} /></button>
        </div>
      </div>

      {showSuggest && suggestions.length > 0 && (
        <div className="cal-suggest">
          <div className="cal-suggest-head">
            <span>📅 日历建议（近 {ctx?.window_days ?? 14} 天）</span>
            <button className="icon-btn" onClick={() => setShowSuggest(false)}>×</button>
          </div>
          <ul>{suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
      )}

      <div className="cal-legend">
        {Object.entries(STATUS_META).map(([k, m]) => (
          <span key={k} className="cal-legend-item">
            <span className="cal-legend-swatch" style={{ ['--sw' as string]: m.color }} />{m.label}
          </span>
        ))}
        <span className="cal-legend-item">
          <span className="cal-legend-swatch sq" style={{ ['--sw' as string]: EVENT_COLOR }} />平台活动
        </span>
        <span className="cal-legend-filter">
          {(['all', 'content', 'event'] as Filter[]).map((f) => (
            <button key={f} className={`chip ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
              {f === 'all' ? '全部' : f === 'content' ? '内容' : '活动'}
            </button>
          ))}
        </span>
      </div>

      <div className="cal-grid-head">
        {WEEKDAYS.map((w) => <div key={w} className="cal-wd">周{w}</div>)}
      </div>
      <div className="cal-grid">
        {cells.map((d, i) => {
          const ds = ymd(d);
          const inMonth = d.getMonth() === cursor.getMonth();
          const bucket = byDate[ds] || { events: [], content: [] };
          const dayItems = [...bucket.events, ...bucket.content];  // 活动在前
          const shown = dayItems.slice(0, MAX_VISIBLE);
          const hidden = dayItems.length - shown.length;
          return (
            <div key={i} className={`cal-cell ${inMonth ? '' : 'dim'} ${ds === todayStr ? 'today' : ''}`}
              onClick={() => (dayItems.length ? setDayView(ds) : openNew(ds))}>
              <div className="cal-daynum">{d.getDate()}</div>
              <div className="cal-events">
                {shown.map(renderChip)}
                {hidden > 0 && (
                  <button className="cal-more" onClick={(e) => { e.stopPropagation(); setDayView(ds); }}>
                    +{hidden} 更多
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {dayView && (() => {
        const b = byDate[dayView] || { events: [], content: [] };
        const list = [...b.events, ...b.content];
        return (
          <div className="overlay" onClick={() => setDayView(null)}>
            <div className="modal" style={{ width: 420, maxWidth: '100%' }} onClick={(e) => e.stopPropagation()}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <h3 style={{ margin: 0 }}>{dayView}（{list.length} 项）</h3>
                <button className="icon-btn" onClick={() => setDayView(null)}>×</button>
              </div>
              <div className="cal-dayview-list">
                {list.map(renderChip)}
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
                <button className="btn btn-sm btn-primary" onClick={() => openNew(dayView)}>+ 新增</button>
              </div>
            </div>
          </div>
        );
      })()}

      {form && (
        <div className="overlay" onClick={close}>
          <div className="modal" style={{ width: 440, maxWidth: '100%' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <h3 style={{ margin: 0 }}>{editing ? '编辑' : '新增'}{isEvent ? '平台活动' : '排期'}</h3>
              <button className="icon-btn" onClick={close}>×</button>
            </div>
            <label className="field-label">类型</label>
            <div style={{ display: 'flex', gap: 7 }}>
              <button className={`chip ${!isEvent ? 'active' : ''}`}
                onClick={() => setForm({ ...form, kind: 'content' })}>内容 / 发布</button>
              <button className={`chip ${isEvent ? 'active' : ''}`}
                onClick={() => setForm({ ...form, kind: 'event', status: 'idea' })}>平台活动</button>
            </div>
            <label className="field-label">标题 *</label>
            <input className="field" value={form.title} autoFocus placeholder={isEvent ? '活动/节点名称' : '要发什么内容'}
              onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <div style={{ display: 'flex', gap: 10 }}>
              <div style={{ flex: 1 }}>
                <label className="field-label">{isEvent ? '开始日期 *' : '日期 *'}</label>
                <input className="field" type="date" value={form.date}
                  onChange={(e) => setForm({ ...form, date: e.target.value })} />
              </div>
              {isEvent ? (
                <div style={{ flex: 1 }}>
                  <label className="field-label">结束日期</label>
                  <input className="field" type="date" value={form.end_date || ''}
                    onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
                </div>
              ) : (
                <div style={{ width: 120 }}>
                  <label className="field-label">时间</label>
                  <input className="field" type="time" value={form.time}
                    onChange={(e) => setForm({ ...form, time: e.target.value })} />
                </div>
              )}
            </div>
            {isEvent ? (
              <>
                <label className="field-label">活动类型</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                  {EVENT_TYPES.map((t) => (
                    <button key={t} className={`chip ${form.event_type === t ? 'active' : ''}`}
                      onClick={() => setForm({ ...form, event_type: form.event_type === t ? '' : t })}>{t}</button>
                  ))}
                </div>
                <label className="field-label">关联平台（可选）</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                  {PLATFORMS.map((p) => (
                    <button key={p} className={`chip ${form.platform === p ? 'active' : ''}`}
                      onClick={() => setForm({ ...form, platform: form.platform === p ? '' : p })}>{p}</button>
                  ))}
                </div>
              </>
            ) : (
              <>
                <label className="field-label">平台</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                  {PLATFORMS.map((p) => (
                    <button key={p} className={`chip ${form.platform === p ? 'active' : ''}`}
                      onClick={() => setForm({ ...form, platform: form.platform === p ? '' : p })}>{p}</button>
                  ))}
                </div>
                <label className="field-label">状态</label>
                <div style={{ display: 'flex', gap: 7 }}>
                  {Object.entries(STATUS_META).map(([k, m]) => (
                    <button key={k} className={`chip ${form.status === k ? 'active' : ''}`}
                      onClick={() => setForm({ ...form, status: k })}>{m.label}</button>
                  ))}
                </div>
              </>
            )}
            <label className="field-label">备注</label>
            <textarea className="field" style={{ minHeight: 60 }} value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })} />
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 18 }}>
              {editing
                ? <button className="btn btn-sm btn-danger" onClick={remove} disabled={saving}><IconTrash size={13} /> 删除</button>
                : <span />}
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-sm" onClick={close}>取消</button>
                <button className="btn btn-sm btn-primary" onClick={save} disabled={saving || !form.title.trim() || !form.date}>
                  {saving ? '保存中…' : '保存'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
