import { callGatewayFromCli } from 'openclaw/plugin-sdk/gateway-runtime';
import { installBudgetHooks } from './hooks.mjs';
import { registerBudgetCapability } from './capability.mjs';
import { dispatchGatewayMethod } from 'openclaw/plugin-sdk/gateway-method-runtime';
import { registerBudgetSend } from './send.mjs';

export default {
  id: 'easel-tool-budget',
  name: 'Easel per-run tool budget',
  register(api) {
    const policy = installBudgetHooks(api, { stop: params => callGatewayFromCli('chat.abort',
      { timeout: '5000', json: true }, params, { progress: false }) });
    if (policy === null) return;
    const instanceId = registerBudgetCapability(api, policy);
    registerBudgetSend(api, policy, instanceId, dispatchGatewayMethod);
  },
};
