import type { AppState, FlowDetail, FlowSummary, Faults, LogLine, LogSource, ReportResult } from './types';

export class ForbiddenError extends Error {
  constructor() {
    super('forbidden');
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let forbiddenListener: (() => void) | null = null;

/** Called once for any HTTP 403, from any request. */
export function setForbiddenListener(fn: (() => void) | null): void {
  forbiddenListener = fn;
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const mutating = init.method === 'PUT' || init.method === 'POST';
  const headers: Record<string, string> = {};
  if (mutating) {
    headers['X-Wiretrace'] = '1';
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, { ...init, headers, credentials: 'same-origin', signal: signal ?? null });
  if (res.status === 403) {
    forbiddenListener?.();
    throw new ForbiddenError();
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const message =
      body && typeof body === 'object' && 'error' in body
        ? String((body as { error: unknown }).error)
        : `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return body as T;
}

export const api = {
  state: () => request<AppState>('/api/state'),
  flows: async () => (await request<{ flows: FlowSummary[] }>('/api/flows')).flows,
  flow: (id: string, signal?: AbortSignal) =>
    request<FlowDetail>(`/api/flows/${encodeURIComponent(id)}`, {}, signal),
  filter: async (expr: string, signal?: AbortSignal) =>
    (await request<{ ids: string[] }>(`/api/filter?expr=${encodeURIComponent(expr)}`, {}, signal)).ids,
  logs: async (source: LogSource) =>
    (await request<{ lines: LogLine[] }>(`/api/logs?source=${source}`)).lines,
  mocks: async () => (await request<{ files: string[] }>('/api/mocks')).files,
  putFaults: (faults: Faults) =>
    request<Faults>('/api/faults', { method: 'PUT', body: JSON.stringify(faults) }),
  report: () => request<ReportResult>('/api/report', { method: 'POST', body: '{}' }),
  reveal: () => request<unknown>('/api/report/reveal', { method: 'POST', body: '{}' }),
};

export function socketUrl(): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}/api/updates`;
}
