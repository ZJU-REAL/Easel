import { request } from './api';

export interface LocalRemotion {
  path: string; version: string | null; ready: boolean; detail: string; missing: string[];
}
export interface RenderProbe { time: number; size: string }
export interface RemotionState { projects: LocalRemotion[]; selected: LocalRemotion | null; probe: RenderProbe | null }
export const getRemotion = () => request<RemotionState>('/api/env/remotion');
export const selectRemotion = (path: string) => request<RemotionState>('/api/env/remotion', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }),
});
export const probeRemotion = () => request<RenderProbe>('/api/env/remotion/probe', { method: 'POST' });
