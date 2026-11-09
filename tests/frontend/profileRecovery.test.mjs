import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const read = path => readFileSync(new URL(`../../web/frontend/src/${path}`, import.meta.url), 'utf8');
const compile = source => ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const apiExports = {};
const personaExports = {};
runInNewContext(compile(read('lib/personas.ts')), { exports: personaExports });
runInNewContext(compile(read('lib/api.ts')), {
  exports: apiExports, require: name => name === './personas' ? personaExports : {}, window: { location: { pathname: '/' } }, Error,
  fetch: async () => ({ ok: false, status: 404, json: async () => ({ detail: '画像不存在' }) }),
});
const { ApiError } = apiExports;

const app = ts.createSourceFile('App.tsx', read('App.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function callback(name) {
  let result;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(app) === name) result = node;
    ts.forEachChild(node, visit);
  }
  visit(app);
  assert.ok(result);
  return compile(`const ${result.getText(app)}; ${name};`);
}

test('sending from a historical missing profile uses general mode and preserves its metadata', () => {
  const old = { id: 'old', persona: 'AI 博主', messages: [{ role: 'assistant', content: '保留历史' }], pendingTurnId: 'recover' };
  let saved, sent;
  const send = runInNewContext(callback('sendUserAndStream'), {
    useCallback: fn => fn, selectedPersona: '', personas: [], personasLoaded: true,
    availablePersona: personaExports.availablePersona,
    sessionsRef: { current: [old] }, streamCtl: { current: {} }, streamAcc: { current: {} },
    setSessions: update => { saved = update([old]); }, saveSessions() {}, updateSessionTitle() {},
    startStream: (...args) => { sent = args; },
  });
  send('old', '继续对话');
  assert.equal(sent[2], undefined);
  assert.equal(saved[0].persona, 'AI 博主');
  assert.equal(saved[0].pendingTurnId, 'recover');
  assert.equal(saved[0].messages[0], old.messages[0]);
  assert.equal(saved[0].messages[1].content, '继续对话');
});

for (const scenario of [
  { name: 'valid profile', persona: '有效画像', catalog: [{ name: '有效画像', description: '' }], loaded: true, expected: '有效画像' },
  { name: 'unverified catalog', persona: '有效画像', catalog: [], loaded: false, expected: '有效画像' },
  { name: 'general mode', persona: undefined, catalog: [], loaded: true, expected: undefined },
]) {
  test(`sending with ${scenario.name} preserves the existing conversation contract`, () => {
    const history = [{ role: 'assistant', content: '原有对话' }];
    const old = { id: 'current', persona: scenario.persona, messages: history, sessionKey: 'remote-session' };
    const other = { id: 'other', persona: '另一画像', messages: [] };
    let saved, sent;
    const send = runInNewContext(callback('sendUserAndStream'), {
      useCallback: fn => fn, selectedPersona: scenario.persona || '',
      personas: scenario.catalog, personasLoaded: scenario.loaded, availablePersona: personaExports.availablePersona,
      sessionsRef: { current: [old, other] }, streamCtl: { current: {} }, streamAcc: { current: {} },
      setSessions: update => { saved = update([old, other]); }, saveSessions() {}, updateSessionTitle() {},
      startStream: (...args) => { sent = args; },
    });
    send(old.id, '继续');
    assert.equal(sent[2], scenario.expected);
    assert.equal(saved[0].persona, old.persona);
    assert.equal(saved[0].sessionKey, old.sessionKey);
    assert.equal(saved[0].messages[0], history[0]);
    assert.equal(saved[1], other);
  });
}

for (const status of [400, 403, 404, 500]) {
  test(`shared HTTP ${status} errors remain compatible with existing Error consumers`, async () => {
    const api = {};
    runInNewContext(compile(read('lib/api.ts')), {
      exports: api, require: name => name === './personas' ? personaExports : {},
      window: { location: { pathname: '/' } }, Error,
      fetch: async () => ({ ok: false, status, json: async () => ({ detail: '请求错误' }) }),
    });
    for (const invoke of [() => api.deletePersona('有效画像'), () => api.buildProfile('新画像', {})]) {
      await assert.rejects(invoke(), error => error instanceof Error && error instanceof api.ApiError
        && error.status === status && error.message === '请求错误');
    }
  });
}

test('network errors are not reclassified as missing profiles by the shared API client', async () => {
  const api = {}, failure = new TypeError('Failed to fetch');
  runInNewContext(compile(read('lib/api.ts')), {
    exports: api, require: name => name === './personas' ? personaExports : {},
    window: { location: { pathname: '/' } }, Error,
    fetch: async () => { throw failure; },
  });
  await assert.rejects(api.deletePersona('有效画像'), error => error === failure);
});

test('API errors retain HTTP status so missing profiles differ from network failures', async () => {
  await assert.rejects(apiExports.deletePersona('AI 博主'), error =>
    error instanceof ApiError && error.status === 404 && error.message === '画像不存在');
});

