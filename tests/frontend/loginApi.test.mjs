import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/api.ts', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true);
const start = parsed.statements.find(node =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'startLogin');
const { outputText } = ts.transpileModule(start.getText(parsed), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
});

for (const platform of ['zhihu', 'xiaohongshu', 'weixin-channels']) {
  test(`starting ${platform} requests a fresh QR runner`, async () => {
    const calls = [];
    const exports = {};
    runInNewContext(outputText, {
      exports, encodeURIComponent,
      request: async (path, options) => { calls.push({ path, options }); return { state: 'starting' }; },
    });
    assert.equal((await exports.startLogin(platform)).state, 'starting');
    assert.equal(calls[0].path, `/api/login/${platform}?restart=true`);
    assert.equal(calls[0].options.method, 'POST');
  });
}
