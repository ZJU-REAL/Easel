function getBasePath(): string {
  const path = window.location.pathname;
  const cleaned = path.replace(/\/index\.html$/, '').replace(/\/$/, '');
  return cleaned;
}

const BASE = getBasePath();

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, options);
  if (!res.ok) {
    // 优先显示后端返回的实质错误信息（FastAPI 的 {detail}），而不是无意义的 "API error: 400"
    let detail = '';
    try {
      const j = await res.json();
      detail = (j && (j.detail || j.message)) || '';
    } catch {
      /* 响应体不是 JSON，忽略 */
    }
    throw new Error(detail || `请求失败（${res.status} ${res.statusText}）`);
  }
  return res.json() as Promise<T>;
}

export interface StatusResponse {
  gateway: boolean;
  skills: SkillItem[];
  personas: PersonaItem[];
}

export interface PersonaItem {
  name: string;
  description: string;
}

export interface PersonaDetail {
  name: string;
  content: string;
}

export interface SkillItem {
  name: string;
  description: string;
  layer: string;
  needsApi: boolean;
  apiConfigured: boolean;
}

export interface ApiKeySpec {
  env: string;
  label: string;
  required: boolean;
  secret: boolean;
  configured: boolean;
  masked: string;   // 脱敏值或非 secret 明文
  choices: string[];
}

export interface ApiProviderSpec {
  id: string;
  name: string;
  keys: ApiKeySpec[];
}

export interface ApiSpec {
  label: string;
  settings: ApiKeySpec[];
  providers: ApiProviderSpec[];
}

export interface SkillDetail {
  name: string;
  layer: string;
  description: string;
  body: string;
  needsApi: boolean;
  apiConfigured: boolean;
  apiSpec: ApiSpec | null;
}

export type FileKind = 'text' | 'image' | 'video' | 'audio' | 'binary';

/** 顶层项目目录的 .easel.json 展示头（供内容库富展示）。 */
export interface OutputMeta {
  title?: string;
  summary?: string;
  platform?: string;
  kind?: string;             // article|xhs-note|video|cards|poster|audio|other
  status?: string;           // draft|ready|published
  tags?: string[];
  cover?: string;            // outputs 下相对路径（后端已解析存在性）
  deliverables?: string[];   // 成品文件名（项目根相对）
  deliverablePaths?: string[];  // 成品的 outputs 相对路径（后端已解析存在性）
}

/** 产物树节点：文件或目录（目录带 children，可无限嵌套点开）。 */
export interface OutputNode {
  name: string;
  type: 'dir' | 'file';
  path: string;              // outputs 下的相对路径，如 "short-drama/监控诡影/episodes/ep01"
  mtime?: number;
  kind?: FileKind;           // 仅 file
  size?: number;             // 仅 file
  children?: OutputNode[];   // 仅 dir
  fileCount?: number;        // 仅 dir：递归文件数
  meta?: OutputMeta;         // 仅顶层项目 dir
}

/** @deprecated 用 OutputNode（type==='file'）。保留别名减少改动面。 */
export type OutputFile = OutputNode;

export interface OutputContent {
  path: string;
  content: string;
  kind: FileKind;
  isBinary: boolean;
}

export interface SkillResponse {
  response: string;
}

export interface ProfileBuildResponse {
  created: boolean;
  name: string;
  async?: boolean;
  status?: string;
  log?: string;
}

export interface ProfileBuildStatus {
  state: 'running' | 'done' | 'failed' | 'unknown';
  log: string;
}

export function fetchStatus(): Promise<StatusResponse> {
  return request<StatusResponse>('/api/status');
}

export function fetchPersonas(): Promise<PersonaItem[]> {
  return request<PersonaItem[]>('/api/personas');
}

export function fetchPersonaDetail(name: string): Promise<PersonaDetail> {
  return request<PersonaDetail>(`/api/persona/${encodeURIComponent(name)}`);
}

export interface PersonaFile {
  filename: string;
  content: string;
}

export function fetchPersonaFiles(name: string): Promise<{ name: string; files: PersonaFile[] }> {
  return request(`/api/persona/${encodeURIComponent(name)}/files`);
}

export function savePersonaFile(name: string, filename: string, content: string): Promise<{ ok: boolean }> {
  return request(`/api/persona/${encodeURIComponent(name)}/file`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content }),
  });
}

