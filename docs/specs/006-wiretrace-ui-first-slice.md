# Spec: Wiretrace UI, first slice (traffic, logs, setup, faults, report)

- **Date**: 2026-10-14
- **Risk**: high — a local web server that shows captured traffic (tokens included), the
  phone's WireGuard private key, and can change faults. Needs a UI, code, security and
  privacy review and a runtime check.
- **Repo**: wiretrace
- **Status**: implemented
- **Branch**: `main` (as specs 003 to 005)
- **Related**: [`PLAN.md`](../../PLAN.md) §8 Phase 2 (U2–U5, U7, U8 and U10 in part),
  §5 (React + TypeScript; "Local WebSocket + REST (FastAPI or mitmproxy's own server)");
  [`mockups/`](../../mockups/README.md) screens 1–5; spec 002 (launcher), 003 (fault options,
  flow comments), 004 (log files), 005 (`./wiretrace report`, which this UI calls)

## Goal

`./wiretrace start --preset <name> --ui wiretrace` opens Wiretrace's own window in the browser
instead of mitmweb: the traffic list, request details and the app's logs on one screen, as
in mockup screen 1, with the setup QR code, faults and the bug report one click away. QA
can run and test it today; the Tauri app (U1) later wraps the same page.

## Acceptance criteria

- [ ] `--ui wiretrace` starts mitmdump with the UI addon and opens
      `http://127.0.0.1:8081/?token=…` in the default browser; the Terminal prints the same
      link. `--ui mitmweb` (the default) and `--no-ui` behave exactly as in 0.5.0.
- [ ] Traffic list (screen 1): one row per HTTP request to the preset's hosts, live, with
      time, method, status (colour by class), path, duration, size, and `MOCK` / `FAULT` /
      `SLOW` badges. `qa-logs.internal` flows are not listed. Errors are red. 10,000 rows
      scroll smoothly.
- [ ] Sidebar: quick filters with live counts — All, Errors 4xx/5xx (including no
      response), Slow > 1 s, Mocked, Faulted, WebSocket — and the preset's hosts with counts.
      The search box filters by text on method, URL and status; input starting with `~` or
      `!` is a mitmproxy filter expression evaluated by the server, and an invalid one shows
      the parser's message. The preset's `default_filter` is the initial search.
- [ ] Detail panel: method, path, status, host, duration, request ID; tabs Request,
      Response (pretty JSON with folding, else text; binary as a size note), Headers,
      Timing, Logs (log lines whose `request_id` or message contains the request ID).
      **Copy cURL** and **Copy as mock** (copies the response body and shows the file path
      to create, `mocks/<preset>/<METHOD>/<path>.json`).
- [ ] Log strip (bottom of screen 1) and Logs view (screen 2, without the timeline and the
      device picker): Device logs / App logs / Crashes tabs with counts; level chips with
      counts; text filter; auto-scroll; lines that carry the selected request's ID are
      highlighted; selecting a line shows its detail and linked request.
- [ ] Title bar: Traffic / Logs switch, recording time, Pause (freezes the list; "N new"),
      Clear (hides what is listed now), preset, device-log state, Faults (active count),
      Setup, Report bug.
- [ ] Setup: in WireGuard mode, the QR code and the configuration text for the WireGuard
      app; in proxy mode, `<Mac IP>:<port>`; the certificate steps; "Traffic received" turns
      green at the first request.
- [ ] Faults: edit the four `qa_fault_*` options; an invalid value shows mitmproxy's message
      and changes nothing; the read-only list of mock files.
- [ ] Report bug: runs spec 005's report on the current session (flows saved so far), shows
      the zip path, the counts and the "check log lines" note, and **Show in Finder**.
- [ ] Without the link's token, from another host name, or from another origin, every page,
      API call and WebSocket is refused. Nothing listens outside `127.0.0.1`.
- [ ] Reloading the page, or the WebSocket dropping, loses nothing: the page reconnects and
      reloads the state.

## Approach

### One process: the UI is a mitmproxy addon

