# Spec: the Wiretrace window like mockup screens 1–4

- **Date**: 2026-10-15
- **Risk**: high — it extends spec 006's local server, which shows captured traffic (tokens
  included) and the phone's WireGuard private key, with new mutations: writing a rules file,
  replaying requests, opening other sessions from disk. Needs a UI, code, security and privacy
  review and a runtime check.
- **Repo**: wiretrace
- **Status**: approved
- **Branch**: `feature/ui-mockups`
- **Related**: [`mockups/`](../../mockups/README.md) screens 1–4; [`PLAN.md`](../../PLAN.md) §8
  U2–U8; spec 003 (fault options, mock files, flow comments), spec 004 (collectors, log files),
  spec 005 (report), spec 006 (the window, its server, security model and API).

## Goal

The Wiretrace window (`--ui wiretrace`) matches mockup screens 1–4 closely enough that the
README can call them built: the main window with previous sessions, saved filters, body search,
replay and compare; the logs view with device status, a timeline and the line detail; a
five-step device setup wizard; and a rules editor that replaces the four-option Faults dialog.
Screens 5 (YouTrack/Jira) and 6 (menu-bar app) are separate specs.

Built in four slices, in this order, one commit each with its tests, so each slice can be
reviewed and used on its own: **A** rules (screen 4), **B** setup wizard (screen 3),
**C** device status and logs view (screen 2), **D** main window (screen 1).

## Decisions (approved 2026-10-15 as written)

