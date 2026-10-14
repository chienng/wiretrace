import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { backoffDelay, Connection, type InitialData } from './connection';
import type { Phase, ServerMessage } from './types';
import { flow } from './logic/testing';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  push(message: ServerMessage) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  drop() {
    this.onclose?.();
  }
}

const json = (status: number, body: unknown) => ({ status, ok: status < 400, json: async () => body });

function stubFetch(handler: (url: string) => ReturnType<typeof json>) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    calls.push(url);
    return handler(url);
  });
  return calls;
}

const okHandler = (url: string) => {
  if (url === '/api/state') return json(200, { preset: 'p', default_filter: '' });
  if (url === '/api/flows') return json(200, { flows: [flow({ id: 'loaded' })] });
  return json(200, { lines: [] });
};

function harness() {
  const phases: Phase[] = [];
  const loads: { data: InitialData; buffered: ServerMessage[] }[] = [];
  const messages: ServerMessage[] = [];
  const connection = new Connection({
    onPhase: (p) => phases.push(p),
    onLoaded: (data, buffered) => loads.push({ data, buffered }),
    onMessage: (m) => messages.push(m),
  });
  return { connection, phases, loads, messages };
}

const flush = async () => {
  for (let i = 0; i < 10; i++) await Promise.resolve();
};

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.stubGlobal('location', { protocol: 'http:', host: '127.0.0.1:8081' });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('backoff', () => {
  it('doubles from 0.5 s up to 5 s', () => {
    expect([0, 1, 2, 3, 4, 5, 9].map(backoffDelay)).toEqual([500, 1000, 2000, 4000, 5000, 5000, 5000]);
  });
});

describe('Connection', () => {
  it('fetches only after the socket opens and hands over what arrived meanwhile', async () => {
    const calls = stubFetch(okHandler);
    const h = harness();
    h.connection.start();
    const ws = FakeWebSocket.instances[0] as FakeWebSocket;
    expect(ws.url).toBe('ws://127.0.0.1:8081/api/updates');
    expect(calls).toEqual([]);

    ws.open();
    ws.push({ type: 'flows', flows: [flow({ id: 'during' })] });
    await flush();

    expect(calls.sort()).toEqual(['/api/flows', '/api/logs?source=app', '/api/logs?source=device', '/api/state']);
    expect(h.loads).toHaveLength(1);
    expect(h.loads[0]?.buffered).toHaveLength(1);
    expect(h.phases.slice(-1)).toEqual(['live']);

    ws.push({ type: 'flows', flows: [flow({ id: 'after' })] });
    expect(h.messages).toHaveLength(1);
    h.connection.stop();
  });

  it('reconnects with backoff and reloads after a drop', async () => {
    stubFetch(okHandler);
    const h = harness();
    h.connection.start();
    (FakeWebSocket.instances[0] as FakeWebSocket).open();
    await flush();
    (FakeWebSocket.instances[0] as FakeWebSocket).drop();
    await flush();
    expect(h.phases.slice(-1)).toEqual(['reconnecting']);
    expect(FakeWebSocket.instances).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
    (FakeWebSocket.instances[1] as FakeWebSocket).open();
    await flush();
    expect(h.loads).toHaveLength(2);
    expect(h.phases.slice(-1)).toEqual(['live']);
    h.connection.stop();
  });

  it('waits longer after each failed attempt', async () => {
    stubFetch(okHandler);
    const h = harness();
    h.connection.start();
    (FakeWebSocket.instances[0] as FakeWebSocket).drop();
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
    (FakeWebSocket.instances[1] as FakeWebSocket).drop();
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeWebSocket.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeWebSocket.instances).toHaveLength(3);
    h.connection.stop();
  });

  it('stops for good on a 403 while loading', async () => {
    stubFetch(() => json(403, {}));
    const h = harness();
    h.connection.start();
    (FakeWebSocket.instances[0] as FakeWebSocket).open();
    await flush();
    expect(h.phases.slice(-1)).toEqual(['forbidden']);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('detects a refused socket (never opened) by probing with a fetch', async () => {
    const calls = stubFetch(() => json(403, {}));
    const h = harness();
    h.connection.start();
    (FakeWebSocket.instances[0] as FakeWebSocket).drop();
    await flush();
    expect(calls).toEqual(['/api/state']);
    expect(h.phases.slice(-1)).toEqual(['forbidden']);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
