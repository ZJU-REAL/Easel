import { activePolicyMatches } from './capability.mjs';

export const BUDGET_SEND_METHOD = 'easel.toolBudget.send';

/** Dispatch in the authenticated RPC scope; never reconnect via CLI/HTTP. */
export function registerBudgetSend(api, policy, instanceId, dispatch) {
  api.registerGatewayMethod(BUDGET_SEND_METHOD, async ({ params, respond }) => {
    const fail = message => respond(false, undefined, { code: 'INVALID_REQUEST', message });
    const fields = ['instanceId', 'maxCalls', 'timeoutMs', 'sessionKey', 'message', 'idempotencyKey'];
    if (!params || Object.keys(params).length !== fields.length ||
        !Object.keys(params).every(key => fields.includes(key)) ||
        typeof params.message !== 'string' || !params.message.trim() || params.message.length > 100000 ||
        typeof params.sessionKey !== 'string' || params.sessionKey.length > 512 ||
        !/^agent:[a-z0-9_-]+:[a-zA-Z0-9:_-]+$/.test(params.sessionKey) ||
        typeof params.idempotencyKey !== 'string' || !/^[a-zA-Z0-9_-]{1,160}$/.test(params.idempotencyKey)) {
      fail('Invalid budgeted chat request'); return;
    }
    if (params.instanceId !== instanceId || params.maxCalls !== policy.maxCalls ||
        params.timeoutMs !== policy.timeoutMs || !activePolicyMatches(api, policy)) {
      fail('Gateway registration or budget policy changed; refresh capability before submitting'); return;
    }
    try {
      // SDK dispatch retains caller authority, profile and request lifetime.
      // No synthetic operator identity and no fallback to another Gateway.
      const result = await dispatch('chat.send', {
        sessionKey: params.sessionKey, message: params.message, idempotencyKey: params.idempotencyKey,
      }, { timeoutMs: 10000 });
      respond(result.ok, result.payload, result.error);
    } catch {
      // Do not retry: a disconnect may occur after chat.send was admitted.
      fail('Budgeted dispatch could not be confirmed; inspect the original task before retrying');
    }
  }, { scope: 'operator.write', profileAccess: 'required' });
}
