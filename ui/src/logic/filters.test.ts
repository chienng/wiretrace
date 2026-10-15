import { describe, expect, it } from 'vitest';
import {
  activeChips,
  applyFilters,
  flowUrl,
  hostCounts,
  isBodySearch,
  isServerExpr,
  matchesQuick,
  matchesText,
  quickCounts,
  type FlowFilter,
} from './filters';
import { flow } from './testing';

const base: FlowFilter = { quick: 'all', host: null, text: '', serverIds: null };

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
    expect(quickCounts(flows)).toEqual({ all: 6, errors: 2, slow: 1, mocked: 1, faulted: 1, websocket: 1 });
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
  it('lists host, quick filter and search, marking the preset filter', () => {
    expect(activeChips({ quick: 'all', host: null, text: '' }, '')).toEqual([]);
    expect(activeChips({ quick: 'errors', host: 'api.example.com', text: 'orders' }, '~d example.com')).toEqual([
      { kind: 'host', label: 'host: api.example.com' },
      { kind: 'quick', label: 'Errors 4xx / 5xx' },
      { kind: 'search', label: 'search: orders' },
    ]);
    expect(activeChips({ quick: 'all', host: null, text: ' ~d example.com ' }, '~d example.com')).toEqual([
      { kind: 'default', label: 'preset filter: ~d example.com' },
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