`addons/wiretrace_ui.py` runs a Tornado application (already a mitmproxy dependency) on
mitmproxy's asyncio loop: same thread as every hook, so flows are read without locks, and
fault options are set with `ctx.options.update`. Rejected: a FastAPI process reading
`flows.mitm` (seconds of lag, a second process to supervise, no live hook data); making
mitmweb's own frontend do this (a fork of a large React app we would have to keep in step
with every mitmproxy release); Tauri now (signing, notarization and a sidecar are a separate
step that needs IT and an Apple account; the same page is wrapped later).

### Frontend: React + TypeScript, built with Vite, output committed

`ui/` (sources, `package.json`, `vite.config.ts`, `tsconfig.json`) builds into `ui/dist/`,
which is **committed**: QA Macs have no Node, and `scripts/build-release.sh` packs the git
tree. `ui/node_modules/` is gitignored. Dependencies: `react`, `react-dom`, `qrcode` (QR
canvas); dev: `typescript`, `vite`, `@vitejs/plugin-react`, `vitest`. No UI kit: colours,
spacing, radius and type come from the CSS variables and classes of
`mockups/wiretrace-mockup.html` (the UI review checks this). Never `dangerouslySetInnerHTML`; the JSON
viewer builds elements.

### Addon options (set by the launcher)

| Option | Type | Default | Meaning |
|---|---|---|---|
| `qa_ui_port` | int | 8081 | Port on `127.0.0.1`. |
| `qa_ui_session_dir` | str | "" | Session folder: `meta.json`, both log files, the report. |
| `qa_ui_default_filter` | str | "" | Initial search. |
| `qa_ui_open_browser` | bool | true | Open the link at start. |

The token is `secrets.token_urlsafe(32)`, made in the addon at `running`, never an option
(options are visible in `ps`) and never written to a file.

### Security (invariants 1–4)

- Listen on `127.0.0.1` only.
- **Host check** on every request and the WebSocket upgrade: `Host` must be
  `127.0.0.1:<port>` or `localhost:<port>`, else 403 (DNS rebinding).
- **Token**: `GET /?token=T` with `hmac.compare_digest` → set cookie
  `wiretrace_ui=T; HttpOnly; SameSite=Strict; Path=/` and redirect to `/`. Every other request
  needs that cookie, else 403 with a page saying "Open the link printed in the Terminal."
- **WebSocket**: cookie and `Origin` equal to `http://127.0.0.1:<port>` or
  `http://localhost:<port>`.
- **Mutations** (`PUT`, `POST`): also need the header `X-Wiretrace: 1`.
- Headers on every response: `Content-Security-Policy: default-src 'self'; img-src 'self'
  data:; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:<port>
  ws://localhost:<port>; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`; API responses `Cache-Control: no-store`.
- The addon prints nothing but the link and errors; no flow content, header or log line is
  printed or logged (the privacy review checks this).

### API (JSON; `ts` values are Unix seconds, floats)

- `GET /api/state` →
  `{version, preset, target, mode, started_at, session, device_logs, default_filter,
  proxy_port, wireguard_conf|null, mac_ip|null, faults: {filter, status, delay_ms, drop},
  faults_on, mocks_dir, flow_count}`. `session` is the folder name, never a path.
  `wireguard_conf` comes from the WireGuard server instance's `client_conf()` (via
  `ctx.master.addons.get("proxyserver").servers`), only in WireGuard mode.
- `GET /api/flows` → `{flows: [Summary…]}`, oldest first.
  `Summary = {id, ts, method, scheme, host, port, path, status|null, error|null,
  duration_ms|null, size|null, mime|null, request_id|null, mock: bool, fault: string|null,
  websocket: bool}`. `path` includes the query. `mock` / `fault` come from the flow comment
  parts (`mock: …`, `fault: …`, spec 003); `request_id` from its `request-id:` part.
- `GET /api/flows/<id>` → `{summary, request: {http_version, headers: [[k,v]…], body},
  response: {status, reason, http_version, headers, body}|null, timing: {start,
  request_end, response_start, response_end}, comment, mock_path}`.
  `body = {text|null, size, truncated: bool, binary: bool}`: text up to 2 MiB, decoded
  (`get_text(strict=False)`); binary bodies have `text: null`. `mock_path` =
  `<mocks_dir relative to the wiretrace folder>/<METHOD><path without query>.json`. 404 if the
  flow is unknown or dropped from memory.
