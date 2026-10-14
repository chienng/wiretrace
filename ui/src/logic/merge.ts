import type { FlowSummary, LogLine, LogSource, ServerMessage } from '../types';

export const MAX_FLOWS = 10_000;
export const MAX_LINES = 50_000;

/** Replace by id (keeping position) or append; drop the oldest beyond `cap`. */
export function mergeFlows(
  current: readonly FlowSummary[],
  incoming: readonly FlowSummary[],
  cap: number = MAX_FLOWS,
): FlowSummary[] {
  if (incoming.length === 0) return current as FlowSummary[];
  const next = current.slice();
  const index = new Map<string, number>();
  next.forEach((f, i) => index.set(f.id, i));
  for (const f of incoming) {
    const at = index.get(f.id);
    if (at === undefined) {
      index.set(f.id, next.length);
      next.push(f);
    } else {
      next[at] = f;
    }
  }
  return next.length > cap ? next.slice(next.length - cap) : next;
}

/** Append lines whose seq is above the last one held; drop the oldest beyond `cap`. */
export function mergeLogs(
  current: readonly LogLine[],
  incoming: readonly LogLine[],
  cap: number = MAX_LINES,
): LogLine[] {
  let last = current.length > 0 ? (current[current.length - 1] as LogLine).seq : -Infinity;
  let next: LogLine[] | null = null;
  for (const line of incoming) {
    if (line.seq <= last) continue;
    if (next === null) next = current.slice();
    next.push(line);
    last = line.seq;
  }
  if (next === null) return current as LogLine[];
  return next.length > cap ? next.slice(next.length - cap) : next;
}

export interface LogSets {
  device: LogLine[];
  app: LogLine[];
}

export function mergeLogSets(current: LogSets, lines: readonly LogLine[], cap: number = MAX_LINES): LogSets {
  const bySource: Record<LogSource, LogLine[]> = { device: [], app: [] };
  for (const line of lines) {
    if (line.source === 'device' || line.source === 'app') bySource[line.source].push(line);
  }
  return {
    device: mergeLogs(current.device, bySource.device, cap),
    app: mergeLogs(current.app, bySource.app, cap),
  };
}

export interface Loaded {
  flows: FlowSummary[];
  logs: LogSets;
}

/** Apply socket messages buffered while the initial load was running (flows by id, logs by seq). */
export function applyMessages(base: Loaded, messages: readonly ServerMessage[]): Loaded {
  let { flows, logs } = base;
  for (const m of messages) {
    if (m.type === 'flows') flows = mergeFlows(flows, m.flows);
    else if (m.type === 'logs') logs = mergeLogSets(logs, m.lines);
  }
  return { flows, logs };
}
