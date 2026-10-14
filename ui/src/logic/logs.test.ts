import { describe, expect, it } from 'vitest';
import {
  findLinkedFlow,
  isCrash,
  levelCounts,
  matchesLevels,
  matchesLogText,
  matchesMinLevel,
  matchesRequest,
  normalizeLevel,
  type Level,
} from './logs';
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
