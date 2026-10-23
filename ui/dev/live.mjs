// Deterministic fake traffic shared by the dev server (node) and the fake socket (browser).
const PATHS = [
  ['GET', '/api/v1/home/feed?page=1', 200],
  ['GET', '/api/v1/profile', 200],
  ['POST', '/api/v1/cart/items', 201],
  ['GET', '/api/v1/products/88213', 200],
  ['POST', '/api/v1/orders', 500],
  ['GET', '/api/v1/promotions?region=XX', 200],
  ['POST', '/api/v1/promo/validate', 422],
  ['GET', '/api/v1/cart', 200],
];

export const LIVE_SEQ_BASE = 100;

export function liveFlow(n, epoch, done = true, prefix = 'live') {
  const [method, path, status] = PATHS[n % PATHS.length];
  return {
    id: `${prefix}-${n}`,
    ts: epoch + n,
    method,
    scheme: 'https',
    host: n % 5 === 0 ? 'events.example.com' : 'api.example.com',
    port: 443,
    path,
    status: done ? status : null,
    error: null,
    duration_ms: done ? 40 + ((n * 37) % 1500) : null,
    size: done ? 200 + ((n * 131) % 9000) : null,
    mime: done ? 'application/json' : null,
    request_id: `req-${prefix}-${n}`,
    client: n % 4 === 0 ? '192.0.2.32' : '192.0.2.31',
    mock: n % 11 === 0,
    fault: n % 13 === 0 ? 'status 500' : null,
    websocket: false,
  };
}

export function liveLines(n, epoch) {
  const flow = liveFlow(n, epoch);
  const device = {
    seq: LIVE_SEQ_BASE + n,
    source: 'device',
    ts: epoch + n + 0.05,
    level: n % 7 === 0 ? 'E' : n % 3 === 0 ? 'W' : 'I',
    tag: 'LiveFixture',
    message: `${flow.method} ${flow.path} -> ${flow.status} req=${flow.request_id}`,
    request_id: null,
  };
  const app =
    n % 3 === 0
      ? {
          seq: LIVE_SEQ_BASE + n,
          source: 'app',
          ts: epoch + n + 0.1,
          level: 'I',
          tag: 'Net',
          message: `response ${flow.status}`,
          request_id: flow.request_id,
        }
      : null;
  return { device, app };
}

export function bulkFlows(count, epoch) {
  const out = [];
  for (let i = 1; i <= count; i++) out.push(liveFlow(i, epoch - count - 10, true, 'bulk'));
  return out;
}