1. **Device picker** (screen 2) shows the state of the source being collected and lists the
   other sources with the command to use them. It does **not** switch the collector at run time.
   Rejected for now: restarting the collector from the window (a second owner of the
   collector's process group besides the launcher; spec 002/004 lifecycle work).
2. **"Once per app launch"** (screen 4) becomes **"Once"**: the rule fires on its first match and
   then waits until it is re-armed (*Re-arm* button, saving the rule, switching it off and on, or
   a new session). Rejected: detecting app launches (Android has PID changes, iOS and app logs
   have no reliable signal).
3. **Rules file**: `rules/<preset>.json` in the wiretrace folder, beside `presets/` and `mocks/`.
   Rejected: a `rules:` key in the preset YAML (writing YAML from the window would drop the
   user's comments).
4. **The four `qa_fault_*` options stay** for mitmweb and `--no-ui` (user guide *Make requests
   fail or slow*). The window's Faults dialog and `PUT /api/faults` are removed; Rules replace
   them. If a `qa_fault_*` option is on, the Rules window says so.
5. **Replay** is allowed for every method; anything but `GET`, `HEAD` and `OPTIONS` asks for
   confirmation first, because it repeats a side effect on the backend.
6. **Saved filters** live in the browser (`localStorage`, per preset), not on disk.

## Acceptance criteria

### A. Rules (screen 4)

- [ ] **Rules** in the title bar (with the number of enabled rules) opens the Rules view:
      a filterable list (text, and type: all / mock / status / delay / drop) with an on/off
      switch and a one-line summary per rule, and the editor on the right.
- [ ] A rule has a name, enabled, a match (method or ANY; host: one of the preset's API hosts,
      or any; path with `*` wildcards; optional "body contains"), an action (mock response,
      status code, delay, drop connection), an extra delay, and apply (always, once, every Nth).
      Mock response: a status (default 200) and a body from a mock file of the preset or typed in.
      Status code: 100–599 and an optional body (default `{"error": "injected by Wiretrace"}`).
- [ ] *Save rule* takes effect for the next request, without a restart. An invalid rule shows
      what is wrong next to the field and changes nothing. Rules are applied in list order;
      the first enabled match wins; then the `qa_fault_*` options; then mock files (spec 003).
- [ ] Each rule shows "Matched N times · applied M · last match HH:MM:SS" for this session.
      *Re-arm* resets the counters of a once / every-Nth rule.
- [ ] *Test against last request* (or the request selected in Traffic) says whether the draft
      rule would match, and if so what the app would get, without changing counters or traffic.
- [ ] A request changed by a rule carries the flow comment part `rule: <name>` plus the existing
      `fault: …` or `mock: …` part, so the list shows FAULT / MOCK badges and the report counts it.
- [ ] *Export…* downloads the rules as JSON; *Import…* reads such a file and either adds its
      rules or replaces all of them (the user picks), with the same validation.
- [ ] *New rule* from a selected request (in Traffic) pre-fills method, host and path.
- [ ] Rules also work with `--ui mitmweb` and `--no-ui`: the launcher always passes the file.
      Editing the file by hand while Wiretrace runs takes effect within a second.

### B. Setup wizard (screen 3)

- [ ] *Setup* opens a five-step wizard with a step rail: **Choose device** (iPhone, Android,
      iOS Simulator, Android emulator; preselected from `--target`), **Connect tunnel**,
      **Install certificate**, **Verify traffic**, **Device logs** (optional, USB). *Back* and
      *Next* move between steps; every step can be opened from the rail.
- [ ] Connect, WireGuard mode: the QR code and the steps for the chosen device type, and
      "Mac address `<ip>` · UDP 51820". Android emulator: the configuration with
      `Endpoint = 10.0.2.2:51820` (QR and text). "Waiting for the device…" turns to
      "Connected" at the first connection from the device, **any** host, not only API hosts.
      After 30 s without one, a hint about guest Wi-Fi networks that block device-to-device traffic.
- [ ] Connect, proxy mode: `<Mac IP>:<port>` and the Wi-Fi proxy steps for the device type.
      iOS Simulator in WireGuard mode, and *Use Wi-Fi proxy instead*: the exact command to
      restart in proxy mode (no switch at run time).
- [ ] Install certificate: the steps for the device type. iPhone and Android download it from
      `http://mitm.it`, which now loads through `./wiretrace start` (it does not today). iOS
      Simulator: the `xcrun simctl keychain booted add-root-cert …` command; Android emulator:
      the `adb push` command; each with a copy button.
- [ ] Verify traffic: green at the first request to an API host. If the device's TLS handshakes
      with an API host fail, it says the certificate is not trusted yet and links back to step 3.
- [ ] Device logs: the device-log state from slice C, or why it is off.
- [ ] The old Setup dialog is gone.

### C. Device status and logs view (screen 2)

- [ ] The collector writes `device.status.json` in the session folder on every state change:
      state, a short message, the source, the app, and the device **model and OS version** only
      (never a serial, UDID or device name). The window shows it as a pill in the title bar
      (for example "Pixel 8 · Android 15 · USB", green while streaming) and in the device picker.
- [ ] Device picker: the active source with its state; the other sources (Android `adb logcat`,
      iPhone `pymobiledevice3`, iOS Simulator `simctl`) each with the `--target` that collects
      it; App logs from the QA build with the line count; a hint when no device is listed.
- [ ] Toolbar: *Pause logs* (with "N new"), *Clear* (hides, keeps the files), *Export .txt*
      (the lines shown now, labelled "not masked"), *Auto-scroll*; a tag filter; "Only lines
      linked to requests".
- [ ] Timeline above the list: requests as dots coloured by status class, log lines as ticks
      (errors red), crashes marked; the part shown in the list is shaded; a click scrolls the
      list to that time. 50,000 lines and 10,000 requests draw without lag.
- [ ] A crash's stack trace is folded after four lines ("Show N more lines").
- [ ] Line detail: *Copy line*, *Copy ±50 lines*, the linked request with *Open in Traffic*,
      the requests within ±5 s of the line, *Show only this tag*.
- [ ] The Logs tab in the title bar shows the crash count.

### D. Main window (screen 1)

- [ ] Sidebar *Previous sessions* (with a count) lists the session folders (start, preset,
      target, request and log counts from `meta.json`). Opening one shows its traffic and logs
      **read-only**, with "Viewing <session> · Back to live"; capture of the live session goes on.
      *Report bug* works on the viewed session. Rules, replay and setup are off while viewing.
- [ ] Sidebar *Saved filters*: save the current search under a name, apply, rename, delete;
      per preset, kept by the browser.
- [ ] Search: plain text of three or more characters also matches header names and values
      and request and response bodies (server side, case-insensitive); `~` / `!` expressions
      work as today. Active filters (host, quick filter, search, the preset's default filter)
      show as removable chips.
- [ ] Detail: *Replay* (confirmation for methods with side effects; the replayed request
      appears as a new row with a REPLAY badge), *Compare…* (pick another request, by default
      the previous one with the same method and path; side by side status, headers, and the
      JSON body as a key-level diff, or a line diff for other text), *Report*, and the
      Logs tab with its line count.

### All slices

- [ ] Spec 006's security invariants hold for every new endpoint (token cookie, Host check,
      `X-Wiretrace: 1` on mutations, Origin on the WebSocket, CSP). No new endpoint takes a file
      path from the client.
- [ ] Nothing new is printed or logged with flow content, log content, device identifiers or
      rule bodies (privacy review).
- [ ] Colours, spacing, radius and type come from `ui/src/styles.css` variables, which follow
      the mockup (UI review). No UI library is added.
- [ ] Version 0.8.0. User guide and README updated (the README's Design table marks screens
      1–4 as built, with the decisions above as the remaining differences).

## Approach

### A. Rules engine in `qa_tools`, rules file written by the window

The engine lives in `addons/qa_tools.py`, in the same `request` hook as faults and mocks, so
there is one place that decides what a request gets, and it works with every UI. New option
`qa_rules_file` (absolute path, like `qa_mocks_dir`). `qa_tools` keeps its rule "never writes
files": it reads the file at `configure` and re-reads it when its mtime changes, checked at most
once a second from `request`. The window writes the file (atomic `os.replace`) and then calls the
live `QATools.reload_rules()` (found with `ctx.master.addons.get("qatools")`), so a save applies at
once. Validation is one function, `parse_rules(data, api_hosts, mocks_dir) -> Rules | error`, in
`qa_tools`; the window imports the module for it (pure functions; the live instance is always the
one from the addon chain). Value types are `NamedTuple`: a `@dataclass` defined in a `-s`
script fails when mitmproxy loads it.

Rejected: rules as more mitmproxy options (lists of structured values do not fit options, and
options are visible in `ps`); an engine inside the window addon (would not work with mitmweb).

File format (`version: 1`):

```json
{"version": 1, "rules": [{
  "id": "k3f9a2", "name": "Order creation fails", "enabled": true,
  "match": {"method": "POST", "host": "", "path": "/api/v1/orders", "body_contains": ""},
  "action": {"type": "status", "status": 500, "body": "{…}", "mock_file": "", "delay_ms": 800},
  "apply": {"mode": "once", "n": 0}
}]}
```

Limits: 200 rules; name ≤ 80 chars; path ≤ 512; `body_contains` ≤ 256; body ≤ 1 MiB; extra
delay 0–120,000 ms; `n` 2–1,000 for every-Nth; `mock_file` must resolve inside `mocks_dir`
(same check as `mock_file()`); `host` empty or one of the preset's API hosts; `id` 6–32 of
`[a-z0-9]`, unique. Path: `*` matches any characters including `/`; the query is ignored unless
the pattern contains `?`. "Body contains": case-sensitive, on the first 1 MiB of the decoded
request body.

### B. Setup state from mitmproxy hooks

The window addon adds `client_connected` (sets `device_seen_at`; nothing about the peer is kept)
and `tls_failed_client` for API hosts (counts `tls_failures`), exposed in `/api/state`. The
launcher adds `--allow-hosts ^mitm\.it(:\d+)?$` (as it does for `qa-logs.internal`) so
mitmproxy's own certificate page loads through the tunnel; the runtime check must show it
loading on a device. The emulator configuration is the WireGuard configuration with its `Endpoint` line
replaced, done in the page.

### C. Device status file

`collectors.Status.say` also writes `device.status.json` (tmp + `os.replace`):
`{state, message, source, app, model, os, updated_at}`, `state` one of `waiting`, `streaming`,
`several`, `stopped`, `error`. Model and OS: Android `getprop ro.product.model` /
`ro.build.version.release`; iPhone `ProductType` / `ProductVersion` from `usbmux list`;
Simulator the booted device's type name and runtime from `simctl list`. The launcher passes the
path. The window's log tailer polls it with the log files. Rejected: parsing the collector's
Terminal lines (they go to the user's Terminal, not to mitmproxy).

### D. Previous sessions, search, replay

- A second, read-only store in the window addon holds one opened session: `flows.mitm` read in a
  worker thread with `io.FlowReader` (newest 10,000 kept, a cut-off file read as far as it goes),
  and both log files. Opening another session or *Back to live* drops it. Read endpoints take
  `?session=<name>`; the name must match `session.NAME` and be in `session.list_sessions()`;
  it is never joined to a path from the client.
- Body search runs in the addon over the flows in memory, with the bounded decoder spec 006 added
  for the detail view (2 MiB per body), in chunks that yield to the event loop.
- Replay calls mitmproxy's `replay.client` command on a copy of the flow; the copy gets the
  comment part `replay: <original id>`. Rules and faults apply to it like to any request.
- Compare and saved filters are page-only.

## API changes (spec 006 rules apply to all)

| Method and path | Body / query | Result |
|---|---|---|
| `GET /api/rules` | | `{revision, rules, stats: {id: {matches, applied, last_ts}}, legacy_faults_on, file}` (`file` relative to the wiretrace folder) |
| `PUT /api/rules` | `{revision, rules}` | writes and reloads; 200 like GET; 400 `{error, index, field}`, nothing changed; 409 if `revision` is stale |
| `POST /api/rules/test` | `{rule, flow_id}` | `{matches, reason, result}`; counters untouched |
| `POST /api/rules/<id>/rearm` | | 200 like GET |
| `GET /api/sessions` | | `{sessions: [{name, preset, target, started_at, requests, device_lines, app_lines, live}]}` |
| `POST /api/view` | `{session}` or `{session: null}` | opens a session read-only, or back to live; `{viewing}` |
| `GET /api/flows`, `/api/flows/<id>`, `/api/logs`, `/api/filter` | `?session=<name>` optional | as today, for the opened session |
| `GET /api/search` | `?q=&session=` | `{ids}` |
| `POST /api/flows/<id>/replay` | | `{id}` of the new flow; 409 while viewing a session |
| `POST /api/report` | `{session}` optional | as today, for that session |
| `PUT /api/faults` | | **removed** |
| `/api/state` | | adds `device_status`, `device_seen_at`, `tls_failures`, `rules_on`, `viewing` |
| WebSocket | | adds `{type: "rules", stats}` (batched) and `{type: "device", status}` |

## Design that needs care

### Rule evaluation (in `request`, on the event loop)

Per request to an API host: take the current `Rules` snapshot (replaced whole on reload, never
edited). For each enabled rule in order: if it matches, `matches += 1`, `last_ts = now`; then
decide by apply mode: `always` → apply; `once` → apply if `applied == 0`; `every_nth` → apply if
`matches % n == 0`. The first rule that **applies** ends the search (a matching rule that does not
apply this time lets the next rule be tried). Apply: extra delay (with the existing "client left"
check), then the action. If no rule applied: `qa_fault_*`, then mock files, as today.

Counters are kept per `(rule id, rule content hash)` in memory: saving a rule with new content
resets its counters, re-arm resets them, a session starts at zero. They are never written.

### Invariants

1. A request sees exactly one rules snapshot; a reload during its delay does not change what it
   gets.
2. A rejected `PUT /api/rules` changes neither the file nor the engine; a file edited by hand that
   does not validate leaves the previous rules in effect and shows the error in the Rules view.
3. The rules file is only ever replaced whole (`os.replace`), so the engine never reads half a file.
4. `POST /api/rules/test` never changes counters, flows or the file.
5. No endpoint opens a file from a client-supplied path: session names are checked against the
   listing; mock files against `mocks_dir`; the rules file comes from the preset.
6. The read-only store never writes to the viewed session folder (the report writes its zip there,
   as `./wiretrace report` does).
7. `device.status.json` never holds a serial, UDID or device name.
8. Replay sends only flows held in memory for the live session.

### Tests derived

- `tests/test_qa_tools.py`: `parse_rules` (each limit and field, unknown keys, duplicate ids,
  `mock_file` outside `mocks_dir`, host not in the preset); matching (method ANY, host empty,
  wildcard paths, query handling, body contains on a gzip body); apply modes and counters; first
  applying rule wins, matching-but-not-applying passes on; order rules → faults → mocks; reload
  on mtime; invalid file keeps old rules; snapshot held across a delay (invariant 1); comment parts.
- A real `mitmdump -s` test loads `qa_tools.py` with a rules file and gets the rule's response
  (guards against the `@dataclass` failure above).
- `tests/test_wiretrace_ui.py`: rules GET/PUT (valid, invalid, 409 stale revision, atomic write),
  test endpoint leaves counters, re-arm; sessions list and view (bad names, names outside the
  listing, symlinks refused, cut-off `flows.mitm`); `?session=` on read endpoints; search over
  headers and bodies; replay (409 while viewing, unknown id 404); report for a viewed session;
  `client_connected` and `tls_failed_client` state; device status in state and over the socket;
  removed `/api/faults` is 404; every new mutation without `X-Wiretrace` is 403.
- `tests/test_collectors.py`: status file contents per state, no serial / UDID / name in it,
  atomic write; model and OS parsing per platform.
- `tests/test_start.py`: `qa_rules_file` for every UI; `mitm.it` allow-host; status file argument.
- `ui/src/**/*.test.ts`: rule form validation and summaries, import add / replace, timeline
  bucketing, JSON key diff and line diff, saved filters storage, crash folding, ±5 s lookup,
  emulator configuration rewrite, connection merge with the new message types.

## Files expected to change

Slice A: `addons/qa_tools.py`; `addons/wiretrace_ui.py`; `cli/start.py`; `rules/example.json`
(new); `ui/src/{types,api,store}.ts(x)`; `ui/src/components/RulesView.tsx`, `RuleEditor.tsx`
(new); `TitleBar.tsx`, `App.tsx`, `DetailPanel.tsx` (*New rule*); `ui/src/logic/rules.ts` (new);
`FaultsDialog.tsx` and `logic/faults.ts` removed; tests above.

Slice B: `addons/wiretrace_ui.py`; `cli/start.py`; `ui/src/components/SetupWizard.tsx` (new,
replaces `SetupDialog.tsx`); `ui/src/logic/setup.ts` (new).

Slice C: `collectors/__init__.py`, `collectors/android.py`, `collectors/ios.py`,
`collectors/__main__.py`; `cli/start.py`; `addons/wiretrace_ui.py`; `ui/src/components/LogsView.tsx`,
`LogRow.tsx`, `TitleBar.tsx`, `Timeline.tsx` and `DevicePicker.tsx` (new); `ui/src/logic/{logs,timeline}.ts`.

Slice D: `addons/wiretrace_ui.py`; `ui/src/components/{Sidebar,TrafficView,DetailPanel,TitleBar}.tsx`,
`SessionsList.tsx` and `CompareDialog.tsx` (new); `ui/src/logic/{diff,savedFilters}.ts` (new).

Every slice: `ui/dist/` rebuilt and committed; `docs/user-guide.md` (*Wiretrace window* section,
*Make requests fail or slow* mentions rules, Part 2 uses the wizard and `mitm.it` through the
launcher); `README.md`. Last slice: `cli/__init__.py` and the version strings to 0.8.0.

## Out of scope

Screens 5 and 6; switching the device, target or mode at run time; app-launch detection;
"Add to bug report" for single lines; "Created by" on rules (a user name); collector rows such as
"App restarted · new PID"; comparing across sessions (U9); writing mock files from the window
(inline rule bodies cover it); intercept and breakpoints; making `--ui wiretrace` the default;
the Tauri app.

## Manual test (about 10 minutes, Android phone)

1. `./wiretrace start --preset <name> --target android --ui wiretrace`; *Setup*: pick Android,
   scan the QR; "Connected" appears before any app traffic; `http://mitm.it` loads on the phone.
2. Open the app: Verify traffic turns green; the title bar shows the device pill.
3. Rules: new rule from a request, status 500, once; the next call fails with FAULT and
   `rule: …`, the one after does not; *Re-arm*; *Test against last request*; export, import (add).
4. Logs: timeline, click a red tick; crash folded; line detail, *Open in Traffic*.
5. Replay a GET; Compare it with the original.
6. Ctrl+C, start again; Previous sessions → open the old one; *Report bug* on it; Back to live.
7. Private window without the token: refused (spec 006).

## Automated tests

`.venv/bin/python -m pytest`, `npm --prefix ui test`, and `npm --prefix ui run build` must
reproduce the committed `ui/dist/` (`tests/test_ui_build.py`).
