import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/App.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const app = parsed.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'App');
const selected = app.body.statements.filter(node => {
  if (ts.isVariableStatement(node)) return node.declarationList.declarations.some(d =>
    ts.isIdentifier(d.name) && ['personaRequestId', 'refreshPersonas'].includes(d.name.text));
  return ts.isExpressionStatement(node) && ts.isCallExpression(node.expression)
    && node.expression.expression.getText(parsed) === 'useEffect'
    && /fetchStatus\(|fetchPersonas\(/.test(node.getText(parsed));
}).map(node => node.getText(parsed)).join('\n');
const { outputText } = ts.transpileModule(selected + '\n({refresh: typeof refreshPersonas === "function" ? refreshPersonas : () => fetchPersonas().then(setPersonas)});', {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const settle = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const status = deferred(), requests = [], lists = [], cleanups = [], recommended = [];
  const control = runInNewContext(outputText, {
    useRef: initial => ({ current: initial }), useCallback: fn => fn,
    useEffect: fn => { const cleanup = fn(); if (cleanup) cleanups.push(cleanup); },
    fetchStatus: () => status.promise,
    fetchPersonas: () => { const request = deferred(); requests.push(request); return request.promise; },
    fetch: async () => ({ ok: true, json: async () => ({ modelConfigured: true }) }),
    setPersonas: list => lists.push(JSON.parse(JSON.stringify(list))),
    setGatewayStatus: () => {}, setApiDirect: () => {}, setAgentRuntime: () => {},
    setNeedModelSetup: () => {}, setSettingsOpen: () => {}, setShowRecommend: value => recommended.push(value),
    onboardingSeen: () => false,
  });
  return { status, requests, lists, cleanups, recommended, ...control };
}
const profile = [{ name: 'existing profile', description: 'test' }];
const statusData = { gateway: true, runtime: 'api', transport: 'api', personas: [] };

test('profiles load even when the broader status endpoint fails', async () => {
  const h = setup();
  assert.equal(h.requests.length, 1);
  h.status.reject(new Error('status unavailable'));
  h.requests[0].resolve(profile);
  await settle();
  assert.deepEqual(h.lists.at(-1), profile);
});

test('old status data neither overwrites profiles nor recommends creating another', async () => {
  const h = setup();
  h.status.resolve(statusData);
  h.requests[0].resolve(profile);
  await settle();
  assert.deepEqual(h.lists.at(-1), profile);
  assert.equal(h.recommended.length, 0);
});

test('status profiles remain a fallback when the dedicated endpoint fails', async () => {
  const h = setup();
  h.status.resolve({ ...statusData, personas: profile });
  h.requests[0].reject(new Error('profiles unavailable'));
  await settle();
  assert.deepEqual(h.lists.at(-1), profile);
});

test('a newer profile refresh wins over an old mount request', async () => {
  const h = setup();
  const refresh = h.refresh();
  const updated = [{ name: 'just created', description: 'test' }];
  h.requests[1].resolve(updated);
  await refresh;
  h.status.resolve(statusData);
  h.requests[0].resolve(profile);
  await settle();
  assert.deepEqual(h.lists.at(-1), updated);
  assert.equal(h.recommended.length, 0);
});

test('late bootstrap callbacks cannot update an unmounted app', async () => {
  const h = setup();
  h.cleanups.forEach(cleanup => cleanup());
  h.status.resolve(statusData);
  h.requests[0].resolve(profile);
  await settle();
  assert.equal(h.lists.length, 0);
  assert.equal(h.recommended.length, 0);
});
