import assert from 'node:assert/strict';
import test from 'node:test';
import { registerBudgetSend } from '../../agents/tool-budget/send.mjs';

function fixture(dispatch = async () => ({ ok: true, payload: { runId: 'accepted' } })) {
  const policy = { maxCalls: 2, timeoutMs: 8000 };
  const entry = { enabled: true, hooks: { allowConversationAccess: true }, config: { ...policy } };
  const request = { instanceId: 'current', ...policy, sessionKey: 'agent:main:test',
    message: 'hello', idempotencyKey: 'request-one' };
  const calls = [];
  let handler;
  registerBudgetSend({ runtime: { version: '2026.10.2', config: { current: () => ({
    plugins: { entries: { 'easel-tool-budget': entry } },
  }) } }, registerGatewayMethod(name, callback, options) {
    assert.equal(name, 'easel.toolBudget.send');
    assert.deepEqual(options, { scope: 'operator.write', profileAccess: 'required' });
    handler = callback;
  } }, policy, 'current', async (...args) => { calls.push(args); return dispatch(...args); });
  return { entry, request, calls, async send(params = request) {
    const replies = [];
    await handler({ params, respond: (...args) => replies.push(args) });
    assert.equal(replies.length, 1);
    return replies[0];
  } };
}

test('matching registration forwards only chat fields through authenticated SDK dispatch', async () => {
  const f = fixture();
  assert.deepEqual(await f.send(), [true, { runId: 'accepted' }, undefined]);
  assert.deepEqual(f.calls, [['chat.send', { sessionKey: 'agent:main:test', message: 'hello',
    idempotencyKey: 'request-one' }, { timeoutMs: 10000 }]]);
});
for (const patch of [{ instanceId: 'previous-process' }, { maxCalls: 3 }, { timeoutMs: 9000 },
  { sessionKey: '../other' }, { idempotencyKey: '' }, { message: '' }, { admin: true }]) {
  test(`rejects request before dispatch ${JSON.stringify(patch)}`, async () => {
    const f = fixture();
    assert.equal((await f.send({ ...f.request, ...patch }))[0], false);
    assert.equal(f.calls.length, 0);
  });
}
test('a policy change between probe and send prevents execution', async () => {
  const f = fixture(); f.entry.enabled = false;
  assert.equal((await f.send())[0], false);
  assert.equal(f.calls.length, 0);
});
test('ambiguous dispatch failure never retries or widens authority', async () => {
  const f = fixture(async () => { throw Error('connection lost after acceptance'); });
  assert.equal((await f.send())[0], false);
  assert.equal(f.calls.length, 1);
});
test('core authorization rejection is preserved', async () => {
  const error = { code: 'FORBIDDEN', message: 'denied' };
  const f = fixture(async () => ({ ok: false, error }));
  assert.deepEqual(await f.send(), [false, undefined, error]);
});
