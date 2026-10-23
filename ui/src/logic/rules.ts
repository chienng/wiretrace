import type {
  ApplyMode, ChangeEntry, FlowSummary, MapTarget, PauseAt, RewriteKind, RewriteOp, RewriteSide, Rule, RuleAction, RuleStats, TargetScheme,
} from '../types';

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
  { id: 'pause', label: 'Pause at a breakpoint' },
  { id: 'rewrite', label: 'Rewrite' },
  { id: 'map_remote', label: 'Map remote' },
];
/** Actions that change the request and let the walk go on; every other action answers (addons/qa_tools.py `CHANGE_ACTIONS`). */
export const CHANGE_ACTIONS: readonly RuleAction[] = ['rewrite', 'map_remote'];
export const RULE_ORDER_NOTE = 'Map remote and Rewrite rules apply in order. Then the first other rule that matches answers.';
export const REWRITE_NOTE =
  'When Wiretrace answers the request itself (mock, status, drop, mock file), the changes are not applied: nothing went to the server.';
export const JSON_PATH_NOTE =
  'JSON paths: data.items[0].price, ["key.with.dots"]. Values are JSON: true, 12, "text", null. A JSON body is written back compactly.';
export const PAUSE_AT: { id: PauseAt; label: string }[] = [
  { id: 'request', label: 'The request' },
  { id: 'response', label: 'The response' },
  { id: 'both', label: 'Both' },
];
export const PAUSE_NOTE =
  'The request waits in Traffic until you Continue or Abort it. Only while a Wiretrace window is open; at most 10 at once. Apps usually give up after 30–60 s.';
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

/** The action switched to `type`: a key of another action is dropped, as the server does; a pause, a rewrite
 *  or a Map remote has no delay. */
export function switchAction(action: Rule['action'], type: RuleAction, status: number): Rule['action'] {
  const { pause_at, ops, target, ...rest } = action;
  const next = { ...rest, type, status };
  if (type === 'pause') return { ...next, delay_ms: 0, pause_at: pause_at ?? 'request' };
  if (type === 'rewrite') return { ...next, delay_ms: 0, ops: ops?.length ? ops : [newOp()] };
  if (type === 'map_remote') return { ...next, delay_ms: 0, target: target ?? { scheme: 'https', host: '', port: 443 } };
  return next;
}

export const DEFAULT_PORTS: Record<TargetScheme, number> = { https: 443, http: 80 };
export const MAP_SCHEMES: { id: TargetScheme; label: string }[] = [
  { id: 'https', label: 'https' },
  { id: 'http', label: 'http' },
];
export const MAP_REMOTE_NOTE =
  'Not this Mac or addresses on your network: localhost, *.local, 10.x, 172.16–31.x, 192.168.x, 100.64–127.x. Path and query are kept.';
export const MAP_TOKENS_WARNING = "The app's tokens and cookies go to this server too.";
export const MAP_HTTP_WARNING = 'Plain HTTP: anyone on the network path can read it.';
const NOT_LOCAL = 'Not this Mac or addresses on your network.';
const DNS_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;

/** The target with the scheme switched; a port left at the old default follows to the new one. */
export function switchScheme(target: MapTarget, scheme: TargetScheme): MapTarget {
  return { ...target, scheme, port: target.port === DEFAULT_PORTS[target.scheme] ? DEFAULT_PORTS[scheme] : target.port };
}

/** The host as addons/qa_tools.py `parse_target` compares it: lowercase, no trailing dot, no IPv6 brackets. */
export function targetHost(host: string): string {
  const h = host.trim().toLowerCase().replace(/\.+$/, '');
  return h.startsWith('[') && h.endsWith(']') ? h.slice(1, -1) : h;
}

function ipv4Parts(host: string): number[] | null {
  const parts = host.split('.');
  if (parts.length !== 4 || !parts.every((p) => /^\d{1,3}$/.test(p))) return null;
  const n = parts.map(Number);
  return n.every((x) => x <= 255) ? n : null;
}

function blockedIpv4([a, b]: number[]): boolean {
  if (a === undefined || b === undefined) return true;
  return a === 0 || a === 10 || a === 127 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
    || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) || a >= 224;
}

