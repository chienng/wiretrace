// Dev only (`vite serve`): answers /api/* from dev/fixtures/*.json and fakes the update socket.
// Never part of the build. Env: WIRETRACE_FIXTURE_BULK=<n> adds n extra flows,
// WIRETRACE_FIXTURE_MODE=proxy|both switches the setup dialog to proxy or both mode,
// WIRETRACE_FIXTURE_TARGET=ios|android|... sets the session's --target (the device menu),
// WIRETRACE_FIXTURE_403=1 answers every /api request with 403,
// WIRETRACE_FIXTURE_NO_DEVICE=1 turns the report form's screenshots off.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { bulkFlows, liveFlow, liveLines } from './live.mjs';

const dir = path.dirname(fileURLToPath(import.meta.url));
const read = (name) => JSON.parse(fs.readFileSync(path.join(dir, 'fixtures', name), 'utf8'));
const SAMPLE_PNG = fs.readFileSync(path.join(dir, 'fixtures', 'screenshot.png'));
const TS_KEYS = new Set(['ts', 'start', 'request_end', 'response_start', 'response_end', 'started_at']);

function shiftTimes(value, shift) {
  if (Array.isArray(value)) return value.map((v) => shiftTimes(v, shift));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = TS_KEYS.has(k) && typeof v === 'number' ? v + shift : shiftTimes(v, shift);
    }
    return out;
  }
  return value;
}

function parseExpr(expr) {
  const preds = [];
  for (const raw of expr.split('&')) {
    let t = raw.trim();
    let negate = false;
    if (t.startsWith('!')) {
      negate = true;
      t = t.slice(1).trim();
    }
    const m = /^~(m|u|c)\s+(\S.*)$/.exec(t);
    if (!m) throw new Error(`Malformed filter expression near "${raw.trim()}" (fixture parser knows ~m, ~u, ~c)`);
    const [, kind, arg] = m;
    const test =
      kind === 'm'
        ? (f) => f.method.toLowerCase() === arg.toLowerCase()
        : kind === 'u'
          ? (f) => (f.host + f.path).toLowerCase().includes(arg.toLowerCase())
          : (f) => String(f.status) === arg;
    preds.push(negate ? (f) => !test(f) : test);
  }
  return (f) => preds.every((p) => p(f));
}

