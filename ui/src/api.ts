import type {
  AppState,
  FlowDetail,
  FlowSummary,
  LogLine,
  LogSource,
  ReportBox,
  ReportDraft,
  ReportFileKind,
  ReportFormat,
  ReportResult,
  Rule,
  RulesPayload,
  RuleTestResult,
  Screenshot,
  SessionInfo,
  ViewResult,
} from './types';

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
  const mutating = init.method === 'PUT' || init.method === 'POST' || init.method === 'DELETE';
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

/** `path` with the query, and `session` when a previous session is open. */
export function withSession(path: string, query: Record<string, string>, session?: string | null): string {
  const params = new URLSearchParams(query);
  if (session) params.set('session', session);
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

/** What the bug report form asks for: the request (null for the whole session) and the boxes ticked. */
export interface ReportQuery {
  flow: string | null;
  session: string | null;
  include: readonly ReportBox[];
}

function reportQuery(q: ReportQuery): Record<string, string> {
  const query: Record<string, string> = { include: q.include.join(',') };
  if (q.flow) query.flow = q.flow;
  return query;
}

/** Downloads are plain links: the browser saves them with the name the server gives. */
export function reportFileUrl(kind: ReportFileKind, q: ReportQuery): string {
  return withSession(`/api/report/file/${kind}`, reportQuery(q), q.session);
}

export function screenshotUrl(name: string, session: string | null, download = false): string {
  return withSession(`/api/report/screenshot/${encodeURIComponent(name)}`, download ? { download: '1' } : {}, session);
}

export const api = {
  state: () => request<AppState>('/api/state'),
  flows: async (session?: string | null) => (await request<{ flows: FlowSummary[] }>(withSession('/api/flows', {}, session))).flows,
  flow: (id: string, signal?: AbortSignal, session?: string | null) =>
    request<FlowDetail>(withSession(`/api/flows/${encodeURIComponent(id)}`, {}, session), {}, signal),
  filter: async (expr: string, signal?: AbortSignal, session?: string | null) =>
    (await request<{ ids: string[] }>(withSession('/api/filter', { expr }, session), {}, signal)).ids,
  search: async (q: string, signal?: AbortSignal, session?: string | null) =>
    (await request<{ ids: string[] }>(withSession('/api/search', { q }, session), {}, signal)).ids,
  logs: async (source: LogSource, session?: string | null) =>
    (await request<{ lines: LogLine[] }>(withSession('/api/logs', { source }, session))).lines,
  mocks: async () => (await request<{ files: string[] }>('/api/mocks')).files,
  rules: () => request<RulesPayload>('/api/rules'),
  putRules: (revision: string, rules: Rule[]) =>
    request<RulesPayload>('/api/rules', { method: 'PUT', body: JSON.stringify({ revision, rules }) }),
  testRule: (rule: Rule, flowId: string) =>
    request<RuleTestResult>('/api/rules/test', { method: 'POST', body: JSON.stringify({ rule, flow_id: flowId }) }),
  rearm: (id: string) =>
    request<RulesPayload>(`/api/rules/${encodeURIComponent(id)}/rearm`, { method: 'POST', body: '{}' }),
  sessions: async () => (await request<{ sessions: SessionInfo[] }>('/api/sessions')).sessions,
  view: (session: string | null) => request<ViewResult>('/api/view', { method: 'POST', body: JSON.stringify({ session }) }),
  replay: (id: string) => request<{ id: string }>(`/api/flows/${encodeURIComponent(id)}/replay`, { method: 'POST', body: '{}' }),
  report: (session?: string | null) =>
    request<ReportResult>('/api/report', { method: 'POST', body: JSON.stringify(session ? { session } : {}) }),
  reveal: () => request<unknown>('/api/report/reveal', { method: 'POST', body: '{}' }),
  reportDraft: (q: ReportQuery, format: ReportFormat, signal?: AbortSignal) =>
    request<ReportDraft>(withSession('/api/report/draft', { ...reportQuery(q), format }, q.session), {}, signal),
  takeScreenshot: () =>
    request<{ name: string; screenshots: Screenshot[] }>('/api/report/screenshot', { method: 'POST', body: '{}' }),
  removeScreenshot: (name: string) =>
    request<{ screenshots: Screenshot[] }>(`/api/report/screenshot/${encodeURIComponent(name)}`, { method: 'DELETE' }),
};

export function socketUrl(): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}/api/updates`;
}
