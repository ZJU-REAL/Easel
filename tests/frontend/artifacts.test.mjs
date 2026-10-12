import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/lib/artifacts.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const exports = {};
runInNewContext(outputText, { exports });
const { artifactFromUrl, archiveFromUrl, mergeArtifacts, fitArtifact } = exports;

test('local media types are recognized without converting text reports or external links', () => {
  for (const [extension, kind] of [
    ['PNG', 'image'], ['svg', 'image'], ['html', 'html'], ['htm', 'html'],
    ['mp4', 'video'], ['webm', 'video'], ['mp3', 'audio'], ['pdf', 'pdf'],
  ]) {
    const artifact = artifactFromUrl(`/api/media/project/card.${extension}`);
    assert.equal(artifact.kind, kind);
    assert.equal(artifact.name, `card.${extension}`);
  }
  assert.equal(artifactFromUrl('/api/media/project/report.md'), null);
  assert.equal(artifactFromUrl('https://example.test/api/media/image.png'), null);
});

test('artifact filenames decode Unicode and preserve download query arguments', () => {
  const url = '/api/media/%E5%8D%A1%E7%89%87/%E6%88%90%E5%93%81.png?download=1';
  assert.equal(artifactFromUrl(url).name, '成品.png');
  assert.equal(artifactFromUrl(url).url, url);
});

test('content-library preview links also join the gallery, including old saved conversations', () => {
  for (const extension of ['png', 'html', 'pdf', 'mp4', 'mp3']) {
    const artifact = artifactFromUrl(`#/outputs/project/file.${extension}`);
    assert.equal(artifact.url, `/api/media/project/file.${extension}`);
  }
  assert.equal(artifactFromUrl('#/outputs/%E5%8D%A1%E7%89%87/a%20b.html').name, 'a b.html');
  assert.equal(artifactFromUrl('#/outputs/project/report.md'), null);
  assert.equal(artifactFromUrl('#/outputs/project'), null);
  assert.equal(artifactFromUrl('#/outputs/../private.png'), null);
});

test('referenced output ZIP files resolve safely without accepting unrelated archive URLs', () => {
  assert.equal(archiveFromUrl('#/outputs/cards/all.zip'), 'cards/all.zip');
  assert.equal(archiveFromUrl('/api/media/cards/all.zip?download=1'), 'cards/all.zip');
  for (const url of ['https://example.test/all.zip', '/api/media/../private.zip',
    '/api/media/%2e%2e/private.zip', '/api/media/%00bad.zip', '/api/media/%ZZ.zip',
    '/api/media/cards/image.png']) assert.equal(archiveFromUrl(url), null);
});

test('gallery merges archive members in order while removing differently encoded duplicate images', () => {
  const original = artifactFromUrl('/api/media/cards/成品.png');
  const encoded = artifactFromUrl('/api/media/cards/%E6%88%90%E5%93%81.png?download=1');
  const second = artifactFromUrl('/api/media/cards/two.png');
  const merged = mergeArtifacts([original], [encoded, second]);
  assert.equal(merged.length, 2);
  assert.equal(merged[0].name, '成品.png');
  assert.equal(merged[1].name, 'two.png');
});

test('invalid encoded or traversing artifact paths never render', () => {
  for (const url of [
    '/api/media/../secret.png', '/api/media/%2e%2e/secret.png', '/api/media/a/./image.png',
    '/api/media//image.png', '/api/media/%ZZ.png', '/api/media/a%5cimage.png',
    '/api/media/%00image.png', '//api/media/image.png', 'javascript:alert(1)',
  ]) assert.equal(artifactFromUrl(url), null, url);
});

test('responsive fit preserves proportions, fits both bounds and never enlarges artwork', () => {
  for (const [width, height] of [[1080, 1440], [1200, 600], [300, 300]]) {
    for (const [availableWidth, availableHeight] of [[1000, 520], [550, 480], [280, 330]]) {
      const fitted = fitArtifact(width, height, availableWidth, availableHeight);
      assert.ok(fitted.width <= availableWidth);
      assert.ok(fitted.height <= availableHeight);
      assert.ok(fitted.scale <= 1);
      assert.ok(Math.abs(fitted.width / fitted.height - width / height) < 0.00001);
    }
  }
});

function gallery() {
  const input = readFileSync(new URL('../../web/frontend/src/components/ArtifactGallery.tsx', import.meta.url), 'utf8');
  const { outputText: compiled } = ts.transpileModule(input, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX },
  });
  let selected = 0;
  const module = {};
  const jsx = (type, props) => ({ type, props });
  runInNewContext(compiled, {
    exports: module,
    require: id => id === 'react' ? {
      useState: initial => typeof initial === 'number' ? [selected, value => { selected = value; }] : [[], () => {}],
      useEffect: () => {},
    } : id === 'react/jsx-runtime' ? { jsx, jsxs: jsx }
      : id.endsWith('/artifacts') ? exports : { IconChevron: 'chevron', IconOutputs: 'outputs' },
  });
  const artifacts = ['first', 'second', 'third'].map(name => ({
    url: `/api/media/project/${name}.png`, name: `${name}.png`, kind: 'image',
  }));
  const render = () => module.default({ artifacts });
  const buttons = tree => {
    const result = [];
    const visit = node => {
      if (!node || typeof node !== 'object') return;
      if (node.type === 'button') result.push(node);
      const children = node.props?.children;
      (Array.isArray(children) ? children.flat(Infinity) : [children]).forEach(visit);
    };
    visit(tree);
    return result;
  };
  return { render, buttons, selected: () => selected };
}

test('multiple artifact arrows and keyboard controls wrap around without losing the files', () => {
  const view = gallery();
  let tree = view.render();
  let buttons = view.buttons(tree);
  assert.equal(buttons.length, 2);
  buttons.find(button => button.props['aria-label'] === '下一个产物').props.onClick();
  assert.equal(view.selected(), 1);
  tree = view.render();
  tree.props.onKeyDown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(view.selected(), 2);
  view.render().props.onKeyDown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(view.selected(), 0);
  buttons = view.buttons(view.render());
  buttons.find(button => button.props['aria-label'] === '上一个产物').props.onClick();
  assert.equal(view.selected(), 2);
});
