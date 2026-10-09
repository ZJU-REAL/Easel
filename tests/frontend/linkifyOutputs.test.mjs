import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
function load(name, imports = {}) {
  const source = readFileSync(new URL(`../../web/frontend/src/lib/${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const exports = {};
  runInNewContext(outputText, { exports, require: id => imports[id], window: { location: { pathname: '/' } } });
  return exports;
}
const api = load('api');
const { linkifyOutputs } = load('linkifyOutputs', { './api': api });

test('absolute Markdown report links retain their label and open the content preview', () => {
  const input = '[查看复盘](/Users/example/Easel/outputs/示例项目/报告.md)';
  const expected = '[查看复盘](#/outputs/示例项目/报告.md)';
  const actual = linkifyOutputs(input);
  assert.equal(actual, expected.replace(/示例项目|报告.md/g, encodeURIComponent));
  assert.equal(linkifyOutputs(actual), actual);
});

test('images and angle-wrapped paths with spaces resolve through media or content routes', () => {
  assert.equal(linkifyOutputs('![图](/Users/example/Easel/outputs/a/cover.png)'), '![图](/api/media/a/cover.png)');
  assert.equal(linkifyOutputs('[报告](</Users/example/Easel/outputs/a b/report.md>)'), '[报告](#/outputs/a%20b/report.md)');
  assert.equal(linkifyOutputs('[报告](outputs/a/report.md)'), '[报告](#/outputs/a/report.md)');
});

test('external URLs, commands, converted links and traversal targets remain unchanged', () => {
  for (const input of [
    '[外部](https://example.com/outputs/report.md)',
    '[外部](//example.com/outputs/report.md)',
    '```\n[命令](/Users/example/Easel/outputs/a.md)\n```',
    '`cat outputs/a.md`',
    '[已处理](/api/media/a.md)',
    '[非法](outputs/../secret.md)',
    '[非法](outputs/%2e%2e/secret.md)',
    '[非法](outputs/a/./report.md)',
    '[损坏](outputs/%ZZ.md)',
    '[损坏](outputs/\uD800.md)',
  ]) assert.equal(linkifyOutputs(input), input);
});

test('Windows paths and encoded file names resolve without corrupting their destination', () => {
  assert.equal(linkifyOutputs('[报告](C:\\Easel\\outputs\\demo\\report.md)'), '[报告](#/outputs/demo/report.md)');
  assert.equal(linkifyOutputs('[报告](outputs/demo/a%20b.md)'), '[报告](#/outputs/demo/a%20b.md)');
  assert.equal(linkifyOutputs('[目录](outputs/demo/)'), '[目录](#/outputs/demo)');
});
