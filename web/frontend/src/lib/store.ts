import type { UploadedFile } from './api';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  agentContent?: string; // 仅发给 Agent 的增强消息（如附件路径），不在对话页面展示
  attachments?: UploadedFile[]; // 结构化附件引用；仅用于请求/重试，不在消息气泡展示
  thinking?: string;   // 模型思考过程（隐思考），流式结束后持久保留
  activity?: string;   // 工具/执行活动步骤（换行分隔），持久保留
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  persona?: string;
  created: number;
  sessionKey?: string;  // OpenClaw 的 session key，用于后端删除
  pendingTurnId?: string; // 进行中的可重连 job；浏览器重开后继续按 eventId 续流
  archived?: boolean;   // 归档：从 History 主列表移到「已归档」区
}

/** 进行中的流式状态（存于 App，不随页面切换/ChatPage 卸载而丢失）。 */
export interface StreamState {
  content: string;
  thinking: string;
  activity: string;
}

/** 发布中心草稿：持久化到 localStorage，切页/刷新都不丢。 */
export interface PublishDraft {
  title: string;
  body: string;
  platforms: string[];
  overrides: Record<string, string>;
  tags: string;   // 话题标签，逗号分隔（小红书绑话题；其它平台按需写入）
}
const PUBLISH_KEY = 'easel_publish_draft';
const PREVIOUS_BRAND = ['post', 'craft'].join('');

// One-time reset after clearing the server-side OpenClaw session store.
const CHAT_RESET_KEY = 'easel_chat_reset_20260902';
if (!localStorage.getItem(CHAT_RESET_KEY)) {
  for (const key of [
    'easel_sessions',
    'easel-sessions',
    'easel_active_session',
    `${PREVIOUS_BRAND}_sessions`,
    `${PREVIOUS_BRAND}_active_session`,
  ]) {
    localStorage.removeItem(key);
  }
  for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
    const key = sessionStorage.key(i);
    if (key === 'easel_tab_session' || key?.startsWith('easel_pending_turn:')) {
      sessionStorage.removeItem(key);
    }
  }
  localStorage.setItem(CHAT_RESET_KEY, '1');
}

function readMigratedLocalValue(key: string, suffix: string): string | null {
  const current = localStorage.getItem(key);
  if (current !== null) return current;
  const previousKey = `${PREVIOUS_BRAND}_${suffix}`;
  const previous = localStorage.getItem(previousKey);
  if (previous !== null) {
    localStorage.setItem(key, previous);
    localStorage.removeItem(previousKey);
  }
  return previous;
}

const PUBLISH_DEFAULT: PublishDraft = {
  title: '', body: '', platforms: ['xiaohongshu', 'douyin'], overrides: {}, tags: '',
};
export function loadPublishDraft(): PublishDraft {
  try {
    const raw = readMigratedLocalValue(PUBLISH_KEY, 'publish_draft');
    if (!raw) return { ...PUBLISH_DEFAULT };
    return { ...PUBLISH_DEFAULT, ...(JSON.parse(raw) as PublishDraft) };
  } catch {
    return { ...PUBLISH_DEFAULT };
  }
}
export function savePublishDraft(d: PublishDraft): void {
  try { localStorage.setItem(PUBLISH_KEY, JSON.stringify(d)); } catch { /* quota */ }
}

const STORAGE_KEY = 'easel_sessions';
const ACTIVE_KEY = 'easel_active_session';
const MAX_SESSIONS = 100;
const TITLE_MAX_CHARS = 24;

/** 上次活跃会话 id：重开网页时据此续接上次对话（而不是丢进新空会话）。 */
export function loadActiveId(): string | null {
  try { return readMigratedLocalValue(ACTIVE_KEY, 'active_session'); } catch { return null; }
}
export function saveActiveId(id: string | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id);
    else localStorage.removeItem(ACTIVE_KEY);
  } catch { /* quota */ }
}

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function loadSessions(): ChatSession[] {
  try {
    const raw = readMigratedLocalValue(STORAGE_KEY, 'sessions');
    if (!raw) return [];
    const sessions = JSON.parse(raw) as ChatSession[];
    // 兼容旧版本：附件内部指令曾被直接存进用户消息，加载时拆出并隐藏。
    return sessions.map((session) => ({
      ...session,
      messages: session.messages.map((message) => {
        if (message.role !== 'user' || message.agentContent || !message.content.includes('【附件素材】')) {
          return message;
        }
        const [visible = ''] = message.content.split('【附件素材】', 1);
        return {
          ...message,
          content: visible.trim(),
          agentContent: message.content,
        };
      }),
    }));
  } catch {
    return [];
  }
}

