import type {
  AppState,
  BreakpointEdits,
  DeviceInfo,
  FlowDetail,
  FlowSummary,
  LogLine,
  LogSource,
  MapLocalSave,
  PresetDetail,
  PresetFields,
  PresetInfo,
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
  TunnelRow,
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
  /** The form field a rejected preset save names (`field` in the 400 body); null when it names none. */
  get field(): string | null {
    const field = this.data && typeof this.data === 'object' ? (this.data as { field?: unknown }).field : null;
    return typeof field === 'string' ? field : null;
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
  presets: async () => (await request<{ presets: PresetInfo[] }>('/api/presets')).presets,
  /** `{switching}` once mitmdump is shutting down; null when that preset is already in use. */
  switchPreset: (name: string) =>
    request<{ switching: string } | null>('/api/preset', { method: 'POST', body: JSON.stringify({ name }) }),
  devices: async () => (await request<{ devices: DeviceInfo[] }>('/api/devices')).devices,
  /** `{switching, target}` once mitmdump is shutting down; null when that device is already in use.
   *  With `client`, the next session's Wi-Fi proxy accepts only that refused address (spec 021). */
  switchDevice: (target: string, client?: string) =>
    request<{ switching: string; target: string } | null>('/api/device', {
      method: 'POST',
      body: JSON.stringify(client === undefined ? { target } : { target, client }),
    }),
  /** Spec 022: let a refused device use the Wi-Fi proxy in this session, or refuse an accepted one again. */
  allowDevice: (client: string) =>
    request<{ accepted: string[] }>('/api/proxy/allow', { method: 'POST', body: JSON.stringify({ client }) }),
  removeDevice: (client: string) =>
    request<{ accepted: string[] }>('/api/proxy/remove', { method: 'POST', body: JSON.stringify({ client }) }),
  /** Spec 022, slice B: whether a valid port is free, then a restart on it. */
  portCheck: (port: string, signal?: AbortSignal) =>
    request<{ port: number; free: boolean }>(`/api/proxy/port-check?port=${encodeURIComponent(port)}`, {}, signal),
  changePort: (port: number) =>
    request<{ switching: string; target: string } | null>('/api/proxy/port', {
      method: 'POST',
      body: JSON.stringify({ port }),
    }),
  /** Spec 022, slice C: the live session's encrypted connections, and decrypting a host from now on. */
  tunnels: async () => (await request<{ tunnels: TunnelRow[] }>('/api/tunnels')).tunnels,
  decryptHost: (host: string) =>
    request<{ host: string; applied: boolean; message?: string }>('/api/api-hosts', {
      method: 'POST',
      body: JSON.stringify({ host }),
    }),
  presetDetail: (name: string) => request<PresetDetail>(`/api/presets/${encodeURIComponent(name)}`),
  createPreset: (name: string, fields: PresetFields) =>
    request<{ name: string; revision: string }>('/api/presets', { method: 'POST', body: JSON.stringify({ name, fields }) }),
  /** `{switching}` (202) when `restart` saved the preset in use and mitmdump is shutting down; else `{revision}`. */
  savePreset: (name: string, revision: string, fields: PresetFields, restart: boolean) =>
    request<{ revision?: string; switching?: string }>(`/api/presets/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(restart ? { revision, fields, restart: true } : { revision, fields }),
    }),
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
  /** Spec 022, slice D: let a paused flow go on with its edits (null: unchanged), or end it. */
  breakpoint: (id: string, action: 'continue' | 'abort', revision: number, edits: BreakpointEdits | null) =>
    request<{ id: string; action: string; edited: boolean }>(`/api/flows/${encodeURIComponent(id)}/breakpoint`, {
      method: 'POST',
      body: JSON.stringify({ action, edits, revision }),
    }),
  continueAll: () => request<{ continued: number }>('/api/breakpoints/continue-all', { method: 'POST', body: '{}' }),
  /** Spec 022, slice F: save a response as a mock file; with `rule`, add the Mock rule for it at the top. */
  mapLocal: (id: string, save: MapLocalSave) =>
    request<{ file: string; rule_id: string | null }>(`/api/flows/${encodeURIComponent(id)}/map-local`, {
      method: 'POST',
      body: JSON.stringify(save),
    }),
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
