import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/RunRecovery.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} });

function harness(initial, mutate = async () => initial) {
  let current = initial, cursor = 0, mounted = false;
  const states = [], effects = [], calls = [];
  const module = { exports: {} };
  runInNewContext(outputText, {
    exports: module.exports, AbortController,
    require: name => name === 'react' ? {
      useState(value) {
        const index = cursor++;
        if (!(index in states)) states[index] = value;
        return [states[index], next => { states[index] = next; }];
      },
      useEffect(effect) { if (!mounted) effects.push(effect); },
    } : name === '../lib/api' ? {
      fetchChatRun: async id => { calls.push(['read', id]); return current; },
      updateChatRun: async (...args) => { calls.push(['write', ...args]); return mutate(); },
    } : require(name),
  });
  const render = () => {
    cursor = 0;
    const tree = module.exports.default({ turnId: 'turn' });
    if (!mounted) { mounted = true; effects.forEach(effect => effect()); }
    return tree;
  };
  const flush = () => new Promise(resolve => setImmediate(resolve));
  function buttons(node, found = []) {
    if (!node || typeof node !== 'object') return found;
    if (Array.isArray(node)) { node.forEach(child => buttons(child, found)); return found; }
    if (node.type === 'button') found.push(node);
    buttons(node.props?.children, found);
    return found;
  }
  return { render, flush, buttons, calls, setCurrent: value => { current = value; } };
}

for (const backend of ['direct_api', 'openclaw', 'codex', 'opencode', 'acp'])
for (const [state, action, label] of [
  ['queued', 'cancel-queued', '取消排队'], ['running', 'reconcile', '核验执行状态'],
]) {
  test(`${backend}/${state} uses the observed revision and never sends a prompt`, async () => {
    const h = harness({ tracking: 'persisted', backend, state, version: 7 });
    h.render(); await h.flush();
    h.buttons(h.render()).find(b => b.props.children === label).props.onClick();
    await h.flush();
    assert.deepEqual(h.calls, [['read', 'turn'], ['write', 'turn', action, 7]]);
  });
}

test('a conflict refreshes the record without repeating the mutation', async () => {
  const h = harness({ tracking: 'persisted', backend: 'direct_api', state: 'running', version: 2 },
    async () => { throw new Error('任务状态已变化'); });
  h.render(); await h.flush();
  h.setCurrent({ tracking: 'persisted', backend: 'direct_api', state: 'succeeded', version: 3 });
  h.buttons(h.render()).find(b => b.props.children === '核验执行状态').props.onClick();
  await h.flush();
  assert.equal(h.calls.filter(call => call[0] === 'write').length, 1);
  assert.deepEqual(h.buttons(h.render()).map(b => b.props.children), ['刷新状态']);
});

for (const run of [
  { tracking: 'legacy', state: 'unknown' },
  { tracking: 'persisted', backend: 'direct_api', state: 'unknown', version: 3 },
]) {
  test(`no mutation for ${run.tracking}/${run.backend}/${run.state}`, async () => {
    const h = harness(run);
    h.render(); await h.flush();
    assert.deepEqual(h.buttons(h.render()).map(b => b.props.children), ['刷新状态']);
    assert.equal(h.calls.length, 1);
  });
}
