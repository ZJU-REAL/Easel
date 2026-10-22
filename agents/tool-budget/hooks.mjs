import { ToolBudget } from './budget.mjs';

const identity = ctx => [ctx?.agentId, ctx?.sessionKey, ctx?.runId].every(
  value => typeof value === 'string' && value.trim() && value.length <= 512);
const key = ctx => JSON.stringify([ctx.agentId, ctx.sessionKey, ctx.runId]);
const denied = reason => ({ block: true, blockReason: `Easel tool budget: ${reason}` });

/** Dependency-injected transport keeps admission synchronous; stop never widens its target. */
export function installBudgetHooks(api, { stop, clock, schedule = setTimeout, cancel = clearTimeout }) {
  if (api.pluginConfig == null || (typeof api.pluginConfig === 'object' &&
      !Array.isArray(api.pluginConfig) && Object.keys(api.pluginConfig).length === 0)) return null;
  const config = Object.freeze({ maxCalls: api.pluginConfig.maxCalls, timeoutMs: api.pluginConfig.timeoutMs });
  // Validate configuration before registering any partial protection.
  new ToolBudget({ maxCalls: config.maxCalls, timeoutMs: config.timeoutMs, clock });
  const runs = new Map();
  const maxTrackedRuns = 10000;
  const emit = (state, event) => api.logger.info(JSON.stringify({
    event, ...state.budget.snapshot(), stopStatus: state.stopStatus,
  }));
  const halt = state => {
    if (state.stopStatus !== 'not_requested') return;
    state.stopStatus = 'pending';
    // Do not await a stop from inside the hook: the host may await this hook
    // during cancellation. Capacity stays closed regardless of RPC outcome.
    Promise.resolve().then(() => stop({ ...state.target, preserveSideRuns: true })).then(
      result => {
        state.stopStatus = result?.aborted === true && Array.isArray(result.runIds) && result.runIds.includes(state.target.runId)
          ? 'confirmed' : 'unconfirmed';
        emit(state, 'easel_budget_stop');
      }, () => { state.stopStatus = 'unconfirmed'; emit(state, 'easel_budget_stop'); });
  };
  api.on('before_agent_run', (_event, ctx) => {
    const block = reason => ({ outcome: 'block', reason, message: `Easel tool budget: ${reason}` });
    if (!identity(ctx)) return block('missing_run_identity');
    const existing = runs.get(key(ctx));
    if (existing) {
      const reason = existing.budget.expire();
      if (reason && !existing.finished) halt(existing);
      return reason ? block(reason) : { outcome: 'pass' };
    }
    // Never evict a run and silently reset its budget. A full registry requires
    // a clean gateway restart, after current runs have finished.
    if (runs.size >= maxTrackedRuns) return block('tracking_capacity_exhausted');
    const state = { budget: new ToolBudget({ maxCalls: config.maxCalls, timeoutMs: config.timeoutMs, clock }),
      target: { runId: ctx.runId, sessionKey: ctx.sessionKey, agentId: ctx.agentId },
      stopStatus: 'not_requested', timer: null, finished: false };
    const arm = () => {
      state.timer = schedule(() => {
        if (state.finished) return;
        if (state.budget.expire()) halt(state);
        else arm(); // Timers may fire early; never silently lose the deadline.
      }, state.budget.remainingMs());
      state.timer?.unref?.();
    };
    arm();
    runs.set(key(ctx), state);
    return { outcome: 'pass' };
  });
  api.on('before_tool_call', (event, ctx) => {
    if (!identity(ctx) || (event.runId && event.runId !== ctx.runId) ||
        (event.toolCallId && ctx.toolCallId && event.toolCallId !== ctx.toolCallId)) {
      return denied('mismatched_run_identity');
    }
    const state = runs.get(key(ctx));
    if (!state) return denied('run_not_admitted');
    const decision = state.budget.admit(event.toolCallId ?? ctx.toolCallId);
    if (!decision.allowed) {
      if (decision.reason !== 'run_finished') halt(state);
      return denied(decision.reason);
    }
  }, { priority: 1000 });
  api.on('after_tool_call', (event, ctx) => {
    if (!identity(ctx) || (event.runId && event.runId !== ctx.runId) ||
        (event.toolCallId && ctx.toolCallId && event.toolCallId !== ctx.toolCallId)) return;
    runs.get(key(ctx))?.budget.settle(event.toolCallId ?? ctx.toolCallId, Boolean(event.error));
  });
  api.on('agent_end', (event, ctx) => {
    const target = { ...ctx, runId: ctx?.runId ?? event.runId };
    if (!identity(target) || (event.runId && event.runId !== target.runId)) return;
    const state = runs.get(key(target));
    if (!state) return;
    state.finished = true;
    cancel(state.timer);
    state.budget.finish();
    emit(state, 'easel_budget_end');
  });
  return config;
}
