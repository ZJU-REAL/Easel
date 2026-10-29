import assert from 'node:assert/strict';
import test from 'node:test';
import { installBudgetHooks } from '../../agents/tool-budget/hooks.mjs';

const context = { agentId: 'fixture', sessionKey: 'session-private', runId: 'run-private' };
const drain = () => new Promise(resolve => setImmediate(resolve));

for (const pluginConfig of [undefined, null, {}]) {
  test(`unconfigured budgets register no restrictions or deadline: ${JSON.stringify(pluginConfig)}`, () => {
    const hooks = [], timers = [], stops = [];
    const policy = installBudgetHooks({ pluginConfig,
      on: (...args) => hooks.push(args), logger: { info() {} } }, {
      clock: () => { throw Error('An unlimited run needs no budget clock'); },
      schedule: (...args) => timers.push(args),
      stop: (...args) => stops.push(args),
    });
    assert.equal(policy, null);
    assert.deepEqual(hooks, []);
    assert.deepEqual(timers, []);
    assert.deepEqual(stops, []);
  });
}

for (const pluginConfig of [{ maxCalls: 2 }, { timeoutMs: 100 },
  { maxCalls: -1, timeoutMs: 100 }, { maxCalls: 2, timeoutMs: 0 }]) {
  test(`explicit incomplete or invalid limits fail before registering hooks: ${JSON.stringify(pluginConfig)}`, () => {
    const hooks = [];
    assert.throws(() => installBudgetHooks({ pluginConfig,
      on: (...args) => hooks.push(args) }, { stop() {} }), TypeError);
    assert.deepEqual(hooks, []);
  });
}

test('registered policy remains the policy enforced by later runs', () => {
  const pluginConfig = { maxCalls: 1, timeoutMs: 100 };
  const hooks = {};
  const policy = installBudgetHooks({ pluginConfig,
    on: (name, handler) => { hooks[name] = handler; }, logger: { info() {} } },
  { stop: () => ({}), clock: () => 0, schedule: () => ({ unref() {} }), cancel() {} });
  pluginConfig.maxCalls = 99;
  pluginConfig.timeoutMs = 99999;
  assert.ok(Object.isFrozen(policy));
  assert.deepEqual(policy, { maxCalls: 1, timeoutMs: 100 });
  assert.equal(hooks.before_agent_run({}, context).outcome, 'pass');
  assert.equal(hooks.before_tool_call({ toolCallId: 'first' }, context), undefined);
  assert.equal(hooks.before_tool_call({ toolCallId: 'second' }, context).block, true);
});
function fixture(options = {}) {
  let now = 0;
  const hooks = {}, logs = [], stops = [], timers = [];
  installBudgetHooks({ pluginConfig: { maxCalls: 2, timeoutMs: 100 },
    on: (name, handler) => { hooks[name] = handler; }, logger: { info: text => logs.push(JSON.parse(text)) } },
  { clock: () => now, schedule: callback => { const timer = { callback }; timers.push(timer); return timer; },
    cancel: timer => { timer.cancelled = true; },
    stop: target => { stops.push(target); return { aborted: true, runIds: [target.runId] }; }, ...options });
  return { hooks, logs, stops, timers, advance: value => { now = value; },
    begin: (ctx = context) => hooks.before_agent_run({}, ctx),
    call: (id, ctx = context) => hooks.before_tool_call({ toolCallId: id }, ctx) };
}

test('hook adapter reserves before effects and preserves budgets across attempts', async () => {
  const f = fixture();
  assert.equal(f.begin().outcome, 'pass');
  let effects = 0;
  for (let i = 0; i < 20; i++) {
    if (!f.call(`call-${i}`)?.block) {
      effects++;
      f.hooks.after_tool_call({ toolCallId: `call-${i}`, error: 'fixture failure' }, context);
    }
  }
  assert.equal(effects, 2);
  assert.equal(f.begin().outcome, 'block');
  await drain();
  assert.deepEqual(f.stops, [{ ...context, preserveSideRuns: true }]);
  assert.equal(f.logs[0].failed, 2);
  assert.equal(f.logs[0].stopStatus, 'confirmed');
  assert.equal(f.begin({ ...context, runId: 'other' }).outcome, 'pass');
  assert.equal(f.call('call-0', { ...context, runId: 'other' }), undefined);
});

test('deadline timer stops a thinking run without waiting for another tool', async () => {
  const f = fixture();
  f.begin();
  f.advance(90);
  assert.equal(f.begin().outcome, 'pass');
  assert.equal(f.timers.length, 1);
  f.advance(100);
  f.timers[0].callback();
  await drain();
  assert.equal(f.stops.length, 1);
  assert.equal(f.logs[0].stopReason, 'time_budget_exhausted');
  assert.equal(f.call('late').block, true);
});

test('missing and mismatched identities never execute a tool', () => {
  const f = fixture();
  assert.equal(f.begin({}).outcome, 'block');
  assert.equal(f.call('unstarted').block, true);
  f.begin();
  assert.equal(f.hooks.before_tool_call({ runId: 'other', toolCallId: 'x' }, context).block, true);
  assert.equal(f.hooks.before_tool_call({ toolCallId: 'x' }, { ...context, toolCallId: 'y' }).block, true);
  assert.equal(f.call(undefined).block, true);
});

test('unconfirmed stop never reopens admission or widens its scope', async () => {
  for (const result of [undefined, { aborted: false }, { aborted: true, runIds: ['other'] }, new Error('private')]) {
    const stops = [];
    const f = fixture({ stop: target => {
      stops.push(target);
      if (result instanceof Error) throw result;
      return result;
    } });
    f.begin();
    for (let i = 0; i < 5; i++) f.call(`call-${i}`);
    await drain();
    assert.deepEqual(stops, [{ ...context, preserveSideRuns: true }]);
    assert.equal(f.logs[0].stopStatus, 'unconfirmed');
    assert.equal(f.call('still-closed').block, true);
    assert.ok(!JSON.stringify(f.logs).includes('private'));
  }
});

test('agent end clears the deadline and rejects late hooks without reopening the run', async () => {
  const f = fixture();
  f.begin();
  f.call('one');
  f.hooks.agent_end({ success: true, runId: context.runId }, context);
  assert.equal(f.timers[0].cancelled, true);
  assert.equal(f.begin().outcome, 'block');
  assert.equal(f.call('late').block, true);
  f.advance(200);
  f.timers[0].callback();
  await drain();
  assert.equal(f.stops.length, 0);
  assert.equal(f.logs[0].stopReason, 'run_finished');
});

test('early timer wakeup rearms the original deadline', async () => {
  const f = fixture();
  f.begin();
  f.advance(99.5);
  f.timers[0].callback();
  assert.equal(f.timers.length, 2);
  assert.equal(f.stops.length, 0);
  f.advance(100);
  f.timers[1].callback();
  await drain();
  assert.equal(f.stops.length, 1);
});

test('full tracking registry fails closed rather than evicting old run identities', () => {
  const f = fixture();
  for (let i = 0; i < 10000; i++) {
    const ctx = { ...context, runId: `run-${i}` };
    assert.equal(f.begin(ctx).outcome, 'pass');
    f.hooks.agent_end({}, ctx);
  }
  assert.equal(f.begin().reason, 'tracking_capacity_exhausted');
  assert.equal(f.begin({ ...context, runId: 'run-0' }).reason, 'run_finished');
});
