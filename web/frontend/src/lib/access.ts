import { request } from './api';

export interface Access {
  scope: string; approval: string; runtime: string; localFull: boolean;
  targets: Record<string, string>;
  scopes: [string, string, string][]; approvals: [string, string, string][];
}
export function getAccess(target = '', session = '') {
  const query = new URLSearchParams();
  if (target) query.set('target', target);
  if (session) query.set('session', session);
  return request<Access>('/api/settings/access?' + query.toString());
}
export const saveAccess = (scope: string, approval: string, previous: Access) => request<Access>('/api/settings/access', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ target: previous.runtime, scope, approval, previousScope: previous.scope, previousApproval: previous.approval }),
});