test('a verified list resolves stale identities without rewriting history or recovery data', () => {
  const old = { id: 'old', persona: 'AI 博主', messages: [{ content: '保留历史' }], pendingTurnId: 'running' };
  const snapshot = JSON.stringify(old);
  assert.equal(personaExports.availablePersona(old.persona, [{ name: '正常画像', description: '' }]), '');
  assert.equal(JSON.stringify(old), snapshot);
  assert.equal(personaExports.availablePersona(old.persona, [{ name: 'AI 博主', description: '' }]), old.persona);
});

test('an unknown catalog does not pretend that a profile is missing', () => {
  assert.equal(personaExports.availablePersona('AI 博主', null), 'AI 博主');
  assert.equal(personaExports.availablePersona(undefined, []), '');
});

for (const value of [null, {}, { personas: [] }, [null], [{ name: 'x' }],
  [{ name: '../outside', description: '' }], [{ name: '_internal', description: '' }],
  [{ name: 'bad\nname', description: '' }], [{ name: 'same', description: '' }, { name: 'same', description: '' }]]) {
  test(`malformed catalog is rejected rather than accepted as empty: ${JSON.stringify(value)}`, () => {
    assert.throws(() => personaExports.parsePersonas(value), /画像列表响应格式无效/);
  });
}
test('empty catalogs and valid Unicode names with spaces remain supported', () => {
  assert.equal(personaExports.parsePersonas([]).length, 0);
  const list = [{ name: 'AI 博主', description: '' }, { name: 'name.with.dots', description: 'description' }];
  assert.equal(personaExports.parsePersonas(list), list);
});

// Execute the component's hooks and event handlers without a browser or extra test dependencies.
function mount(component, api = {}, confirm = true) {
  const slots = [], effects = [];
  let cursor = 0;
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], update => { slots[index] = typeof update === 'function' ? update(slots[index]) : update; }];
    },
    useEffect(callback, deps) {
      const index = cursor++, old = slots[index];
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) {
        old?.cleanup?.();
        const slot = { deps };
        slots[index] = slot;
        effects.push(() => { slot.cleanup = callback(); });
      }
    },
    useCallback(callback, deps) {
      const index = cursor++, old = slots[index];
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) slots[index] = { callback, deps };
      return slots[index].callback;
    },
  };
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  runInNewContext(compile(`${read('components/ProfilePage.tsx')}\nexport { ProfileDetail };`), {
    exports, Error, setTimeout: () => 0, window: { confirm: () => confirm },
    require: name => name === 'react' ? hooks : name === 'react/jsx-runtime' ? { jsx, jsxs: jsx }
      : name === '../lib/api' ? { ApiError, ...api } : {},
  });
  const render = props => {
    cursor = 0;
    const tree = exports[component](props);
    effects.splice(0).forEach(effect => effect());
    return tree;
  };
  render.unmount = () => slots.forEach(slot => slot?.cleanup?.());
  return render;
}
const drain = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  const children = tree.props?.children;
  return [tree, ...[children].flat(Infinity).flatMap(nodes)];
}
const props = { persona: 'AI 博主', onDeleted() {}, loadPersonas: async () => [], onNewProfile() {}, onUsePersona() {} };

test('a stale selected profile never opens a detail page before or after list validation', async () => {
  const render = mount('default');
  const input = props;
  assert.equal(typeof render(input).type, 'string');
  await drain();
  const tree = render(input);
  assert.equal(typeof tree.type, 'string');
  assert.ok(nodes(tree).some(node => node.type === 'h3' && node.props.children === '创建你的第一个画像'));
});

test('a valid profile opens after validation; a list request failure cannot erase selection', async () => {
  const render = mount('default');
  const valid = { ...props, loadPersonas: async () => [{ name: 'AI 博主', description: '' }] };
  render(valid);
  await drain();
  assert.equal(render(valid).type.name, 'ProfileDetail');
  const failedProps = { ...props, loadPersonas: async () => { throw Error('offline'); } };
  const failed = mount('default');
  failed(failedProps);
  await drain();
  assert.ok(nodes(failed(failedProps)).some(node => node.props?.role === 'alert'));
});

for (const original of ['', '原有画像']) {
  test(`creating a profile from the profile page refreshes its catalog (${original || 'general mode'})`, async () => {
    let catalog = original ? [{ name: original, description: '' }] : [];
    let requests = 0;
    const loadPersonas = async () => { requests++; return catalog; };
    const render = mount('default');
    const before = { ...props, persona: original, loadPersonas };
    render(before);
    await drain();
    render(before);
    catalog = [...catalog, { name: '新建画像', description: '' }];
    const after = { ...before, persona: '新建画像' };
    render(after);
    await drain();
    const detail = render(after);
    assert.equal(detail.type.name, 'ProfileDetail');
    assert.equal(detail.props.persona, '新建画像');
    assert.equal(requests, 2);
  });
}

