import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const require = createRequire(new URL('../../web/frontend/package.json', import.meta.url));
const ts = require('typescript');
const source = readFileSync(new URL('../../web/frontend/src/components/HarnessSettings.tsx', import.meta.url), 'utf8');
const parsed = ts.createSourceFile('HarnessSettings.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = parsed.statements.find(node =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'HarnessSettings');
assert.ok(declaration);
const { outputText } = ts.transpileModule(
  declaration.getText(parsed).replace('export default ', '') + '\nHarnessSettings;', {
    compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  });

const settle = () => new Promise(resolve => setImmediate(resolve));

test('settings defer environment probes and wait for the actual runtime before loading models', () => {
  const panel = readFileSync(new URL('../../web/frontend/src/components/SettingsPanel.tsx', import.meta.url), 'utf8');
  assert.match(panel, /const \[harness, setHarness\] = useState\(''\)/);
  assert.match(panel, /if \(sec === 'env'\) void refreshEnv\(\)/);
  assert.match(panel, /if \(!harness\) return;/);
  assert.match(panel, /if \(harness !== 'openclaw'\) return;/);
});

test('sidebar keeps its settings button unwrapped beside a truncated status', () => {
  const css = readFileSync(new URL('../../web/frontend/src/styles/index.css', import.meta.url), 'utf8');
  const sidebar = readFileSync(new URL('../../web/frontend/src/components/Sidebar.tsx', import.meta.url), 'utf8');
  const status = css.match(/\.sidebar-status-text\s*\{([^}]+)\}/)?.[1];
  const gear = css.match(/\.settings-gear\s*\{([^}]+)\}/)?.[1];
  assert.ok(status && gear);
  assert.match(sidebar, /className="sidebar-status-text"/);
  assert.match(status, /min-width:\s*0/);
  assert.match(status, /text-overflow:\s*ellipsis/);
  assert.match(gear, /flex-shrink:\s*0/);
  assert.match(gear, /white-space:\s*nowrap/);
});

function setup({ runtime = 'openclaw', locked = false, installed = true, saveError = '', modelError = '',
  settingsErrors = [] } = {}) {
  const state = [];
  let cursor = 0;
  const effects = [];
  let effectCursor = 0;
  const settingsRequests = [];
  const changes = [];
  const saves = [];
  const selections = [];
  const modelRequests = [];
  const settings = {
    runtime,
    models: { codex: 'codex-model', opencode: 'provider/model' },
    sandbox: 'workspace-write',
    locked,
    agents: ['api', 'openclaw', 'opencode', 'codex', 'acp'].map(id => ({
      id, label: id === 'api' ? '仅聊天模式' : id,
      installed: ['api', 'openclaw'].includes(id) || installed, install_hint: `install ${id}`,
    })),
  };
  const component = runInNewContext(outputText, {
    React: {
      Fragment: 'fragment',
      createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }),
    },
    SettingsSelect: 'settings-select',
    useState: initial => {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    },
    useRef: initial => {
      const index = cursor++;
      if (!(index in state)) state[index] = { current: initial };
      return state[index];
    },
    useEffect: (callback, dependencies) => {
      const index = effectCursor++;
      const previous = effects[index];
      if (!previous || dependencies.some((value, position) => value !== previous.dependencies[position])) {
        previous?.cleanup?.();
        effects[index] = { dependencies, cleanup: callback() };
      }
    },
    fetchHarnessSettings: async () => {
      const index = settingsRequests.length;
      settingsRequests.push(index);
      if (settingsErrors[index]) throw new Error(settingsErrors[index]);
      return settings;
    },
    fetchHarnessModels: async runtime => {
      modelRequests.push(runtime);
      if (modelError) throw new Error(modelError);
      return { runtime, models: [{ id: 'another-model', label: 'Another model', default: true }] };
    },
    saveHarnessSettings: async (runtime, model, sandbox) => {
      saves.push({ runtime, model, sandbox });
      if (saveError) throw new Error(saveError);
      return { ...settings, runtime, models: { ...settings.models, [runtime]: model }, sandbox };
    },
  });
  const onChange = value => changes.push(value);
  const onSelect = value => selections.push(value);
  return {
    changes,
    saves,
    selections,
    modelRequests,
    settingsRequests,
    render() {
      cursor = 0;
      effectCursor = 0;
      const tree = component({ onChange, onSelect });
      return tree;
    },
  };
}

function nodes(tree, type) {
  if (!tree || typeof tree !== 'object') return [];
  return [
    ...(tree.type === type ? [tree] : []),
    ...(tree.children || []).flatMap(child => nodes(child, type)),
  ];
}

