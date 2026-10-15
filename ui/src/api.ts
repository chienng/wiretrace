import type { AppState, FlowDetail, FlowSummary, LogLine, LogSource, ReportResult, Rule, RulesPayload, RuleTestResult } from './types';

export class ForbiddenError extends Error {
  constructor() {
    super('forbidden');
  }
}

export class ApiError extends Error {
  status: number;
  /** The JSON error body, e.g. `{error, index, field}` from a rejected rules save. */
  data: unknown;
  constructor(status: number, message: string, data: unknown = null) {
    super(message);
    this.status = status;
    this.data = data;
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
    throw new ApiError(res.status, message, body);
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
  rules: () => request<RulesPayload>('/api/rules'),
  putRules: (revision: string, rules: Rule[]) =>
    request<RulesPayload>('/api/rules', { method: 'PUT', body: JSON.stringify({ revision, rules }) }),
  testRule: (rule: Rule, flowId: string) =>
    request<RuleTestResult>('/api/rules/test', { method: 'POST', body: JSON.stringify({ rule, flow_id: flowId }) }),
  rearm: (id: string) =>
    request<RulesPayload>(`/api/rules/${encodeURIComponent(id)}/rearm`, { method: 'POST', body: '{}' }),
  report: () => request<ReportResult>('/api/report', { method: 'POST', body: '{}' }),
  reveal: () => request<unknown>('/api/report/reveal', { method: 'POST', body: '{}' }),
};

export function socketUrl(): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}/api/updates`;
}
