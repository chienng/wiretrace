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
