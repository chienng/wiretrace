import { describe, expect, it } from 'vitest';
import {
  contextText,
  crashLines,
  exportText,
  findLinkedFlow,
  foldCrashes,
  foldMessage,
  isCrash,
  isLinked,
  itemAtTime,
  levelCounts,
  requestIds,
  requestsAround,
  tagCounts,
  type LogItem,
  matchesLevels,
  matchesLogText,
  matchesMinLevel,
  matchesRequest,
  normalizeLevel,
  type Level,
} from './logs';
import type { LogLine } from '../types';
import { flow, line } from './testing';

describe('levels', () => {
  it('normalises letters and names', () => {
    expect(normalizeLevel('e')).toBe('E');
    expect(normalizeLevel('Warning')).toBe('W');
    expect(normalizeLevel('FATAL')).toBe('F');
    expect(normalizeLevel('nonsense')).toBeNull();
    expect(normalizeLevel(null)).toBeNull();
  });
  it('counts lines per level', () => {
    const lines = [line({ level: 'I' }), line({ level: 'I' }), line({ level: 'E' }), line({ level: null })];
    expect(levelCounts(lines)).toEqual({ V: 0, D: 0, I: 2, W: 0, E: 1, F: 0 });
  });
  it('filters by enabled chips but never hides lines without a level', () => {
    const on = new Set<Level>(['E']);
    expect(matchesLevels(line({ level: 'E' }), on)).toBe(true);
    expect(matchesLevels(line({ level: 'I' }), on)).toBe(false);
    expect(matchesLevels(line({ level: null }), on)).toBe(true);
  });
  it('filters by minimum level', () => {
    expect(matchesMinLevel(line({ level: 'D' }), 'I')).toBe(false);
    expect(matchesMinLevel(line({ level: 'W' }), 'I')).toBe(true);
  });
});

describe('crashes', () => {
  it('is level F or a FATAL EXCEPTION message', () => {
    expect(isCrash(line({ level: 'F' }))).toBe(true);
    expect(isCrash(line({ level: 'E', message: 'FATAL EXCEPTION: main' }))).toBe(true);
    expect(isCrash(line({ level: 'E', message: 'plain error' }))).toBe(false);
  });
});

describe('request ID', () => {
  it('matches by request_id or by the message', () => {
    expect(matchesRequest(line({ request_id: 'req-1' }), 'req-1')).toBe(true);
    expect(matchesRequest(line({ message: 'POST /x req=req-1 failed' }), 'req-1')).toBe(true);
    expect(matchesRequest(line({ message: 'other' }), 'req-1')).toBe(false);
  });
  it('never matches an empty ID', () => {
    expect(matchesRequest(line({ message: 'anything' }), null)).toBe(false);
    expect(matchesRequest(line({ message: 'anything' }), '')).toBe(false);
  });
  it('finds the newest linked flow', () => {
    const flows = [flow({ id: 'a', request_id: 'req-1' }), flow({ id: 'b', request_id: 'req-2' }), flow({ id: 'c', request_id: 'req-1' })];
    expect(findLinkedFlow(line({ request_id: 'req-1' }), flows)?.id).toBe('c');
    expect(findLinkedFlow(line({ message: 'x req-2 y' }), flows)?.id).toBe('b');
    expect(findLinkedFlow(line({ message: 'none' }), flows)).toBeNull();
  });
});

describe('text filter', () => {
  it('matches tag and message, ignoring case', () => {
    expect(matchesLogText(line({ tag: 'OkHttp', message: 'GET /x' }), 'okhttp')).toBe(true);
    expect(matchesLogText(line({ message: 'GET /x' }), 'post')).toBe(false);
  });
});

const T0 = 1_700_000_000;
const time = (ts: number | null | undefined) => (ts == null ? '' : `t${ts - T0}`);

/** A crash at seq `at` with `trace` stack lines after it, then a line of another tag. */
function crash(at: number, trace: number, source: 'device' | 'app' = 'device') {
  const head = line({ seq: at, source, ts: T0 + at, level: 'E', tag: 'AndroidRuntime', message: 'FATAL EXCEPTION: main' });
  const stack = Array.from({ length: trace }, (_, i) =>
    line({ seq: at + 1 + i, source, ts: T0 + at, level: 'E', tag: 'AndroidRuntime', message: `  at frame ${i}` }),
  );
  const after = line({ seq: at + 1 + trace, source, ts: T0 + at + 1, level: 'I', tag: 'Other', message: 'next' });
  return [head, ...stack, after];
}

