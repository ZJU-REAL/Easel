import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/DashboardPage.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('DashboardPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let declaration;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(parsed) === 'runAna') declaration = node;
  ts.forEachChild(node, visit);
}
visit(parsed);
const { outputText } = ts.transpileModule(`const ${declaration.getText(parsed)}; exports.runAna = runAna;`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
});
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  let data = {}, errors = {};
  const pending = [], storage = new Map(), exports = {};
  runInNewContext(outputText, {
    exports, Error,
    anaPending: { current: new Set() },
    setAnaSel: () => {},
    setAnaErrors: update => { errors = update(errors); },
    setAnaData: update => { data = update(data); },
    fetchAccountAnalytics: platform => new Promise((resolve, reject) => pending.push({ platform, resolve, reject })),
    localStorage: { setItem: (key, value) => storage.set(key, value) },
  });
  return { exports, pending, storage, get data() { return data; }, get errors() { return errors; } };
}

test('repeated clicks share one fetch and refresh is possible afterwards', async () => {
  const view = setup();
  view.exports.runAna('xiaohongshu');
  view.exports.runAna('xiaohongshu');
  assert.equal(view.pending.length, 1);
  view.pending[0].resolve({ platform: 'xiaohongshu', loggedIn: true, followers: 0 });
  await settle();
  assert.equal(view.data.xiaohongshu.followers, 0);
  view.exports.runAna('xiaohongshu');
  assert.equal(view.pending.length, 2);
});

test('a completed request does not persist another platforms loading state', async () => {
  const view = setup();
  view.exports.runAna('xiaohongshu');
  view.exports.runAna('zhihu');
  view.pending[0].resolve({ platform: 'xiaohongshu', loggedIn: true });
  await settle();
  const cache = JSON.parse(view.storage.get('easel_analytics'));
  assert.equal(cache.xiaohongshu.loggedIn, true);
  assert.equal(cache.zhihu, undefined);
});

test('failed fetch displays the server reason and can retry', async () => {
  const view = setup();
  view.exports.runAna('xiaohongshu');
  view.pending[0].reject(new Error('登录目录正被占用'));
  await settle();
  assert.equal(view.data.xiaohongshu, 'error');
  assert.equal(view.errors.xiaohongshu, '登录目录正被占用');
  view.exports.runAna('xiaohongshu');
  assert.equal(view.pending.length, 2);
  assert.equal(view.errors.xiaohongshu, '');
});

test('analytics requests have platform-specific bounded deadlines', async () => {
  const api = readFileSync(new URL('../../web/frontend/src/lib/api.ts', import.meta.url), 'utf8');
  const apiParsed = ts.createSourceFile('api.ts', api, ts.ScriptTarget.Latest, true);
  const fetchDeclaration = apiParsed.statements.find(node =>
    ts.isFunctionDeclaration(node) && node.name?.text === 'fetchAccountAnalytics');
  const compiled = ts.transpileModule(fetchDeclaration.getText(apiParsed), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {}, calls = [];
  runInNewContext(compiled, {
    exports, encodeURIComponent,
    AbortSignal: { timeout: duration => ({ duration }) },
    request: async (path, options) => { calls.push({ path, options }); return {}; },
  });
  await exports.fetchAccountAnalytics('xiaohongshu');
  await exports.fetchAccountAnalytics('wechat-oa');
  assert.equal(calls[0].options.signal.duration, 105000);
  assert.equal(calls[1].options.signal.duration, 195000);
});
