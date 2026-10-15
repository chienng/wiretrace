import type { FlowSummary, Headers } from '../types';

// Compare: two requests side by side. Page-only (spec 008).

/** The request to compare with by default: the newest earlier one with the same method and path, else a later one. */
export function defaultOther(flow: FlowSummary, flows: readonly FlowSummary[]): FlowSummary | null {
  let before: FlowSummary | null = null;
  let after: FlowSummary | null = null;
  for (const f of flows) {
    if (f.id === flow.id || f.method !== flow.method || f.path !== flow.path) continue;
    if (f.ts <= flow.ts) {
      if (!before || f.ts >= before.ts) before = f;
    } else if (!after || f.ts < after.ts) {
      after = f;
    }
  }
  return before ?? after;
}

/** Up to `limit` requests to pick from: the same method and path first, then the others, newest first. */
export function compareChoices(flow: FlowSummary, flows: readonly FlowSummary[], limit = 500): FlowSummary[] {
  const others = flows.filter((f) => f.id !== flow.id);
  const newest = (a: FlowSummary, b: FlowSummary) => b.ts - a.ts;
  const same = others.filter((f) => f.method === flow.method && f.path === flow.path).sort(newest);
  const rest = others.filter((f) => f.method !== flow.method || f.path !== flow.path).sort(newest);
  return [...same, ...rest].slice(0, limit);
}

export interface HeaderRow {
  name: string;
  left: string | null;
  right: string | null;
  changed: boolean;
}

function headerMap(headers: Headers): Map<string, { name: string; value: string }> {
  const map = new Map<string, { name: string; value: string }>();
  for (const [name, value] of headers) {
    const key = name.toLowerCase();
    const seen = map.get(key);
    map.set(key, seen ? { name: seen.name, value: `${seen.value}, ${value}` } : { name, value });
  }
  return map;
}

/** One row per header name (ignoring case), repeated headers joined; the left order first. */
export function headerDiff(left: Headers, right: Headers): HeaderRow[] {
  const a = headerMap(left);
  const b = headerMap(right);
  const keys = [...a.keys(), ...[...b.keys()].filter((k) => !a.has(k))];
  return keys.map((k) => {
    const l = a.get(k);
    const r = b.get(k);
    return { name: (l ?? r)!.name, left: l?.value ?? null, right: r?.value ?? null, changed: l?.value !== r?.value };
  });
}

export function parseJson(text: string | null): { ok: true; value: unknown } | { ok: false } {
  if (text === null || text.trim() === '') return { ok: false };
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false };
  }
}

export type KeyKind = 'added' | 'removed' | 'changed';

export interface KeyChange {
  path: string;
  kind: KeyKind;
  left?: string;
  right?: string;
}

export interface JsonDiff {
  changes: KeyChange[];
  same: number;
  /** More changes than the limit: the rest is not listed. */
  truncated: boolean;
}

const IDENT = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const MAX_VALUE = 200;

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export function childPath(parent: string, key: string | number): string {
  if (typeof key === 'number') return `${parent}[${key}]`;
  return IDENT.test(key) ? `${parent}.${key}` : `${parent}[${JSON.stringify(key)}]`;
}

export function shortValue(v: unknown): string {
  const text = JSON.stringify(v) ?? String(v);
  return text.length > MAX_VALUE ? `${text.slice(0, MAX_VALUE)}…` : text;
}

/** Key-level differences of two JSON values: objects by key, arrays by index, anything else by value. */
export function jsonDiff(left: unknown, right: unknown, limit = 1000): JsonDiff {
  const out: JsonDiff = { changes: [], same: 0, truncated: false };
  const push = (c: KeyChange) => {
    if (out.changes.length >= limit) out.truncated = true;
    else out.changes.push(c);
  };
  const walk = (a: unknown, b: unknown, path: string) => {
    if (out.truncated) return;
    if (isObject(a) && isObject(b)) {
      for (const k of Object.keys(a)) {
        if (k in b) walk(a[k], b[k], childPath(path, k));
        else push({ path: childPath(path, k), kind: 'removed', left: shortValue(a[k]) });
      }
      for (const k of Object.keys(b)) if (!(k in a)) push({ path: childPath(path, k), kind: 'added', right: shortValue(b[k]) });
      return;
    }
    if (Array.isArray(a) && Array.isArray(b)) {
      const n = Math.max(a.length, b.length);
      for (let i = 0; i < n; i++) {
        if (i >= b.length) push({ path: childPath(path, i), kind: 'removed', left: shortValue(a[i]) });
        else if (i >= a.length) push({ path: childPath(path, i), kind: 'added', right: shortValue(b[i]) });
        else walk(a[i], b[i], childPath(path, i));
      }
      return;
    }
    if (JSON.stringify(a) === JSON.stringify(b)) out.same++;
    else push({ path, kind: 'changed', left: shortValue(a), right: shortValue(b) });
  };
  walk(left, right, '$');
  return out;
}

export type LineKind = 'same' | 'added' | 'removed';

export interface LineDiff {
  lines: { kind: LineKind; text: string }[];
  /** Too large for a line diff: only the start of each side was compared. */
  cut: boolean;
}

// The table is (lines + 1)² four-byte cells: 1,500 lines is about 9 MB at worst.
export const MAX_DIFF_LINES = 1500;

/** A line diff (longest common subsequence) after trimming the common start and end. */
export function lineDiff(left: string, right: string, maxLines = MAX_DIFF_LINES): LineDiff {
  let a = left.split('\n');
  let b = right.split('\n');
  const cut = a.length > maxLines || b.length > maxLines;
  a = a.slice(0, maxLines);
  b = b.slice(0, maxLines);
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const midA = a.slice(start, endA);
  const midB = b.slice(start, endB);
  const n = midA.length;
  const m = midB.length;
  // lcs[i * (m + 1) + j]: the LCS length of midA[i:] and midB[j:].
  const lcs = new Uint32Array((n + 1) * (m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i * (m + 1) + j] =
        midA[i] === midB[j] ? (lcs[(i + 1) * (m + 1) + j + 1] as number) + 1 : Math.max(lcs[(i + 1) * (m + 1) + j] as number, lcs[i * (m + 1) + j + 1] as number);
    }
  }
  const lines: LineDiff['lines'] = a.slice(0, start).map((text) => ({ kind: 'same' as const, text }));
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (midA[i] === midB[j]) {
      lines.push({ kind: 'same', text: midA[i] as string });
      i++;
      j++;
    } else if ((lcs[(i + 1) * (m + 1) + j] as number) >= (lcs[i * (m + 1) + j + 1] as number)) {
      lines.push({ kind: 'removed', text: midA[i++] as string });
    } else {
      lines.push({ kind: 'added', text: midB[j++] as string });
    }
  }
  while (i < n) lines.push({ kind: 'removed', text: midA[i++] as string });
  while (j < m) lines.push({ kind: 'added', text: midB[j++] as string });
  for (const text of a.slice(endA)) lines.push({ kind: 'same', text });
  return { lines, cut };
}
