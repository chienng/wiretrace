import { describe, expect, it } from 'vitest';
import { flow, line } from './testing';
import {
  bucket,
  columnOf,
  LOG_ERROR,
  LOG_OTHER,
  LOG_WARN,
  REQ_CLIENT,
  REQ_OK,
  REQ_REDIRECT,
  REQ_SERVER,
  requestClass,
  ticks,
  timeAt,
  timeRange,
} from './timeline';

const T0 = 1_700_000_000;

describe('timeline', () => {
  it('spans the flows and the timed lines, at least one second', () => {
    expect(timeRange([flow({ ts: T0 + 5 })], [line({ ts: T0 }), line({ ts: null })])).toEqual({ start: T0, end: T0 + 5 });
    expect(timeRange([flow({ ts: T0 })], [])).toEqual({ start: T0, end: T0 + 1 });
    expect(timeRange([], [line({ ts: null })])).toBeNull();
  });

  it('maps times to columns and back, clamped to the ends', () => {
    const range = { start: T0, end: T0 + 100 };
    expect(columnOf(T0, range, 100)).toBe(0);
    expect(columnOf(T0 + 50.2, range, 100)).toBe(50);
    expect(columnOf(T0 + 100, range, 100)).toBe(99);
    expect(columnOf(T0 - 9, range, 100)).toBe(0);
    expect(timeAt(50, range, 100)).toBe(T0 + 50.5);
  });

  it('classes requests by status, a failure as a server error', () => {
    expect(requestClass({ status: 204, error: null })).toBe(REQ_OK);
    expect(requestClass({ status: 304, error: null })).toBe(REQ_REDIRECT);
    expect(requestClass({ status: null, error: null })).toBe(REQ_REDIRECT);
    expect(requestClass({ status: 404, error: null })).toBe(REQ_CLIENT);
    expect(requestClass({ status: 503, error: null })).toBe(REQ_SERVER);
    expect(requestClass({ status: null, error: 'reset' })).toBe(REQ_SERVER);
  });

  it('keeps the most severe value per column, and marks crashes', () => {
    const range = { start: T0, end: T0 + 10 };
    const flows = [flow({ ts: T0 + 1, status: 200 }), flow({ ts: T0 + 1.5, status: 500 }), flow({ ts: T0 + 5, status: 200 })];
    const lines = [
      line({ ts: T0 + 1, level: 'W' }),
      line({ ts: T0 + 1.2, level: 'E' }),
      line({ ts: T0 + 3, level: 'I' }),
      line({ ts: T0 + 3.1, level: 'W' }),
      line({ ts: T0 + 7, level: 'F' }),
      line({ ts: null, level: 'E' }),
    ];
    const b = bucket(flows, lines, range, 10);
    expect([...b.requests]).toEqual([0, REQ_SERVER, 0, 0, 0, REQ_OK, 0, 0, 0, 0]);
    expect([...b.logs]).toEqual([0, LOG_ERROR, 0, LOG_WARN, 0, 0, 0, LOG_ERROR, 0, 0]);
    expect([...b.crashes]).toEqual([0, 0, 0, 0, 0, 0, 0, 1, 0, 0]);
    expect(bucket([], [line({ ts: T0, level: 'D' })], range, 10).logs[0]).toBe(LOG_OTHER);
  });

  it('buckets 50,000 lines and 10,000 requests quickly', () => {
    const lines = Array.from({ length: 50_000 }, (_, i) => line({ seq: i, ts: T0 + i / 10, level: i % 97 === 0 ? 'E' : 'I' }));
    const flows = Array.from({ length: 10_000 }, (_, i) => flow({ id: String(i), ts: T0 + i / 2, status: i % 50 === 0 ? 500 : 200 }));
    const started = performance.now();
    const range = timeRange(flows, lines);
    if (!range) throw new Error('no range');
    const b = bucket(flows, lines, range, 1200);
    expect(performance.now() - started).toBeLessThan(250);
    expect(b.columns).toBe(1200);
    expect(b.logs.some((v) => v === LOG_ERROR)).toBe(true);
  });

  it('labels the axis at whole seconds', () => {
    const t = ticks({ start: T0 + 0.5, end: T0 + 30 }, 360, 120);
    expect(t.every((x) => Number.isInteger(x) && x >= T0 + 0.5 && x <= T0 + 30)).toBe(true);
    expect(t.length).toBeGreaterThanOrEqual(2);
  });
});