export function deletePersona(name: string): Promise<{ ok: boolean; deleted: string }> {
  return request(`/api/persona/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

// ---- 热点雷达 ----
export interface TrendItem { title: string; hot: string; url: string; }
export interface TrendGroup { platform: string; label: string; items: TrendItem[]; }
export function fetchTrends(platforms: string, limit = 12): Promise<{ trends: TrendGroup[]; updated: number }> {
  return request(`/api/trends?platforms=${encodeURIComponent(platforms)}&limit=${limit}`);
}

// ---- 内容排期 ----
export interface ScheduleItem {
  id: string; title: string; date: string; platform: string;
  time: string; status: string; note: string;
  kind?: string;          // content（内容/发布）| event（平台活动/节日/特殊日期）
  url?: string;           // 已发布链接
  source?: string;        // manual | publish-page | chat | scheduler
  event_type?: string;    // event 专属：节日/电商/平台活动/行业
  end_date?: string;      // event 专属：活动区间结束日
}
export type ScheduleInput = Omit<ScheduleItem, 'id'>;
export interface ScheduleContext {
  today?: string; window_days?: number; published_recent?: number;
  per_platform?: { platform: string; recent_count: number; last_date: string | null; days_since_last: number | null }[];
  upcoming_schedules?: ScheduleItem[];
  upcoming_events?: ScheduleItem[];
  suggestions?: string[];
}
export function fetchSchedule(): Promise<ScheduleItem[]> {
  return request('/api/schedule');
}
export function fetchScheduleContext(days = 14): Promise<ScheduleContext> {
  return request(`/api/schedule/context?days=${days}`);
}
export function createSchedule(item: ScheduleInput): Promise<ScheduleItem> {
  return request('/api/schedule', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item),
  });
}
export function updateSchedule(id: string, item: ScheduleInput): Promise<ScheduleItem> {
  return request(`/api/schedule/${encodeURIComponent(id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item),
  });
}
export function deleteSchedule(id: string): Promise<{ ok: boolean }> {
  return request(`/api/schedule/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

// ---- 选题库 ----
export interface Idea {
  id: string; title: string; note: string; source: string; status: string; created: number;
}
export type IdeaInput = { title: string; note?: string; source?: string; status?: string };
export function fetchIdeas(): Promise<Idea[]> { return request('/api/ideas'); }
export function createIdea(item: IdeaInput): Promise<Idea> {
  return request('/api/ideas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item) });
}
export function updateIdea(id: string, item: IdeaInput): Promise<Idea> {
  return request(`/api/ideas/${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item) });
}
export function deleteIdea(id: string): Promise<{ ok: boolean }> {
  return request(`/api/ideas/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function fetchSkills(): Promise<SkillItem[]> {
  return request<SkillItem[]>('/api/skills');
}

export function fetchSkillDetail(name: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/api/skill/${encodeURIComponent(name)}`);
}

/** 保存 API key 到项目根 .env（仅注册表内变量）。返回各需 API 的 skill 是否已就绪。 */
export function saveEnv(updates: Record<string, string>): Promise<{ ok: boolean; skills: Record<string, boolean> }> {
  return request('/api/env', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ updates }),
  });
}

export function executeSkill(skill: string, input: string, persona?: string): Promise<SkillResponse> {
  return request<SkillResponse>('/api/skill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill, input, persona: persona || undefined }),
  });
}

/** 一次性 agent 任务（返回整段 markdown）——用于一稿多改 / 爆款拆解 / 发布预检等工具型调用。 */
export function runAgent(message: string, persona?: string): Promise<{ response: string }> {
  return request('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, persona: persona || undefined }),
  });
}

/** 从表单构建画像（首次引导）。后端写基线 + agent 分析社媒链接增强。 */
export function buildProfile(name: string, form: Record<string, unknown>): Promise<ProfileBuildResponse> {
  return request<ProfileBuildResponse>('/api/profile/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, form }),
  });
}

/** 轮询画像 AI 增强进度（构建异步化后用）。 */
export function profileBuildStatus(name: string): Promise<ProfileBuildStatus> {
  return request<ProfileBuildStatus>(`/api/profile/build/status/${encodeURIComponent(name)}`);
}

export function fetchOutputs(): Promise<OutputNode[]> {
  return request<OutputNode[]>('/api/outputs');
}

export function fetchOutputContent(path: string): Promise<OutputContent> {
  return request<OutputContent>(`/api/output/${path.split('/').map(encodeURIComponent).join('/')}`);
}

/** 媒体文件（图片/视频/音频/HTML/PDF）的原样 URL，用于 <img>/<video>/iframe/下载。 */
export function mediaUrl(path: string): string {
  return `${BASE}/api/media/${path.split('/').map(encodeURIComponent).join('/')}`;
}

/** 删除内容库里的文件或整个项目目录（系统数据受保护，后端会拒）。 */
export function deleteOutput(path: string): Promise<{ ok: boolean; deleted: string }> {
  return request(`/api/output/${path.split('/').map(encodeURIComponent).join('/')}`, { method: 'DELETE' });
}

