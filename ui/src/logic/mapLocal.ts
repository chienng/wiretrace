import type { Body, FlowSummary } from '../types';

/** Limits of addons/qa_tools.py `mock_name_problem` and addons/wiretrace_ui.py `map_local`. */
export const MAP_LOCAL_LIMITS = { part: 80, name: 120, bodyBytes: 1 << 20 } as const;
export const MAP_LOCAL_WARNING =
  'The file keeps the response as it is, tokens and personal data included. Edit them out before you share the mocks folder.';
export const NAME_PROBLEM = 'Parts of 1 to 80 letters, digits, . _ or - joined by /, none starting with a dot, ending with .json';
const PART = /^[A-Za-z0-9._-]{1,80}$/;
const MOCK_METHODS = new Set(['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']);
const BINARY_PREFIXES = ['image/', 'audio/', 'video/', 'font/'];
const BINARY_TYPES = new Set([
  'application/octet-stream',
  'application/zip',
  'application/gzip',
  'application/pdf',
  'application/x-protobuf',
  'application/protobuf',
  'application/grpc',
]);

/** `saved/GET_api_v1_profile.json`: the path without the query, `/` as `_`, other characters as `_`, cut to fit. */
export function defaultMockName(method: string, path: string): string {
  const bare = (path.split(/[?#]/)[0] ?? '').replace(/^\/+/, '') || 'index';
  const stem = `${method.toUpperCase()}_${bare}`.replace(/[^A-Za-z0-9._-]/g, '_');
  const room = Math.min(MAP_LOCAL_LIMITS.part, MAP_LOCAL_LIMITS.name - 'saved/'.length) - '.json'.length;
  return `saved/${stem.slice(0, room)}.json`;
}

export function mockNameProblem(name: string): string | null {
  if (!name.endsWith('.json')) return NAME_PROBLEM;
  return name.split('/').every((p) => PART.test(p) && !p.startsWith('.')) ? null : NAME_PROBLEM;
}

/** A name under `<METHOD>/…` also answers on its own, through the mock-file mapping. */
export function answersAlone(name: string): boolean {
  const first = name.split('/', 1)[0] ?? '';
  return name.includes('/') && MOCK_METHODS.has(first);
}

export function mapLocalNote(name: string, rule: boolean): string {
  if (answersAlone(name)) return `A file under ${name.split('/', 1)[0]}/ answers the matching request on its own, even without a rule.`;
  return rule ? 'A Mock rule answers with the file, from the next request on.' : 'Only the file is written: no request is answered with it until a rule uses it.';
}

function isBinaryMime(mime: string | null): boolean {
  return !!mime && (BINARY_PREFIXES.some((p) => mime.startsWith(p)) || BINARY_TYPES.has(mime));
}

/** Why Map local is off for a row, or null. The dialog checks the body itself once loaded. */
export function mapLocalOff(flow: Pick<FlowSummary, 'status' | 'error' | 'mime' | 'size' | 'websocket'>, viewing: string | null): string | null {
  if (viewing) return 'Map local is off while a previous session is open';
  if (flow.status === null) return flow.error === null ? 'This request is still in progress' : 'This request has no response';
  if (flow.websocket) return 'A WebSocket connection cannot be saved as a mock';
  if (isBinaryMime(flow.mime)) return 'The response is binary';
  if (flow.size !== null && flow.size > MAP_LOCAL_LIMITS.bodyBytes) return 'The response is over 1 MiB';
  return null;
}

export function bodyOff(body: Body): string | null {
  if (body.binary || body.text === null) return 'The response is binary';
  if (body.truncated || body.size > MAP_LOCAL_LIMITS.bodyBytes) return 'The response is over 1 MiB';
  return null;
}

/** The body to edit: pretty-printed when it is JSON, else as it came. */
export function editableBody(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

export function bodyProblem(text: string): string | null {
  return new TextEncoder().encode(text).length > MAP_LOCAL_LIMITS.bodyBytes ? 'At most 1 MiB' : null;
}

export function ruleName(method: string, path: string): string {
  return `Map local ${method.toUpperCase()} ${path.split('?', 1)[0] || '/'}`.slice(0, 80);
}
