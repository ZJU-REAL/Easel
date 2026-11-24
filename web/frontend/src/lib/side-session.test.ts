import { describe, it, expect } from 'vitest';
import type { ChatSession, ChatMessage } from './store';
import { buildSeedMessage, deriveSideSession, isSeedOnlySideSession } from './side-session';

function msg(role: 'user' | 'assistant', content: string): ChatMessage {
  return { role, content };
}

function makeMain(messages: ChatMessage[]): ChatSession {
  return {
    id: 'main-1',
    title: '测试',
    messages,
    created: 1000,
  };
}

describe('buildSeedMessage', () => {
  it('seed 首行文案精确匹配模板（轮数为数字）', () => {
    const main = makeMain([msg('user', '你好'), msg('assistant', '在的')]);
    const seed = buildSeedMessage('测试', main.messages, 2);
    expect(seed.role).toBe('user');
    expect(seed.content.split('\n', 1)[0]).toBe(
      '【旁路会话 · 交接上下文】来自主会话「测试」最近 2 轮：'
    );
  });

  it("seed 首行文案精确匹配模板（轮数为 all 时解析为消息总数）", () => {
    const main = makeMain([msg('user', '你好'), msg('assistant', '在的')]);
    const seed = buildSeedMessage('测试', main.messages, 'all');
    expect(seed.content.split('\n', 1)[0]).toBe(
      '【旁路会话 · 交接上下文】来自主会话「测试」最近 2 轮：'
    );
  });

  it('turns=2 时从倒数第 2 条 user 消息起切片（含其后的 assistant 消息）', () => {
    const main = makeMain([
      msg('user', 'u1'),
      msg('assistant', 'a1'),
      msg('user', 'u2'),
      msg('assistant', 'a2'),
      msg('user', 'u3'),
      msg('assistant', 'a3'),
    ]);
    const seed = buildSeedMessage('测试', main.messages, 2);
    // 倒数第 2 条 user 是 u2，切片应含 u2/a2/u3/a3
    expect(seed.content).toContain('user: u2');
    expect(seed.content).toContain('assistant: a2');
    expect(seed.content).toContain('user: u3');
    expect(seed.content).toContain('assistant: a3');
    expect(seed.content).not.toContain('user: u1');
    expect(seed.content).not.toContain('assistant: a1');
  });

  it("turns='all' 时含全部消息", () => {
    const main = makeMain([
      msg('user', 'u1'),
      msg('assistant', 'a1'),
      msg('user', 'u2'),
      msg('assistant', 'a2'),
    ]);
    const seed = buildSeedMessage('测试', main.messages, 'all');
    expect(seed.content).toContain('user: u1');
    expect(seed.content).toContain('assistant: a1');
    expect(seed.content).toContain('user: u2');
    expect(seed.content).toContain('assistant: a2');
  });

  it('超过 2000 字符的单条 content 被截断为 2000 字符 + …', () => {
    const long = 'x'.repeat(2500);
    const main = makeMain([msg('user', long)]);
    const seed = buildSeedMessage('测试', main.messages, 'all');
    const line = seed.content.split('\n')[1];
    expect(line).toBe(`user: ${'x'.repeat(2000)}…`);
  });

  it('主会话标题含「」时原样嵌入不转义', () => {
    const main = makeMain([msg('user', '你好')]);
    const seed = buildSeedMessage('「带引号」标题', main.messages, 1);
    expect(seed.content.split('\n', 1)[0]).toBe(
      '【旁路会话 · 交接上下文】来自主会话「「带引号」标题」最近 1 轮：'
    );
  });

  it('轮数超过 user 消息数时从第一条消息起切片', () => {
    const main = makeMain([
      msg('user', 'u1'),
      msg('assistant', 'a1'),
      msg('user', 'u2'),
    ]);
    const seed = buildSeedMessage('测试', main.messages, 5);
    expect(seed.content).toContain('user: u1');
    expect(seed.content).toContain('user: u2');
  });
});

describe('deriveSideSession', () => {
  it('返回带血缘的旁路会话，主会话消息数组零改动', () => {
    const main = makeMain([
      msg('user', 'u1'),
      msg('assistant', 'a1'),
      msg('user', 'u2'),
      msg('assistant', 'a2'),
    ]);
    const before = main.messages.length;
    const seed = buildSeedMessage('测试', main.messages, 1);
    const side = deriveSideSession(main, 1, 'side-1', 2000);

    expect(side.id).toBe('side-1');
    expect(side.title).toBe('旁路 · 测试');
    expect(side.messages).toHaveLength(1);
    expect(side.messages[0].role).toBe('user');
    expect(side.messages[0].content).toBe(seed.content);
    expect(side.parentSessionId).toBe('main-1');
    expect(side.derivedAt).toBe(2000);
    expect(side.seedTurns).toBe(1);
    expect(side.created).toBe(2000);
    // 主会话 history 零改动
    expect(main.messages.length).toBe(before);
  });

  it("seedTurns 在 'all' 时解析为消息总数", () => {
    const main = makeMain([
      msg('user', 'u1'),
      msg('assistant', 'a1'),
      msg('user', 'u2'),
    ]);
    const side = deriveSideSession(main, 'all', 'side-2', 3000);
    expect(side.seedTurns).toBe(3);
  });
});

describe('isSeedOnlySideSession', () => {
  it('旁路会话且仅含 seed（首条真实轮次未发出）时为 true', () => {
    const main = makeMain([msg('user', 'u1'), msg('assistant', 'a1')]);
    const side = deriveSideSession(main, 1, 'side-1', 2000);
    expect(isSeedOnlySideSession(side)).toBe(true);
  });

  it('旁路会话首轮已发出（有真实往返）后为 false', () => {
    const main = makeMain([msg('user', 'u1'), msg('assistant', 'a1')]);
    const side = deriveSideSession(main, 1, 'side-1', 2000);
    side.messages.push(msg('assistant', '回复'));
    expect(isSeedOnlySideSession(side)).toBe(false);
  });

  it('主会话（无血缘）永远为 false', () => {
    const main = makeMain([msg('user', 'u1')]);
    expect(isSeedOnlySideSession(main)).toBe(false);
  });
});

