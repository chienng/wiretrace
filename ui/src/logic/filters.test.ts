import { describe, expect, it } from 'vitest';
import {
  activeChips,
  applyFilters,
  clientCounts,
  flowUrl,
  hostCounts,
  isBodySearch,
  isServerExpr,
  matchesQuick,
  matchesText,
  mergeRows,
  quickCounts,
  type FlowFilter,
} from './filters';
import { flow, tunnel } from './testing';

const base: FlowFilter = { quick: 'all', host: null, client: null, text: '', serverIds: null };

describe('quick filters', () => {
  it('treats 4xx, 5xx and flows without a response as errors', () => {
    expect(matchesQuick(flow({ status: 404 }), 'errors')).toBe(true);
    expect(matchesQuick(flow({ status: 500 }), 'errors')).toBe(true);
    expect(matchesQuick(flow({ status: null, error: 'Connection refused' }), 'errors')).toBe(true);
    expect(matchesQuick(flow({ status: 302 }), 'errors')).toBe(false);
    expect(matchesQuick(flow({ status: null, error: null }), 'errors')).toBe(false);
  });

  it('treats only durations above one second as slow', () => {
    expect(matchesQuick(flow({ duration_ms: 1000 }), 'slow')).toBe(false);
    expect(matchesQuick(flow({ duration_ms: 1001 }), 'slow')).toBe(true);
    expect(matchesQuick(flow({ duration_ms: null }), 'slow')).toBe(false);
  });

  it('counts every quick filter', () => {
    const flows = [
      flow({ id: 'a' }),
      flow({ id: 'b', status: 500, duration_ms: 2000 }),
      flow({ id: 'c', mock: true }),
      flow({ id: 'd', fault: 'status 500' }),
      flow({ id: 'e', websocket: true, status: 101 }),
      flow({ id: 'f', status: null, error: 'boom', duration_ms: null }),
    ];
    expect(quickCounts(flows)).toEqual({ all: 6, errors: 2, slow: 1, mocked: 1, faulted: 1, websocket: 1, encrypted: 0 });
  });
});

describe('encrypted connections (spec 022, slice C)', () => {
  const rows = mergeRows(
    [flow({ id: 'a', ts: 10 }), flow({ id: 'b', ts: 30, status: 500 }), flow({ id: 'c', ts: 50, client: '192.168.1.31' })],
    [
      tunnel({ id: 'tunnel-1', ts: 5, host: 'cdn.example.net' }),
      tunnel({ id: 'tunnel-2', ts: 30, host: 'o1.ingest.sentry.io', client: '192.168.1.31' }),
      tunnel({ id: 'tunnel-3', ts: 60, host: 'push.example.org', tls: false, method: 'TCP' }),
    ],
  );
  const ids = (r: readonly { id: string }[]) => r.map((x) => x.id);

  it('merges requests and connections by time, a request first at the same time', () => {
    expect(ids(rows)).toEqual(['tunnel-1', 'a', 'b', 'tunnel-2', 'c', 'tunnel-3']);
    expect(mergeRows([flow({ id: 'a' })], [])).toHaveLength(1);
  });
  it('lists connections in All and Encrypted only, and hides them with Show encrypted off', () => {
    expect(ids(applyFilters(rows, { ...base, quick: 'encrypted' }))).toEqual(['tunnel-1', 'tunnel-2', 'tunnel-3']);
    expect(ids(applyFilters(rows, { ...base, quick: 'errors' }))).toEqual(['b']);
    expect(ids(applyFilters(rows, { ...base, showEncrypted: false }))).toEqual(['a', 'b', 'c']);
    expect(ids(applyFilters(rows, { ...base, quick: 'encrypted', showEncrypted: false }))).toHaveLength(3);
  });
  it('matches connections by host in the search, the host filter and the device filter', () => {
    expect(ids(applyFilters(rows, { ...base, text: 'sentry' }))).toEqual(['tunnel-2']);
    expect(ids(applyFilters(rows, { ...base, text: 'connect example' }))).toEqual(['tunnel-1']);
    expect(ids(applyFilters(rows, { ...base, host: 'cdn.example.net' }))).toEqual(['tunnel-1']);
    expect(ids(applyFilters(rows, { ...base, client: '192.168.1.31' }))).toEqual(['tunnel-2', 'c']);
  });
  it('never matches a connection with a mitmproxy expression', () => {
    expect(ids(applyFilters(rows, { ...base, text: '~d example', serverIds: null }))).toEqual(['a', 'b', 'c']);
  });
  it('counts connections in All while shown and in Encrypted always', () => {
    const flows = [flow({ id: 'a' })];
    const tunnels = [tunnel({ id: 'tunnel-1' }), tunnel({ id: 'tunnel-2' })];
    expect(quickCounts(flows, tunnels)).toMatchObject({ all: 3, encrypted: 2, errors: 0 });
    expect(quickCounts(flows, tunnels, false)).toMatchObject({ all: 1, encrypted: 2 });
  });
  it('names the quick filter in its chip', () => {
    expect(activeChips({ quick: 'encrypted', host: null, client: null, text: '' }, '')).toEqual([{ kind: 'quick', label: 'Encrypted' }]);
  });
});

