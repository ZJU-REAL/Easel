import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/store.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
});

function storage(initial = {}) {
  const entries = new Map(Object.entries(initial));
  return {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, String(value)),
    removeItem: key => entries.delete(key),
  };
}

function load(initial) {
  const localStorage = storage(initial);
  const sessionStorage = storage({ easel_tab_session: 'original', 'easel_pending_turn:original': 'pending' });
  const exports = {};
  runInNewContext(outputText, { exports, localStorage, sessionStorage, Date, Math });
  return { exports, localStorage, sessionStorage };
}

test('loading without the obsolete reset marker preserves existing conversation history and recovery', () => {
  const original = [{ id: 'original', messages: [{ role: 'user', content: '历史对话' }], created: 1 }];
  const state = load({ easel_sessions: JSON.stringify(original), easel_active_session: 'original' });
  assert.equal(JSON.stringify(state.exports.loadSessions()), JSON.stringify(original));
  assert.equal(state.exports.loadActiveId(), 'original');
  assert.equal(state.sessionStorage.getItem('easel_tab_session'), 'original');
  assert.equal(state.sessionStorage.getItem('easel_pending_turn:original'), 'pending');
});

test('legacy conversation history migrates rather than being deleted on first load', () => {
  const original = [{ id: 'original', messages: [{ role: 'user', content: '迁移的历史' }], created: 1 }];
  const previous = ['post', 'craft'].join('');
  const state = load({
    [`${previous}_sessions`]: JSON.stringify(original),
    [`${previous}_active_session`]: 'original',
  });
  assert.equal(JSON.stringify(state.exports.loadSessions()), JSON.stringify(original));
  assert.equal(state.exports.loadActiveId(), 'original');
  assert.equal(state.localStorage.getItem('easel_sessions'), JSON.stringify(original));
  assert.equal(state.localStorage.getItem(`${previous}_sessions`), null);
});