- `GET /api/filter?expr=<expr>` → `{ids: [...]}` of the flows in memory that match, or 400
  `{error}` with the parser's message.
- `GET /api/logs?source=device|app` → `{lines: [Line…]}`, oldest first.
  `Line = {seq, source, ts|null, level|null, tag|null, message, request_id|null, raw?}`
  from the log files; a line that is not JSON has only `seq`, `source`, `message` (the raw
  text).
- `GET /api/mocks` → `{files: ["GET/api/v1/profile.json", …]}` (relative to `mocks_dir`).
- `PUT /api/faults` `{filter, status, delay_ms, drop}` → `ctx.options.update(...)`; 200 with
  the new `faults`, or 400 `{error}` with the `OptionsError` message and nothing changed.
- `POST /api/report` → runs `cli.report.run` for the session folder in a worker thread;
  `{ok, zip|null, requests, failed, device_lines, app_lines, message}`. `zip` is the file
  name only. One report at a time (409 while running).
- `POST /api/report/reveal` → `open -R <last report zip>`; never takes a path from the client.
- `GET /api/updates` (WebSocket) → server messages, batched every 100 ms:
  `{type: "flows", flows: [Summary…]}` (new or changed), `{type: "logs", lines: [Line…]}`,
  `{type: "state", state: {...}}` (after a fault change or a report). No client messages.

### Data in memory

- Flows: an insertion-ordered dict `id → flow`, capped at 10,000 (oldest dropped from the
  UI only; `flows.mitm` still has them). Updated in `request`, `response`, `error`,
  `websocket_end`; HTTP flows only; host `qa-logs.internal` skipped.
- Logs: a tailer task polls both log files every 250 ms from the last offset, keeps a
  partial last line until its newline, and keeps the last 50,000 lines per source.
  A file that does not exist yet is retried. `seq` increases per source.

### Launcher (`cli/start.py`, `cli/__main__.py`)

- `--ui {mitmweb,wiretrace}` (default `mitmweb`); `--no-ui` unchanged and conflicts with `--ui`.
- `wiretrace`: mitmdump with `-s addons/wiretrace_ui.py` after the two existing addons,
  `--set flow_detail=0`, the four `qa_ui_*` options, no `view_filter` / `dumper_filter`.
  Port check label `Wiretrace UI` (TCP 127.0.0.1:8081). Banner: `UI: Wiretrace (link below)`,
  `Faults: Wiretrace > Faults`. `meta.json` `ui: "wiretrace"`.
- `cli/__init__.py`: version `0.6.0`.

## Design that needs care

### Connection lifecycle (frontend)

`CONNECTING → LOADING → LIVE → (dropped) RECONNECTING → LOADING → LIVE`.
On open: fetch `/api/state`, `/api/flows`, both `/api/logs` **after** the socket is open,
apply buffered socket messages whose items are newer (flows by `id`, replace; logs by
`seq`, skip `seq` ≤ last loaded). Reconnect with backoff 0.5 s → 5 s. A 403 → show
"Open the link printed in the Terminal" and stop retrying.

### Invariants

1. No response leaves the server without the token cookie and a valid `Host`, except the
   403 page and the `/?token=` exchange.
2. The token exists only in memory, the cookie, and the printed link.
3. A mutation needs the cookie, `X-Wiretrace: 1`, and a valid `Host`; a WebSocket needs the
   cookie, a valid `Host` and `Origin`.
4. The report reveal opens only the file the last report wrote.
5. A fault change is all-or-nothing (`ctx.options.update` with the four values at once).
6. The UI's caps (10,000 flows, 50,000 lines per source) never change what is saved.
7. One flow appears once in the list, whatever the order of socket messages and the
   initial load (merge by `id`).

### Tests derived