export default function fixtures() {
  const epoch = Date.now() / 1000;
  const shift = epoch - 12 - read('flows.json')[0].ts;
  const bulkCount = Number(process.env.WIRETRACE_FIXTURE_BULK || 0);
  const state = shiftTimes(read('state.json'), shift);
  if (process.env.WIRETRACE_FIXTURE_MODE === 'proxy') {
    state.mode = 'proxy';
    state.wireguard_conf = null;
  } else if (process.env.WIRETRACE_FIXTURE_MODE === 'both') {
    state.mode = 'both';
  }
  if (process.env.WIRETRACE_FIXTURE_TARGET) state.target = process.env.WIRETRACE_FIXTURE_TARGET;
  const DEVICES = [
    ['ios', 'iPhone'],
    ['android', 'Android phone'],
    ['android-emu', 'Android emulator'],
    ['ios-sim', 'iOS Simulator'],
    ['device', 'Another device'],
  ];
  const deviceList = () =>
    DEVICES.map(([target, label]) => {
      const simOff = target === 'ios-sim' && state.mode === 'wireguard';
      return {
        target,
        label,
        allowed: !simOff,
        why_not: simOff ? 'The iOS Simulator needs the Wi-Fi proxy: stop and start Wiretrace for it.' : null,
        device_logs: target === 'device' ? 'off (--target device has no device log)' : target.startsWith('android') ? 'com.example.app' : 'ExampleApp',
      };
    });
  const baseFlows = [
    ...bulkFlows(bulkCount, epoch),
    ...shiftTimes(read('flows.json'), shift).map((f) => ({ ...f, client: f.client ?? '192.0.2.31' })),
  ];
  const details = shiftTimes(read('flow-details.json'), shift);
  const wsBase = read('ws-messages.json').messages;
  const logs = { device: shiftTimes(read('logs-device.json'), shift), app: shiftTimes(read('logs-app.json'), shift) };
  let reportBusy = false;

  const liveCount = () => Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  const allFlows = () => {
    const out = baseFlows.slice();
    for (let n = 1; n <= liveCount(); n++) out.push(liveFlow(n, epoch));
    const messages = wsMessagesFor('fx-05');
    return out.map((f) =>
      f.id === 'fx-05'
        ? {
            ...f,
            status: 101,
            websocket: true,
            duration_ms: null,
            size: null,
            ws_messages: messages.length,
            ws_closed_by: null,
            ws_close_code: null,
            ws_close_reason: null,
          }
        : {
            ...f,
            ws_messages: f.ws_messages ?? null,
            ws_closed_by: f.ws_closed_by ?? null,
            ws_close_code: f.ws_close_code ?? null,
            ws_close_reason: f.ws_close_reason ?? null,
          },
    );
  };

  function materialize(raw, index, ts) {
    const type = raw.type === 'binary' ? 'binary' : 'text';
    const text = type === 'text' ? String(raw.text ?? '') : null;
    const hex = type === 'binary' ? String(raw.hex ?? '') : null;
    const size = type === 'text' ? text.length : Math.floor(hex.length / 2);
    const preview = type === 'text' ? text.split('\n', 1)[0] : `binary, ${size} B`;
    return {
      index,
      from_client: !!raw.from_client,
      type,
      ts,
      size,
      preview,
      dropped: !!raw.dropped,
      injected: !!raw.injected,
      text,
      hex,
    };
  }

  function wsMessagesFor(id) {
    if (id !== 'fx-05') return null;
    const out = wsBase.map((raw, index) => materialize(raw, index, epoch - 12 + index * 0.2));
    const extra = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
    for (let i = 0; i < extra; i++) {
      const text = JSON.stringify({ type: 'tick', n: i + 1 });
      out.push(materialize({ from_client: i % 2 === 1, type: 'text', text }, out.length, epoch + i));
    }
    return out;
  }

  function wsSummary(message) {
    const { text: _text, hex: _hex, ...row } = message;
    return row;
  }

  function wsAnswer(id, index, url) {
    const all = wsMessagesFor(id);
    if (all === null) {
      const found = allFlows().find((flow) => flow.id === id);
      return found ? [400, { error: 'Not a WebSocket connection' }] : [404, { error: 'unknown flow' }];
    }
    if (index !== undefined) {
      const message = all[Number(index)];
      if (!message) return [400, { error: 'No message at that index' }];
      return [
        200,
        {
          index: message.index,
          from_client: message.from_client,
          type: message.type,
          ts: message.ts,
          size: message.size,
          truncated: false,
          dropped: message.dropped,
          injected: message.injected,
          text: message.text,
          hex: message.hex,
        },
      ];
    }
    const from = Number(url.searchParams.get('from') ?? '0');
    const rawLimit = Number(url.searchParams.get('limit') ?? '500');
    const dir = url.searchParams.get('dir') ?? 'all';
    const q = url.searchParams.get('q') ?? '';
    if (!Number.isInteger(from) || from < 0) return [400, { error: 'from must be a whole number' }];
    if (!Number.isInteger(rawLimit) || rawLimit < 1) return [400, { error: 'limit must be a whole number' }];
    if (dir !== 'all' && dir !== 'sent' && dir !== 'received') return [400, { error: 'dir must be all, sent or received' }];
    if (q.length > 200) return [400, { error: 'Search for at most 200 characters' }];
    const limit = Math.min(500, rawLimit);
    const needle = q.toLowerCase();
    const matched = all.filter((message) => {
      if (dir === 'sent' && !message.from_client) return false;
      if (dir === 'received' && message.from_client) return false;
      if (!needle) return true;
      return message.type === 'text' && String(message.text ?? '').toLowerCase().includes(needle);
    });
    return [200, { total: all.length, matched: matched.length, messages: matched.filter((message) => message.index >= from).slice(0, limit).map(wsSummary) }];
  }
  const allLogs = (source) => {
    const out = logs[source].slice();
    for (let n = 1; n <= liveCount(); n++) {
      const l = liveLines(n, epoch)[source];
      if (l) out.push(l);
    }
    return out;
  };

  function genericDetail(f) {
    const body = (text) => ({ text, size: text.length, truncated: false, binary: false });
    return {
      summary: f,
      request: {
        http_version: 'HTTP/2.0',
        headers: [[':authority', f.host], ['authorization', 'Bearer test-token'], ['x-request-id', f.request_id ?? '']],
        body: body(f.method === 'GET' ? '' : JSON.stringify({ example: true })),
      },
      response:
        f.status === null
          ? null
          : {
              status: f.status,
              reason: 'Example',
              http_version: 'HTTP/2.0',
              headers: [['content-type', 'application/json']],
              body: body(JSON.stringify({ ok: f.status < 400, path: f.path, note: 'generated by the dev fixture' })),
            },
      timing: { start: f.ts, request_end: f.ts + 0.02, response_start: f.ts + (f.duration_ms ?? 0) / 1000 - 0.01, response_end: f.ts + (f.duration_ms ?? 0) / 1000 },
      comment: '',
      mock_path: `${state.mocks_dir}/${f.method}${f.path.split('?')[0]}.json`,
    };
  }

  function route(req, url, body) {
    const p = url.pathname;
    const method = req.method;
    if (process.env.WIRETRACE_FIXTURE_403) return [403, { error: 'forbidden' }];
    if ((method === 'PUT' || method === 'POST' || method === 'DELETE') && req.headers['x-wiretrace'] !== '1') return [403, { error: 'missing header' }];
    if (method === 'GET' && p === '/api/state') return [200, { ...state, flow_count: allFlows().length }];
    if (method === 'GET' && p === '/api/flows') return [200, { flows: allFlows() }];
    if (method === 'GET' && p === '/api/tunnels') return [200, read('tunnels.json')];
    if (method === 'GET' && p === '/api/rules') return [200, read('rules.json')];
    if (method === 'POST' && p === '/api/api-hosts') {
      const host = body?.host;
      if (typeof host !== 'string' || !host) return [400, { error: 'Send {"host": "<host name>"}' }];
      if (!state.api_hosts.includes(host)) state.api_hosts.push(host);
      return [200, { host, applied: true }];
    }
    const wsPath = /^\/api\/flows\/([^/]+)\/messages(?:\/(\d+))?$/.exec(p);
    if (method === 'GET' && wsPath) return wsAnswer(decodeURIComponent(wsPath[1]), wsPath[2], url);
    if (method === 'GET' && p.startsWith('/api/flows/')) {
      const id = decodeURIComponent(p.slice('/api/flows/'.length));
      if (details[id]) return [200, details[id]];
      const f = allFlows().find((x) => x.id === id);
      return f ? [200, genericDetail(f)] : [404, { error: 'unknown flow' }];
    }
    if (method === 'GET' && p === '/api/filter') {
      try {
        const test = parseExpr(url.searchParams.get('expr') ?? '');
        return [200, { ids: allFlows().filter(test).map((f) => f.id) }];
      } catch (e) {
        return [400, { error: e.message }];
      }
    }
    if (method === 'GET' && p === '/api/logs') {
      const source = url.searchParams.get('source');
      return source === 'device' || source === 'app' ? [200, { lines: allLogs(source) }] : [400, { error: 'bad source' }];
    }
    if (method === 'GET' && p === '/api/mocks') return [200, { files: read('mocks.json') }];
    if (method === 'GET' && p === '/api/devices') return [200, { devices: deviceList() }];
    if (method === 'POST' && p === '/api/device') {
      const device = deviceList().find((d) => d.target === body?.target);
      if (!device) return [400, { error: 'Unknown device.' }];
      if (!device.allowed) return [400, { error: device.why_not }];
      if (device.target === state.target) return [204, null];
      return [202, { switching: state.preset, target: device.target }];
    }
    if (method === 'PUT' && p === '/api/faults') {
      const { filter, status, delay_ms: delay, drop } = body ?? {};
      if (typeof filter === 'string' && filter.trim() && !filter.trim().startsWith('~') && !filter.trim().startsWith('!'))
        return [400, { error: 'qa_fault_filter: not a valid filter expression' }];
      if (!Number.isInteger(status) || (status !== 0 && (status < 100 || status > 599)))
        return [400, { error: 'qa_fault_status must be 0 (off) or 100 to 599' }];
      if (!Number.isInteger(delay) || delay < 0) return [400, { error: 'qa_fault_delay_ms must not be negative' }];
      state.faults = { filter: filter.trim(), status, delay_ms: delay, drop: !!drop };
      state.faults_on = !!state.faults.filter && (status > 0 || delay > 0 || !!drop);
      return [200, state.faults];
    }
    if (method === 'POST' && p === '/api/report') {
      if (reportBusy) return [409, { error: 'a report is already being written' }];
      reportBusy = true;
      return [
        'later',
        () => {
          reportBusy = false;
          return [200, { ok: true, zip: 'wiretrace-report-example.zip', requests: allFlows().length, failed: 2, device_lines: allLogs('device').length, app_lines: allLogs('app').length, message: 'Report written (fixture, nothing was created).' }];
        },
      ];
    }
    if (method === 'POST' && p === '/api/report/reveal') return [200, { ok: true }];
    if (method === 'GET' && p === '/api/report/draft') return [200, reportDraft(url.searchParams)];
    if (method === 'GET' && p.startsWith('/api/report/file/')) {
      const kind = p.slice('/api/report/file/'.length);
      const file = reportFiles(url.searchParams)[kind];
      if (!file) return [404, { error: 'Nothing to report with these boxes' }];
      return ['raw', 200, kind === 'zip' ? 'application/zip' : 'text/plain; charset=utf-8', Buffer.from(file.text), file.name];
    }
    if (method === 'POST' && p === '/api/report/screenshot') {
      if (process.env.WIRETRACE_FIXTURE_NO_DEVICE) return [422, { error: 'No Android device connected' }];
      const now = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      const name = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.png`;
      if (screenshots.some((s) => s.name === name)) return [409, { error: 'A screenshot is already being taken' }];
      screenshots.push({ name, size: SAMPLE_PNG.length, time: `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}` });
      return ['later', () => [200, { name, screenshots }]];
    }
    if (p.startsWith('/api/report/screenshot/')) {
      const name = decodeURIComponent(p.slice('/api/report/screenshot/'.length));
      const index = screenshots.findIndex((s) => s.name === name);
      if (index < 0) return [404, { error: 'unknown screenshot' }];
      if (method === 'DELETE') {
        screenshots.splice(index, 1);
        return [200, { screenshots }];
      }
      if (method === 'GET') return ['raw', 200, 'image/png', SAMPLE_PNG, url.searchParams.get('download') ? `example-screenshot-${name.slice(9, 15)}.png` : null];
    }
    return [404, { error: 'not found' }];
  }

  const screenshots = [];

  function reportFiles(params) {
    const include = new Set((params.get('include') ?? '').split(',').filter(Boolean));
    const session = state.session ?? 'example';
    const files = {
      har: { name: `${session}-requests.har`, text: JSON.stringify({ log: { entries: include.has('others') ? allFlows() : allFlows().slice(0, 1) } }) },
    };
    if (include.has('device')) files['device-log'] = { name: `${session}-device-log.txt`, text: allLogs('device').map((l) => `${l.level} ${l.tag} ${l.message}`).join('\n') };
    if (include.has('app')) files['app-log'] = { name: `${session}-app-log.txt`, text: allLogs('app').map((l) => `${l.level} ${l.tag} ${l.message}`).join('\n') };
    files.zip = { name: `${session}-report.zip`, text: 'fixture zip, not a real archive' };
    return files;
  }

  function reportDraft(params) {
    const flowId = params.get('flow');
    const f = flowId ? allFlows().find((x) => x.id === flowId) : null;
    const jira = params.get('format') === 'jira';
    const h = (text) => (jira ? `h2. ${text}` : `## ${text}`);
    const status = f ? (f.status ?? 'no response') : null;
    const description = [
      h('Steps to reproduce'), jira ? '# ' : '1. ', '',
      h('Expected'), '', h('Actual'), '',
      h('Environment'),
      `${jira ? '*' : '-'} Preset: ${state.preset} · Target: ${state.target} · Mode: ${state.mode}`,
      `${jira ? '*' : '-'} Device: Pixel 8 · Android 15 · Wiretrace ${state.version}`, '',
      ...(f ? [h('Failed request'), `${jira ? '*' : '-'} ${f.method} ${f.host}${f.path.split('?')[0]} → ${status} · ${f.duration_ms ?? '—'} ms`, ''] : []),
      'Log lines are masked by pattern only; check them before sharing.',
    ].join('\n');
    const files = reportFiles(params);
    return {
      title: f ? `${f.method} ${f.path.split('?')[0]} ${f.status === null ? 'gets no response' : `returns ${f.status}`}` : `Bug in session ${state.session ?? 'example'}`,
      description,
      format: jira ? 'jira' : 'markdown',
      lead: {
        request: f ? `${f.method} ${f.path.split('?')[0]} → ${status}` : null,
        at: f ? new Date(f.ts * 1000).toTimeString().slice(0, 8) : null,
        device: 'Pixel 8 · Android 15',
        session: state.session ?? 'example',
      },
      counts: { others: allFlows().length - (f ? 1 : 0), device: allLogs('device').length, app: allLogs('app').length },
      masked: { headers: ['Authorization', 'Cookie', 'Set-Cookie'], fields: ['accessToken', 'refreshToken', 'password', 'otp'] },
      files: Object.entries(files).map(([kind, file]) => ({ kind, name: file.name, size: Buffer.byteLength(file.text) })),
      screenshots: params.get('session')
        ? { state: 'off', reason: 'Screenshots are off for a previous session', items: screenshots }
        : process.env.WIRETRACE_FIXTURE_NO_DEVICE
          ? { state: 'off', reason: 'No Android device connected', items: screenshots }
          : { state: 'available', reason: null, items: screenshots },
    };
  }

  return {
    name: 'wiretrace-dev-fixtures',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://localhost');
        if (url.pathname === '/__dev/live.mjs' || url.pathname === '/__dev/fake-socket.js') {
          const file = url.pathname.endsWith('.mjs') ? 'live.mjs' : 'fake-socket.js';
          let text = fs.readFileSync(path.join(dir, file), 'utf8');
          text = text.replace('__EPOCH__', String(epoch));
          res.setHeader('Content-Type', 'text/javascript');
          res.end(text);
          return;
        }
        if (!url.pathname.startsWith('/api/')) return next();
        const chunks = [];
        req.on('data', (c) => chunks.push(c));
        req.on('end', () => {
          let body = null;
          try {
            body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null;
          } catch {
            body = null;
          }
          const send = ([status, payload]) => {
            res.statusCode = status;
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Cache-Control', 'no-store');
            res.end(JSON.stringify(payload));
          };
          const result = route(req, url, body);
          if (result[0] === 'raw') {
            const [, status, type, data, filename] = result;
            res.statusCode = status;
            res.setHeader('Content-Type', type);
            res.setHeader('Cache-Control', 'no-store');
            if (filename) res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
            res.end(data);
          } else if (result[0] === 'later') setTimeout(() => send(result[1]()), 900);
          else send(result);
        });
      });
    },
    transformIndexHtml() {
      return [{ tag: 'script', attrs: { type: 'module', src: '/__dev/fake-socket.js' }, injectTo: 'head-prepend' }];
    },
  };
}
