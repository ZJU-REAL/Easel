import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/SettingsPanel.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('SettingsPanel.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = parsed.statements.find(node =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'OptionsDropdown');
assert.ok(declaration);
const { outputText } = ts.transpileModule(declaration.getText(parsed) + '\nOptionsDropdown;', {
  compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
});

test('Escape is captured by the dropdown, not the surrounding settings dialog', () => {
  const listeners = [];
  const removed = [];
  const cleanups = [];
  let closed = 0;
  let focused = 0;
  const component = runInNewContext(outputText, {
    useRef: () => ({ current: null }),
    useState: () => [null, () => {}],
    useEffect: callback => {
      const cleanup = callback();
      if (cleanup) cleanups.push(cleanup);
    },
    window: {
      innerHeight: 800, innerWidth: 1200,
      addEventListener: () => {}, removeEventListener: () => {},
    },
    document: {
      addEventListener: (...args) => listeners.push(args),
      removeEventListener: (...args) => removed.push(args),
    },
  });
  component({
    anchor: {
      getBoundingClientRect: () => ({ top: 100, bottom: 130, left: 20, width: 100 }),
      focus: () => { focused += 1; },
    },
    items: [], current: '', onClose: () => { closed += 1; },
  });
  const registration = listeners.find(([name]) => name === 'keydown');
  assert.equal(registration[2], true);
  const event = {
    key: 'Escape', defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this.stopped = true; },
  };
  registration[1](event);
  assert.equal(closed, 1);
  assert.equal(focused, 1);
  assert.equal(event.defaultPrevented, true);
  assert.equal(event.stopped, true);
  registration[1]({ key: 'Enter' });
  assert.equal(closed, 1);
  for (const cleanup of cleanups) cleanup();
  assert.ok(removed.some(([name, callback, capture]) =>
    name === 'keydown' && callback === registration[1] && capture === true));
});
