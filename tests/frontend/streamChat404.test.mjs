import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/api.ts', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true);
const declaration = parsed.statements.find(node =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'streamChat');
assert.ok(declaration);
// Like the replay tests, exercise the stream without evaluating unrelated API imports.
const { outputText } = ts.transpileModule(declaration.getText(parsed), {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
});

/**
 * streamChat 回归：首发 POST 5xx → jobs 流 404 必须**终结**并触发 onError。
 *
 * 旧行为（bug）：404 分支依赖 onRecoveryUnavailable（新发送不传），不传时静默落入
 * 无限 1s 重试（最长 130 分钟），onError 永不触发，会话卡死在「自动续接」。
 */
function loadApi(fetchImpl) {
  const calls = { fetch: 0, post: 0, jobs: 0, onError: [], onDone: 0, onRecovery: 0, onInterrupted: 0 };
  const module = { exports: {} };
  const sandbox = {
    exports: module.exports,
    BASE: '',
    console,
    window: { location: { pathname: '/' } },
    AbortController,
    TextDecoder,
    setTimeout: (fn, ms) => setTimeout(fn, Math.min(ms ?? 0, 2)),
    clearTimeout,
    fetch: (...args) => {
      calls.fetch += 1;
      return fetchImpl(...args);
    },
  };
  runInNewContext(outputText, sandbox);
  return { api: module.exports, calls };
}

function jsonResponse(status, detail) {
  return {
    ok: status < 400,
    status,
    json: async () => ({ detail }),
  };
}

function sseStream(status = 200) {
  // 最小可读流：立即结束（consume 只在 !ok 时读 json）
  return { ok: status < 400, status, json: async () => ({ detail: 'noop' }), body: null };
}

test('streamChat: POST 5xx 后 jobs 404 终结并报错（不再无限重试）', async () => {
  const script = [];
  const { api, calls } = loadApi((url, init) => {
    const u = String(url);
    if (init?.method === 'POST' || u.includes('/api/chat/stream')) {
      calls.post += 1;
      script.length === 0 && script.push('post-502');
      return Promise.resolve(jsonResponse(502, '上游网关过载'));
    }
    calls.jobs += 1;
    return Promise.resolve(jsonResponse(404, '任务记录不存在'));
  });

  const events = { error: [], done: 0, interrupted: 0 };
  const controller = api.streamChat(
    'hi', undefined, 'sess-1',
    () => {},                                  // onToken
    () => { events.done += 1; },               // onDone
    (err) => { events.error.push(err.message); },
    undefined, undefined,                       // onThinking / onActivity
    () => { events.interrupted += 1; },         // onInterrupted
    'turn-fixed-1',                            // turnId
    false,                                     // resumeOnly
    undefined,                                 // onRecoveryUnavailable（新发送不传）
  );

  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(calls.post, 1, '首发 POST 只发一次');
  assert.equal(calls.jobs, 1, 'jobs 404 后必须终结，不得继续重试');
  assert.equal(events.error.length, 1, 'onError 必须触发一次');
  assert.match(events.error[0], /任务记录不存在|失效/);
  assert.equal(events.done, 0);
  assert.equal(events.interrupted, 1, '首次 5xx 后应提示中断（续接状态）');
});

test('streamChat: 提供 onRecoveryUnavailable 时仍走回调（恢复语义不变）', async () => {
  const { api, calls } = loadApi((url, init) => {
    const u = String(url);
    if (init?.method === 'POST' || u.includes('/api/chat/stream')) {
      return Promise.resolve(jsonResponse(502, '上游网关过载'));
    }
    return Promise.resolve(jsonResponse(404, '任务记录不存在'));
  });

  const seen = { recovered: 0, error: 0 };
  api.streamChat(
    'hi', undefined, 'sess-2',
    () => {}, () => {},
    () => { seen.error += 1; },
    undefined, undefined, () => {},
    'turn-fixed-2', true,                      // resumeOnly（恢复路径）
    () => { seen.recovered += 1; },            // onRecoveryUnavailable
  );

  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(seen.recovered, 1, '恢复回调必须被调用');
  assert.equal(seen.error, 0, '有回调时不应再走 onError 兜底');
  assert.equal(calls.fetch, 1, '只发一次 jobs 请求后终结');
});