- Python (`tests/test_wiretrace_ui.py`, Tornado `AsyncHTTPTestCase` or an app factory driven
  from pytest): token exchange and cookie flags; missing / wrong cookie → 403 on page, API,
  assets and WebSocket; wrong `Host` → 403 even with the cookie; wrong `Origin` on the
  WebSocket; mutation without `X-Wiretrace` → 403; CSP and nosniff headers; summaries from
  `tflow` (status, error, duration, mock / fault / request ID from comments, websocket,
  receiver host skipped); detail bodies (JSON, truncated at 2 MiB, binary); unknown id →
  404; filter endpoint with a valid and an invalid expression; faults update valid /
  invalid (nothing changed); flow cap; log tailer (partial line, file created later,
  non-JSON line, cap); report endpoint (monkeypatched `cli.report.run`, 409 while
  running); reveal uses only the stored path (monkeypatched `subprocess`); WebSocket batch
  delivers a new flow.
- Launcher (`tests/test_start.py`): `--ui wiretrace` command and options; no token on the
  command line; `--ui` with `--no-ui` is an error; port label; banner lines.
- Frontend (`ui/src/**/*.test.ts`, vitest): text and quick filters, counts, host counts,
  cURL builder (quoting), mock path, merge of initial load and socket messages (invariant
  7), log level counts, request-ID highlight, virtual-list window math.

## Files expected to change

- `addons/wiretrace_ui.py` — new. Options, server, auth, API, WebSocket, flow store, log tailer.
- `cli/start.py`, `cli/__main__.py` — `--ui`; command, banner, port label, meta.
- `cli/__init__.py` — `0.6.0`.
- `ui/` — new: `package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`,
  `index.html`, `src/` (api client, store, components), `dist/` (committed build).
- `.gitignore` — `ui/node_modules/`.
- `tests/test_wiretrace_ui.py` — new; `tests/test_start.py` — updated.
- `docs/user-guide.md` — a section "Wiretrace window (preview)": how to start it, what each
  area does, the link and token, mitmweb still the default; troubleshooting rows.
- `README.md` — one line for `--ui wiretrace`.

## Out of scope

- Tauri app, signing, menu bar (U1); a device picker; previous sessions and saved filters;
  the log timeline; replay and compare; the rules editor beyond the four fault options
  (U8: once, every Nth call); YouTrack (U10, F13); writing mock files from the UI;
  intercept / breakpoints; making `--ui wiretrace` the default.

## Manual test

1. `./wiretrace start --preset <name> --target android --ui wiretrace`: the browser opens the
   Wiretrace window; Setup shows the QR; connect the phone; requests appear live.
2. Click a 4xx/5xx row: Response shows pretty JSON; Headers, Timing, Copy cURL work.
3. Faults: filter `~u /api/v1/orders`, status 500: the next request gets `FAULT`; clear it.
4. Logs: device lines stream; the selected request's lines are highlighted.
5. Report bug → zip path; Show in Finder.
6. Copy the link into a private window without the token: refused.

## Automated tests

`.venv/bin/python -m pytest` and `npm --prefix ui test`, plus `npm --prefix ui run build`
(must reproduce the committed `ui/dist/`).

## Errata

Decided while building the backend:

- The report endpoint calls a new `cli.report.create(folder, presets_dir, now)`, which returns
  the zip and counts or raises `Failure`; `run` prints from it. A failed report is a 200 with
  `ok: false` and the message.
- `start.run`, `build_command`, `banner` and `needed_ports` take `ui` as `bool | str`
  (`True` = mitmweb, `False` = none, `"wiretrace"`) and a `ui_port`, so tests avoid 8081.
- A wrong `?token=` is refused even with a valid cookie. A WebSocket without `Origin` is refused.
- `websocket_start` is tracked too, so the WebSocket badge appears early.
- If the UI port cannot be bound, the addon logs the error and shuts mitmproxy down.
- JSON log lines also carry `raw` (the original line) for Copy.

Changed after review, before the first commit:

- Security review: the detail body is decoded at most 2 MiB + 1 byte for gzip, deflate (zlib or raw),
  br and zstd; the rest is counted in 1 MiB steps up to 64 MiB and not kept, so a compression
  bomb cannot exhaust memory. Past 64 MiB the size shown is a lower bound. A body that does not
  decode is shown as it travelled.
- Code review: the size of a truncated raw-deflate body is counted with the same raw fallback.

Known limits (found in the runtime check): masking works on field names, so a URL with secrets inside another
string value of a JSON body is not masked in the report. The Terminal still prints mitmproxy's
connection lines (`client connect`, `server connect <host>`) in this mode.