test('a late catalog from the previous selected identity cannot override the new identity', async () => {
  const pending = [];
  const loadPersonas = () => new Promise(resolve => pending.push(resolve));
  const render = mount('default');
  render({ ...props, persona: '旧画像', loadPersonas });
  const latest = { ...props, persona: '新画像', loadPersonas };
  render(latest);
  pending[1]([{ name: '新画像', description: '' }]);
  await drain();
  assert.equal(render(latest).props.persona, '新画像');
  pending[0]([{ name: '旧画像', description: '' }]);
  await drain();
  const detail = render(latest);
  assert.equal(detail.type.name, 'ProfileDetail');
  assert.equal(detail.props.persona, '新画像');
});

test('a superseded catalog request prompts retry instead of displaying an empty catalog', async () => {
  const render = mount('default');
  const input = { ...props, loadPersonas: async () => null };
  render(input);
  await drain();
  assert.ok(nodes(render(input)).some(node => node.props?.role === 'alert'));
});

test('an old list response cannot replace the current detail selection', async () => {
  let resolveOld;
  const render = mount('default');
  render({ ...props, loadPersonas: () => new Promise(yes => { resolveOld = yes; }) });
  const latest = { ...props, loadPersonas: async () => [{ name: 'AI 博主', description: '' }] };
  render(latest);
  await drain();
  assert.equal(render(latest).type.name, 'ProfileDetail');
  resolveOld([]);
  await drain();
  assert.equal(render(latest).type.name, 'ProfileDetail');
});

test('a late detail 404 after unmount cannot clear another active profile', async () => {
  let reject;
  const deleted = [];
  const render = mount('ProfileDetail', { fetchPersonaFiles: () => new Promise((_, no) => { reject = no; }) });
  render({ ...props, onDeleted: (...args) => deleted.push(args) });
  render.unmount();
  reject(new ApiError('画像不存在', 404));
  await drain();
  assert.equal(deleted.length, 0);
});

test('a profile disappearing before detail load triggers list reconciliation', async () => {
  const deleted = [];
  const input = { ...props, onDeleted: (...args) => deleted.push(args) };
  const render = mount('ProfileDetail', { fetchPersonaFiles: async () => { throw new ApiError('画像不存在', 404); } });
  render(input);
  await drain();
  assert.deepEqual(deleted, [['AI 博主', true]]);
});

for (const status of [404, 403, 500]) {
  test(`deletion HTTP ${status} reconciles missing data or shows an error without a success checkmark`, async () => {
    const deleted = [];
    const input = { ...props, onDeleted: (...args) => deleted.push(args) };
    const render = mount('ProfileDetail', {
      fetchPersonaFiles: async () => ({ files: [] }),
      deletePersona: async () => { throw new ApiError(status === 404 ? '画像不存在' : '写入失败', status); },
    });
    render(input);
    await drain();
    const button = nodes(render(input)).find(node => node.type === 'button' && node.props.children === '🗑 删除画像');
    await button.props.onClick();
    const alerts = nodes(render(input)).filter(node => node.props?.role === 'alert');
    if (status === 404) {
      assert.deepEqual(deleted, [['AI 博主', true]]);
      assert.equal(alerts.length, 0);
    } else {
      assert.equal(deleted.length, 0);
      assert.equal(alerts.length, 1);
      assert.equal(alerts[0].props.className, 'toast error');
      assert.equal(alerts[0].props.children[0].props.children, '!');
      assert.equal(alerts[0].props.children[1], '删除失败：写入失败');
    }
  });
}

for (const outcome of ['cancel', 'success', 'network']) {
  test(`delete ${outcome} preserves confirmation and failure semantics`, async () => {
    const deleted = [];
    let requests = 0;
    const input = { ...props, onDeleted: (...args) => deleted.push(args) };
    const render = mount('ProfileDetail', {
      fetchPersonaFiles: async () => ({ files: [] }),
      deletePersona: async () => {
        requests++;
        if (outcome === 'network') throw Error('Failed to fetch');
        return { ok: true };
      },
    }, outcome !== 'cancel');
    render(input);
    await drain();
    const button = nodes(render(input)).find(node => node.type === 'button' && node.props.children === '🗑 删除画像');
    await button.props.onClick();
    assert.equal(requests, outcome === 'cancel' ? 0 : 1);
    assert.equal(deleted.length, outcome === 'success' ? 1 : 0);
    if (outcome === 'network') {
      const alert = nodes(render(input)).find(node => node.props?.role === 'alert');
      assert.equal(alert.props.children[0].props.children, '!');
      assert.equal(alert.props.children[1], '删除失败：Failed to fetch');
    }
  });
}

test('profile management retains a general-mode action after sidebar selector removal', async () => {
  const selected = [];
  const input = { ...props, onUsePersona: name => selected.push(name),
    loadPersonas: async () => [{ name: props.persona, description: '' }] };
  const render = mount('default');
  render(input);
  await drain();
  let tree = render(input);
  tree.props.onBack();
  render(input);
  await drain();
  const button = nodes(render(input)).find(node => node.type === 'button' && node.props.children === '使用通用模式');
  assert.ok(button);
  button.props.onClick();
  assert.deepEqual(selected, ['']);
});