describe('text filter', () => {
  const f = flow({ method: 'POST', path: '/api/v1/orders?x=1', status: 500 });
  it('matches method, URL and status', () => {
    expect(matchesText(f, 'post')).toBe(true);
    expect(matchesText(f, 'orders')).toBe(true);
    expect(matchesText(f, 'api.example.com')).toBe(true);
    expect(matchesText(f, '500')).toBe(true);
    expect(matchesText(f, 'x=1')).toBe(true);
  });
  it('requires every word and ignores case', () => {
    expect(matchesText(f, 'POST ORDERS 500')).toBe(true);
    expect(matchesText(f, 'post profile')).toBe(false);
  });
  it('matches everything when empty', () => {
    expect(matchesText(f, '   ')).toBe(true);
  });
  it('detects server expressions', () => {
    expect(isServerExpr('~m POST')).toBe(true);
    expect(isServerExpr(' !~c 200')).toBe(true);
    expect(isServerExpr('orders')).toBe(false);
  });
});

describe('applyFilters', () => {
  const flows = [
    flow({ id: 'a', host: 'api.example.com', path: '/a' }),
    flow({ id: 'b', host: 'auth.example.com', path: '/b', status: 401 }),
    flow({ id: 'c', host: 'api.example.com', path: '/c', status: 500 }),
  ];
  const ids = (f: ReturnType<typeof applyFilters>) => f.map((x) => x.id);

  it('combines quick, host and text', () => {
    expect(ids(applyFilters(flows, { ...base, quick: 'errors', host: 'api.example.com' }))).toEqual(['c']);
    expect(ids(applyFilters(flows, { ...base, text: '/b' }))).toEqual(['b']);
  });
  it('uses the server result for expressions and shows everything while it is unknown', () => {
    expect(ids(applyFilters(flows, { ...base, text: '~c 500', serverIds: new Set(['c']) }))).toEqual(['c']);
    expect(ids(applyFilters(flows, { ...base, text: '~c 500', serverIds: null }))).toEqual(['a', 'b', 'c']);
  });
  it('adds the server body matches to the plain text matches', () => {
    expect(ids(applyFilters(flows, { ...base, text: 'token', serverIds: new Set(['c']) }))).toEqual(['c']);
    expect(ids(applyFilters(flows, { ...base, text: '/b', serverIds: new Set(['c']) }))).toEqual(['b', 'c']);
    expect(ids(applyFilters(flows, { ...base, text: 'token', serverIds: null }))).toEqual([]);
  });
});

describe('body search and chips', () => {
  it('asks the server for plain text of 3 characters or more only', () => {
    expect(isBodySearch('ab')).toBe(false);
    expect(isBodySearch(' abc ')).toBe(true);
    expect(isBodySearch('~c 500')).toBe(false);
  });
  it('lists host, device, quick filter and search, marking the preset filter', () => {
    expect(activeChips({ quick: 'all', host: null, client: null, text: '' }, '')).toEqual([]);
    expect(
      activeChips({ quick: 'errors', host: 'api.example.com', client: '192.168.1.42', text: 'orders' }, '~d example.com'),
    ).toEqual([
      { kind: 'host', label: 'host: api.example.com' },
      { kind: 'client', label: 'device: 192.168.1.42' },
      { kind: 'quick', label: 'Errors 4xx / 5xx' },
      { kind: 'search', label: 'search: orders' },
    ]);
    expect(activeChips({ quick: 'all', host: null, client: null, text: ' ~d example.com ' }, '~d example.com')).toEqual([
      { kind: 'default', label: 'preset filter: ~d example.com' },
    ]);
  });
});

describe('devices (spec 022)', () => {
  const flows = [
    flow({ id: 'a', client: '192.168.1.31' }),
    flow({ id: 'b', client: '192.168.1.42' }),
    flow({ id: 'c', client: '192.168.1.31' }),
    flow({ id: 'd', client: 'mac' }),
    flow({ id: 'e', client: null }),
  ];
  it('filters by one device and leaves the others alone without one', () => {
    expect(applyFilters(flows, { ...base, client: '192.168.1.31' }).map((f) => f.id)).toEqual(['a', 'c']);
    expect(applyFilters(flows, base)).toHaveLength(5);
  });
  it('counts requests per device', () => {
    expect([...clientCounts(flows)]).toEqual([
      ['192.168.1.31', 2],
      ['192.168.1.42', 1],
      ['mac', 1],
    ]);
  });
});

describe('hosts and URLs', () => {
  it('counts hosts, busiest first', () => {
    const flows = [flow({ host: 'b.example.com' }), flow({ host: 'a.example.com' }), flow({ host: 'b.example.com' })];
    expect(hostCounts(flows)).toEqual([
      { host: 'b.example.com', count: 2 },
      { host: 'a.example.com', count: 1 },
    ]);
  });
  it('omits default ports from the URL', () => {
    expect(flowUrl(flow())).toBe('https://api.example.com/api/v1/profile');
    expect(flowUrl(flow({ scheme: 'http', port: 8080 }))).toBe('http://api.example.com:8080/api/v1/profile');
  });
});
