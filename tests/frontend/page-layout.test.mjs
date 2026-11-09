import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/SkillPage.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('SkillPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let card;
function visit(node) {
  if (ts.isJsxOpeningElement(node) && node.attributes.properties.some(p =>
    ts.isJsxAttribute(p) && p.name.getText(ast) === 'className' && p.initializer?.text?.split(/\s+/).includes('skill-card'))) card = node;
  ts.forEachChild(node, visit);
}
visit(ast);

test('skill cards support Enter and Space without responding to unrelated keys', () => {
  assert.ok(card, 'skill card must exist');
  const attribute = (name) => card.attributes.properties.find(p => ts.isJsxAttribute(p) && p.name.getText(ast) === name);
  assert.equal(attribute('role')?.initializer?.text, 'button');
  assert.equal(attribute('tabIndex')?.initializer?.expression?.getText(ast), '0');
  const handler = attribute('onKeyDown')?.initializer?.expression;
  assert.ok(handler);
  let selected;
  const compiled = ts.transpileModule(`(${handler.getText(ast)})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const onKeyDown = runInNewContext(compiled, { setSelected: value => { selected = value; }, s: { name: 'sample' } });
  for (const key of ['Enter', ' ']) {
    selected = undefined;
    let prevented = false;
    onKeyDown({ key, preventDefault: () => { prevented = true; } });
    assert.equal(selected, 'sample');
    assert.equal(prevented, true);
  }
  selected = undefined;
  let prevented = false;
  onKeyDown({ key: 'Escape', preventDefault: () => { prevented = true; } });
  assert.equal(selected, undefined);
  assert.equal(prevented, false);
});