function text(tree) {
  if (typeof tree === 'string') return tree;
  if (!tree || typeof tree !== 'object') return '';
  return (tree.children || []).map(text).join('');
}

test('changing harness is local until save and retains its model override', async () => {
  const view = setup();
  view.render();
  await settle();
  let tree = view.render();
  assert.equal(nodes(tree, 'settings-select')[0].props.options.length, 5);
  nodes(tree, 'settings-select')[0].props.onChange('codex');
  tree = view.render();
  assert.equal(nodes(tree, 'input')[0].props.value, 'codex-model');
  assert.deepEqual(view.changes, ['openclaw']);
  assert.equal(view.saves.length, 0);
  nodes(tree, 'settings-select').find(node => node.props.label === 'Codex 沙箱').props.onChange('read-only');
  nodes(tree, 'input')[0].props.onChange({ target: { value: 'custom-model' } });
  tree = view.render();
  nodes(tree, 'button')[0].props.onClick();
  assert.equal(nodes(view.render(), 'button')[0].props.disabled, true);
  await settle();
  assert.deepEqual(view.saves, [{ runtime: 'codex', model: 'custom-model', sandbox: 'read-only' }]);
  assert.deepEqual(view.changes, ['openclaw', 'codex']);
  assert.match(text(view.render()), /已保存，请新建对话/);
});

test('environment-locked harness cannot be changed or saved', async () => {
  const view = setup({ locked: true });
  view.render();
  await settle();
  const tree = view.render();
  assert.equal(nodes(tree, 'settings-select')[0].props.disabled, true);
  assert.equal(nodes(tree, 'button')[0].props.disabled, true);
  assert.match(text(tree), /EASEL_AGENT_RUNTIME 已固定底座/);
});

test('settings can retry a failed read without saving or silently changing the engine', async () => {
  const view = setup({ settingsErrors: ['temporary connection failure'] });
  view.render();
  await settle();
  let tree = view.render();
  assert.match(text(tree), /读取失败：.*temporary connection failure/);
  assert.equal(nodes(tree, 'button')[0].props.disabled, true);
  const reload = nodes(tree, 'button').find(node => text(node) === '重新读取');
  assert.ok(reload);
  assert.equal(reload.props.disabled, false);
  reload.props.onClick();
  view.render();
  await settle();
  tree = view.render();
  assert.equal(view.settingsRequests.length, 2);
  assert.equal(nodes(tree, 'settings-select')[0].props.disabled, false);
  assert.deepEqual(view.changes, ['openclaw']);
  assert.deepEqual(view.saves, []);
  assert.doesNotMatch(text(tree), /读取失败/);
});

test('uninstalled native harness cannot be saved and does not show Codex sandbox for ACP', async () => {
  const view = setup({ installed: false });
  view.render();
  await settle();
  nodes(view.render(), 'settings-select')[0].props.onChange('acp');
  const tree = view.render();
  assert.equal(nodes(tree, 'button')[0].props.disabled, true);
  assert.equal(nodes(tree, 'settings-select').length, 1);
  assert.match(text(tree), /不代表模型已登录/);
});

test('engine options retain missing harnesses with configuration previews and installation hints', async () => {
  const view = setup({ installed: false });
  view.render();
  await settle();
  assert.deepEqual(nodes(view.render(), 'settings-select')[0].props.options.map(option => option.value),
    ['api', 'openclaw', 'opencode', 'codex', 'acp']);
  const option = nodes(view.render(), 'settings-select')[0].props.options.find(item => item.value === 'opencode');
  assert.match(option.label, /未安装 \/ 未配置/);
  nodes(view.render(), 'settings-select')[0].props.onChange('opencode');
  const preview = view.render();
  assert.match(text(preview), /未检测到 opencode/);
  assert.match(text(preview), /原有配置未删除/);
  assert.equal(nodes(preview, 'input')[0].props.value, 'provider/model');
  assert.equal(nodes(preview, 'button')[0].props.disabled, true);
  const missing = setup({ runtime: 'codex', installed: false });
  missing.render();
  await settle();
  assert.deepEqual(nodes(missing.render(), 'settings-select')[0].props.options.map(option => option.value),
    ['api', 'openclaw', 'opencode', 'codex', 'acp']);
  assert.equal(nodes(missing.render(), 'button')[0].props.disabled, true);
});
test('failed harness save shows error without switching the active runtime', async () => {
  const view = setup({ saveError: 'active task' });
  view.render();
  await settle();
  nodes(view.render(), 'settings-select')[0].props.onChange('opencode');
  nodes(view.render(), 'button')[0].props.onClick();
  await settle();
  assert.match(text(view.render()), /保存失败：.*active task/);
  assert.deepEqual(view.changes, ['openclaw']);
  assert.equal(nodes(view.render(), 'button')[0].props.disabled, false);
});

