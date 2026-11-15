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
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function nodes(tree, type, found = []) {
  if (!tree || typeof tree !== 'object') return found;
  if (Array.isArray(tree)) { tree.forEach(child => nodes(child, type, found)); return found; }
  if (tree.type === type) found.push(tree);
  nodes(tree.props?.children, type, found);
  return found;
}
function harness() {
  const slots = [], pending = [], reads = [], writes = [];
  let cursor = 0, mounted = true, writesAfterUnmount = 0;
  const module = { exports: {} };
  runInNewContext(outputText, {
    exports: module.exports, AbortController,
    require: name => name === 'react' ? {
      useState(value) {
        const index = cursor++;
        if (!(index in slots)) slots[index] = value;
        return [slots[index], next => {
          if (!mounted) writesAfterUnmount++;
          slots[index] = typeof next === 'function' ? next(slots[index]) : next;
        }];
      },
      useRef(value) { const index = cursor++; return slots[index] ??= { current: value }; },
      useEffect(effect, deps) {
        const index = cursor++, previous = slots[index];
        if (!previous || deps.some((value, i) => value !== previous.deps[i])) {
          pending.push(() => { previous?.cleanup?.(); slots[index] = { deps, cleanup: effect() }; });
        }
      },
    } : name === '../lib/api' ? {
      fetchChatRun: id => { const request = { id, ...deferred() }; reads.push(request); return request.promise; },
      updateChatRun: (...args) => { const request = { args, ...deferred() }; writes.push(request); return request.promise; },
    } : require(name),
  });
  return {
    reads, writes,
    render(id) { cursor = 0; const tree = module.exports.default({ turnId: id }); pending.splice(0).forEach(effect => effect()); return tree; },
    unmount() { mounted = false; slots.forEach(slot => slot?.cleanup?.()); },
    get writesAfterUnmount() { return writesAfterUnmount; },
  };
}
const run = (id, state) => ({ turn_id: id, tracking: 'persisted', backend: 'hermes', version: 2, state });

test('a late read from the previous task cannot replace the current task', async () => {
  const h = harness();
  h.render('old'); h.render('new');
  h.reads[1].resolve(run('new', 'unknown')); await flush();
  h.reads[0].resolve(run('old', 'queued')); await flush();
  const labels = nodes(h.render('new'), 'button').map(node => node.props.children);
  assert.deepEqual(labels, ['刷新状态']);
});

test('a late queued cancellation cannot replace a different task', async () => {
  const h = harness();
  h.render('old'); h.reads[0].resolve(run('old', 'queued')); await flush();
  nodes(h.render('old'), 'button').find(node => node.props.children === '取消排队').props.onClick();
  h.render('new'); h.reads[1].resolve(run('new', 'unknown')); await flush();
  h.writes[0].resolve(run('old', 'queued')); await flush();
  assert.deepEqual(h.writes[0].args, ['old', 'cancel-queued', 2]);
  assert.deepEqual(nodes(h.render('new'), 'button').map(node => node.props.children), ['刷新状态']);
});

test('an in-flight mutation does not update an unmounted recovery panel', async () => {
  const h = harness();
  h.render('old'); h.reads[0].resolve(run('old', 'queued')); await flush();
  nodes(h.render('old'), 'button').find(node => node.props.children === '取消排队').props.onClick();
  h.unmount(); h.writes[0].resolve(run('old', 'cancelled')); await flush();
  assert.equal(h.writesAfterUnmount, 0);
});
