import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/CodexConnection.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('CodexConnection.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = parsed.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'CodexConnection');
const { outputText } = ts.transpileModule(declaration.getText(parsed).replace('export default ', '') + '\nCodexConnection;', {
  compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
});
const settle = () => new Promise(resolve => setImmediate(resolve));
function setup(status = { state: 'authenticated', authType: 'chatgpt', windows: [] }) {
  const state = [], effects = [], probes = [];
  let cursor, effectCursor, finish;
  const component = runInNewContext(outputText, {
    CodexLogin: 'codex-login',
    React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) },
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
    fetchCodexStatus: async () => status,
    probeCodex: (model, effort) => {
      probes.push({ model, effort });
      return new Promise(resolve => { finish = resolve; });
    },
  });
  return {
    probes,
    resolve: value => finish(value),
    render(model = 'selected-model', effort = 'low') {
      cursor = 0; effectCursor = 0;
      return component({ model, effort, disabled: false });
    },
  };
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return (tree?.children || []).map(text).join('');
}
function buttons(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return [...(tree.type === 'button' ? [tree] : []), ...(tree.children || []).flatMap(buttons)];
}
test('login diagnostics do not infer until clicked; tests pass preview model and effort', async () => {
  const view = setup();
  view.render(); await settle();
  let tree = view.render();
  assert.match(text(tree), /已登录/);
  assert.match(text(tree), /不代表额度为零/);
  assert.equal(view.probes.length, 0);
  buttons(tree).find(button => text(button) === '测试连接').props.onClick();
  tree = view.render();
  assert.equal(buttons(tree).find(button => text(button) === '测试连接中…').props.disabled, true);
  assert.deepEqual(view.probes, [{ model: 'selected-model', effort: 'low' }]);
  view.resolve({ ok: true, model: 'selected-model', elapsedMs: 1000 }); await settle();
  assert.match(text(view.render()), /连接成功：selected-model/);
});
test('a stale success cannot validate a different model', async () => {
  const view = setup();
  view.render(); await settle();
  buttons(view.render()).find(button => text(button) === '测试连接').props.onClick();
  view.render('different-model');
  view.resolve({ ok: true, model: 'selected-model', elapsedMs: 1000 }); await settle();
  assert.doesNotMatch(text(view.render('different-model')), /连接成功/);
});
test('missing login and provider failure remain actionable', async () => {
  const view = setup({ state: 'unauthenticated', windows: [] });
  view.render(); await settle();
  let tree = view.render();
  assert.match(text(tree), /点击下方按钮/);
  buttons(tree).find(button => text(button) === '测试连接').props.onClick();
  view.resolve({ ok: false, error: { code: 'model', message: '请重新选择模型' } }); await settle();
  assert.match(text(view.render()), /请重新选择模型/);
});
