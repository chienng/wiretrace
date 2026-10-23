import type { FlowSummary } from '../types';

/** Methods that repeat no side effect on the backend: replayed without asking (spec 008 decision 5). */
export const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** Why a request cannot be replayed, or null. */
export function replayOff(flow: Pick<FlowSummary, 'status' | 'error' | 'websocket'>, viewing: string | null): string | null {
  if (viewing) return 'Replay is off while a previous session is open';
  if (flow.websocket) return 'WebSocket connections cannot be replayed';
  if (flow.status === null && flow.error === null) return 'This request is still in progress';
  return null;
}

export function newRuleOff(viewing: string | null): string | null {
  return viewing ? 'Rules are off while a previous session is open' : null;
}

export function copyMockOff(flow: Pick<FlowSummary, 'status'>): string | null {
  return flow.status === null ? 'This request has no response' : null;
}