/** The eight 16-bit groups of an IPv6 address (a trailing dotted IPv4 allowed), or null. */
function ipv6Groups(host: string): number[] | null {
  let h = host;
  const tail = /(\d+\.\d+\.\d+\.\d+)$/.exec(h);
  if (tail?.[1]) {
    const v4 = ipv4Parts(tail[1]);
    if (!v4) return null;
    h = h.slice(0, -tail[1].length) + `${((v4[0] ?? 0) << 8 | (v4[1] ?? 0)).toString(16)}:${((v4[2] ?? 0) << 8 | (v4[3] ?? 0)).toString(16)}`;
  }
  const halves = h.split('::');
  if (halves.length > 2) return null;
  const part = (s: string | undefined) => (s ? s.split(':') : []);
  const head = part(halves[0]);
  const rest = part(halves[1]);
  const fill = 8 - head.length - rest.length;
  if (halves.length === 1 ? fill !== 0 : fill < 1) return null;
  const groups = [...head, ...Array<string>(halves.length === 1 ? 0 : fill).fill('0'), ...rest];
  if (!groups.every((g) => /^[0-9a-f]{1,4}$/.test(g))) return null;
  return groups.map((g) => parseInt(g, 16));
}

/** IPv6 loopback, unspecified, link-local, unique-local and multicast, and IPv4-mapped forms of blocked IPv4. */
function blockedIpv6(host: string): boolean {
  const g = ipv6Groups(host);
  if (!g) return false;
  const [first = 0] = g;
  if (g.slice(0, 5).every((x) => x === 0) && g[5] === 0xffff) {
    return blockedIpv4([(g[6] ?? 0) >> 8, (g[6] ?? 0) & 0xff]);
  }
  if (g.slice(0, 7).every((x) => x === 0) && (g[7] === 0 || g[7] === 1)) return true;
  return (first & 0xffc0) === 0xfe80 || (first & 0xfe00) === 0xfc00 || (first & 0xff00) === 0xff00;
}

/** Problems of a Map remote target, by field, as addons/qa_tools.py `parse_target` checks them on save. */
export function validateTarget(target: MapTarget | undefined, matchHost: string): FieldErrors {
  if (!target) return { 'action.target.host': 'Enter the server to send requests to' };
  const e: FieldErrors = {};
  if (!MAP_SCHEMES.some((s) => s.id === target.scheme)) e['action.target.scheme'] = 'https or http';
  if (!isWhole(target.port) || target.port < 1 || target.port > 65535) e['action.target.port'] = '1 to 65535';
  const host = targetHost(target.host);
  const v4 = ipv4Parts(host);
  if (!host) {
    e['action.target.host'] = 'Enter the server to send requests to';
  } else if (v4) {
    if (blockedIpv4(v4)) e['action.target.host'] = NOT_LOCAL;
  } else if (host.includes(':') && ipv6Groups(host)) {
    if (blockedIpv6(host)) e['action.target.host'] = NOT_LOCAL;
  } else if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) {
    e['action.target.host'] = NOT_LOCAL;
  } else {
    const labels = host.split('.');
    if (host.length > 253 || labels.length < 2 || !labels.every((l) => DNS_LABEL.test(l)) || /^\d+$/.test(labels[labels.length - 1] ?? '')) {
      e['action.target.host'] = 'A DNS name or an IP address, e.g. staging-api.example.com';
    }
  }
  if (!e['action.target.host'] && matchHost && host === matchHost.toLowerCase() && target.port === DEFAULT_PORTS[target.scheme]) {
    e['action.target.host'] = 'Must differ from the host the rule matches';
  }
  return e;
}

/** `https://staging-api.example.com`, with the port only when it is not the scheme's default. */
export function targetUrl(target: MapTarget): string {
  const host = targetHost(target.host);
  const shown = host.includes(':') ? `[${host}]` : host;
  return `${target.scheme}://${shown}${target.port === DEFAULT_PORTS[target.scheme] ? '' : `:${target.port}`}`;
}

