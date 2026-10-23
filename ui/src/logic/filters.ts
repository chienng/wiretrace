import type { FlowSummary, TrafficRow, TunnelRow } from '../types';
import { covered, hostPort, isTunnel } from './hosts';

export type QuickFilter = 'all' | 'errors' | 'slow' | 'mocked' | 'faulted' | 'websocket' | 'encrypted';

export const SLOW_MS = 1000;

export const QUICK_FILTERS: { id: QuickFilter; label: string }[] = [
  { id: 'all', label: 'All requests' },
  { id: 'errors', label: 'Errors 4xx / 5xx' },
  { id: 'slow', label: 'Slow > 1 s' },
  { id: 'mocked', label: 'Mocked' },
  { id: 'faulted', label: 'Faulted' },
  { id: 'websocket', label: 'WebSocket' },
  { id: 'encrypted', label: 'Encrypted' },
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
    case 'encrypted':
      return false;
  }
}

/** An encrypted connection is in All requests (while shown) and Encrypted, never in the other filters. */
export function quickCounts(
  flows: readonly FlowSummary[],
  tunnels: readonly TunnelRow[] = [],
  showEncrypted = true,
): Record<QuickFilter, number> {
  const counts: Record<QuickFilter, number> = {
    all: showEncrypted ? tunnels.length : 0,
    errors: 0,
    slow: 0,
    mocked: 0,
    faulted: 0,
    websocket: 0,
    encrypted: tunnels.length,
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

function busiestFirst(map: ReadonlyMap<string, number>): HostCount[] {
  return [...map.entries()]
    .map(([host, count]) => ({ host, count }))
    .sort((a, b) => b.count - a.count || a.host.localeCompare(b.host));
}

/** Hosts by flow count, busiest first; ties alphabetical. */
export function hostCounts(flows: readonly FlowSummary[]): HostCount[] {
  const map = new Map<string, number>();
  for (const f of flows) map.set(f.host, (map.get(f.host) ?? 0) + 1);
  return busiestFirst(map);
}

/** Hosts of encrypted connections by connection count, without those the API hosts decrypt now. */
export function encryptedHostCounts(tunnels: readonly TunnelRow[], apiHosts: readonly string[]): HostCount[] {
  const map = new Map<string, number>();
  for (const t of tunnels) if (!covered(apiHosts, t.host)) map.set(t.host, (map.get(t.host) ?? 0) + 1);
  return busiestFirst(map);
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

/** Plain text search: every word must appear in method, URL or status; for a connection, method and host. */
export function matchesText(f: TrafficRow, text: string): boolean {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = (isTunnel(f) ? `${f.method} ${hostPort(f)}` : `${f.method} ${flowUrl(f)} ${f.status ?? ''}`).toLowerCase();
  return words.every((w) => haystack.includes(w));
}

/** Requests and encrypted connections in one list by time; each list is already in time order. */
export function mergeRows(flows: readonly FlowSummary[], tunnels: readonly TunnelRow[]): TrafficRow[] {
  if (tunnels.length === 0) return flows as FlowSummary[];
  const rows: TrafficRow[] = [];
  let i = 0;
  let j = 0;
  while (i < flows.length && j < tunnels.length) {
    const f = flows[i] as FlowSummary;
    const t = tunnels[j] as TunnelRow;
    if (t.ts < f.ts) {
      rows.push(t);
      j++;
    } else {
      rows.push(f);
      i++;
    }
  }
  while (i < flows.length) rows.push(flows[i++] as FlowSummary);
  while (j < tunnels.length) rows.push(tunnels[j++] as TunnelRow);
  return rows;
}

/** Requests per device, by the summary's `client`. */
export function clientCounts(flows: readonly FlowSummary[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const f of flows) if (f.client) map.set(f.client, (map.get(f.client) ?? 0) + 1);
  return map;
}

export interface FlowFilter {
  quick: QuickFilter;
  host: string | null;
  /** One device by its `client` value; null for all devices. */
  client: string | null;
  text: string;
  /**
   * From the server, null while unknown: for a `~`/`!` expression the ids it matches; for plain
   * text the ids whose headers or bodies contain it, added to what the text matches here.
   */
  serverIds: ReadonlySet<string> | null;
  /** Show encrypted; the Encrypted quick filter lists them either way. */
  showEncrypted?: boolean;
}

export function applyFilters<T extends TrafficRow>(rows: readonly T[], filter: FlowFilter): T[] {
  const server = isServerExpr(filter.text);
  const ids = filter.serverIds;
  const encrypted = filter.quick === 'encrypted' || (filter.quick === 'all' && filter.showEncrypted !== false);
  return rows.filter((f) => {
    if ((filter.host !== null && f.host !== filter.host) || (filter.client !== null && f.client !== filter.client)) return false;
    // A mitmproxy expression only matches requests: the server never saw a connection's content.
    if (isTunnel(f)) return encrypted && !server && matchesText(f, filter.text);
    return (
      matchesQuick(f, filter.quick) &&
      (server ? ids === null || ids.has(f.id) : matchesText(f, filter.text) || (ids !== null && ids.has(f.id)))
    );
  });
}

export type ChipKind = 'host' | 'client' | 'quick' | 'default' | 'search';

export interface Chip {
  kind: ChipKind;
  label: string;
}

/** The active filters, each removable: host, quick filter, and the search (marked when it is the preset's default). */
export function activeChips(filter: Pick<FlowFilter, 'quick' | 'host' | 'client' | 'text'>, defaultFilter: string): Chip[] {
  const chips: Chip[] = [];
  if (filter.host) chips.push({ kind: 'host', label: `host: ${filter.host}` });
  if (filter.client) chips.push({ kind: 'client', label: `device: ${filter.client}` });
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
