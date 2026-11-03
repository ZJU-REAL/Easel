import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/skillDisplayNames.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
runInNewContext(outputText, { exports });

test('skill display names fall back safely for unknown and prototype names', () => {
  assert.equal(exports.displayName('skill-xhs-analyzer'), '小红书分析');
  for (const name of ['new-skill', 'constructor', 'toString', '__proto__']) {
    assert.equal(exports.displayName(name), name);
  }
});

test('icon lookup selects exact matches and safely falls back for unknown IDs', () => {
  const page = readFileSync(new URL('../../web/frontend/src/components/SkillPage.tsx', import.meta.url), 'utf8');
  const ast = ts.createSourceFile('SkillPage.tsx', page, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const fn = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'iconFor');
  assert.ok(fn);
  const compiled = ts.transpileModule(fn.getText(ast) + '\niconFor;', {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const fallback = () => null;
  const exact = () => null;
  const context = { specific: { 'skill-xhs-publisher': exact } };
  for (const name of ['Video', 'Image', 'Music', 'Mic', 'Layout', 'Text', 'Chart', 'Send', 'Search', 'Profile', 'Compass', 'Outputs']) {
    context[`Icon${name}`] = fallback;
  }
  const iconFor = runInNewContext(compiled, context);
  assert.equal(iconFor('SKILL-XHS-PUBLISHER', fallback), exact);
  for (const name of ['constructor', 'toString', '__proto__', 'unknown']) {
    assert.equal(iconFor(name, fallback), fallback);
  }
});
