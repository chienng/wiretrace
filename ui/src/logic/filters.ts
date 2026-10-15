import type { FlowSummary } from '../types';

export type QuickFilter = 'all' | 'errors' | 'slow' | 'mocked' | 'faulted' | 'websocket';

export const SLOW_MS = 1000;

export const QUICK_FILTERS: { id: QuickFilter; label: string }[] = [
  { id: 'all', label: 'All requests' },
  { id: 'errors', label: 'Errors 4xx / 5xx' },
  { id: 'slow', label: 'Slow > 1 s' },
  { id: 'mocked', label: 'Mocked' },
  { id: 'faulted', label: 'Faulted' },
  { id: 'websocket', label: 'WebSocket' },
];

/** 4xx/5xx, or a flow that failed without a response. */
export function isError(f: FlowSummary): boolean {
  return (f.status !== null && f.status >= 400) || f.error !== null;
}

export function isSlow(f: FlowSummary): boolean {
  return f.duration_ms !== null && f.duration_ms > SLOW_MS;
}

export function matchesQuick(f: FlowSummary, q: QuickFilter): boolean {
  switch (q) {
    case 'all':
      return true;
    case 'errors':
      return isError(f);
    case 'slow':
      return isSlow(f);
    case 'mocked':
      return f.mock;
    case 'faulted':
      return f.fault !== null && f.fault !== '';
    case 'websocket':
      return f.websocket;
  }
}

export function quickCounts(flows: readonly FlowSummary[]): Record<QuickFilter, number> {
  const counts: Record<QuickFilter, number> = {
    all: 0,
    errors: 0,
    slow: 0,
    mocked: 0,
    faulted: 0,
    websocket: 0,
  };
  for (const f of flows) {
    counts.all++;
    if (isError(f)) counts.errors++;
    if (isSlow(f)) counts.slow++;
    if (f.mock) counts.mocked++;
    if (f.fault !== null && f.fault !== '') counts.faulted++;
    if (f.websocket) counts.websocket++;
  }
  return counts;
}

export interface HostCount {
  host: string;
  count: number;
}

/** Hosts by flow count, busiest first; ties alphabetical. */
export function hostCounts(flows: readonly FlowSummary[]): HostCount[] {
  const map = new Map<string, number>();
  for (const f of flows) map.set(f.host, (map.get(f.host) ?? 0) + 1);
  return [...map.entries()]
    .map(([host, count]) => ({ host, count }))
    .sort((a, b) => b.count - a.count || a.host.localeCompare(b.host));
}

const DEFAULT_PORTS: Record<string, number> = { http: 80, https: 443, ws: 80, wss: 443 };

export function flowUrl(f: Pick<FlowSummary, 'scheme' | 'host' | 'port' | 'path'>): string {
  const port = DEFAULT_PORTS[f.scheme] === f.port || !f.port ? '' : `:${f.port}`;
  return `${f.scheme}://${f.host}${port}${f.path}`;
}

/** Input starting with `~` or `!` is a mitmproxy filter expression, evaluated by the server. */
export function isServerExpr(input: string): boolean {
  const t = input.trimStart();
  return t.startsWith('~') || t.startsWith('!');
}

export const BODY_SEARCH_MIN = 3;

/** Plain text long enough for the server to search headers and bodies too. */
export function isBodySearch(input: string): boolean {
  return !isServerExpr(input) && input.trim().length >= BODY_SEARCH_MIN;
}

/** Plain text search: every word must appear in method, URL or status. */
export function matchesText(f: FlowSummary, text: string): boolean {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = `${f.method} ${flowUrl(f)} ${f.status ?? ''}`.toLowerCase();
  return words.every((w) => haystack.includes(w));
}

export interface FlowFilter {
  quick: QuickFilter;
  host: string | null;
  text: string;
  /**
   * From the server, null while unknown: for a `~`/`!` expression the ids it matches; for plain
   * text the ids whose headers or bodies contain it, added to what the text matches here.
   */
  serverIds: ReadonlySet<string> | null;
}

export function applyFilters(flows: readonly FlowSummary[], filter: FlowFilter): FlowSummary[] {
  const server = isServerExpr(filter.text);
  const ids = filter.serverIds;
  return flows.filter(
    (f) =>
      matchesQuick(f, filter.quick) &&
      (filter.host === null || f.host === filter.host) &&
      (server ? ids === null || ids.has(f.id) : matchesText(f, filter.text) || (ids !== null && ids.has(f.id))),
  );
}

export type ChipKind = 'host' | 'quick' | 'default' | 'search';

export interface Chip {
  kind: ChipKind;
  label: string;
}

/** The active filters, each removable: host, quick filter, and the search (marked when it is the preset's default). */
export function activeChips(filter: Pick<FlowFilter, 'quick' | 'host' | 'text'>, defaultFilter: string): Chip[] {
  const chips: Chip[] = [];
  if (filter.host) chips.push({ kind: 'host', label: `host: ${filter.host}` });
  if (filter.quick !== 'all') {
    const q = QUICK_FILTERS.find((x) => x.id === filter.quick);
    chips.push({ kind: 'quick', label: q ? q.label : filter.quick });
  }
  const text = filter.text.trim();
  if (text) {
    const isDefault = defaultFilter.trim() !== '' && text === defaultFilter.trim();
    chips.push({ kind: isDefault ? 'default' : 'search', label: isDefault ? `preset filter: ${text}` : `search: ${text}` });
  }
  return chips;
}
