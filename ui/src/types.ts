export interface FlowSummary {
  id: string;
  ts: number;
  method: string;
  scheme: string;
  host: string;
  port: number;
  path: string;
  status: number | null;
  error: string | null;
  duration_ms: number | null;
  size: number | null;
  mime: string | null;
  request_id: string | null;
  mock: boolean;
  fault: string | null;
  websocket: boolean;
  /** The id of the request this one replays; null for a request from the app. */
  replay_of: string | null;
}

/** A session folder, from its name and meta.json. Counts are null when meta.json does not have them. */
export interface SessionInfo {
  name: string;
  preset: string;
  target: string;
  started_at: number | null;
  ended_at: number | null;
  status: string | null;
  requests: number | null;
  device_lines: number | null;
  app_lines: number | null;
  live: boolean;
}

export interface ViewResult {
  viewing: string | null;
  cut_off?: boolean;
  requests?: number;
}

export interface Faults {
  filter: string;
  status: number;
  delay_ms: number;
  drop: boolean;
}

export interface AppState {
  version: string;
  preset: string;
  target: string;
  mode: string;
  started_at: number;
  session: string;
  device_logs: string | null;
  /** Why device logs are off, when they are. */
  device_logs_off: string | null;
  default_filter: string;
  proxy_port: number;
  wireguard_conf: string | null;
  mac_ip: string | null;
  faults: Faults;
  faults_on: boolean;
  mocks_dir: string;
  flow_count: number;
  rules_on: number;
  /** When a device last connected to mitmproxy, any host (Unix seconds). */
  device_seen_at: number | null;
  /** Failed TLS handshakes of the device with API hosts: the certificate is not trusted yet. */
  tls_failures: number;
  /** The collector's device.status.json; null until it wrote one. */
  device_status: DeviceStatus | null;
  /** The previous session opened read-only, or null while showing the live one. */
  viewing: string | null;
  viewing_cut_off: boolean;
}

/** Model and OS version only: never a serial, a UDID or the device's name. */
export interface DeviceStatus {
  state: 'waiting' | 'streaming' | 'several' | 'stopped' | 'error';
  message: string;
  source: string;
  app: string;
  model: string;
  os: string;
  updated_at: number | null;
}

export type RuleAction = 'mock' | 'status' | 'delay' | 'drop';
export type ApplyMode = 'always' | 'once' | 'every_nth';

/** The rules file format (`version: 1`) of addons/qa_tools.py. */
export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  match: { method: string; host: string; path: string; body_contains: string };
  action: { type: RuleAction; status: number; body: string; mock_file: string; delay_ms: number };
  apply: { mode: ApplyMode; n: number };
}

export interface RuleStats {
  matches: number;
  applied: number;
  last_ts: number | null;
}

export interface RulesPayload {
  revision: string;
  rules: Rule[];
  stats: Record<string, RuleStats>;
  legacy_faults_on: boolean;
  file: string;
  error: string | null;
  api_hosts: string[];
}

export interface RuleTestResult {
  matches: boolean;
  reason: string;
  result: string | null;
}

export type LogSource = 'device' | 'app';

export interface LogLine {
  seq: number;
  source: LogSource;
  ts?: number | null;
  level?: string | null;
  tag?: string | null;
  message: string;
  request_id?: string | null;
  raw?: string;
}

export interface Body {
  text: string | null;
  size: number;
  truncated: boolean;
  binary: boolean;
}

export type Headers = [string, string][];

export interface FlowDetail {
  summary: FlowSummary;
  request: { http_version: string; headers: Headers; body: Body };
  response: {
    status: number;
    reason: string;
    http_version: string;
    headers: Headers;
    body: Body;
  } | null;
  timing: {
    start: number | null;
    request_end: number | null;
    response_start: number | null;
    response_end: number | null;
  };
  comment: string;
  mock_path: string;
}

export type ServerMessage =
  | { type: 'flows'; flows: FlowSummary[] }
  | { type: 'logs'; lines: LogLine[] }
  | { type: 'state'; state: AppState }
  | { type: 'rules'; revision: string; stats: Record<string, RuleStats>; error: string | null }
  | { type: 'device'; status: DeviceStatus };

export interface ReportResult {
  ok: boolean;
  zip: string | null;
  requests: number;
  failed: number;
  device_lines: number;
  app_lines: number;
  message: string;
}

export type Phase = 'connecting' | 'loading' | 'live' | 'reconnecting' | 'forbidden';
