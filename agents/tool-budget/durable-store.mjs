import { createHash } from 'node:crypto';
import { closeSync, openSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

const APP_ID = 0x45425431;
const stopReasons = new Set(['run_finished', 'time_budget_exhausted', 'call_budget_exhausted',
  'clock_invalid', 'duplicate_call_identity', 'missing_call_identity', 'policy_mismatch']);
const deny = reason => ({ allowed: false, reason });
const validId = value => typeof value === 'string' && value.trim() && value.length <= 512;
const digest = value => createHash('sha256').update(value).digest('hex');
const runKey = identity => {
  const parts = [identity?.agentId, identity?.sessionKey, identity?.runId];
  return parts.every(validId) ? digest(JSON.stringify(parts)) : null;
};
const validPolicy = policy => Number.isSafeInteger(policy?.maxCalls) && policy.maxCalls >= 0 &&
  policy.maxCalls <= 10000 && Number.isSafeInteger(policy?.timeoutMs) &&
  policy.timeoutMs >= 1 && policy.timeoutMs <= 3600000;
const validTime = now => Number.isSafeInteger(now) && now >= 0 && now <= Number.MAX_SAFE_INTEGER - 3600000;

/** Durable reservations, not proof of tool completion or an exactly-once executor. */
export class DurableToolStore {
  #db;
  #clock;
  #failed = false;

  constructor(path, { create = false, clock = Date.now } = {}) {
    if (typeof path !== 'string' || !isAbsolute(path)) throw new TypeError('Absolute budget database path required');
    this.#clock = clock;
    try {
      // Creation is an explicit, exclusive setup action. Runtime reopen never creates a missing ledger.
      closeSync(openSync(path, create ? 'wx' : 'r+', 0o600));
      this.#db = new DatabaseSync(path);
      this.#db.exec('PRAGMA busy_timeout=0; PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL;');
      if (create) {
        this.#db.exec(`BEGIN IMMEDIATE;
          CREATE TABLE runs (
            id TEXT PRIMARY KEY, max_calls INTEGER NOT NULL CHECK(max_calls BETWEEN 0 AND 10000),
            timeout_ms INTEGER NOT NULL CHECK(timeout_ms BETWEEN 1 AND 3600000),
            deadline_ms INTEGER NOT NULL, last_ms INTEGER NOT NULL,
            used INTEGER NOT NULL DEFAULT 0 CHECK(used BETWEEN 0 AND max_calls),
            reason TEXT
          ) STRICT;
          CREATE TABLE calls (
            run_id TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL,
            PRIMARY KEY(run_id, id)
          ) STRICT;
          PRAGMA application_id=${APP_ID}; PRAGMA user_version=1; COMMIT;`);
      }
      if (this.#db.prepare('PRAGMA application_id').get().application_id !== APP_ID ||
          this.#db.prepare('PRAGMA user_version').get().user_version !== 1) throw new Error();
    } catch {
      try { this.#db?.close(); } catch { /* Preserve the original database for inspection. */ }
      throw new Error('Cannot open a supported durable tool budget database');
    }
  }

  #transaction(operation) {
    if (this.#failed) return deny('storage_unavailable');
    try {
      this.#db.exec('BEGIN IMMEDIATE');
      const result = operation();
      this.#db.exec('COMMIT');
      return result; // No admission escapes before the reservation commits.
    } catch {
      try { this.#db.exec('ROLLBACK'); } catch { /* Includes failed BEGIN and closed handles. */ }
      this.#failed = true;
      return deny('storage_unavailable');
    }
  }

  #stop(id, reason) {
    this.#db.prepare('UPDATE runs SET reason=COALESCE(reason, ?) WHERE id=?').run(reason, id);
    return deny(reason);
  }

  #check(row, now) {
    if (row.reason) return deny(row.reason);
    if (!validTime(now) || now < row.last_ms) return this.#stop(row.id, 'clock_invalid');
    if (now >= row.deadline_ms) return this.#stop(row.id, 'time_budget_exhausted');
    this.#db.prepare('UPDATE runs SET last_ms=? WHERE id=?').run(now, row.id);
    return { allowed: true, used: row.used, remainingCalls: row.max_calls - row.used,
      remainingMs: row.deadline_ms - now };
  }

  begin(identity, policy) {
    const id = runKey(identity);
    if (!id) return deny('missing_run_identity');
    if (!validPolicy(policy)) return deny('invalid_policy');
    return this.#transaction(() => {
      const now = this.#clock();
      let row = this.#db.prepare('SELECT * FROM runs WHERE id=?').get(id);
      if (!row) {
        if (!validTime(now)) return deny('clock_invalid');
        if (this.#db.prepare('SELECT count(*) AS n FROM runs').get().n >= 10000) {
          return deny('tracking_capacity_exhausted');
        }
        this.#db.prepare('INSERT INTO runs(id,max_calls,timeout_ms,deadline_ms,last_ms) VALUES(?,?,?,?,?)')
          .run(id, policy.maxCalls, policy.timeoutMs, now + policy.timeoutMs, now);
        row = this.#db.prepare('SELECT * FROM runs WHERE id=?').get(id);
      }
      if (row.max_calls !== policy.maxCalls || row.timeout_ms !== policy.timeoutMs) {
        return this.#stop(id, 'policy_mismatch');
      }
      return this.#check(row, now);
    });
  }

  reserve(identity, callId) {
    const id = runKey(identity);
    if (!id) return deny('missing_run_identity');
    return this.#transaction(() => {
      const row = this.#db.prepare('SELECT * FROM runs WHERE id=?').get(id);
      if (!row) return deny('run_not_admitted');
      const checked = this.#check(row, this.#clock());
      if (!checked.allowed) return checked;
      if (!validId(callId)) return this.#stop(id, 'missing_call_identity');
      const call = digest(callId);
      if (this.#db.prepare('SELECT 1 FROM calls WHERE run_id=? AND id=?').get(id, call)) {
        return this.#stop(id, 'duplicate_call_identity');
      }
      if (row.used >= row.max_calls) return this.#stop(id, 'call_budget_exhausted');
      this.#db.prepare('INSERT INTO calls(run_id,id) VALUES(?,?)').run(id, call);
      this.#db.prepare('UPDATE runs SET used=used+1 WHERE id=?').run(id);
      return { allowed: true };
    });
  }

  finish(identity, reason = 'run_finished') {
    const id = runKey(identity);
    if (!id) return deny('missing_run_identity');
    if (!stopReasons.has(reason)) return deny('invalid_stop_reason');
    return this.#transaction(() => {
      const row = this.#db.prepare('SELECT * FROM runs WHERE id=?').get(id);
      if (!row) return deny('run_not_admitted');
      return this.#stop(id, row.reason ?? reason);
    });
  }

  close() {
    this.#failed = true;
    this.#db.close();
  }
}
