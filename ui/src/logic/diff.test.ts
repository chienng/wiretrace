import { describe, expect, it } from 'vitest';
import { compareChoices, defaultOther, headerDiff, jsonDiff, lineDiff, parseJson, shortValue } from './diff';
import { flow } from './testing';

describe('the request to compare with', () => {
  const a = flow({ id: 'a', ts: 10, path: '/orders' });
  const b = flow({ id: 'b', ts: 20, path: '/orders' });
  const other = flow({ id: 'o', ts: 25, path: '/profile' });
  const c = flow({ id: 'c', ts: 30, path: '/orders' });
  const post = flow({ id: 'p', ts: 15, path: '/orders', method: 'POST' });

  it('is the newest earlier request with the same method and path', () => {
    expect(defaultOther(c, [a, b, other, c, post])?.id).toBe('b');
  });
  it('is the next later one when there is no earlier one', () => {
    expect(defaultOther(a, [a, c, b, post])?.id).toBe('b');
  });
  it('is nothing when no request matches', () => {
    expect(defaultOther(other, [a, other])).toBeNull();
  });
  it('offers the same method and path first, newest first, without the request itself', () => {
    expect(compareChoices(b, [a, b, other, c, post]).map((f) => f.id)).toEqual(['c', 'a', 'o', 'p']);
    expect(compareChoices(b, [a, b, other, c, post], 2).map((f) => f.id)).toEqual(['c', 'a']);
  });
});

describe('header diff', () => {
  it('compares names ignoring case and joins repeated headers', () => {
    const rows = headerDiff(
      [
        ['Content-Type', 'application/json'],
        ['Set-Cookie', 'a=1'],
        ['Set-Cookie', 'b=2'],
        ['X-Old', '1'],
      ],
      [
        ['content-type', 'application/json'],
        ['set-cookie', 'a=1, b=3'],
        ['X-New', '2'],
      ],
    );
    expect(rows).toEqual([
      { name: 'Content-Type', left: 'application/json', right: 'application/json', changed: false },
      { name: 'Set-Cookie', left: 'a=1, b=2', right: 'a=1, b=3', changed: true },
      { name: 'X-Old', left: '1', right: null, changed: true },
      { name: 'X-New', left: null, right: '2', changed: true },
    ]);
  });
});

describe('JSON diff', () => {
  it('reads JSON only when the whole body parses', () => {
    expect(parseJson('{"a":1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(parseJson('{"a":')).toEqual({ ok: false });
    expect(parseJson('  ')).toEqual({ ok: false });
    expect(parseJson(null)).toEqual({ ok: false });
  });

  it('lists added, removed and changed keys with their paths', () => {
    const d = jsonDiff(
      { id: 1, items: [{ sku: 'A' }, { sku: 'B' }], 'x-y': true, gone: 'old' },
      { id: 1, items: [{ sku: 'A' }, { sku: 'C' }, { sku: 'D' }], 'x-y': false, added: null },
    );
    expect(d.changes).toEqual([
      { path: '$.items[1].sku', kind: 'changed', left: '"B"', right: '"C"' },
      { path: '$.items[2]', kind: 'added', right: '{"sku":"D"}' },
      { path: '$["x-y"]', kind: 'changed', left: 'true', right: 'false' },
      { path: '$.gone', kind: 'removed', left: '"old"' },
      { path: '$.added', kind: 'added', right: 'null' },
    ]);
    expect(d.same).toBe(2);
    expect(d.truncated).toBe(false);
  });

  it('compares values of different types as a change', () => {
    expect(jsonDiff({ a: [1] }, { a: { 0: 1 } }).changes).toEqual([{ path: '$.a', kind: 'changed', left: '[1]', right: '{"0":1}' }]);
  });

  it('stops listing at the limit', () => {
    const left = Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`k${i}`, i]));
    const d = jsonDiff(left, {}, 5);
    expect(d.changes).toHaveLength(5);
    expect(d.truncated).toBe(true);
  });

  it('shortens long values', () => {
    expect(shortValue('x'.repeat(500))).toHaveLength(201);
  });
});

describe('line diff', () => {
  it('keeps the common lines and marks the others', () => {
    const d = lineDiff('a\nb\nc\nd', 'a\nB\nc\nd\ne');
    expect(d.lines).toEqual([
      { kind: 'same', text: 'a' },
      { kind: 'removed', text: 'b' },
      { kind: 'added', text: 'B' },
      { kind: 'same', text: 'c' },
      { kind: 'same', text: 'd' },
      { kind: 'added', text: 'e' },
    ]);
    expect(d.cut).toBe(false);
  });

  it('marks everything the same for equal text', () => {
    expect(lineDiff('x\ny', 'x\ny').lines.every((l) => l.kind === 'same')).toBe(true);
  });

  it('compares only the start of very large bodies', () => {
    const big = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n');
    const d = lineDiff(big, `${big}\nmore`, 10);
    expect(d.cut).toBe(true);
    expect(d.lines).toHaveLength(10);
  });

  it('diffs 1,500 changed lines quickly', () => {
    const left = Array.from({ length: 1500 }, (_, i) => `left ${i}`).join('\n');
    const right = Array.from({ length: 1500 }, (_, i) => (i % 3 ? `left ${i}` : `right ${i}`)).join('\n');
    const started = performance.now();
    const d = lineDiff(left, right);
    expect(performance.now() - started).toBeLessThan(1000);
    expect(d.lines.filter((l) => l.kind === 'added')).toHaveLength(500);
  });
});
