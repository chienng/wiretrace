import { describe, expect, it } from 'vitest';
import { formatDuration, formatElapsed, formatSize, formatVersion, statusClass } from './format';
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
  it('labels the version, or nothing without one', () => {
    expect(formatVersion('0.8.0')).toBe('v0.8.0');
    expect(formatVersion(' 0.8.0 ')).toBe('v0.8.0');
    expect(formatVersion('')).toBe('');
    expect(formatVersion(undefined)).toBe('');
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

describe('json', () => {
  it('parses objects and arrays only', () => {
    expect(tryParseJson('{"a":1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(tryParseJson('[1]').ok).toBe(true);
    expect(tryParseJson('42').ok).toBe(false);
    expect(tryParseJson('{broken').ok).toBe(false);
  });
});
