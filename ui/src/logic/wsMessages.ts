import { formatSize } from './format';

/** The page keeps this many messages of the open connection. */
export const MAX_KEPT = 5_000;
/** One list request. The server clamps to the same number. */
export const PAGE_LIMIT = 500;
/** The hex dump shows this many bytes; Copy still has the rest, up to 2 MiB. */
export const HEX_DUMP_BYTES = 4 * 1024;

export const OVERSIZE = 'Larger than 2 MiB: shown up to 2 MiB; the HAR in a bug report has it';
export const NEWEST_NOTE = 'Showing the newest 5,000; scroll up to load older';

export type WsClosedBy = 'client' | 'server' | null;

export interface DetailTab {
  id: 'messages' | 'request' | 'response' | 'headers' | 'changes' | 'timing' | 'logs';
  label: string;
}

/** Messages is first, and only for a WebSocket row. Changes stays where it is for other rows. */
export function detailTabs(websocket: boolean, changes: boolean): DetailTab[] {
  const tabs: DetailTab[] = [
    { id: 'request', label: 'Request' },
    { id: 'response', label: 'Response' },
    { id: 'headers', label: 'Headers' },
  ];
  if (changes) tabs.push({ id: 'changes', label: 'Changes' });
  tabs.push({ id: 'timing', label: 'Timing' }, { id: 'logs', label: 'Logs' });
  return websocket ? [{ id: 'messages', label: 'Messages' }, ...tabs] : tabs;
}

/** The size column: a WebSocket shows how many messages it has carried. */
export function trafficSize(websocket: boolean, wsMessages: number | null | undefined, size: number | null): string {
  if (websocket) return `↕ ${wsMessages ?? 0}`;
  return formatSize(size);
}

/** The line above the list. The count is every message, not the filtered ones. */
export function connectionHeader(closedBy: WsClosedBy, code: number | null, reason: string | null, count: number): string {
  const messages = `${count} ${count === 1 ? 'message' : 'messages'}`;
  if (closedBy === null) return `Open · ${messages}`;
  const who = closedBy === 'client' ? 'Closed by the app' : 'Closed by the server';
  const codeText = code === null ? '' : code === 1000 ? ' · code 1000 (normal)' : ` · code ${code}`;
  const reasonText = reason ? ` · reason: ${reason}` : '';
  return `${who}${codeText}${reasonText} · ${messages}`;
}

/** "12 of 128" beside the filter. */
export function matchLabel(matched: number, total: number): string {
  return `${matched} of ${total}`;
}

export function newestNote(total: number, kept: number, oldestIndex: number): string | null {
  if (total > MAX_KEPT && kept >= MAX_KEPT && oldestIndex > 0) return NEWEST_NOTE;
  return null;
}

/** Where a first fetch starts: the tail, so the list opens on the newest messages. */
export function tailFrom(total: number, limit = PAGE_LIMIT): number {
  return Math.max(0, total - limit);
}

/** The next index after a full page, or null when this page already reached the end. */
export function continueFrom(lastIndex: number | null, got: number, total: number, limit = PAGE_LIMIT): number | null {
  if (got < limit || lastIndex === null) return null;
  const next = lastIndex + 1;
  return next < total ? next : null;
}

/** The page before the oldest one loaded, or null at the start of the connection. */
export function olderFrom(oldestIndex: number | null, limit = PAGE_LIMIT): number | null {
  if (oldestIndex === null || oldestIndex <= 0) return null;
  return Math.max(0, oldestIndex - limit);
}

export function mergeMessages<T extends { index: number }>(current: ReadonlyMap<number, T>, page: readonly T[]): Map<number, T> {
  const next = new Map(current);
  for (const message of page) next.set(message.index, message);
  return next;
}

/** Keep `max` messages. `newest` drops the oldest; `oldest` drops the newest, for a scroll up into older ones. */
export function trimWindow<T>(items: ReadonlyMap<number, T>, max: number, side: 'newest' | 'oldest'): Map<number, T> {
  if (items.size <= max) return new Map(items);
  const keys = [...items.keys()].sort((a, b) => a - b);
  const keep = side === 'newest' ? keys.slice(keys.length - max) : keys.slice(0, max);
  const next = new Map<number, T>();
  for (const key of keep) {
    const value = items.get(key);
    if (value !== undefined) next.set(key, value);
  }
  return next;
}

export function sortedMessages<T extends { index: number }>(items: ReadonlyMap<number, T>): T[] {
  return [...items.values()].sort((a, b) => a.index - b.index);
}

export function oldestIndex(items: ReadonlyMap<number, unknown>): number | null {
  let min: number | null = null;
  for (const key of items.keys()) if (min === null || key < min) min = key;
  return min;
}

export interface LoadToken {
  id: string;
  generation: number;
}

/** A new load for a row. A fetch started under an older token is discarded when it returns. */
export function startLoad(id: string, generation: number): { token: LoadToken; generation: number } {
  const next = generation + 1;
  return { token: { id, generation: next }, generation: next };
}

export function acceptLoad(token: LoadToken, generation: number): boolean {
  return token.generation === generation;
}

export type FollowEvent = 'append' | 'scroll-up' | 'scroll-bottom' | 'select';

/** Following the newest stops when the tester scrolls up or selects a message, and starts again at the bottom. */
export function followAfter(event: FollowEvent, follow: boolean): boolean {
  if (event === 'scroll-up' || event === 'select') return false;
  if (event === 'scroll-bottom') return true;
  return follow;
}

/** A hex and ASCII dump of the first 4 KiB. `hex` is the continuous lowercase hex from the server. */
export function hexDump(hex: string): string {
  const bytes: number[] = [];
  for (let i = 0; i + 1 < hex.length && bytes.length < HEX_DUMP_BYTES; i += 2) {
    const value = Number.parseInt(hex.slice(i, i + 2), 16);
    if (Number.isNaN(value)) break;
    bytes.push(value);
  }
  const lines: string[] = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const chunk = bytes.slice(i, i + 16);
    const hexPart = chunk.map((b) => b.toString(16).padStart(2, '0')).join(' ');
    const ascii = chunk.map((b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : '.')).join('');
    lines.push(`${i.toString(16).padStart(8, '0')}  ${hexPart.padEnd(47, ' ')}  ${ascii}`);
  }
  return lines.join('\n');
}