export interface UploadedFile { id: string; name: string; path: string; }
/** 上传素材到当前会话的隔离 inbox，返回后端可校验的附件引用。 */
export async function uploadFiles(files: File[], sessionId: string): Promise<UploadedFile[]> {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  fd.append('sessionId', sessionId);
  const r = await request<{ ok: boolean; files: UploadedFile[] }>('/api/upload', { method: 'POST', body: fd });
  return r.files;
}

export function deleteSession(sessionKey: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/session/${encodeURIComponent(sessionKey)}`, {
    method: 'DELETE',
  });
}

// ---- 账号登录 ----
export interface AccountItem {
  platform: string;
  name: string;
  backend: string;      // xhs | web | biliup | unsupported
  supported: boolean;
  loggedIn: boolean;
  note: string;
}

export interface LoginStart {
  mode: 'qr' | 'terminal';
  state?: string;       // starting | qr_ready | success | expired | error | unknown
  message?: string;
  qr?: string;          // outputs 下相对路径，用 mediaUrl() 取图
}

export interface LoginStatus {
  mode: 'qr';
  state: string;
  message: string;
  qr: string;
  qrTs?: number;
}

export function fetchAccounts(): Promise<AccountItem[]> {
  return request<AccountItem[]>('/api/accounts');
}

export interface AccountWhoami {
  loggedIn: boolean;
  name: string;
  avatar: string;   // 头像 URL（http）或空
}

/** 真校验某平台登录态 + 拉昵称/头像（后端起 headless 浏览器，数秒）。 */
export function accountWhoami(platform: string): Promise<AccountWhoami> {
  return request<AccountWhoami>(`/api/accounts/${encodeURIComponent(platform)}/whoami`);
}

/** 退出登录：删该平台持久化登录态。 */
export function logoutAccount(platform: string): Promise<{ ok: boolean; deleted: string[] }> {
  return request(`/api/logout/${encodeURIComponent(platform)}`, { method: 'POST' });
}

export interface PublishResult {
  ok?: boolean;
  message: string;
  detail?: string;
  async?: boolean;   // true = 异步发布（抖音，可能触发短信验证），需轮询 publishStatus
  pending?: boolean;
}

/** 一键发布到某平台（真发布，--exec）。media 为 outputs 相对路径数组。
 * 抖音返回 {async:true}，需轮询 publishStatus；其他平台同步返回结果。 */
export function publishNow(
  platform: string,
  payload: { title: string; body: string; media: string[]; tags?: string },
): Promise<PublishResult> {
  return request<PublishResult>(`/api/publish/${encodeURIComponent(platform)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export interface PublishStatus {
  mode: 'publish';
  state: string;     // starting | sms_required | verifying | success | error | unknown
  message: string;
}

/** 轮询异步发布状态（抖音）。 */
export function publishStatus(platform: string): Promise<PublishStatus> {
  return request<PublishStatus>(`/api/publish/${encodeURIComponent(platform)}/status`);
}

/** 发布触发短信墙时回填验证码。 */
export function submitPublishSms(platform: string, code: string): Promise<{ ok: boolean }> {
  return request(`/api/publish/${encodeURIComponent(platform)}/sms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
}

export function startLogin(platform: string): Promise<LoginStart> {
  return request<LoginStart>(`/api/login/${encodeURIComponent(platform)}`, { method: 'POST' });
}

export function loginStatus(platform: string): Promise<LoginStatus> {
  return request<LoginStatus>(`/api/login/${encodeURIComponent(platform)}/status`);
}

// ---- 归因层：账号创作数据 ----
export interface AnalyticsPlatform {
  platform: string;
  name: string;
  loggedIn: boolean;
}

export interface AccountAnalytics {
  platform: string;
  name: string;
  nickname: string;
  loggedIn: boolean;
  followers: number | null;
  likes: number | null;
  following: number | null;
  posts: number | null;
  metrics: { label: string; value: string; vs: string }[];
  notes: { title: string; url: string; cover?: string; stat?: string }[];
  growth: Record<'last' | 'day' | 'week' | 'month' | 'year',
    { followers: number | null; likes: number | null; posts: number | null; since_days: number | null } | null>;
  fetched_at: number;
}

/** 支持抓数据的平台 + 各自登录态。 */
export function fetchAnalyticsPlatforms(): Promise<AnalyticsPlatform[]> {
  return request<AnalyticsPlatform[]>('/api/analytics/platforms');
}

/** 抓某平台已登录账号的创作数据（后端起 headless 浏览器，数秒）。 */
export function fetchAccountAnalytics(platform: string): Promise<AccountAnalytics> {
  return request<AccountAnalytics>(`/api/analytics/${encodeURIComponent(platform)}`);
}

/** 回填短信验证码（登录风控短信墙）：提交后 runner 读走填码继续登录。 */
export function submitLoginSms(platform: string, code: string): Promise<{ ok: boolean }> {
  return request(`/api/login/${encodeURIComponent(platform)}/sms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
}

/** 用户显式停止：终止后端正在跑的对话 agent，释放会话锁，令下一句能立刻发。 */
export function stopChat(sessionId: string): Promise<{ stopped: boolean }> {
  return request('/api/chat/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId }),
  });
}

export function streamChat(
  message: string,
  persona: string | undefined,
  sessionId: string,
  onToken: (chunk: string) => void,
  onDone: (sessionKey?: string) => void,
  onError: (err: Error) => void,
  onThinking?: (chunk: string) => void,
  onActivity?: (status: string) => void,
  onInterrupted?: () => void,
  turnId?: string,
  resumeOnly = false,
  onRecoveryUnavailable?: () => void,
  attachments: UploadedFile[] = [],
): AbortController {
  const controller = new AbortController();
  let lastEventId = 0;

  const consume = async (res: Response): Promise<boolean> => {
      if (!res.ok) {
        let detail = `Stream error: ${res.status}`;
        try {
          const payload = await res.json() as { detail?: string };
          if (payload.detail) detail = payload.detail;
        } catch { /* non-JSON error */ }
        const error = new Error(detail) as Error & { status?: number };
        error.status = res.status;
        throw error;
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';
      let currentEvent = '';
      let currentId = 0;
      let dataLines: string[] = [];

      const dispatch = () => {
        if (!currentEvent || dataLines.length === 0) return false;
        if (currentId > lastEventId) lastEventId = currentId;
        const data = dataLines.join('\n');
        if (currentEvent === 'token') {
          try { onToken(JSON.parse(data) as string); } catch { onToken(data); }
        } else if (currentEvent === 'thinking' && onThinking) {
          try { onThinking(JSON.parse(data) as string); } catch { onThinking(data); }
        } else if (currentEvent === 'activity' && onActivity) {
          try { onActivity(JSON.parse(data) as string); } catch { onActivity(data); }
        } else if (currentEvent === 'error') {
          let msg = '执行失败';
          try { msg = JSON.parse(data) as string; } catch { msg = data; }
          onError(new Error(msg));
          return true;
        } else if (currentEvent === 'done') {
          try { onDone((JSON.parse(data) as { sessionKey?: string }).sessionKey); } catch { onDone(); }
          return true;
        }
        return false;
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line === '') {
            if (dispatch()) return true;
            currentEvent = ''; currentId = 0; dataLines = [];
          } else if (line.startsWith('id:')) currentId = Number(line.slice(3).trim()) || 0;
          else if (line.startsWith('event:')) currentEvent = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
        }
      }
      buffer += decoder.decode();
      if (buffer) {
        for (const line of buffer.split(/\r?\n/)) {
          if (line.startsWith('id:')) currentId = Number(line.slice(3).trim()) || 0;
          else if (line.startsWith('event:')) currentEvent = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
        }
      }
      return dispatch();
  };

  void (async () => {
    const started = Date.now();
    let first = !resumeOnly;
    while (!controller.signal.aborted) {
      try {
        const res = first
          ? await fetch(`${BASE}/api/chat/stream`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ message, persona: persona || undefined, sessionId, turnId, attachments }),
              signal: controller.signal,
            })
          : await fetch(`${BASE}/api/chat/jobs/${encodeURIComponent(turnId || '')}/stream?after=${lastEventId}`, {
              signal: controller.signal,
            });
        if (!first && res.status === 404 && onRecoveryUnavailable) {
          onRecoveryUnavailable();
          return;
        }
        if (await consume(res)) return;
      } catch (err: unknown) {
        if (err instanceof Error && err.name === 'AbortError') return;
        const status = (err as Error & { status?: number })?.status;
        if (first && status && status >= 400 && status < 500) {
          onError(err instanceof Error ? err : new Error('请求失败'));
          return;
        }
      }
      first = false;
      // Backend chat runs may spend 5 minutes waiting for a session lock and then
      // run for 2 hours. Keep reconnecting for the same end-to-end budget.
      if (!turnId || Date.now() - started >= 130 * 60 * 1000) {
        onError(new Error('连接中断，自动重连超时'));
        return;
      }
      onInterrupted?.();
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  })();

  return controller;
}

/** 取某会话最近一轮的完整结果（SSE 断线后据此取回）。 */
export function fetchLastTurn(sessionId: string, turnId?: string): Promise<{ status: string; text: string; turn_id?: string }> {
  const query = turnId ? `?turn_id=${encodeURIComponent(turnId)}` : '';
  return request(`/api/chat/last/${encodeURIComponent(sessionId)}${query}`);
}