test('harness form reuses settings input styling and managed connection hints', async () => {
  const view = setup();
  view.render();
  await settle();
  nodes(view.render(), 'settings-select')[0].props.onChange('codex');
  const tree = view.render();
  assert.equal(nodes(tree, 'input')[0].props.className, 'mock');
  assert.equal(nodes(tree, 'select').length, 0);
  assert.match(text(tree), /连接由适配器管理，无需另选连接方式/);
});

test('chat-only is the initial default with an accessible explanation beside the engine', async () => {
  const view = setup({ runtime: 'api' });
  assert.equal(nodes(view.render(), 'settings-select')[0].props.value, 'api');
  await settle();
  const tree = view.render();
  assert.equal(nodes(tree, 'settings-select')[0].props.options[0].value, 'api');
  assert.equal(nodes(tree, 'settings-select')[0].props.options[0].label, '仅聊天模式');
  assert.equal(nodes(tree, 'settings-select').length, 1);
  assert.equal(nodes(tree, 'input').length, 0);
  const help = nodes(tree, 'button').find(node => node.props['aria-label'] === '仅聊天模式说明');
  const tooltip = nodes(tree, 'span').find(node => node.props.role === 'tooltip');
  assert.equal(help.props['aria-describedby'], tooltip.props.id);
  assert.match(text(tooltip), /不能操作本机文件、运行命令、使用浏览器或执行技能/);
  assert.deepEqual(view.changes, ['api']);
});

test('chat-only can be saved without any agent CLI and preserves the active engine until save', async () => {
  const view = setup({ installed: false });
  view.render();
  await settle();
  nodes(view.render(), 'settings-select')[0].props.onChange('api');
  let tree = view.render();
  assert.equal(nodes(tree, 'button')[0].props.disabled, false);
  assert.equal(nodes(tree, 'input').length, 0);
  assert.deepEqual(view.changes, ['openclaw']);
  nodes(tree, 'button')[0].props.onClick();
  await settle();
  tree = view.render();
  assert.deepEqual(view.changes, ['openclaw', 'api']);
  assert.equal(view.saves[0].runtime, 'api');
  assert.match(text(tree), /无需安装 Agent/);
});

test('OpenClaw selection previews its API configuration without changing the active engine', async () => {
  const view = setup({ runtime: 'codex' });
  view.render();
  await settle();
  nodes(view.render(), 'settings-select')[0].props.onChange('openclaw');
  assert.deepEqual(view.selections, ['codex', 'openclaw']);
  assert.deepEqual(view.changes, ['codex']);
  assert.match(text(view.render()), /OpenClaw 的模型、API 地址和 Key 在下方配置/);
  assert.match(text(view.render()), /当前为配置预览/);
});

for (const runtime of ['codex', 'opencode']) {
  test(`${runtime} loads native models only on request and saves a dropdown selection`, async () => {
    const view = setup({ runtime });
    view.render();
    await settle();
    let tree = view.render();
    assert.equal(view.modelRequests.length, 0);
    nodes(tree, 'button').find(node => text(node) === '拉取模型').props.onClick();
    await settle();
    tree = view.render();
    const dropdown = nodes(tree, 'settings-select').find(node => node.props.label === '原生模型');
    assert.equal(dropdown.props.options[0].value, '');
    assert.equal(dropdown.props.options[1].value, 'another-model');
    dropdown.props.onChange('another-model');
    tree = view.render();
    assert.equal(nodes(tree, 'input')[0].props.value, 'another-model');
    nodes(tree, 'button')[0].props.onClick();
    await settle();
    assert.equal(view.saves[0].model, 'another-model');
    assert.equal(view.saves[0].runtime, runtime);
  });
}

test('native model listing failure preserves the saved model and allows manual input', async () => {
  const view = setup({ runtime: 'codex', modelError: 'CLI unavailable' });
  view.render();
  await settle();
  nodes(view.render(), 'button').find(node => text(node) === '拉取模型').props.onClick();
  await settle();
  const tree = view.render();
  assert.match(text(tree), /读取失败：(Error: )?CLI unavailable/);
  assert.equal(nodes(tree, 'input')[0].props.value, 'codex-model');
  assert.equal(view.saves.length, 0);
});
