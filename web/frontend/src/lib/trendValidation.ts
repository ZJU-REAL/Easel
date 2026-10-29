import type { TrendGroup, TrendItem, TrendSource, TrendManagedSource } from './api';

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Obj : null;
// Strip controls before display; the expression deliberately matches control characters.
// eslint-disable-next-line no-control-regex
const text = (v: unknown, max: number) => typeof v === 'string' ? v.slice(0, max).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '') : '';
const id = (v: unknown) => typeof v === 'string' && /^[a-z0-9][a-z0-9_-]{0,63}$/.test(v) ? v : '';
const date = (v: unknown) => typeof v === 'string' && v.length <= 64 && Number.isFinite(Date.parse(v)) ? v : null;
export const trendLabel = (v: unknown) => text(v, 80).replace(/(?:\s*[·•|]\s*(?:python|http|rss|atom))+$/i, '').trim() || '未命名来源';
const warnings = (v: unknown) => Array.isArray(v) ? v.filter((s): s is string => typeof s === 'string').slice(0, 20).map(s => text(s, 240)) : [];
const rows = (v: unknown) => Array.isArray(v) ? v.slice(0, 70) : [];

function version(value: unknown): Obj {
  const data = obj(value);
  if (!data || data.version !== 1) throw new Error('热点接口响应格式异常，请稍后重试。');
  return data;
}

export function parseTrendSources(value: unknown) {
  const data = version(value);
  if (!Array.isArray(data.sources)) throw new Error('数据源列表格式异常。');
  const seen = new Set<string>();
  const sources: TrendSource[] = [];
  for (const row of rows(data.sources)) {
    const source = obj(row);
    if (!source || !id(source.id) || seen.has(String(source.id)) || !['python', 'http', 'rss'].includes(String(source.type))) continue;
    seen.add(String(source.id));
    sources.push({ id: String(source.id), label: trendLabel(source.label), type: source.type as TrendSource['type'],
      default: source.default === true, refresh_seconds: typeof source.refresh_seconds === 'number' && Number.isFinite(source.refresh_seconds) ? source.refresh_seconds : 300 });
  }
  return { version: 1, sources, warnings: warnings(data.warnings) };
}

function item(value: unknown): TrendItem | null {
  const row = obj(value);
  if (!row || typeof row.title !== 'string' || !row.title.trim()) return null;
  const title = text(row.title, 1000);
  let url = '';
  try {
    if (typeof row.url === 'string' && row.url.length <= 8192 && !/\s|\\/.test(row.url)) {
      const parsed = new URL(row.url);
      if (['http:', 'https:'].includes(parsed.protocol) && !parsed.username && !parsed.password) url = parsed.href;
    }
  } catch { /* Invalid links remain non-clickable. */ }
  const heat = obj(row.heat);
  return { id: text(row.id, 512) || url || title, title, url, published_at: date(row.published_at),
    hot: text(row.hot, 128), heat: { value: heat && typeof heat.value === 'number' && Number.isFinite(heat.value) ? heat.value : null,
      text: text(heat?.text, 128), unit: text(heat?.unit, 32) } };
}

export function parseTrends(value: unknown) {
  const data = version(value);
  if (!Array.isArray(data.trends)) throw new Error('热点列表格式异常。');
  const seen = new Set<string>();
  const trends: TrendGroup[] = [];
  for (const value of rows(data.trends)) {
    const row = obj(value);
    if (!row || !id(row.platform) || seen.has(String(row.platform))) continue;
    seen.add(String(row.platform));
    const items: TrendItem[] = [];
    const itemIds = new Set<string>();
    if (Array.isArray(row.items)) for (const raw of row.items.slice(0, 30)) {
      const normalized = item(raw);
      if (normalized && !itemIds.has(normalized.id)) { itemIds.add(normalized.id); items.push(normalized); }
    }
    const error = obj(row.error);
    const valid = Array.isArray(row.items);
    trends.push({ platform: String(row.platform), label: trendLabel(row.label), items,
      ok: valid && row.ok === true, status: valid && ['fresh', 'stale', 'error'].includes(String(row.status)) ? row.status as TrendGroup['status'] : 'error',
      stale: row.stale === true, fetched_at: date(row.fetched_at), last_attempt_at: typeof row.last_attempt_at === 'number' && Number.isFinite(row.last_attempt_at) ? row.last_attempt_at : 0,
      error: !valid ? { code: 'invalid_response', message: '该来源返回了异常数据，已忽略。' } : error ?
        { code: text(error.code, 64) || 'collector_failed', message: text(error.message, 240) || '采集失败' } : null });
  }
  return { version: 1, trends, updated: typeof data.updated === 'number' && Number.isFinite(data.updated) && data.updated >= 0 && data.updated < 253402300800 ? data.updated : 0,
    warnings: warnings(data.warnings) };
}

export function parseTrendManagement(value: unknown) {
  const data = obj(value);
  if (!data || !Array.isArray(data.sources) || !Array.isArray(data.scripts)) throw new Error('数据源管理响应异常。');
  const sources: TrendManagedSource[] = [];
  const seen = new Set<string>();
  for (const raw of rows(data.sources)) {
    const row = obj(raw);
    if (!row || !id(row.id) || seen.has(String(row.id))) continue;
    seen.add(String(row.id));
    sources.push({ id: String(row.id), label: trendLabel(row.label), type: ['python', 'http', 'rss'].includes(String(row.type)) ? row.type as TrendSource['type'] : 'unknown',
      enabled: row.enabled === true, default: row.default === true, builtin: row.builtin === true });
  }
  const scripts = rows(data.scripts).flatMap(raw => { const row = obj(raw); return row && id(row.id) ? [{ id: String(row.id), label: trendLabel(row.label) }] : []; });
  return { sources, scripts, warnings: warnings(data.warnings), python_template: text(data.python_template, 65536),
    script_max_bytes: typeof data.script_max_bytes === 'number' && data.script_max_bytes >= 1024 && data.script_max_bytes <= 65536 ? data.script_max_bytes : 65536 };
}
