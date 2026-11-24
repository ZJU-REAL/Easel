import type { ChatMessage, ChatSession } from './store';

/** 快照单条消息的最大字符数，超出截断并追加省略号。 */
const SNIPPET_MAX_CHARS = 2000;
/** 快照模板首行文案（spec 逐字值），`<标题>` / `<N>` 为占位。 */
const SEED_HEADER_TMPL = '【旁路会话 · 交接上下文】来自主会话「<标题>」最近 <N> 轮：';

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
      const content =
        m.content.length > SNIPPET_MAX_CHARS
          ? m.content.slice(0, SNIPPET_MAX_CHARS) + '…'
          : m.content;
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
