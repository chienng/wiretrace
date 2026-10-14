import { describe, expect, it } from 'vitest';
import { initialStore, reducer, type Store } from './store';
import { flow, line } from './logic/testing';
import type { AppState } from './types';

const appState = { default_filter: '~u /api', faults: { filter: '', status: 0, delay_ms: 0, drop: false }, faults_on: false } as AppState;

function loaded(): Store {
  return reducer(initialStore, {
    type: 'loaded',
    data: { state: appState, flows: [flow({ id: 'a', status: null }), flow({ id: 'b' })], device: [line({ seq: 1 })], app: [] },
    buffered: [
      { type: 'flows', flows: [flow({ id: 'a', status: 200 }), flow({ id: 'c' })] },
      { type: 'logs', lines: [line({ seq: 1 }), line({ seq: 2 })] },
    ],
  });
}

describe('store', () => {
  it('merges the initial load with buffered messages and applies the default filter once', () => {
    const s = loaded();
    expect(s.flows.map((f) => f.id)).toEqual(['a', 'b', 'c']);
    expect(s.flows[0]?.status).toBe(200);
    expect(s.logs.device.map((l) => l.seq)).toEqual([1, 2]);
    expect(s.ui.search).toBe('~u /api');
    const typed = reducer(s, { type: 'ui', patch: { search: 'orders' } });
    const reloaded = reducer(typed, { type: 'loaded', data: { state: appState, flows: [], device: [], app: [] }, buffered: [] });
    expect(reloaded.ui.search).toBe('orders');
  });

  it('keeps one row per flow when a socket message repeats it', () => {
    const s = reducer(loaded(), { type: 'message', message: { type: 'flows', flows: [flow({ id: 'b', status: 500 })] } });
    expect(s.flows.filter((f) => f.id === 'b')).toHaveLength(1);
    expect(s.flows.find((f) => f.id === 'b')?.status).toBe(500);
  });

  it('pause freezes the listed ids, clear hides them, openFlow brings one back', () => {
    let s = reducer(loaded(), { type: 'pause' });
    expect([...(s.ui.frozen ?? [])]).toEqual(['a', 'b', 'c']);
    s = reducer(s, { type: 'message', message: { type: 'flows', flows: [flow({ id: 'd' })] } });
    expect(s.ui.frozen?.has('d')).toBe(false);
    s = reducer(s, { type: 'clear' });
    expect([...s.ui.hidden].sort()).toEqual(['a', 'b', 'c', 'd']);
    expect(s.ui.clearedSeq.device).toBe(2);
    s = reducer(s, { type: 'openFlow', id: 'b' });
    expect(s.ui.hidden.has('b')).toBe(false);
    expect(s.ui.selectedFlowId).toBe('b');
  });
});
