import type { FlowSummary, LogLine, TunnelRow } from '../types';

export function tunnel(over: Partial<TunnelRow> = {}): TunnelRow {
  return {
    id: 'tunnel-1',
    ts: 1_700_000_000,
    closed_at: null,
    client: null,
    host: 'cdn.example.net',
    port: 443,
    tls: true,
    method: 'CONNECT',
    headers: [['Host', 'cdn.example.net:443']],
    answer: 'HTTP/1.1 200 Connection established',
    ...over,
  };
}

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
    ws_messages: null,
    ws_closed_by: null,
    ws_close_code: null,
    ws_close_reason: null,
    replay_of: null,
    client: null,
    paused: null,
    paused_since: null,
    edited: false,
    rewritten: false,
    mapped: false,
    sent_to: null,
    ...over,
  };
}

export function line(over: Partial<LogLine> = {}): LogLine {
  return { seq: 1, source: 'device', ts: 1_700_000_000, level: 'I', tag: 'Tag', message: 'hello', ...over };
}
