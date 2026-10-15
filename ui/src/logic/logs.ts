import type { FlowSummary, LogLine } from '../types';

export type Level = 'V' | 'D' | 'I' | 'W' | 'E' | 'F';
export const LEVELS: Level[] = ['V', 'D', 'I', 'W', 'E', 'F'];
export const LEVEL_NAMES: Record<Level, string> = {
  V: 'Verbose',
  D: 'Debug',
  I: 'Info',
  W: 'Warning',
  E: 'Error',
  F: 'Fatal',
};

const ALIASES: Record<string, Level> = {
  V: 'V', VERBOSE: 'V', TRACE: 'V',
  D: 'D', DEBUG: 'D',
  I: 'I', INFO: 'I',
  W: 'W', WARN: 'W', WARNING: 'W',
  E: 'E', ERROR: 'E', ERR: 'E',
  F: 'F', FATAL: 'F', ASSERT: 'F', CRITICAL: 'F',
};

export function normalizeLevel(level: string | null | undefined): Level | null {
  if (!level) return null;
  return ALIASES[level.trim().toUpperCase()] ?? null;
}

export function isCrash(line: LogLine): boolean {
  return normalizeLevel(line.level) === 'F' || line.message.includes('FATAL EXCEPTION');
}

export function levelCounts(lines: readonly LogLine[]): Record<Level, number> {
  const counts: Record<Level, number> = { V: 0, D: 0, I: 0, W: 0, E: 0, F: 0 };
  for (const line of lines) {
    const l = normalizeLevel(line.level);
    if (l) counts[l]++;
  }
  return counts;
}

/** A line belongs to a request when its `request_id` equals the ID or its message contains it. */
export function matchesRequest(line: LogLine, requestId: string | null | undefined): boolean {
  if (!requestId) return false;
  return line.request_id === requestId || line.message.includes(requestId);
}

/** Lines without a parsed level (raw text) are never hidden by level filters. */
export function matchesLevels(line: LogLine, enabled: ReadonlySet<Level>): boolean {
  const l = normalizeLevel(line.level);
  return l === null || enabled.has(l);
}

const RANK: Record<Level, number> = { V: 0, D: 1, I: 2, W: 3, E: 4, F: 5 };

export function matchesMinLevel(line: LogLine, min: Level): boolean {
  const l = normalizeLevel(line.level);
  return l === null || RANK[l] >= RANK[min];
}

export function matchesLogText(line: LogLine, text: string): boolean {
  const t = text.trim().toLowerCase();
  if (!t) return true;
  return `${line.tag ?? ''} ${line.message}`.toLowerCase().includes(t);
}

export function logKey(line: Pick<LogLine, 'source' | 'seq'>): string {
  return `${line.source}:${line.seq}`;
}

/** The newest flow a log line belongs to: by `request_id`, else by a request ID inside the message. */
export function findLinkedFlow(line: LogLine, flows: readonly FlowSummary[]): FlowSummary | null {
  for (let i = flows.length - 1; i >= 0; i--) {
    const f = flows[i] as FlowSummary;
    if (f.request_id && matchesRequest(line, f.request_id)) return f;
  }
  return null;
}

/** The request IDs of the captured flows, for a fast "linked to a request" test over many lines. */
export function requestIds(flows: readonly FlowSummary[]): ReadonlySet<string> {
  const ids = new Set<string>();
  for (const f of flows) if (f.request_id) ids.add(f.request_id);
  return ids;
}

const ID_SEPARATORS = /[^A-Za-z0-9_.:-]+/;
const EDGE_PUNCTUATION = /^[.:]+|[.:]+$/g;

/** A line is linked when its `request_id`, or a word of its message, is a captured request's ID. */
export function isLinked(line: LogLine, ids: ReadonlySet<string>): boolean {
  if (ids.size === 0) return false;
  if (line.request_id && ids.has(line.request_id)) return true;
  for (const word of line.message.split(ID_SEPARATORS)) {
    if (!word) continue;
    if (ids.has(word) || ids.has(word.replace(EDGE_PUNCTUATION, ''))) return true;
  }
  return false;
}

export function matchesTag(line: LogLine, tag: string | null): boolean {
  return tag === null || (line.tag ?? '') === tag;
}

/** Tags by line count, most first; ties alphabetical. At most `limit`. */
export function tagCounts(lines: readonly LogLine[], limit = 200): { tag: string; count: number }[] {
  const map = new Map<string, number>();
  for (const l of lines) map.set(l.tag ?? '', (map.get(l.tag ?? '') ?? 0) + 1);
  return [...map.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag))
    .slice(0, limit);
}

// Crashes: a crash line and the stack trace after it, folded after FOLD_AFTER lines.

export const FOLD_AFTER = 4;

