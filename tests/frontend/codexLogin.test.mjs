import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/CodexLogin.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('CodexLogin.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = parsed.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'CodexLogin');
const { outputText } = ts.transpileModule(declaration.getText(parsed).replace('export default ', '') + '\nCodexLogin;', {
  compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
});
const settle = () => new Promise(resolve => setImmediate(resolve));
function setup({ blocked = false, initial = { state: 'idle' }, failStart = false, authenticated = false } = {}) {
  const state = [], effects = [], calls = [], timers = new Map();
  let cursor, effectCursor, serial = 0, server = initial, connected = 0;
  const popup = { opener: 'parent', location: { replace: url => calls.push(['redirect', url]) }, close: () => calls.push(['close']) };
  const component = runInNewContext(outputText, {
    React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) },
    window: { open: () => { calls.push(['open']); return blocked ? null : popup; }, confirm: () => true },
    setTimeout: callback => { timers.set(++serial, callback); return serial; },
    clearTimeout: id => timers.delete(id),
    useState: initial => {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    },
    useRef: initial => {
      const index = cursor++;
      if (!(index in state)) state[index] = { current: initial };
      return state[index];
    },
    useEffect: (callback, dependencies) => {
      const index = effectCursor++;
      const previous = effects[index];
      if (!previous || dependencies.some((value, position) => value !== previous.dependencies[position])) {
        previous?.cleanup?.();
        effects[index] = { dependencies, cleanup: callback() };
      }
    },
    fetchCodexLogin: async () => ({ ...server }),
    startCodexLogin: async method => {
      calls.push(['start', method]);
      if (failStart) throw new Error('暂时无法登录');
      server = { id: 'attempt', state: 'pending', method, authUrl: 'https://auth.openai.com/authorize',
        ...(method === 'device' ? { userCode: 'TEST-1234' } : {}) };
      return server;
    },
    cancelCodexLogin: async id => {
      calls.push(['cancel', id]);
      server = { id, state: 'cancelled', message: '已取消本次登录。' };
      return server;
    },
    logoutCodex: async () => {
      calls.push(['logout']);
      server = { state: 'logged_out', message: '已退出 Codex' };
      return server;
    },
  });
  return {
    calls, popup,
    connected: () => connected,
    server: value => { server = value; },
    tick() { const [id, callback] = timers.entries().next().value; timers.delete(id); callback(); },
    render() {
      cursor = 0; effectCursor = 0;
      return component({ disabled: false, authenticated, onConnected: () => { connected += 1; } });
    },
  };
}
function nodes(tree, type) {
  if (!tree || typeof tree !== 'object') return [];
  return [...(tree.type === type ? [tree] : []), ...(tree.children || []).flatMap(child => nodes(child, type))];
}
function text(tree) {
  if (typeof tree === 'string') return tree;
  return (tree?.children || []).map(text).join('');
}
const button = (tree, label) => nodes(tree, 'button').find(node => text(node) === label);

test('login opens a tab on the click, isolates opener, then follows official URL', async () => {
  const view = setup(); view.render(); await settle();
  button(view.render(), '登录 Codex').props.onClick(); await settle();
  const tree = view.render();
  assert.deepEqual(view.calls, [['open'], ['start', 'browser'], ['redirect', 'https://auth.openai.com/authorize']]);
  assert.equal(view.popup.opener, null);
  assert.equal(button(tree, '登录 Codex').props.disabled, true);
  assert.ok(button(tree, '取消登录'));
});
test('blocked popups retain a manual link and device flow shows the code', async () => {
  const view = setup({ blocked: true }); view.render(); await settle();
  button(view.render(), '使用验证码登录').props.onClick(); await settle();
  const tree = view.render();
  assert.match(text(tree), /TEST-1234/);
  assert.equal(nodes(tree, 'a')[0].props.rel, 'noopener noreferrer');
  assert.equal(nodes(tree, 'a')[0].props.href, 'https://auth.openai.com/authorize');
});
test('reopening settings resumes polling and completion refreshes the account once', async () => {
  const view = setup({ initial: { id: 'resumed', state: 'pending', authUrl: 'https://auth.openai.com/authorize' } });
  view.render(); await settle();
  assert.ok(button(view.render(), '取消登录'));
  assert.equal(view.calls.length, 0);
  view.server({ id: 'resumed', state: 'success', message: '登录成功' });
  view.tick(); await settle();
  assert.match(text(view.render()), /登录成功/);
  assert.equal(view.connected(), 1);
  assert.equal(nodes(view.render(), 'a').length, 0);
});
test('cancel removes the login link and allows a new attempt', async () => {
  const view = setup({ initial: { id: 'pending', state: 'pending', authUrl: 'https://auth.openai.com/authorize' } });
  view.render(); await settle();
  button(view.render(), '取消登录').props.onClick(); await settle();
  const tree = view.render();
  assert.deepEqual(view.calls, [['cancel', 'pending']]);
  assert.equal(nodes(tree, 'a').length, 0);
  assert.equal(button(tree, '登录 Codex').props.disabled, false);
});
test('failed starts close the empty popup and allow retry', async () => {
  const view = setup({ failStart: true }); view.render(); await settle();
  button(view.render(), '登录 Codex').props.onClick(); await settle();
  const tree = view.render();
  assert.match(text(tree), /暂时无法登录/);
  assert.equal(button(tree, '登录 Codex').props.disabled, false);
  assert.deepEqual(view.calls.at(-1), ['close']);
});
test('authenticated users can confirm logout and then see a login action', async () => {
  const view = setup({ authenticated: true, initial: { state: 'success', id: 'account' } }); view.render(); await settle();
  let tree = view.render();
  button(tree, '退出登录').props.onClick(); await settle();
  tree = view.render();
  assert.deepEqual(view.calls, [['logout']]);
  assert.match(text(tree), /已退出 Codex/);
  assert.ok(button(tree, '登录 Codex'));
});
