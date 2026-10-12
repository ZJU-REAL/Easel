import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/QuestionCards.tsx', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX,
  },
});
const component = { exports: {} };
runInNewContext(outputText, {
  exports: component.exports,
  require: name => name === '../lib/api' ? {} : require(name),
});
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

test('approval cards preserve long multiline commands and both permission choices', () => {
  const command = `Codex 请求额外权限（仅本次）：python /data/project/Easel/${'long_segment_'.repeat(200)}/render.py\n第二行 <script>alert(1)</script>`;
  const rendered = renderToStaticMarkup(React.createElement(component.exports.default, {
    questions: [{
      id: 'codex-approval',
      questions: [{
        questionId: 'permission',
        header: '执行授权',
        question: command,
        options: [{ label: '允许本次' }, { label: '拒绝' }],
      }],
    }],
  }));
  assert.ok(rendered.includes('long_segment_'.repeat(200)));
  assert.ok(rendered.includes('\n第二行 &lt;script&gt;alert(1)&lt;/script&gt;'));
  assert.match(rendered, /<strong>允许本次<\/strong>/);
  assert.match(rendered, /<strong>拒绝<\/strong>/);
  assert.match(rendered, /disabled="">提交<\/button>/);
});

test('approval card grids can shrink and wrap commands without clipping their content', () => {
  const styles = readFileSync(new URL('../../web/frontend/src/styles/index.css', import.meta.url), 'utf8');
  const rule = selector => {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const matched = styles.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`));
    assert.ok(matched, selector);
    return matched[1];
  };
  for (const selector of ['.question-card', '.question-card__item', '.question-card__option']) {
    assert.match(rule(selector), /grid-template-columns:\s*minmax\(0,\s*1fr\)/);
    assert.match(rule(selector), /min-width:\s*0/);
  }
  assert.match(rule('.question-card'), /overflow-wrap:\s*anywhere/);
  assert.match(rule('.question-card__title'), /white-space:\s*pre-wrap/);
  assert.match(rule('.question-card__options'), /minmax\(min\(150px,\s*100%\),\s*1fr\)/);
  assert.match(rule('.question-card__custom input'), /min-width:\s*0/);
});
