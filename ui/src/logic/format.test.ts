import { describe, expect, it } from 'vitest';
import { activeFaultCount, isFaultsOn } from './faults';
import { formatDuration, formatElapsed, formatSize, statusClass } from './format';
import { tryParseJson } from './json';

describe('format', () => {
  it('formats sizes, durations and the timer', () => {
    expect(formatSize(418)).toBe('418 B');
    expect(formatSize(1234)).toBe('1.2 KB');
    expect(formatDuration(1420)).toBe('1,420 ms');
    expect(formatDuration(null)).toBe('—');
    expect(formatElapsed(754)).toBe('00:12:34');
    expect(formatElapsed(-5)).toBe('00:00:00');
  });
  it('classes statuses', () => {
    expect(statusClass(200)).toBe('s2');
    expect(statusClass(302)).toBe('s3');
    expect(statusClass(404)).toBe('s4');
    expect(statusClass(503)).toBe('s5');
    expect(statusClass(101)).toBe('ws');
    expect(statusClass(null)).toBe('none');
  });
});

describe('faults', () => {
  it('counts active effects only while a filter is set', () => {
    const faults = { filter: '~u /x', status: 500, delay_ms: 800, drop: false };
    expect(activeFaultCount(faults, true)).toBe(2);
    expect(activeFaultCount(faults, false)).toBe(0);
    expect(isFaultsOn(faults)).toBe(true);
    expect(isFaultsOn({ ...faults, filter: '' })).toBe(false);
  });
});

describe('json', () => {
  it('parses objects and arrays only', () => {
    expect(tryParseJson('{"a":1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(tryParseJson('[1]').ok).toBe(true);
    expect(tryParseJson('42').ok).toBe(false);
    expect(tryParseJson('{broken').ok).toBe(false);
  });
});