/** A line of a crash's stack trace: right after it, same source and tag, an error, not a new crash. */
export function continuesCrash(crash: LogLine, line: LogLine): boolean {
  const level = normalizeLevel(line.level);
  return line.source === crash.source && (line.tag ?? '') === (crash.tag ?? '') && (level === 'E' || level === 'F') && !isCrash(line);
}

/** Each crash line with its stack trace, from every source; crashes by time, a trace never split. */
export function crashLines(...sources: (readonly LogLine[])[]): LogLine[] {
  const groups: LogLine[][] = [];
  for (const lines of sources) {
    for (let i = 0; i < lines.length; i++) {
      const head = lines[i] as LogLine;
      if (!isCrash(head)) continue;
      const group = [head];
      while (i + 1 < lines.length && continuesCrash(head, lines[i + 1] as LogLine)) group.push(lines[++i] as LogLine);
      groups.push(group);
    }
  }
  const head = (g: LogLine[]) => g[0] as LogLine;
  groups.sort((a, b) => (head(a).ts ?? 0) - (head(b).ts ?? 0) || head(a).seq - head(b).seq);
  return groups.flat();
}

export type LogItem = { kind: 'line'; line: LogLine } | { kind: 'more'; crash: string; hidden: number };

/** The rows of the list: lines, and "Show N more lines" in place of a long stack trace not expanded. */
export function foldCrashes(lines: readonly LogLine[], expanded: ReadonlySet<string>): LogItem[] {
  const items: LogItem[] = [];
  for (let i = 0; i < lines.length; i++) {
    const head = lines[i] as LogLine;
    items.push({ kind: 'line', line: head });
    if (!isCrash(head)) continue;
    let end = i + 1;
    while (end < lines.length && continuesCrash(head, lines[end] as LogLine)) end++;
    const trace = end - i - 1;
    const key = logKey(head);
    const shown = trace > FOLD_AFTER && !expanded.has(key) ? FOLD_AFTER : trace;
    for (let k = i + 1; k <= i + shown; k++) items.push({ kind: 'line', line: lines[k] as LogLine });
    if (shown < trace) items.push({ kind: 'more', crash: key, hidden: trace - shown });
    i = end - 1;
  }
  return items;
}

/** The first item at or after `ts`; the last item when all are earlier, -1 when there are none. */
export function itemAtTime(items: readonly LogItem[], ts: number): number {
  let last = -1;
  for (let i = 0; i < items.length; i++) {
    const item = items[i] as LogItem;
    if (item.kind !== 'line' || item.line.ts == null) continue;
    if (item.line.ts >= ts) return i;
    last = i;
  }
  return last;
}

// Line detail

export const AROUND_S = 5;
export const CONTEXT_LINES = 50;
const MAX_AROUND = 50;

/** Requests that started within ±AROUND_S seconds of the line, oldest first. */
export function requestsAround(line: LogLine, flows: readonly FlowSummary[], seconds = AROUND_S): FlowSummary[] {
  const ts = line.ts;
  if (ts == null) return [];
  return flows
    .filter((f) => Math.abs(f.ts - ts) <= seconds)
    .sort((a, b) => a.ts - b.ts)
    .slice(0, MAX_AROUND);
}

export function formatLogLine(line: LogLine, time: (ts: number | null | undefined) => string): string {
  const level = normalizeLevel(line.level) ?? '-';
  return `${time(line.ts)} ${level} ${line.tag ?? ''}: ${line.message}`;
}

/** The line and up to `n` lines before and after it, as text. */
export function contextText(lines: readonly LogLine[], line: LogLine, time: (ts: number | null | undefined) => string, n = CONTEXT_LINES): string {
  const at = lines.findIndex((l) => l.source === line.source && l.seq === line.seq);
  if (at < 0) return formatLogLine(line, time);
  return lines
    .slice(Math.max(0, at - n), at + n + 1)
    .map((l) => formatLogLine(l, time))
    .join('\n');
}

/** The text of Export .txt: a header that says the lines are not masked, then one line per log line. */
export function exportText(lines: readonly LogLine[], title: string, time: (ts: number | null | undefined) => string): string {
  const head = [`Wiretrace log export: ${title}`, `${lines.length} lines. NOT MASKED: may contain tokens and personal data.`, ''];
  return [...head, ...lines.map((l) => formatLogLine(l, time))].join('\n') + '\n';
}

/** A multi-line message folded after FOLD_AFTER lines: the shown part and how many lines are hidden. */
export function foldMessage(message: string, expanded: boolean): { text: string; hidden: number } {
  const parts = message.split('\n');
  if (expanded || parts.length <= FOLD_AFTER + 1) return { text: message, hidden: 0 };
  return { text: parts.slice(0, FOLD_AFTER).join('\n'), hidden: parts.length - FOLD_AFTER };
}