/** The editor's preview: the URL the app asks for and where it goes, path and query kept. */
export function mapPreview(rule: Rule, apiHosts: readonly string[]): { from: string; to: string; path: string } | null {
  const target = rule.action.target;
  if (!target || !targetHost(target.host)) return null;
  const host = rule.match.host || apiHosts[0] || 'api.example.com';
  const path = rule.match.path || '/';
  return { from: `https://${host}${path}`, to: targetUrl(target), path };
}

/** Limits of addons/rewrite.py `parse_ops`. */
export const REWRITE_LIMITS = { ops: 20, headerValue: 4096, pathParts: 20, pathChars: 256, jsonValueBytes: 64 << 10 } as const;
export const REWRITE_SIDES: { id: RewriteSide; label: string }[] = [
  { id: 'request', label: 'Request' },
  { id: 'response', label: 'Response' },
];
export const REWRITE_KINDS: { id: RewriteKind; label: string }[] = [
  { id: 'set_header', label: 'Set header' },
  { id: 'add_header', label: 'Add header' },
  { id: 'remove_header', label: 'Remove header' },
  { id: 'set_json', label: 'Set JSON field' },
  { id: 'remove_json', label: 'Remove JSON field' },
];
const REFUSED_HEADERS = new Set(['host', 'content-length', 'transfer-encoding', 'connection', 'keep-alive', 'te', 'trailer', 'upgrade']);
const TOKEN = /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}$/;

export const isHeaderOp = (kind: RewriteKind) => kind.endsWith('_header');
export const hasValue = (kind: RewriteKind) => kind.startsWith('set_') || kind === 'add_header';

export function newOp(): RewriteOp {
  return { on: 'request', op: 'set_header', name: '', value: '' };
}

/** The change with another kind and exactly that kind's keys (the server refuses others); the typed name or path and value carry over. */
export function opOfKind(op: RewriteOp, kind: RewriteKind): RewriteOp {
  const target = (isHeaderOp(op.op) ? op.name : op.path) ?? '';
  const next: RewriteOp = isHeaderOp(kind) ? { on: op.on, op: kind, name: target } : { on: op.on, op: kind, path: target };
  return hasValue(kind) ? { ...next, value: op.value ?? '' } : next;
}

