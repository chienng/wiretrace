import { describe, expect, it } from 'vitest';
import { applyMessages, mergeFlows, mergeLogs, mergeLogSets } from './merge';
import { flow, line } from './testing';

describe('mergeFlows', () => {
  it('replaces by id and keeps the position', () => {
    const merged = mergeFlows([flow({ id: 'a' }), flow({ id: 'b' })], [flow({ id: 'a', status: 500 }), flow({ id: 'c' })]);
    expect(merged.map((f) => f.id)).toEqual(['a', 'b', 'c']);
    expect(merged[0]?.status).toBe(500);
  });
  it('lists a flow once whatever the order of batches (invariant 7)', () => {
    const pending = flow({ id: 'x', status: null, duration_ms: null });
    const done = flow({ id: 'x', status: 200 });
    for (const order of [[pending, done], [done, pending], [done, done]]) {
      const merged = mergeFlows([], order);
      expect(merged.filter((f) => f.id === 'x')).toHaveLength(1);
    }
  });
  it('drops the oldest beyond the cap', () => {
    const current = [1, 2, 3].map((n) => flow({ id: `f${n}` }));
    const merged = mergeFlows(current, [flow({ id: 'f4' }), flow({ id: 'f5' })], 3);
    expect(merged.map((f) => f.id)).toEqual(['f3', 'f4', 'f5']);
  });
});

describe('mergeLogs', () => {
  it('skips lines whose seq is not above the last one', () => {
    const merged = mergeLogs([line({ seq: 1 }), line({ seq: 2 })], [line({ seq: 2 }), line({ seq: 3 })]);
    expect(merged.map((l) => l.seq)).toEqual([1, 2, 3]);
  });
  it('caps per source and keeps the newest', () => {
    const current = [1, 2, 3].map((seq) => line({ seq }));
    expect(mergeLogs(current, [line({ seq: 4 })], 3).map((l) => l.seq)).toEqual([2, 3, 4]);
  });
  it('routes lines to their source', () => {
    const sets = mergeLogSets({ device: [], app: [] }, [line({ seq: 1, source: 'app' }), line({ seq: 1, source: 'device' })]);
    expect(sets.device).toHaveLength(1);
    expect(sets.app).toHaveLength(1);
  });
});

describe('applyMessages (initial load plus buffered socket messages)', () => {
  it('lets buffered flows replace loaded ones and ignores logs already loaded', () => {
    const base = {
      flows: [flow({ id: 'a', status: null }), flow({ id: 'b' })],
      logs: { device: [line({ seq: 1 }), line({ seq: 2 })], app: [] },
    };
    const result = applyMessages(base, [
      { type: 'flows', flows: [flow({ id: 'a', status: 200 }), flow({ id: 'c' })] },
      { type: 'logs', lines: [line({ seq: 2 }), line({ seq: 3 })] },
    ]);
    expect(result.flows.map((f) => f.id)).toEqual(['a', 'b', 'c']);
    expect(result.flows[0]?.status).toBe(200);
    expect(result.logs.device.map((l) => l.seq)).toEqual([1, 2, 3]);
  });
  it('ignores state messages', () => {
    const base = { flows: [], logs: { device: [], app: [] } };
    expect(applyMessages(base, [{ type: 'logs', lines: [] }]).flows).toEqual([]);
  });
});
