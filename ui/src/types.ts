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
  /** Who sent it: the device's address, `mac` for this Mac (simulator, emulator), `wireguard` for a tunnel client. */
  client: string | null;
  /** Held at a breakpoint now (spec 022, slice D): its phase and since when (Unix seconds); live session only. */
  paused: PausePhase | null;
  paused_since: number | null;
  /** Changed at a breakpoint before it went on. */
  edited: boolean;
  /** Changed by a Rewrite rule (spec 022, slice E). */
  rewritten: boolean;
  /** Sent elsewhere by a Map remote rule (spec 022, slice G); `host` stays the one the app asked for. */
  mapped: boolean;
  /** Where it went, e.g. `https://staging-api.example.com`; null unless mapped. */
  sent_to: string | null;
}

export type PausePhase = 'request' | 'response';

/** A connection Wiretrace passed through without decrypting (spec 022, slice C): live session only. */
export interface TunnelRow {
  id: string;
  ts: number;
  /** null while it is open. */
  closed_at: number | null;
  client: string | null;
  host: string;
  port: number | null;
  tls: boolean;
  /** `CONNECT` on the Wi-Fi proxy; `TLS`, or `TCP` when it is not TLS, on WireGuard. */
  method: 'CONNECT' | 'TLS' | 'TCP';
  /** The CONNECT request headers the phone sent, `Proxy-Authorization` masked; null on WireGuard. */
  headers: Headers | null;
  answer: string | null;
}

/** A row of Traffic: a request, or an encrypted connection. */
export type TrafficRow = FlowSummary | TunnelRow;

