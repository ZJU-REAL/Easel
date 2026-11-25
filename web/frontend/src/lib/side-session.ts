import type { ChatMessage, ChatSession } from './store';

/** 快照单条消息的最大字符数，超出截断并追加省略号。 */
const SNIPPET_MAX_CHARS = 2000;
/** seed 消息首行前缀（识别与前端卡片化渲染用） */
const SEED_HEADER_PREFIX = '【旁路会话 · 交接上下文】';
/** 快照模板首行文案（spec 逐字值），`<标题>` / `<N>` 为占位。 */
const SEED_HEADER_TMPL = SEED_HEADER_PREFIX + '来自主会话「<标题>」最近 <N> 轮：';

/**
 * 把快照轮数解析成切片起点索引：倒序收集 user 消息索引，
 * 取倒数第 N 个 user 消息为切片起点（含其后的所有消息）。
 * 轮数超过 user 消息数时从第一条消息开始。
 */
function resolveSliceStart(messages: ChatMessage[], turns: number | 'all'): number {
  if (turns === 'all') return 0;
  const userIdx: number[] = [];
  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === 'user') userIdx.push(i);
  }
  if (userIdx.length === 0) return 0;
  const n = Math.min(turns, userIdx.length);
  return userIdx[userIdx.length - n];
}

/**
 * 构建旁路会话的「交接首条消息」：固定模板首行 + 逐条 `role: content`（超长截断）。
 * 纯函数，不修改传入的消息数组。
 */
export function buildSeedMessage(
  mainTitle: string,
  msgs: ChatMessage[],
  turns: number | 'all'
): ChatMessage {
  const start = resolveSliceStart(msgs, turns);
  const slice = msgs.slice(start);
  // 模板中的 <N> 始终为实际轮数（'all' 解析为消息总数），保证文案可审计
  const n = turns === 'all' ? msgs.length : turns;
  const lines = [
    SEED_HEADER_TMPL.replace('<标题>', mainTitle).replace('<N>', String(n)),
    ...slice.map((m) => {
      // 裁掉首尾空白：流式失败回复常带前导换行（App.tsx 的 \n\nError: …），
      // 不裁会让 seed 的行结构被空行污染（卡片渲染与后端 payload 都受影响）
      const trimmed = m.content.trim();
      const content =
        trimmed.length > SNIPPET_MAX_CHARS
          ? trimmed.slice(0, SNIPPET_MAX_CHARS) + '…'
          : trimmed;
      return `${m.role}: ${content}`;
    }),
  ];
  return { role: 'user', content: lines.join('\n') };
}

/**
 * 从主会话派生旁路会话：携带快照作为首条消息，记录血缘字段。
 * 纯函数，不修改主会话；id 与时间由调用方注入以便测试。
 */
export function deriveSideSession(
  main: ChatSession,
  turns: number | 'all',
  newId: string,
  now: number
): ChatSession {
  const seed = buildSeedMessage(main.title, main.messages, turns);
  return {
    id: newId,
    title: `旁路 · ${main.title}`,
    messages: [seed],
    created: now,
    parentSessionId: main.id,
    derivedAt: now,
    seedTurns: turns === 'all' ? main.messages.length : turns,
  };
}

/**
 * 旁路会话是否处于「仅含 seed、尚未真实开局」状态。
 * - C1 修复用：首轮真实发送时需把 seed 前置拼进发往后端的消息，让服务端历史以快照开局；
 *   首个回复落库后 messages.length > 1，自然停止拼接。
 * - I1 修复用：此状态下没有悬空轮可恢复，resumePendingTurn 应跳过，
 *   避免旁路会话每次激活都触发注定落空的「接回上一轮」兜底（spec 反目标：续接行为差异）。
 */
export function isSeedOnlySideSession(session: ChatSession): boolean {
  return !!session.parentSessionId
    && session.messages.length === 1
    && session.messages[0].role === 'user';
}

/** 解析后的 seed 单条轮次 */
export interface SeedTurnItem {
  role: 'user' | 'assistant';
  content: string;
}

/** 解析后的 seed 消息（前端卡片化渲染用） */
export interface ParsedSeedMessage {
  mainTitle: string;
  turnsLabel: string;
  items: SeedTurnItem[];
}

/**
 * 把 seed 消息文本解析回结构化数据，供前端渲染「交接上下文卡片」。
 * 非 seed 内容（普通用户消息、前缀不符或头部格式不符）返回 null。
 * 多行 content 归属到当前轮次——只有 `user: `/`assistant: ` 开头的行才开新轮次。
 */
export function parseSeedMessage(content: string): ParsedSeedMessage | null {
  if (!content.startsWith(SEED_HEADER_PREFIX)) return null;
  const lines = content.split('\n');
  const m = lines[0].match(/^【旁路会话 · 交接上下文】来自主会话「(.+)」最近 (.+) 轮：$/);
  if (!m) return null;
  const items: SeedTurnItem[] = [];
  for (const line of lines.slice(1)) {
    const tm = line.match(/^(user|assistant): /);
    if (tm) items.push({ role: tm[1] as 'user' | 'assistant', content: line.slice(tm[0].length) });
    else if (items.length > 0) items[items.length - 1].content += '\n' + line;
  }
  return { mainTitle: m[1], turnsLabel: m[2], items };
}
