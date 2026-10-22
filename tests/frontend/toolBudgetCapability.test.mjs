import assert from 'node:assert/strict';
import test from 'node:test';
import { registerBudgetCapability, CAPABILITY_METHOD } from '../../agents/tool-budget/capability.mjs';

const nonce = 'ab'.repeat(16);
function fixture() {
  const policy = Object.freeze({ maxCalls: 2, timeoutMs: 8000 });
  const entry = { enabled: true, hooks: { allowConversationAccess: true }, config: { ...policy } };
  let handler;
  const runtime = { version: '2026.10.2', config: { current: () => ({ plugins: {
    entries: { 'easel-tool-budget': entry },
  } }) } };
  registerBudgetCapability({ runtime, registerGatewayMethod(name, callback, options) {
    assert.equal(name, CAPABILITY_METHOD);
    assert.deepEqual(options, { scope: 'operator.read', profileAccess: 'required' });
    handler = callback;
  } }, policy);
  return { entry, runtime, read(params = { nonce }) {
    let reply;
    handler({ params, respond: (...args) => { assert.equal(reply, undefined); reply = args; } });
    return reply;
  } };
}

test('active evidence echoes the challenge and scopes its policy to this registration', () => {
  const f = fixture();
  const [ok, proof] = f.read();
  assert.equal(ok, true);
  assert.equal(proof.nonce, nonce);
  assert.equal(proof.maxCalls, 2);
  assert.equal(proof.timeoutMs, 8000);
  assert.equal(proof.requestAdmissionToken, false);
  assert.equal(f.read({ nonce: 'cd'.repeat(16) })[1].instanceId, proof.instanceId);
  assert.notEqual(fixture().read()[1].instanceId, proof.instanceId);
});

for (const mutate of [
  f => { f.entry.enabled = false; },
  f => { f.entry.hooks.allowConversationAccess = false; },
  f => { f.entry.config.maxCalls = 3; },
  f => { f.entry.config.timeoutMs = 9999; },
  f => { f.runtime.version = '2026.10.3'; },
  f => { f.runtime.config.current = () => { throw Error('unavailable'); }; },
]) test(`rejects stale or unverified policy: ${mutate}`, () => {
  const f = fixture(); mutate(f);
  assert.equal(f.read()[0], false);
  assert.equal(f.read()[1], undefined);
});

for (const params of [{}, null, { nonce: true }, { nonce: 'x'.repeat(32) }, { nonce, extra: true }]) {
  test(`rejects invalid challenge ${JSON.stringify(params)}`, () => assert.equal(fixture().read(params)[0], false));
}
