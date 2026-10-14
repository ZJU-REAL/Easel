import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';
import { DurableToolStore } from '../../agents/tool-budget/durable-store.mjs';

const identity = { agentId: 'private-agent', sessionKey: 'private-session', runId: 'private-run' };
const policy = { maxCalls: 2, timeoutMs: 1000 };
const moduleUrl = new URL('../../agents/tool-budget/durable-store.mjs', import.meta.url).href;
const children = new WeakMap();
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'easel-budget-'));
  const path = join(root, 'budget.sqlite');
  const stores = [];
  children.set(t, []);
  let now = 100;
  t.after(async () => {
    for (const { proc, exited } of children.get(t)) {
      if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
      await exited;
    }
    for (const store of stores) { try { store.close(); } catch {} }
    rmSync(root, { recursive: true });
  });
  const open = (create = false) => {
    const store = new DurableToolStore(path, { create, clock: () => now });
    stores.push(store);
    return store;
  };
  return { path, open, advance: value => { now = value; } };
}

test('reopen preserves reservations, original deadline and closed runs', t => {
  const f = fixture(t), first = f.open(true);
  assert.equal(first.begin(identity, policy).remainingMs, 1000);
  assert.equal(first.reserve(identity, 'first').allowed, true);
  first.close();
  f.advance(500);
  const resumed = f.open();
  assert.deepEqual(resumed.begin(identity, policy), { allowed: true, used: 1, remainingCalls: 1, remainingMs: 600 });
  assert.equal(resumed.reserve(identity, 'second').allowed, true);
  assert.equal(resumed.reserve(identity, 'third').reason, 'call_budget_exhausted');
  resumed.close();
  assert.equal(f.open().begin(identity, policy).reason, 'call_budget_exhausted');
  assert.ok(!readFileSync(f.path).includes(Buffer.from('private-')));
});

test('policy changes, duplicate calls and finish cannot reset a durable identity', t => {
  const f = fixture(t), store = f.open(true);
  for (const kind of ['policy', 'duplicate', 'finish']) {
    const ctx = { ...identity, runId: kind };
    store.begin(ctx, policy);
    store.reserve(ctx, 'one');
    if (kind === 'policy') store.begin(ctx, { ...policy, maxCalls: 3 });
    if (kind === 'duplicate') store.reserve(ctx, 'one');
    if (kind === 'finish') store.finish(ctx);
  }
  store.close();
  const reopened = f.open();
  for (const [runId, reason] of [['policy', 'policy_mismatch'], ['duplicate', 'duplicate_call_identity'], ['finish', 'run_finished']]) {
    assert.equal(reopened.begin({ ...identity, runId }, policy).reason, reason);
  }
  assert.equal(reopened.begin({ ...identity, sessionKey: 'other' }, policy).allowed, true);
});

test('downtime consumes the deadline and observed clock rollback closes admission', t => {
  const f = fixture(t), store = f.open(true);
  store.begin(identity, policy);
  f.advance(50);
  assert.equal(store.reserve(identity, 'one').reason, 'clock_invalid');
  store.close();
  f.advance(1000);
  assert.equal(f.open().begin(identity, policy).reason, 'clock_invalid');
  const other = { ...identity, runId: 'expired' };
  const writer = f.open();
  writer.begin(other, policy);
  writer.close();
  f.advance(2000);
  assert.equal(f.open().begin(other, policy).reason, 'time_budget_exhausted');
});

test('missing, corrupt and unsupported databases are never silently replaced', t => {
  const f = fixture(t);
  assert.throws(() => f.open(), /Cannot open/);
  writeFileSync(f.path, 'private-invalid-database');
  assert.throws(() => f.open(), /Cannot open/);
  assert.throws(() => f.open(true), /Cannot open/);
  assert.equal(readFileSync(f.path, 'utf8'), 'private-invalid-database');
  rmSync(f.path);
  f.open(true).close();
  const db = new DatabaseSync(f.path);
  db.exec('PRAGMA user_version=99');
  db.close();
  assert.throws(() => f.open(), /Cannot open/);
});

test('lock conflicts and failed reservation writes deny admission without partial debit', t => {
  const f = fixture(t), store = f.open(true);
  store.begin(identity, policy);
  const db = new DatabaseSync(f.path);
  try {
    db.exec('BEGIN IMMEDIATE');
    assert.deepEqual(store.reserve(identity, 'one'), { allowed: false, reason: 'storage_unavailable' });
    db.exec('ROLLBACK');
    assert.equal(store.reserve(identity, 'two').allowed, false); // Failed handle stays closed.
    db.exec("CREATE TRIGGER reject_debit BEFORE UPDATE OF used ON runs BEGIN SELECT RAISE(ABORT, 'private'); END;");
    const reopened = f.open();
    assert.equal(reopened.reserve(identity, 'three').reason, 'storage_unavailable');
    assert.equal(db.prepare('SELECT count(*) AS n FROM calls').get().n, 0);
    assert.equal(db.prepare('SELECT used FROM runs').get().used, 0);
  } finally { db.close(); }
});