/** 保存前清理：只保留最新 1 个空会话（避免空会话无限堆积），并封顶总数。 */
function prune(sessions: ChatSession[]): ChatSession[] {
  let keptEmpty = false;
  const pruned = sessions.filter((s) => {
    if (s.messages.length > 0) return true;
    if (keptEmpty) return false;
    keptEmpty = true;
    return true;
  });
  return pruned.slice(0, MAX_SESSIONS);
}

export function saveSessions(sessions: ChatSession[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prune(sessions)));
}

export function createSession(persona?: string): ChatSession {
  return {
    id: generateId(),
    title: 'New Chat',
    messages: [],
    persona,
    created: Date.now(),
  };
}

type TitleIntent = 'issue' | 'create' | 'optimize' | 'publish' | 'inspect' | 'general';

function titleIntent(text: string): TitleIntent {
  // 明确请求比“有点问题”更能表达用户意图，所以 issue 放在最后。
  if (/(?:优化|改进|调整|完善|增强|多样|随机)/.test(text)) return 'optimize';
  if (/(?:发布|投稿|分发)|(?:上传.*(?:平台|账号|小红书|抖音|B站|bilibili))/i.test(text)) return 'publish';
  if (/(?:制作|生成|创建|设计|写一|做一|剪辑|合成)/.test(text)) return 'create';
  if (/(?:检查|排查|分析|看看|查看|确认|什么逻辑)/.test(text)) return 'inspect';
  if (/(?:bug|修复|解决|问题|异常|报错|失败|卡住|断开|不对|不生效|混乱|拉伸)/i.test(text)) return 'issue';
  return 'general';
}

