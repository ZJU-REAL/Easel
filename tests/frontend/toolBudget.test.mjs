import assert from 'node:assert/strict';
import test from 'node:test';
import { ToolBudget } from '../../agents/tool-budget/budget.mjs';

const create = (options = {}) => new ToolBudget({ maxCalls: 2, timeoutMs: 100, clock: () => 0, ...options });

test('concurrent reservations never over-admit and remain isolated per run', async () => {
  const budget = create();
  const decisions = await Promise.all(Array.from({ length: 20 }, (_, i) =>
    Promise.resolve().then(() => budget.admit(`call-${i}`))));
  assert.equal(decisions.filter(d => d.allowed).length, 2);
  assert.equal(budget.snapshot().admitted, 2);
  assert.deepEqual(create().admit('call-0'), { allowed: true });
});

test('failed tools consume admission; repeated results cannot refund or double-count', () => {
  const budget = create();
  assert.equal(budget.admit('one').allowed, true);
  assert.equal(budget.settle('one', true), true);
  assert.equal(budget.settle('one'), false);
  assert.equal(budget.settle('unknown'), false);
  assert.equal(budget.admit('two').allowed, true);
  assert.equal(budget.admit('three').reason, 'call_budget_exhausted');
  assert.equal(budget.snapshot().failed, 1);
});

test('duplicate call IDs fail closed without a second reservation', () => {
  const budget = create();
  budget.admit('one');
  assert.equal(budget.admit('one').reason, 'duplicate_call_identity');
  assert.equal(budget.admit('two').allowed, false);
  assert.equal(budget.snapshot().admitted, 1);
});

test('deadline includes time before the first tool and cannot be reset', () => {
  let now = 20;
  const budget = create({ clock: () => now });
  now = 120;
  assert.equal(budget.expire(), 'time_budget_exhausted');
  assert.equal(budget.admit('late').allowed, false);
  assert.equal(budget.snapshot().admitted, 0);
});

test('invalid/backwards clocks fail closed', () => {
  for (const invalid of [NaN, Infinity, 9]) {
    let now = 10;
    const budget = create({ clock: () => now });
    now = invalid;
    assert.equal(budget.admit('call').reason, 'clock_invalid');
  }
});

test('finished runs cannot admit late calls but may drain admitted results', () => {
  const budget = create();
  budget.admit('one');
  budget.finish();
  assert.equal(budget.admit('late').reason, 'run_finished');
  assert.equal(budget.settle('one'), true);
  assert.equal(budget.snapshot().succeeded, 1);
});

test('zero budget, missing identities and invalid limits are explicit', () => {
  assert.equal(create({ maxCalls: 0 }).admit('call').reason, 'call_budget_exhausted');
  for (const id of ['', ' ', null, 3, 'x'.repeat(513)]) {
    assert.equal(create().admit(id).reason, 'missing_call_identity');
  }
  for (const value of [-1, 1.5, NaN, Infinity, true, '2', 10001]) {
    assert.throws(() => create({ maxCalls: value }), TypeError);
  }
  for (const value of [0, -1, 1.5, Infinity, 3600001]) {
    assert.throws(() => create({ timeoutMs: value }), TypeError);
  }
});

test('snapshot contains only aggregate facts and cannot mutate the ledger', () => {
  const budget = create();
  budget.admit('private-call-id');
  const snapshot = budget.snapshot();
  assert.ok(!JSON.stringify(snapshot).includes('private'));
  assert.throws(() => { snapshot.admitted = 0; }, TypeError);
  assert.equal(budget.snapshot().admitted, 1);
});
