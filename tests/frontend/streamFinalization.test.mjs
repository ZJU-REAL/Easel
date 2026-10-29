import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/App.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declarations = new Map();
function visit(node) {
  if (ts.isVariableDeclaration(node)) declarations.set(node.name.getText(parsed), node.getText(parsed));
  ts.forEachChild(node, visit);
}
visit(parsed);

function setup() {
  const owner = { content: 'shown', thinking: 'thinking', steps: ['step'], questions: [{ id: 'question' }] };
  const streamAcc = { current: { session: owner } };
  const finalizers = { current: new Map() };
  const typingBuf = { current: { session: ' buffered' } };
  const callbacks = [];
  const messages = [];
  const stops = [];
  const context = {
    useCallback: callback => callback, finalizers, streamAcc, typingBuf,
    streamCtl: { current: { session: { abort() {} } } },
    document: { visibilityState: 'visible' },
    setTimeout: callback => { callbacks.push(callback); return callbacks.length; },
    clearTimeout() {}, sessionStorage: { removeItem() {} },
    setSessions: update => update([]), saveSessions() {},
    stopChat: session => { stops.push(session); return Promise.resolve({ stopped: true }); },
    flushTyping: session => {
      const current = streamAcc.current[session];
      if (current) current.content += typingBuf.current[session] || '';
      typingBuf.current[session] = '';
    },
    appendAssistant: (session, message) => messages.push({ session, message }),
    clearStream: session => { finalizers.current.delete(session); delete streamAcc.current[session]; },
  };
  const output = ts.transpileModule(
    `const ${declarations.get('finalizeStream')}; const ${declarations.get('handleStopStream')}; ({finalizeStream,handleStopStream});`,
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  return { ...runInNewContext(output, context), owner, streamAcc, typingBuf, finalizers,
    callbacks, messages, stops, document: context.document };
}

test('done then stop finalizes complete reply exactly once, without backend cancellation', () => {
  const state = setup();
  state.finalizeStream('session', state.owner, 'native');
  assert.equal(state.messages.length, 0);
  state.handleStopStream('session');
  state.callbacks.forEach(callback => callback());
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].message.content, 'shown buffered');
  assert.equal(state.messages[0].message.questions[0].id, 'question');
  assert.equal(state.stops.length, 0);
});

test('a delayed callback and delayed terminal event cannot erase the following turn', () => {
  const state = setup();
  state.finalizeStream('session', state.owner);
  state.handleStopStream('session');
  const next = { content: 'next reply', thinking: '', steps: [], questions: [] };
  state.streamAcc.current.session = next;
  state.typingBuf.current.session = ' more';
  state.callbacks.forEach(callback => callback());
  state.finalizeStream('session', state.owner);
  assert.equal(state.messages.length, 1);
  assert.equal(state.streamAcc.current.session, next);
  assert.equal(state.typingBuf.current.session, ' more');
});

test('hidden-tab completion flushes all buffered text immediately and ignores duplicate done', () => {
  const state = setup();
  state.document.visibilityState = 'hidden';
  state.finalizeStream('session', state.owner);
  state.finalizeStream('session', state.owner);
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].message.content, 'shown buffered');
  assert.equal(state.callbacks.length, 0);
});

test('error completion preserves buffered text and activity only once', () => {
  const state = setup();
  state.finalizeStream('session', state.owner, undefined, new Error('failed'));
  state.handleStopStream('session');
  state.callbacks.forEach(callback => callback());
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].message.content, 'shown buffered\n\nError: failed');
  assert.equal(state.messages[0].message.activity, 'step');
});