const JSON_STRING = /"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
const PATH_KEY = /[^.[\]"]+/y;
const PATH_INDEX = /\[(0|[1-9][0-9]{0,8})\]/y;

/** `data.items[0]["a.b"]` as its parts, or null when it does not parse; addons/rewrite.py `parse_path`. */
export function parsePath(text: string): (string | number)[] | null {
  if (!text || text.length > REWRITE_LIMITS.pathChars) return null;
  const parts: (string | number)[] = [];
  let i = 0;
  const at = (re: RegExp) => {
    re.lastIndex = i;
    return re.exec(text);
  };
  while (i < text.length) {
    if (text.startsWith('["', i)) {
      i += 1;
      const quoted = at(JSON_STRING);
      if (!quoted || text[i + quoted[0].length] !== ']') return null;
      parts.push(JSON.parse(quoted[0]) as string);
      i += quoted[0].length + 1;
      continue;
    }
    const index = at(PATH_INDEX);
    if (index) {
      parts.push(Number(index[1]));
      i += index[0].length;
      continue;
    }
    if (parts.length) {
      if (text[i] !== '.') return null;
      i += 1;
    }
    const key = at(PATH_KEY);
    if (!key) return null;
    parts.push(key[0]);
    i += key[0].length;
  }
  return parts.length <= REWRITE_LIMITS.pathParts ? parts : null;
}

/** Problems of a Rewrite rule's changes, by field (`action.ops`, `action.ops.2.name`, …), as addons/rewrite.py checks them. */
export function validateOps(ops: readonly RewriteOp[] | undefined): FieldErrors {
  const e: FieldErrors = {};
  if (!ops || ops.length < 1 || ops.length > REWRITE_LIMITS.ops) {
    e['action.ops'] = `Add 1 to ${REWRITE_LIMITS.ops} changes`;
    return e;
  }
  ops.forEach((op, i) => {
    const f = (key: string) => `action.ops.${i}.${key}`;
    if (isHeaderOp(op.op)) {
      const name = op.name ?? '';
      if (!TOKEN.test(name)) e[f('name')] = "A header name: letters, digits and - _ . ! # $ % & ' * + ^ ` | ~";
      else if (REFUSED_HEADERS.has(name.toLowerCase()) || name.toLowerCase().startsWith('proxy-')) {
        e[f('name')] = 'Wiretrace or the connection sets this header; it cannot be changed';
      }
      const value = op.value ?? '';
      if (hasValue(op.op) && ([...value].length > REWRITE_LIMITS.headerValue || /[\r\n\0]/.test(value))) {
        e[f('value')] = `At most ${REWRITE_LIMITS.headerValue.toLocaleString('en-US')} characters, without a line break`;
      }
      return;
    }
    if (parsePath(op.path ?? '') === null) {
      e[f('path')] = `Keys joined by . with [n] for items; at most ${REWRITE_LIMITS.pathParts} parts and ${REWRITE_LIMITS.pathChars} characters`;
    }
    if (op.op === 'set_json') {
      const value = op.value ?? '';
      if (utf8Length(value) > REWRITE_LIMITS.jsonValueBytes) e[f('value')] = 'At most 64 KiB';
      else if (!isJson(value)) e[f('value')] = 'JSON: true, 12, "text", null or {"a": 1}';
    }
  });
  return e;
}

function isJson(text: string): boolean {
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

export interface ChangeGroup {
  rule: string;
  applied: number;
  entries: ChangeEntry[];
}

/** The Changes tab: the entries grouped by rule, in order. */
export function changeGroups(changes: readonly ChangeEntry[]): ChangeGroup[] {
  const groups: ChangeGroup[] = [];
  for (const c of changes) {
    let g = groups[groups.length - 1];
    if (!g || g.rule !== c.rule) groups.push((g = { rule: c.rule, applied: 0, entries: [] }));
    g.entries.push(c);
    if (c.applied) g.applied += 1;
  }
  return groups;
}

export function changeGroupTitle(g: ChangeGroup): string {
  return `Rewrite · rule ${g.rule || '(unnamed)'} · ${g.applied} of ${g.entries.length} applied`;
}

/** One change as a line: "Set header", the header or path, and the value (null when the change has none). */
export function changeParts(c: ChangeEntry): { label: string; target: string; value: string | null } {
  const label = REWRITE_KINDS.find((k) => k.id === c.op)?.label ?? c.op;
  return { label, target: c.target, value: c.value };
}

export const sideText = (on: string) => REWRITE_SIDES.find((s) => s.id === on)?.label ?? '';

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
  } else if (a.type === 'pause' && a.delay_ms !== 0) {
    e['action.delay_ms'] = 'A pause rule has no delay';
  } else if (a.type === 'rewrite' && a.delay_ms !== 0) {
    e['action.delay_ms'] = 'A Rewrite rule has no delay';
  } else if (a.type === 'map_remote' && a.delay_ms !== 0) {
    e['action.delay_ms'] = 'A Map remote rule has no delay';
  }
  if (a.type === 'pause' && !PAUSE_AT.some((p) => p.id === a.pause_at)) e['action.pause_at'] = 'The request, the response or both';
  if (a.type === 'rewrite') Object.assign(e, validateOps(a.ops));
  if (a.type === 'map_remote') Object.assign(e, validateTarget(a.target, m.host));
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
    case 'pause':
      return `${{ request: 'request', response: 'response', both: 'request and response' }[a.pause_at ?? 'request']} · ${applySummary(rule)}`;
    case 'rewrite': {
      const n = a.ops?.length ?? 0;
      return `Rewrite, ${n} ${n === 1 ? 'change' : 'changes'} · ${applySummary(rule)}`;
    }
    case 'map_remote':
      return `Map remote → ${a.target ? targetHost(a.target.host) || '?' : '?'} · ${applySummary(rule)}`;
  }
}

/** The list's label: a change rule lets the walk go on, an answer rule ends it. */
export function ruleKind(rule: Rule): 'Changes' | 'Answers' {
  return CHANGE_ACTIONS.includes(rule.action.type) ? 'Changes' : 'Answers';
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