describe('crash folding', () => {
  it('folds a stack trace after four lines and says how many are hidden', () => {
    const items = foldCrashes(crash(1, 18), new Set());
    expect(items.filter((i) => i.kind === 'line')).toHaveLength(1 + 4 + 1);
    expect(items[5]).toEqual({ kind: 'more', crash: 'device:1', hidden: 14 });
    expect((items[6] as Extract<LogItem, { kind: 'line' }>).line.message).toBe('next');
  });
  it('shows the whole trace once expanded, and a short trace is never folded', () => {
    expect(foldCrashes(crash(1, 18), new Set(['device:1'])).every((i) => i.kind === 'line')).toBe(true);
    expect(foldCrashes(crash(1, 4), new Set()).every((i) => i.kind === 'line')).toBe(true);
  });
  it('ends the trace at a line of another tag or a new crash', () => {
    const items = foldCrashes([...crash(1, 2).slice(0, 3), ...crash(10, 6)], new Set());
    expect(items.filter((i) => i.kind === 'more')).toEqual([{ kind: 'more', crash: 'device:10', hidden: 2 }]);
  });
  it('lists crashes with their traces from every source, by time, a trace never split', () => {
    const out = crashLines(crash(5, 2), crash(1, 2, 'app'));
    expect(out.map((l) => `${l.source}:${l.seq}`)).toEqual(['app:1', 'app:2', 'app:3', 'device:5', 'device:6', 'device:7']);
  });
  it('folds a long multi-line message after four lines', () => {
    expect(foldMessage('a\nb\nc\nd\ne\nf', false)).toEqual({ text: 'a\nb\nc\nd', hidden: 2 });
    expect(foldMessage('a\nb\nc\nd\ne', false).hidden).toBe(0);
    expect(foldMessage('a\nb\nc\nd\ne\nf', true).hidden).toBe(0);
  });
});

describe('timeline click', () => {
  it('picks the first line at or after the time, else the last', () => {
    const items = foldCrashes([line({ seq: 1, ts: T0 }), line({ seq: 2, ts: null }), line({ seq: 3, ts: T0 + 10 })], new Set());
    expect(itemAtTime(items, T0 + 4)).toBe(2);
    expect(itemAtTime(items, T0 - 4)).toBe(0);
    expect(itemAtTime(items, T0 + 99)).toBe(2);
    expect(itemAtTime([], T0)).toBe(-1);
  });
});

describe('line detail', () => {
  it('finds the requests within ±5 s, oldest first', () => {
    const flows = [flow({ id: 'late', ts: T0 + 6 }), flow({ id: 'b', ts: T0 + 5 }), flow({ id: 'a', ts: T0 - 5 }), flow({ id: 'early', ts: T0 - 5.5 })];
    expect(requestsAround(line({ ts: T0 }), flows).map((f) => f.id)).toEqual(['a', 'b']);
    expect(requestsAround(line({ ts: null }), flows)).toEqual([]);
  });
  it('a line is linked by its request_id or a whole word of its message', () => {
    const ids = requestIds([flow({ request_id: '7f3a9c2e' }), flow({ request_id: null })]);
    expect(isLinked(line({ request_id: '7f3a9c2e' }), ids)).toBe(true);
    expect(isLinked(line({ message: 'createOrder failed req=7f3a9c2e: HTTP 500' }), ids)).toBe(true);
    expect(isLinked(line({ message: 'id 7f3a9c2e1 differs' }), ids)).toBe(false);
    expect(isLinked(line({ message: 'anything' }), new Set())).toBe(false);
  });
  it('copies the line with up to 50 lines before and after it', () => {
    const lines = Array.from({ length: 200 }, (_, i) => line({ seq: i + 1, ts: T0 + i, message: `m${i + 1}` }));
    const text = contextText(lines, lines[100] as LogLine, time).split('\n');
    expect(text).toHaveLength(101);
    expect(text[0]).toBe('t50 I Tag: m51');
    expect(text[100]).toBe('t150 I Tag: m151');
    expect(contextText(lines, lines[0] as LogLine, time).split('\n')).toHaveLength(51);
  });
  it('counts tags, most first', () => {
    const lines = [line({ tag: 'B' }), line({ tag: 'A' }), line({ tag: 'B' }), line({ tag: null })];
    expect(tagCounts(lines)).toEqual([
      { tag: 'B', count: 2 },
      { tag: '', count: 1 },
      { tag: 'A', count: 1 },
    ]);
  });
});

describe('export', () => {
  it('says the text is not masked, then one line per log line', () => {
    const lines = [line({ seq: 1, ts: T0, level: 'W', tag: 'Net', message: 'slow' }), line({ seq: 2, ts: null, level: null, message: 'raw' })];
    const rows = exportText(lines, 'Device logs', time).trimEnd().split('\n');
    expect(rows[0]).toBe('Wiretrace log export: Device logs');
    expect(rows[1]).toContain('NOT MASKED');
    expect(rows.slice(3)).toEqual(['t0 W Net: slow', ' - Tag: raw']);
  });
});
