/** One run's admission ledger. No tool arguments/results or credentials retained. */
export class ToolBudget {
  #calls = new Map();
  #reason = null;
  #rejected = 0;
  #deadline;
  #lastNow;
  #clock;
  #limit;
  #finished = false;
  #admitted = 0;
  #succeeded = 0;
  #failed = 0;

  constructor({ maxCalls, timeoutMs, clock = () => performance.now() }) {
    if (!Number.isSafeInteger(maxCalls) || maxCalls < 0 || maxCalls > 10000 ||
        !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 3600000) {
      throw new TypeError('Invalid tool budget');
    }
    this.#clock = clock;
    this.#lastNow = clock();
    if (!Number.isFinite(this.#lastNow)) throw new TypeError('Invalid budget clock');
    this.#deadline = this.#lastNow + timeoutMs;
    this.#limit = maxCalls;
  }

  expire() {
    if (this.#reason) return this.#reason;
    const now = this.#clock();
    if (!Number.isFinite(now) || now < this.#lastNow) this.#reason = 'clock_invalid';
    else if (now >= this.#deadline) this.#reason = 'time_budget_exhausted';
    this.#lastNow = now;
    return this.#reason;
  }

  remainingMs() {
    return this.expire() ? 0 : Math.max(0, Math.ceil(this.#deadline - this.#lastNow));
  }

  // Synchronous check-and-reserve: callers must invoke before executing a tool.
  // Failures and later policy vetoes do not refund a reservation.
  admit(callId) {
    this.expire();
    if (!this.#reason) {
      if (typeof callId !== 'string' || !callId.trim() || callId.length > 512) {
        this.#reason = 'missing_call_identity';
      } else if (this.#calls.has(callId)) this.#reason = 'duplicate_call_identity';
      else if (this.#calls.size >= this.#limit) this.#reason = 'call_budget_exhausted';
    }
    if (this.#reason) {
      this.#rejected++;
      return { allowed: false, reason: this.#reason };
    }
    this.#calls.set(callId, 'pending');
    this.#admitted++;
    return { allowed: true };
  }

  settle(callId, failed = false) {
    if (this.#calls.get(callId) !== 'pending') return false;
    this.#calls.set(callId, failed ? 'failed' : 'succeeded');
    if (failed) this.#failed++;
    else this.#succeeded++;
    if (this.#finished) this.#calls.delete(callId);
    return true;
  }

  finish() {
    this.expire();
    this.#reason ??= 'run_finished';
    this.#finished = true;
    for (const [id, state] of this.#calls) if (state !== 'pending') this.#calls.delete(id);
  }

  snapshot() {
    return Object.freeze({ admitted: this.#admitted, rejected: this.#rejected,
      pending: this.#admitted - this.#succeeded - this.#failed,
      succeeded: this.#succeeded, failed: this.#failed, stopReason: this.#reason });
  }
}
