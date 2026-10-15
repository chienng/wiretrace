import type { ApplyMode, FlowSummary, Rule, RuleAction, RuleStats } from '../types';

/** Limits of addons/qa_tools.py `parse_rules`; the server checks them again on save. */
export const LIMITS = {
  rules: 200,
  name: 80,
  path: 512,
  bodyContains: 256,
  bodyBytes: 1 << 20,
  delayMs: 120_000,
  minNth: 2,
  maxNth: 1_000,
} as const;

export const METHODS = ['ANY', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'] as const;
export const ACTIONS: { id: RuleAction; label: string }[] = [
  { id: 'mock', label: 'Mock response' },
  { id: 'status', label: 'Status code' },
  { id: 'delay', label: 'Delay' },
  { id: 'drop', label: 'Drop connection' },
];
export const APPLY_MODES: { id: ApplyMode; label: string }[] = [
  { id: 'always', label: 'Always' },
  { id: 'once', label: 'Once' },
  { id: 'every_nth', label: 'Every Nth' },
];
export const DEFAULT_ERROR_BODY = '{"error": "injected by Wiretrace"}';
export const STATUS_TEXT: Record<number, string> = {
  200: 'OK',
  201: 'Created',
  204: 'No Content',
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  409: 'Conflict',
  422: 'Unprocessable Entity',
  429: 'Too Many Requests',
  500: 'Internal Server Error',
  502: 'Bad Gateway',
  503: 'Service Unavailable',
  504: 'Gateway Timeout',
};

export type TypeFilter = 'all' | RuleAction;
export type FieldErrors = Partial<Record<string, string>>;

const ID_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';
const ID_RE = /^[a-z0-9]{6,32}$/;

export function newRuleId(random: () => number = Math.random): string {
  let id = '';
  for (let i = 0; i < 10; i++) id += ID_CHARS[Math.floor(random() * ID_CHARS.length)];
  return id;
}

/** The preset API host that `host` belongs to (itself or a subdomain), or ''. */
export function apiHostFor(host: string, apiHosts: readonly string[]): string {
  const h = host.toLowerCase();
  return apiHosts.find((a) => h === a || h.endsWith(`.${a}`)) ?? '';
}

export function emptyRule(id: string): Rule {
  return {
    id,
    name: '',
    enabled: true,
    match: { method: 'ANY', host: '', path: '/', body_contains: '' },
    action: { type: 'status', status: 500, body: '', mock_file: '', delay_ms: 0 },
    apply: { mode: 'always', n: 0 },
  };
}

/** A new rule matching a captured request's method, host and path (query left out). */
export function ruleFromFlow(flow: Pick<FlowSummary, 'method' | 'host' | 'path'>, apiHosts: readonly string[], id: string): Rule {
  const method = flow.method.toUpperCase();
  const path = flow.path.split('?', 1)[0] || '/';
  const rule = emptyRule(id);
  return {
    ...rule,
    name: `${method} ${path}`.slice(0, LIMITS.name),
    match: { ...rule.match, method: (METHODS as readonly string[]).includes(method) ? method : 'ANY', host: apiHostFor(flow.host, apiHosts), path: path.slice(0, LIMITS.path) },
  };
}

function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length;
}

const isWhole = (n: number) => Number.isInteger(n);

/** The same checks as the server, by field (`name`, `match.path`, `action.status`, …). Empty when valid. */
export function validateRule(rule: Rule, apiHosts: readonly string[], mockFiles: readonly string[] | null, others: readonly Rule[] = []): FieldErrors {
  const e: FieldErrors = {};
  if (!ID_RE.test(rule.id)) e.id = 'Must be 6 to 32 lowercase letters or digits';
  else if (others.some((o) => o.id === rule.id)) e.id = 'Used by another rule';
  const name = rule.name.trim();
  if (!name) e.name = 'Give the rule a name';
  else if (rule.name.length > LIMITS.name) e.name = `At most ${LIMITS.name} characters`;
  else if (/[\u0000-\u001f]/.test(rule.name)) e.name = 'No control characters';

  const m = rule.match;
  if (m.method !== 'ANY' && !/^[A-Z]{1,16}$/.test(m.method)) e['match.method'] = 'ANY or an HTTP method';
  if (m.host && !apiHosts.includes(m.host.toLowerCase())) e['match.host'] = "Not one of the preset's API hosts";
  if (!m.path) e['match.path'] = 'Enter a path, e.g. /api/v1/orders or /api/*';
  else if (m.path.length > LIMITS.path) e['match.path'] = `At most ${LIMITS.path} characters`;
  else if (!m.path.startsWith('/') && !m.path.startsWith('*')) e['match.path'] = 'Must start with / or *';
  if (m.body_contains.length > LIMITS.bodyContains) e['match.body_contains'] = `At most ${LIMITS.bodyContains} characters`;

  const a = rule.action;
  if ((a.type === 'mock' || a.type === 'status') && (!isWhole(a.status) || a.status < 100 || a.status > 599)) {
    e['action.status'] = '100 to 599';
  }
  if (utf8Length(a.body) > LIMITS.bodyBytes) e['action.body'] = 'At most 1 MiB';
  if (a.type === 'mock' && a.mock_file && mockFiles !== null && !mockFiles.includes(a.mock_file)) {
    e['action.mock_file'] = 'Not a mock file of this preset';
  }
  if (!isWhole(a.delay_ms) || a.delay_ms < 0 || a.delay_ms > LIMITS.delayMs) {
    e['action.delay_ms'] = `0 to ${LIMITS.delayMs.toLocaleString('en-US')} ms`;
  } else if (a.type === 'delay' && a.delay_ms === 0) {
    e['action.delay_ms'] = 'More than 0 ms for a delay rule';
  }
  if (rule.apply.mode === 'every_nth' && (!isWhole(rule.apply.n) || rule.apply.n < LIMITS.minNth || rule.apply.n > LIMITS.maxNth)) {
    e['apply.n'] = `${LIMITS.minNth} to ${LIMITS.maxNth.toLocaleString('en-US')}`;
  }
  return e;
}

