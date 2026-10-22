import { randomUUID } from 'node:crypto';

export const CAPABILITY_METHOD = 'easel.toolBudget.capability';
export const VERIFIED_RUNTIME = '2026.10.2';

export function activePolicyMatches(api, policy) {
  let current;
  try { current = api.runtime.config.current(); } catch { return false; }
  const entry = current?.plugins?.entries?.['easel-tool-budget'];
  return api.runtime.version === VERIFIED_RUNTIME && entry?.enabled === true &&
    entry?.hooks?.allowConversationAccess === true &&
    entry?.config?.maxCalls === policy.maxCalls && entry?.config?.timeoutMs === policy.timeoutMs;
}

/** Read-only evidence from the process that registered the execution hooks.
 * This does not authorize a later request on a different connection/process.
 */
export function registerBudgetCapability(api, policy) {
  const instanceId = randomUUID();
  api.registerGatewayMethod(CAPABILITY_METHOD, ({ params, respond }) => {
    if (!params || Object.keys(params).length !== 1 ||
        typeof params.nonce !== 'string' || !/^[a-f0-9]{32,128}$/.test(params.nonce)) {
      respond(false, undefined, { code: 'INVALID_REQUEST', message: 'A fresh hexadecimal nonce is required' });
      return;
    }
    if (!activePolicyMatches(api, policy)) {
      respond(false, undefined, { code: 'INVALID_REQUEST', message: 'Active runtime policy is not verified' });
      return;
    }
    respond(true, { protocol: 1, nonce: params.nonce, instanceId, runtime: VERIFIED_RUNTIME,
      plugin: 'easel-tool-budget', maxCalls: policy.maxCalls, timeoutMs: policy.timeoutMs,
      scope: 'native_gateway_runs', durability: 'process_memory',
      evidence: 'active_hook_registration', requestAdmissionToken: false });
  }, { scope: 'operator.read', profileAccess: 'required' });
  return instanceId;
}