/** A device the Wi-Fi proxy accepts in this session (spec 022): only on the token-protected API. */
export interface ProxyClient {
  address: string;
  /** When it first connected since it was accepted; null until then. */
  seen_at: number | null;
  requests: number;
  /** Failed TLS handshakes with API hosts: it does not trust the certificate yet. */
  tls_failures: number;
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

/** A `presets/*.yaml` file for the preset menu. No hosts: the file does not load. */
export interface PresetInfo {
  name: string;
  api_hosts: string[];
  /** This target collects device logs and the preset names its app. */
  device_logs: boolean;
  app: string | null;
}

/** One row of the device menu: whether this session can switch to it, and its device logs with the preset in use. */
export interface DeviceInfo {
  target: string;
  label: string;
  allowed: boolean;
  why_not: string | null;
  /** The app whose log is collected, or "off (why)". */
  device_logs: string;
}

/** The form's values for a preset file. An empty string or list is left out of the file. `name` is not here. */
export interface PresetFields {
  api_hosts: string[];
  android_package: string;
  ios_process: string;
  request_id_header: string;
  default_filter: string;
  redact_headers: string[];
  redact_fields: string[];
}

/** The form fields a rejected save can name; null when the message is about the whole file. */
export type PresetFieldName = 'name' | keyof PresetFields;

/** One preset as the sheet edits it. `error` is why the file does not load; `revision` guards the save. */
export interface PresetDetail {
  name: string;
  revision: string;
  fields: PresetFields;
  in_use: boolean;
  read_only: boolean;
  error: string | null;
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
  /** The API hosts the running session decrypts; one decrypted from the window is added at once. */
  api_hosts: string[];
  proxy_port: number;
  /** The Wi-Fi proxy accepts only the first device that connects (no `--client`). */
  proxy_pin: boolean;
  /** The address the Wi-Fi proxy accepts in this session; null until a device is pinned, or without pinning. */
  proxy_device: string | null;
  /** Devices the Wi-Fi proxy refused, the most recent first; empty without pinning or while viewing. */
  proxy_waiting: ProxyWaiting[];
  /** The sidebar's devices: accepted ones in order with pinning, the `--client` ones that connected without.
   *  Empty in WireGuard mode and while viewing. */
  proxy_clients: ProxyClient[];
  /** How many devices besides this Mac a session accepts at most. */
  proxy_max: number;
  /** What phones set as their Wi-Fi proxy, `<Mac IP>:<port>`; null in WireGuard mode. */
  proxy_address: string | null;
  /** Started from Wiretrace.app: there is no Terminal, the menu bar is the stop. */
  from_app: boolean;
  wireguard_conf: string | null;
  mac_ip: string | null;
  faults: Faults;
  faults_on: boolean;
  mocks_dir: string;
  flow_count: number;
  /** Requests held at a breakpoint now, and how many may be at once. */
  paused_count: number;
  paused_max: number;
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

/** A device the Wi-Fi proxy refused: when first and last (Unix seconds), and how many times. */
export interface ProxyWaiting {
  address: string;
  first_at: number;
  last_at: number;
  count: number;
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

export type RuleAction = 'mock' | 'status' | 'delay' | 'drop' | 'pause' | 'rewrite' | 'map_remote';
export type TargetScheme = 'https' | 'http';

/** Where a Map remote rule sends matching requests; path and query are kept. */
export interface MapTarget {
  scheme: TargetScheme;
  host: string;
  port: number;
}
export type ApplyMode = 'always' | 'once' | 'every_nth';
export type PauseAt = 'request' | 'response' | 'both';
export type RewriteSide = 'request' | 'response';
export type RewriteKind = 'set_header' | 'add_header' | 'remove_header' | 'set_json' | 'remove_json';

/** One change of a Rewrite rule; a header change has `name`, a JSON change `path`, and a set has `value`. */
export interface RewriteOp {
  on: RewriteSide;
  op: RewriteKind;
  name?: string;
  path?: string;
  value?: string;
}

/** The rules file format (`version: 1`) of addons/qa_tools.py. A key a newer action added is present only
 *  for that action, so a file without such rules still loads in an older Wiretrace. */
export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  match: { method: string; host: string; path: string; body_contains: string };
  action: { type: RuleAction; status: number; body: string; mock_file: string; delay_ms: number; pause_at?: PauseAt; ops?: RewriteOp[];
    target?: MapTarget };
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
  /** Present on the live session's detail; null unless the flow is held at a breakpoint now. */
  breakpoint?: BreakpointInfo | null;
  /** What Rewrite rules did to this request, in order; values of secret headers come masked. */
  changes: ChangeEntry[];
  /** The Map remote step, when one sent this request elsewhere. */
  map_remote?: { rule: string; from: string; to: string } | null;
}

/** What Map local sends (spec 022, slice F); `revision` is the rules revision the dialog loaded. */
export interface MapLocalSave {
  file: string;
  status: number;
  body: string;
  rule: boolean;
  replace: boolean;
  revision: string;
}

export interface ChangeEntry {
  rule: string;
  on: RewriteSide | '';
  op: RewriteKind | string;
  /** The header name or JSON path. */
  target: string;
  value: string | null;
  applied: boolean;
  /** Why it was skipped: `not found`, `body is not JSON`, `body is over 1 MiB`. */
  reason: string;
}

/** A flow held at a breakpoint. `original` is the message as it arrived; `revision` guards an action. */
export interface BreakpointInfo {
  phase: PausePhase;
  since: number;
  revision: number;
  /** Why the body cannot be edited as text: `binary` or `over 1 MiB`; null when it can. */
  body_not_editable: string | null;
  original: { method?: string; path?: string; status?: number; headers: Headers; body: Body };
}

/** What Continue sends: every part of the held message, the body null when it was not edited. */
export type BreakpointEdits =
  | { method: string; path: string; headers: Headers; body: string | null }
  | { status: number; headers: Headers; body: string | null };

export type ServerMessage =
  | { type: 'flows'; flows: FlowSummary[] }
  | { type: 'tunnels'; tunnels: TunnelRow[] }
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

export type ReportFormat = 'markdown' | 'jira';
export type ReportBox = 'others' | 'device' | 'app';
export type ReportFileKind = 'har' | 'device-log' | 'app-log' | 'zip';

export interface ReportFile {
  kind: ReportFileKind;
  name: string;
  size: number;
}

/** A screenshot in the session's screenshots/ folder; `name` is made by the server. */
export interface Screenshot {
  name: string;
  size: number;
  /** HH:MM:SS, when it was taken. */
  time: string;
}

/** `manual` is a real iPhone: the tester takes the screenshot on the phone. */
export interface ScreenshotState {
  state: 'available' | 'off' | 'manual';
  reason: string | null;
  items: Screenshot[];
}

/** The bug report form's draft (spec 012). Every captured value in it is masked by the server. */
export interface ReportDraft {
  title: string;
  description: string;
  format: ReportFormat;
  lead: { request: string | null; at: string | null; device: string | null; session: string };
  counts: Record<ReportBox, number>;
  masked: { headers: string[]; fields: string[] };
  files: ReportFile[];
  screenshots: ScreenshotState;
}
