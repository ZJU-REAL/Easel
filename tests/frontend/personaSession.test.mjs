import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/App.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let declaration;
function findCallback(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(parsed) === 'handlePersonaChange') {
    declaration = node;
  }
  ts.forEachChild(node, findCallback);
}
findCallback(parsed);
assert.ok(declaration);
const { outputText } = ts.transpileModule(`const ${declaration.getText(parsed)}; handlePersonaChange;`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
});

function setup(sessions, activeSessionId) {
  const state = { sessions, activeSessionId, selectedPersona: undefined, saved: undefined };
  const changePersona = runInNewContext(outputText, {
    activeSessionId,
    sessionsRef: { current: sessions },
    useCallback: callback => callback,
    setSelectedPersona: persona => { state.selectedPersona = persona; },
    setCurrentPage: page => { state.page = page; },
    setSessions: update => { state.sessions = update(state.sessions); },
    saveSessions: updated => { state.saved = updated; },
    createSession: persona => ({ id: 'new-session', persona, messages: [] }),
    setActiveSessionId: id => { state.activeSessionId = id; },
  });
  return { state, changePersona };
}

test('changing persona on a populated conversation preserves its identity and history', () => {
  const original = { id: 'original', persona: '旧画像', messages: [{ role: 'user', content: '历史' }] };
  const { state, changePersona } = setup([original], original.id);
  changePersona('新画像');
  assert.equal(state.sessions.length, 2);
  assert.equal(state.activeSessionId, 'new-session');
  assert.equal(state.sessions[0].persona, '新画像');
  assert.equal(state.sessions[1], original);
  assert.equal(original.persona, '旧画像');
  assert.equal(original.messages[0].content, '历史');
  assert.equal(state.selectedPersona, '新画像');
  assert.equal(state.saved, state.sessions);
  assert.equal(state.page, 'chat');
});

test('an empty conversation adopts its persona without creating another conversation', () => {
  const original = { id: 'original', persona: '旧画像', messages: [] };
  const { state, changePersona } = setup([original], original.id);
  changePersona('新画像');
  assert.equal(state.sessions.length, 1);
  assert.equal(state.activeSessionId, original.id);
  assert.equal(state.sessions[0].persona, '新画像');
  assert.equal(state.saved, state.sessions);
});

test('switching to general mode creates an unbound conversation and keeps the old one', () => {
  const original = { id: 'original', persona: '旧画像', messages: [{ role: 'user', content: '历史' }] };
  const { state, changePersona } = setup([original], original.id);
  changePersona('');
  assert.equal(state.sessions[0].persona, undefined);
  assert.equal(state.sessions[1], original);
  assert.equal(state.selectedPersona, '');
});

test('without an active conversation, persona selection safely creates one', () => {
  const { state, changePersona } = setup([], null);
  changePersona('新画像');
  assert.equal(state.sessions.length, 1);
  assert.equal(state.sessions[0].persona, '新画像');
  assert.equal(state.activeSessionId, 'new-session');
});
