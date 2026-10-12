import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/whoami.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
});
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  const entries = new Map();
  const pending = [];
  const exports = {};
  runInNewContext(outputText, {
    exports, Date,
    require: () => ({
      accountWhoami: platform => new Promise(resolve => pending.push({ platform, resolve })),
    }),
    localStorage: {
      getItem: key => entries.get(key) ?? null,
      setItem: (key, value) => entries.set(key, String(value)),
    },
  });
  return { exports, pending, entries };
}

test('legacy and previously incorrect account identity caches are ignored', () => {
  const view = setup();
  view.entries.set('easel_whoami', JSON.stringify({
    xiaohongshu: { loggedIn: true, name: 'Wrong feed author', avatar: '', ts: Date.now() },
  }));
  view.entries.set('easel_whoami_v2', view.entries.get('easel_whoami'));
  view.entries.set('easel_whoami_v3', view.entries.get('easel_whoami'));
  assert.equal(view.exports.getWhoamiCache().xiaohongshu, undefined);
  view.exports.setWhoamiCache('xiaohongshu', { loggedIn: true, name: 'Me', avatar: '' });
  assert.equal(JSON.parse(view.entries.get('easel_whoami_v4')).xiaohongshu.name, 'Me');
});
test('a verification started before login cannot overwrite the new login cache', async () => {
  const view = setup();
  const updates = [];
  view.exports.verifyStale(['xiaohongshu'], { onUpdate: (...args) => updates.push(args) });
  view.exports.setWhoamiCache('xiaohongshu', { loggedIn: true, name: '已登录', avatar: '' });
  view.pending[0].resolve({ loggedIn: false, name: '', avatar: '' });
  await settle();
  assert.equal(view.exports.getWhoamiCache().xiaohongshu.loggedIn, true);
  assert.equal(updates.length, 0);
});

test('invalidating login cache discards a previously running background verification', async () => {
  const view = setup();
  const updates = [];
  view.exports.verifyStale(['xiaohongshu'], { onUpdate: (...args) => updates.push(args) });
  view.exports.setWhoamiCache('xiaohongshu', null);
  view.pending[0].resolve({ loggedIn: false, name: '', avatar: '' });
  await settle();
  assert.equal(view.exports.getWhoamiCache().xiaohongshu, undefined);
  assert.equal(updates.length, 0);
});

test('fresh verification still updates and caches the actual account result', async () => {
  const view = setup();
  const updates = [];
  view.exports.verifyStale(['xiaohongshu'], { onUpdate: (...args) => updates.push(args) });
  view.pending[0].resolve({ loggedIn: true, name: '账号', avatar: '' });
  await settle();
  assert.equal(view.exports.getWhoamiCache().xiaohongshu.loggedIn, true);
  assert.equal(updates.length, 1);
});

test('incomplete account identity is refreshed after one minute instead of ten', () => {
  const view = setup();
  view.entries.set('easel_whoami_v4', JSON.stringify({
    xiaohongshu: { loggedIn: true, name: '', avatar: '', ts: Date.now() - 61_000 },
    zhihu: { loggedIn: true, name: 'Me', avatar: 'https://self.test/avatar', ts: Date.now() - 61_000 },
  }));
  view.exports.verifyStale(['xiaohongshu', 'zhihu']);
  assert.equal(view.pending.length, 1);
  assert.equal(view.pending[0].platform, 'xiaohongshu');
});