test('identity validation and zero budget never create an admission', t => {
  const f = fixture(t), store = f.open(true);
  assert.equal(store.begin({}, policy).allowed, false);
  assert.equal(store.begin(identity, { ...policy, maxCalls: -1 }).allowed, false);
  assert.equal(store.reserve(identity, 'one').reason, 'run_not_admitted');
  store.begin(identity, { ...policy, maxCalls: 0 });
  assert.equal(store.reserve(identity, 'one').reason, 'call_budget_exhausted');
  const stopped = { ...identity, runId: 'stopped' };
  store.begin(stopped, policy);
  assert.equal(store.finish(stopped, 'private arbitrary reason').reason, 'invalid_stop_reason');
  store.finish(stopped, 'time_budget_exhausted');
  store.close();
  assert.equal(f.open().begin(stopped, policy).reason, 'time_budget_exhausted');
});

test('full ledger retains existing identities rather than evicting their budgets', t => {
  const f = fixture(t), store = f.open(true);
  store.begin(identity, policy);
  store.finish(identity);
  const db = new DatabaseSync(f.path);
  try {
    const id = db.prepare('SELECT id FROM runs').get().id;
    const insert = db.prepare('INSERT INTO runs SELECT ?,max_calls,timeout_ms,deadline_ms,last_ms,used,reason FROM runs WHERE id=?');
    db.exec('BEGIN IMMEDIATE');
    for (let i = 0; i < 9999; i++) insert.run(`fixture-${i}`, id);
    db.exec('COMMIT');
  } finally { db.close(); }
  assert.equal(store.begin({ ...identity, runId: 'new' }, policy).reason, 'tracking_capacity_exhausted');
  assert.equal(store.begin(identity, policy).reason, 'run_finished');
});

function child(t, source, path) {
  const proc = spawn(process.execPath, ['--input-type=module', '-e', source, path],
    { stdio: ['ignore', 'ignore', 'pipe', 'ipc'], windowsHide: true });
  let stderr = '';
  proc.stderr.on('data', data => { stderr += data; });
  const exited = once(proc, 'exit');
  children.get(t).push({ proc, exited });
  const message = () => Promise.race([once(proc, 'message').then(([value]) => value),
    exited.then(() => { throw new Error(`Fixture exited before reporting: ${stderr}`); })]);
  return { proc, exited, message };
}

test('two processes racing for one remaining reservation admit exactly one', { timeout: 15000 }, async t => {
  const f = fixture(t), store = f.open(true);
  store.begin(identity, { maxCalls: 1, timeoutMs: 1000 });
  store.close();
  const source = `import { DurableToolStore } from ${JSON.stringify(moduleUrl)};
    const s = new DurableToolStore(process.argv[1], { clock: () => 100 });
    process.on('message', id => { process.send(s.reserve(${JSON.stringify(identity)}, id)); });
    process.send('ready');`;
  const workers = [child(t, source, f.path), child(t, source, f.path)];
  await Promise.all(workers.map(worker => worker.message()));
  const results = workers.map(worker => worker.message());
  workers.forEach((worker, i) => worker.proc.send(`call-${i}`));
  assert.equal((await Promise.all(results)).filter(result => result.allowed).length, 1);
  for (const worker of workers) { worker.proc.kill('SIGKILL'); await worker.exited; }
  assert.equal(f.open().begin(identity, { maxCalls: 1, timeoutMs: 1000 }).remainingCalls ?? 0, 0);
});

for (const committed of [false, true]) {
  test(`process death ${committed ? 'after' : 'before'} commit preserves reservation semantics`, { timeout: 15000 }, async t => {
    const f = fixture(t), store = f.open(true);
    store.begin(identity, policy);
    store.close();
    const source = committed
      ? `import { DurableToolStore } from ${JSON.stringify(moduleUrl)};
         const s = new DurableToolStore(process.argv[1], { clock: () => 100 });
         process.send(s.reserve(${JSON.stringify(identity)}, 'one'));`
      : `import { DatabaseSync } from 'node:sqlite';
         const db = new DatabaseSync(process.argv[1]);
         db.exec('BEGIN IMMEDIATE; UPDATE runs SET used=1;'); process.send('uncommitted');`;
    const worker = child(t, source + '\nsetInterval(() => {}, 1000);', f.path);
    const reported = await worker.message();
    if (committed) assert.equal(reported.allowed, true);
    else assert.equal(reported, 'uncommitted');
    worker.proc.kill('SIGKILL');
    await worker.exited;
    assert.equal(f.open().begin(identity, policy).used, committed ? 1 : 0);
  });
}
