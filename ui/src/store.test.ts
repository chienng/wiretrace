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

  it('a device message updates the state, also one buffered while loading', () => {
    const status = { state: 'streaming', message: 'streaming', source: 'adb logcat', app: 'a', model: 'Pixel 8', os: 'Android 15', updated_at: null } as const;
    const s = reducer(loaded(), { type: 'message', message: { type: 'device', status } });
    expect(s.appState?.device_status).toEqual(status);
    expect(s.appState?.default_filter).toBe('~u /api');
    const buffered = reducer(initialStore, {
      type: 'loaded',
      data: { state: { ...appState, device_status: null }, flows: [], device: [], app: [] },
      buffered: [{ type: 'device', status }],
    });
    expect(buffered.appState?.device_status).toEqual(status);
    expect(reducer(initialStore, { type: 'message', message: { type: 'device', status } }).appState).toBeNull();
  });

  it('pausing logs keeps the seq listed, clearing logs leaves the flows', () => {
    let s = reducer(loaded(), { type: 'logsPause' });
    expect(s.ui.logsFrozen).toEqual({ device: 2, app: -Infinity });
    s = reducer(s, { type: 'logsResume' });
    expect(s.ui.logsFrozen).toBeNull();
    s = reducer(s, { type: 'logsClear' });
    expect(s.ui.clearedSeq.device).toBe(2);
    expect(s.ui.hidden.size).toBe(0);
  });

  it('opening a previous session leaves the live data alone and the rules view', () => {
    let s = reducer(loaded(), { type: 'ui', patch: { view: 'rules', selectedFlowId: 'a', host: 'api.example.com', dialog: 'report' } });
    s = reducer(s, { type: 'viewOpened', view: { ...old, flows: [flow({ id: 'x' })] } });
    expect(s.view?.flows.map((f) => f.id)).toEqual(['x']);
    expect(s.flows.map((f) => f.id)).toEqual(['a', 'b', 'c']);
    expect(s.ui).toMatchObject({ view: 'traffic', selectedFlowId: null, host: null, dialog: null });
    s = reducer(s, { type: 'message', message: { type: 'flows', flows: [flow({ id: 'd' })] } });
    expect(s.flows.map((f) => f.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(s.view?.flows.map((f) => f.id)).toEqual(['x']);
    s = reducer(s, { type: 'viewClosed' });
    expect(s.view).toBeNull();
  });

  it('drops the view when the server is no longer showing that session', () => {
    let s = reducer(loaded(), { type: 'viewOpened', view: old });
    s = reducer(s, { type: 'message', message: { type: 'state', state: { ...appState, viewing: old.name } } });
    expect(s.view?.name).toBe(old.name);
    s = reducer(s, { type: 'message', message: { type: 'state', state: { ...appState, viewing: '20261015-090000-other' } } });
    expect(s.view).toBeNull();
    s = reducer(reducer(s, { type: 'viewOpened', view: old }), { type: 'message', message: { type: 'state', state: { ...appState, viewing: null } } });
    expect(s.view).toBeNull();
  });
});

const old = { name: '20261015-080000-myapp', flows: [], logs: { device: [], app: [] }, cutOff: false };
