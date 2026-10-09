import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/api.ts', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true);
const declaration = parsed.statements.find(node =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'streamChat');
assert.ok(declaration);
const { outputText } = ts.transpileModule(
  declaration.getText(parsed).replace('export ', '') + '\nstreamChat;',
  { compilerOptions: { target: ts.ScriptTarget.ES2022 } },
);

async function consume(payloads, resumeOnly) {
  const questions = [];
  const tokens = [];
  const requests = [];
  const frames = payloads.map((payload, index) =>
    `id: ${index + 1}\nevent: question\ndata: ${payload}\n\n`).join('') +
    'event: token\ndata: "继续"\n\nevent: done\ndata: {"sessionKey":"web:test"}\n\n';
  let finish;
  const completed = new Promise(resolve => { finish = resolve; });
  const streamChat = runInNewContext(outputText, {
    AbortController, TextDecoder, Date, Error, setTimeout, BASE: '',
    fetch: async url => {
      requests.push(url);
      return new Response(new ReadableStream({
        start(controller) {
          const bytes = new TextEncoder().encode(frames);
          for (let offset = 0; offset < bytes.length; offset += 7) {
            controller.enqueue(bytes.slice(offset, offset + 7));
          }
          controller.close();
        },
      }));
    },
  });
  streamChat('hello', undefined, 'test', token => tokens.push(token), finish,
    error => { throw error; }, undefined, undefined, undefined, 'test-turn',
    resumeOnly, undefined, [], question => questions.push(question));
  await completed;
  return { questions, tokens, requests };
}

for (const resumeOnly of [false, true]) {
  test(`question parser handles chunked ${resumeOnly ? 'replayed' : 'live'} SSE`, async () => {
    const question = { id: 'question-1', questions: [{ question: '选择？', options: ['抖音'] }] };
    const result = await consume([
      JSON.stringify(question), JSON.stringify(JSON.stringify(question)),
      'null', '"text"', '{}', '{"questions":null}', 'not-json',
    ], resumeOnly);
    assert.deepEqual(JSON.parse(JSON.stringify(result.questions)), [question]);
    assert.deepEqual(result.tokens, ['继续']);
    assert.match(result.requests[0], resumeOnly ? /jobs\/test-turn\/stream/ : /chat\/stream/);
  });
}