function semanticTopic(text: string, fallback: string): string {
  if (/(?:历史)?会话.*(?:命名|标题|主题|名字)|(?:命名|标题|主题|名字).*(?:历史)?会话/.test(text)) return '历史会话标题';
  if (/(?:模型)?回答(?:完成|完).*?(?:运行|断开)|(?:运行|断开).*?(?:模型)?回答(?:完成|完)/.test(text)) return '对话完成状态';
  if (/(?:paper-explainer|paper explainer).*(?:skill|逻辑|流程)|(?:skill|逻辑|流程).*(?:paper-explainer|paper explainer)/i.test(text)) return 'paper-explainer 逻辑';
  if (/(?:论文|paper).*(?:ppt|slide).*(?:拉伸|移动|缩放|画面)|(?:拉伸|移动|缩放).*(?:ppt|slide)/i.test(text)) return '论文 PPT 画面';
  if (/(?:论文|paper).*(?:ppt|slide|幻灯|讲解)|(?:ppt|slide|幻灯).*(?:论文|paper)/i.test(text)) return '论文讲解 PPT';
  if (/(?:附件|素材).*(?:上传|重名|多个|显示|隐藏)|(?:上传|重名).*(?:附件|素材)/.test(text)) return '附件上传';
  if (/(?:小红书|xhs).*种草.*文案/i.test(text)) return '小红书种草文案';
  if (/(?:小红书|xhs).*(?:文案|笔记|卡片)/i.test(text)) return '小红书内容';
  if (/交接文档.*项目|项目.*交接文档/.test(text)) return '项目交接';
  if (/视频.*(?:横版|竖版|画幅)|(?:横版|竖版|画幅).*视频/.test(text)) return '视频画幅';
  if (/配置.*模型|模型.*配置/.test(text)) return '模型配置';

  const quoted = text.match(/[「『“"]([^」』”"]{2,24})[」』”"]/u)?.[1];
  if (quoted && /(?:围绕|关于|选题|主题|热点)/.test(text)) return quoted.trim();

  const publishTarget = text.match(/^(?:把|将)?(.{2,18}?)(?:发布|投稿|分发)(?:到|至|去|给)/)?.[1];
  if (publishTarget) return publishTarget.trim();

  return fallback
    .replace(/^(?:做|制作|生成|创建|设计|写|检查|排查|分析|优化|改进|调整|修复)(?:一个|一条|一份|个|条|份)?/, '')
    .replace(/(?:有个|出现了?|遇到)?\s*(?:bug|问题|异常|报错|有点乱).*$/i, '')
    .replace(/[，,、：:\s]+$/g, '')
    .trim() || fallback;
}

function cleanTitleClause(value: string): string {
  return value
    .replace(/^(?:(?:然后|还有|另外|对了|那个|嗯|就是|首先|先说一下|麻烦你?|请问|请你?|能不能|能否|是否可以|可不可以|你能否|你可以|我想(?:要|让你)?|想让你|帮忙|帮我|给我|先|看看|看一下|看下|查一下|查下|确认一下|确认下|我发现|我觉得)[，,、：:\s]*)+/g, '')
    .replace(/^(?:现在|目前|当前)的?/g, '')
    .replace(/[吗么呢吧啊呀哦]+[？?！!。.]?$/g, '')
    .trim();
}

function chooseFocusClause(text: string): string {
  const clauses = text.split(/[。！？?!；;\n，,]/).map(cleanTitleClause).filter(Boolean);
  if (!clauses.length) return text;
  const domain = /(?:skill|paper-explainer|会话|历史|标题|命名|附件|素材|论文|ppt|slide|视频|字幕|配音|发布|小红书|抖音|图片|模型|配置|项目|页面|前端)/i;
  const action = /(?:优化|修复|改进|调整|制作|生成|创建|发布|分析|排查|检查)/;
  return clauses.reduce((best, clause) => {
    const score = (domain.test(clause) ? 4 : 0) + (action.test(clause) ? 2 : 0)
      - (/(?:有可能|是不是|为什么|怎么回事|有点)/.test(clause) ? 1 : 0)
      - Math.max(0, Array.from(clause).length - 28) / 20;
    const bestScore = (domain.test(best) ? 4 : 0) + (action.test(best) ? 2 : 0)
      - (/(?:有可能|是不是|为什么|怎么回事|有点)/.test(best) ? 1 : 0)
      - Math.max(0, Array.from(best).length - 28) / 20;
    return score > bestScore ? clause : best;
  }, clauses[0]);
}

/** 从首条提问提取“主题对象 + 动作”；确定性生成，不请求模型或后端。 */
export function generateSessionTitle(message: string, _seed = message): string {
  const attachmentMarker = '【附件素材】';
  const [question = '', attachmentBlock = ''] = message.split(attachmentMarker, 2);
  let text = question
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!text && attachmentBlock) {
    const path = attachmentBlock.match(/outputs\/([^\s]+)/)?.[1] || '';
    const filename = path.split('/').pop() || '上传素材';
    text = `处理附件 ${filename}`;
  }

  text = cleanTitleClause(text);
  const focusClause = chooseFocusClause(text);
  const baseTitle = focusClause
    .replace(/^(.+?)配置的?是什么模型$/i, '$1模型配置')
    .replace(/^对(.+?)进行/g, '$1')
    .replace(/然后(?:再)?(?:对)?/g, '')
    .replace(/进行|这个|一下/g, '')
    .replace(/(?:怎么|如何|怎样)(?:去)?/g, '')
    .replace(/(?:是不是|是否|是什么|有哪些|有啥)$/g, '')
    .replace(/[吗么呢吧啊呀]+$/g, '')
    .replace(/[，,、：:\s]+$/g, '')
    .trim();

  const core = Array.from(semanticTopic(text, baseTitle || '新对话'))
    .slice(0, 18).join('')
    .replace(/(?:问题排查|故障分析|异常|问题|优化|改进|分析|检查|制作|生成|发布)$/g, '')
    .trim() || '新对话';
  const intent = titleIntent(text);
  const titles: Record<TitleIntent, string> = {
    issue: `${core}问题排查`,
    create: /(?:文案|脚本|方案)$/.test(core) ? core : `${core}制作`,
    optimize: `${core}优化`,
    publish: `${core}发布`,
    inspect: `${core}分析`,
    general: core,
  };
  const title = titles[intent] || core;
  const chars = Array.from(title);
  return chars.length > TITLE_MAX_CHARS
    ? `${chars.slice(0, TITLE_MAX_CHARS).join('')}…`
    : title;
}

export function updateSessionTitle(session: ChatSession): void {
  if (session.messages.length > 0 && session.title === 'New Chat') {
    session.title = generateSessionTitle(session.messages[0].content, session.id);
  }
}
