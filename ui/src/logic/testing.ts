import type { FlowSummary, LogLine } from '../types';

export function flow(over: Partial<FlowSummary> = {}): FlowSummary {
  return {
    id: 'f1',
    ts: 1_700_000_000,
    method: 'GET',
    scheme: 'https',
    host: 'api.example.com',
    port: 443,
    path: '/api/v1/profile',
    status: 200,
    error: null,
    duration_ms: 120,
    size: 1200,
    mime: 'application/json',
    request_id: null,
    mock: false,
    fault: null,
    websocket: false,
    ...over,
  };
}

export function line(over: Partial<LogLine> = {}): LogLine {
  return { seq: 1, source: 'device', ts: 1_700_000_000, level: 'I', tag: 'Tag', message: 'hello', ...over };
}