export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;
}

export function applySummary(rule: Rule): string {
  if (rule.apply.mode === 'once') return 'once';
  if (rule.apply.mode === 'every_nth') return `every ${ordinal(rule.apply.n)} call`;
  return 'always';
}

const ms = (n: number) => `${n.toLocaleString('en-US')} ms`;

/** One line for the list, e.g. "Return 500 · once". */
export function ruleSummary(rule: Rule): string {
  const a = rule.action;
  const after = a.delay_ms && a.type !== 'delay' ? ` after ${ms(a.delay_ms)}` : '';
  switch (a.type) {
    case 'mock':
      return `${a.mock_file ? a.mock_file.split('/').pop() : `Mock ${a.status}`}${after} · ${applySummary(rule)}`;
    case 'status':
      return `Return ${a.status}${after} · ${applySummary(rule)}`;
    case 'delay':
      return `${ms(a.delay_ms)} then forward · ${applySummary(rule)}`;
    case 'drop':
      return `Close connection (simulate network loss)${after} · ${applySummary(rule)}`;
  }
}

export function filterRules(rules: readonly Rule[], text: string, type: TypeFilter): Rule[] {
  const q = text.trim().toLowerCase();
  return rules.filter((r) => {
    if (type !== 'all' && r.action.type !== type) return false;
    if (!q) return true;
    return [r.name, r.match.method, r.match.host, r.match.path].some((s) => s.toLowerCase().includes(q));
  });
}

export const EMPTY_STATS: RuleStats = { matches: 0, applied: 0, last_ts: null };

/** HH:MM:SS of a Unix time, local. */
export function clockTime(ts: number | null): string {
  if (ts === null) return '—';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function exportJson(rules: readonly Rule[]): string {
  return `${JSON.stringify({ version: 1, rules }, null, 2)}\n`;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** The rules of an exported file; the shape of each rule is checked by the server on save. */
export function parseImport(text: string): Rule[] | { error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: 'The file is not JSON.' };
  }
  if (!isObject(data) || data.version !== 1 || !Array.isArray(data.rules)) {
    return { error: 'Not a Wiretrace rules file ({"version": 1, "rules": [...]}).' };
  }
  if (!data.rules.every((r) => isObject(r) && isObject(r.match) && isObject(r.action) && isObject(r.apply))) {
    return { error: 'A rule in the file is not complete.' };
  }
  return data.rules as Rule[];
}

/** Add: imported rules go after the current ones, with new ids where they collide. Replace: only the imported ones. */
export function mergeImport(current: readonly Rule[], incoming: readonly Rule[], mode: 'add' | 'replace', makeId: () => string = newRuleId): Rule[] {
  if (mode === 'replace') return incoming.slice();
  const used = new Set(current.map((r) => r.id));
  const added = incoming.map((r) => {
    let id = r.id;
    while (used.has(id) || !ID_RE.test(id)) id = makeId();
    used.add(id);
    return id === r.id ? r : { ...r, id };
  });
  return [...current, ...added];
}

/** The server's 400 `{error, index, field}` as a field error of the rule at `index`, or a general message. */
export function serverError(data: unknown, index: number): { field: string | null; message: string } | null {
  if (!isObject(data) || typeof data.error !== 'string') return null;
  const field = typeof data.field === 'string' && data.field ? data.field : null;
  if (typeof data.index === 'number' && data.index !== index) {
    return { field: null, message: `Rule ${data.index + 1}: ${field ?? ''} ${data.error}`.replace(/\s+/g, ' ') };
  }
  return { field, message: data.error };
}

export function replaceAt(rules: readonly Rule[], index: number, rule: Rule): Rule[] {
  const next = rules.slice();
  if (index < 0 || index >= next.length) next.push(rule);
  else next[index] = rule;
  return next;
}

export function sameRule(a: Rule, b: Rule): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
