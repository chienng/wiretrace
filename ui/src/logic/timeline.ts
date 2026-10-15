import type { FlowSummary, LogLine } from '../types';
import { isCrash, normalizeLevel } from './logs';

/** Per pixel column, the most severe request: 0 none, 1 2xx, 2 3xx or pending, 3 4xx, 4 5xx or failed. */
export const REQ_NONE = 0;
export const REQ_OK = 1;
export const REQ_REDIRECT = 2;
export const REQ_CLIENT = 3;
export const REQ_SERVER = 4;

/** Per pixel column, the most severe log line: 0 none, 1 other, 2 warning, 3 error. Crashes apart. */
export const LOG_NONE = 0;
export const LOG_OTHER = 1;
export const LOG_WARN = 2;
export const LOG_ERROR = 3;

export interface Range {
  start: number;
  end: number;
}

export interface Buckets {
  range: Range;
  columns: number;
  requests: Uint8Array;
  logs: Uint8Array;
  crashes: Uint8Array;
}

export function requestClass(f: Pick<FlowSummary, 'status' | 'error'>): number {
  if (f.error !== null || (f.status !== null && f.status >= 500)) return REQ_SERVER;
  if (f.status === null) return REQ_REDIRECT;
  if (f.status >= 400) return REQ_CLIENT;
  if (f.status >= 300) return REQ_REDIRECT;
  return REQ_OK;
}

export function logClass(line: LogLine): number {
  const level = normalizeLevel(line.level);
  if (level === 'E' || level === 'F') return LOG_ERROR;
  if (level === 'W') return LOG_WARN;
  return LOG_OTHER;
}

/** The time span of the flows and timed lines, or null when nothing has a time. At least one second wide. */
export function timeRange(flows: readonly FlowSummary[], lines: readonly LogLine[]): Range | null {
  let start = Infinity;
  let end = -Infinity;
  for (const f of flows) {
    if (f.ts < start) start = f.ts;
    if (f.ts > end) end = f.ts;
  }
  for (const l of lines) {
    if (l.ts == null) continue;
    if (l.ts < start) start = l.ts;
    if (l.ts > end) end = l.ts;
  }
  if (start === Infinity) return null;
  return end - start < 1 ? { start, end: start + 1 } : { start, end };
}

export function columnOf(ts: number, range: Range, columns: number): number {
  const at = Math.floor(((ts - range.start) / (range.end - range.start)) * columns);
  return Math.min(columns - 1, Math.max(0, at));
}

/** The time at the middle of a column. */
export function timeAt(column: number, range: Range, columns: number): number {
  return range.start + ((column + 0.5) / columns) * (range.end - range.start);
}

/** One pass over the flows and the lines: the most severe value per column. */
export function bucket(flows: readonly FlowSummary[], lines: readonly LogLine[], range: Range, columns: number): Buckets {
  const n = Math.max(1, Math.floor(columns));
  const requests = new Uint8Array(n);
  const logs = new Uint8Array(n);
  const crashes = new Uint8Array(n);
  for (const f of flows) {
    const c = columnOf(f.ts, range, n);
    const v = requestClass(f);
    if (v > (requests[c] as number)) requests[c] = v;
  }
  for (const l of lines) {
    if (l.ts == null) continue;
    const c = columnOf(l.ts, range, n);
    const v = logClass(l);
    if (v > (logs[c] as number)) logs[c] = v;
    if (isCrash(l)) crashes[c] = 1;
  }
  return { range, columns: n, requests, logs, crashes };
}

/** Axis labels: about one per `spacing` pixels, at whole seconds. */
export function ticks(range: Range, width: number, spacing = 120): number[] {
  const count = Math.max(1, Math.floor(width / spacing));
  const step = Math.max(1, Math.ceil((range.end - range.start) / count));
  const out: number[] = [];
  for (let t = Math.ceil(range.start / step) * step; t <= range.end; t += step) out.push(t);
  return out;
}
