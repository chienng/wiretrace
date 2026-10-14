# Spec: QA addon — mocks, fault injection, request ID tagging

- **Date**: 2026-10-13
- **Tier**: M
- **Repo**: wiretrace
- **Status**: implemented
- **Branch**: `feature/qa-addon`
- **Related**: [`PLAN.md`](../../PLAN.md) §8 Phase 1 (F3, F4, F6), §9.3; spec 002 (launcher,
  presets), whose `start.build_command` gains the addon arguments

## Goal

Let a QA engineer replace a backend response with a local JSON file, make chosen requests
fail or slow down while the app is running, and see each request's `X-Request-ID` on the
flow, without writing mitmproxy commands. Everything runs in one mitmproxy addon that
`./wiretrace start` loads.

## Acceptance criteria

- [ ] With `mocks/<preset>/GET/api/v1/profile.json` present, `GET /api/v1/profile` (any
      query string) to a preset API host gets `200`, `Content-Type: application/json` and
      that file's bytes. The backend is not contacted. The flow is marked 🚧 in mitmweb.
- [ ] A mock file added or edited while Wiretrace runs is used from the next request on.
- [ ] No mock file matches → the request goes to the backend unchanged.
- [ ] In mitmweb, **Options** → `qa_fault_filter` = `~u /api/v1/orders` and
      `qa_fault_status` = `500` → matching API requests get `500` and the JSON body
      `{"error": "injected by Wiretrace"}`, the backend is not contacted, and the flow is
      marked 💥. Clearing `qa_fault_filter` stops it, without a restart.
- [ ] `qa_fault_delay_ms` = `3000` delays matching API requests by 3 s before they continue
      (to a mock, an injected status, or the backend). Other requests are not delayed.
- [ ] `qa_fault_drop` = on → matching API requests get their connection closed without a
      response.
- [ ] An invalid `qa_fault_filter`, a status outside 100–599, or a negative delay is
      rejected in the Options panel with a message; the previous value stays in effect.
- [ ] An API flow whose request (or, failing that, response) has an `X-Request-ID` header
      shows `request-id: <value>` as its comment in mitmweb, and the comment is in
      `flows.mitm`.
- [ ] Traffic to hosts outside the preset is never mocked, faulted, marked or commented.
- [ ] Ctrl+C while requests are being delayed still stops Wiretrace within the normal time
      (well under the launcher's 15-second "still stopping" message).
- [ ] The banner says where mocks are read from and how many mock files exist.
- [ ] Every spec 002 behavior is unchanged (sessions, HAR, ports, presets without the
      new keys).

## Approach

**One addon, `addons/qa_tools.py`, configured only through mitmproxy options.** The
launcher already loads and validates the preset; it passes the addon what it needs:

```text
-s <wiretrace>/addons/qa_tools.py
--set qa_api_hosts=<host>            (once per api_hosts entry)
--set qa_mocks_dir=<absolute mocks path>
--set qa_request_id_header=<header name>
```

The addon imports nothing from `cli/`, so it also works in the "Without the launcher"
mitmproxy command. Rejected: the addon reading the preset YAML itself (as in PLAN §9.3)
— that is two loaders and two validators, and the addon would have to find the wiretrace
folder on `sys.path`.

**Options** (all registered in `load`; mitmweb lists them under Options):

| Option | Type | Default | Meaning |
|---|---|---|---|
| `qa_api_hosts` | `Sequence[str]` | `[]` | Hosts (and subdomains) the QA features apply to. Empty = addon does nothing. |
| `qa_mocks_dir` | `str` | `""` | Folder of mock files. Empty or missing = no mocks. |
| `qa_request_id_header` | `str` | `X-Request-ID` | Header read for request ID tagging. |
| `qa_fault_filter` | `str` | `""` | mitmproxy filter expression selecting faulted requests. Empty = no faults. |
| `qa_fault_status` | `int` | `0` | Status to return instead of forwarding. `0` = off. |
| `qa_fault_delay_ms` | `int` | `0` | Delay before the request continues. |
| `qa_fault_drop` | `bool` | `false` | Close the connection instead of answering. |

Faults use a **filter expression**, not a path option (PLAN §9.3 had `qa_fault_path`):
QA already types the same expressions into mitmweb's search box, and one expression covers
path, method and host (`~m POST & ~u /orders`). Use `~all` to fault every API request.
The filter is evaluated when the request arrives, so response filters (`~c`, `~bs`) never
match; the user guide says so.

**Mock file layout**: `<mocks_dir>/<METHOD>/<path>.json`, with `<path>` the request path
without the query string, its leading and trailing `/` removed, used as nested folders:
`GET /api/v1/profile` → `mocks/staging/GET/api/v1/profile.json`; `GET /` →
`GET/index.json`. The path is used as sent, not percent-decoded. Rejected: PLAN §9.1's flat
`api_v1_profile.json`, where `/api/v1_profile` and `/api/v1/profile` collide; and a host
folder level, which makes every mock path longer to protect against two API hosts sharing
a path, which has not happened yet. Only `.json` mocks, always `200` — an error status is
what faults are for.

**Order inside the `request` hook**, API flows only:

1. Request ID from the request header → comment.
2. Fault: take a snapshot of the fault options; if the filter matches, wait the delay,
   then drop (if on) or answer with the status (if non-zero) and stop.
3. Mock: if the file exists, answer with it.

So a delay combines with a mock (slow mock) or with the backend (slow backend). In the
`response` hook: request ID from the response header if the request had none.

**Marks and comments**: mock → `marked = ":construction:"`; fault (status or drop) →
`":boom:"`; delay only → no mark. The comment holds parts joined by `; ` in this order:
`request-id: <value>` (value cut to 128 characters), `fault: status 500` /
`fault: delay 3000 ms` / `fault: dropped` (several if combined), `mock: GET/api/v1/profile.json`.

**Preset keys** (spec 002 already accepts unknown keys; these become known and validated):

- `mocks_dir` — optional, default `mocks/<name>`. Relative to the wiretrace folder; no
  absolute path, no `..`.
- `request_id_header` — optional, default `X-Request-ID`. A valid HTTP header name.

**Launcher banner** gains one line, e.g. `Mocks: 3 files in mocks/staging/` or
`Mocks: none (add files under mocks/staging/<METHOD>/…)`, and with mitmweb:
`Faults: mitmweb > Options > qa_fault_*`.

**Addon logging** (mitmweb's event log): only counts and states, e.g.
`Wiretrace QA: 2 API hosts, mocks on, faults off`. Never hosts, paths, header values or
request IDs — the flows already hold those, and the event log is often screenshotted.

## Design that needs care

Faults are changed at runtime while other requests are sleeping inside the addon, and a
stop can arrive while they sleep.

**Per-flow decision.** A flow takes one snapshot of `(filter, status, delay_ms, drop)`
when its `request` hook starts and uses only that snapshot. The snapshot is an immutable
object rebuilt in `configure`; the hook reads the reference once.

**States of one API flow inside the addon**

| State | Entered when | Exits to |
|---|---|---|
| `TAGGED` | request hook starts; request ID read | `DELAYING` (fault matches, delay > 0); `FAULTING` (matches, no delay); `MOCKING` (no fault match) |
| `DELAYING` | `await asyncio.sleep(delay)` | `FAULTING` (flow still live); `GONE` (client left or proxy shutting down: sleep cancelled or flow no longer live) |
| `FAULTING` | after the delay, or directly | `DONE` (dropped or status answered); `MOCKING` (delay-only snapshot) |
| `MOCKING` | no fault answer | `DONE` (mock answered or not found → forwarded) |

**Invariants**

1. Flows to hosts outside `qa_api_hosts` are never modified: no response, mark, comment,
   delay or kill.
2. A flow answered by a mock or an injected status never reaches the backend (the
   response is set in the `request` hook).
3. Each flow uses exactly one fault snapshot, taken when its request arrives. Changing
   options affects only requests that arrive afterwards; a flow already delaying finishes
   with its old snapshot.
4. A delay never blocks other flows (`asyncio.sleep`, never `time.sleep`) and is
   cancellable: on shutdown it ends without answering, and the addon does not swallow
   `asyncio.CancelledError`. (Checked in mitmproxy 12.2.3: SIGINT cancels a `request`
   hook sleeping in `asyncio.sleep(30)` and mitmdump exits in under 1 s.)
5. After a delay the addon touches the flow only if it is still live (`flow.live` and not
   killed).
6. Mock lookup never opens a file outside `qa_mocks_dir`: a path segment that is empty,
   `.` or `..` means no mock, and the resolved file must be inside the resolved mocks
   folder (symlinks pointing out are refused).
7. An option value that fails validation never replaces the snapshot in effect.
8. The addon never writes files.

**Tests derived from the invariants** (unit tests with `mitmproxy.test.taddons` and
`tflow`, run inside `asyncio.run`, since `taddons.context` needs an event loop):

- Non-API host with matching mock and fault → flow untouched (1).
- Mock present → response 200 with file bytes, `:construction:`, comment; no mock →
  `flow.response is None` (2).
- Fault status → response set in request hook, `:boom:` (2).
- Snapshot: start a delayed request, change `qa_fault_status` during the delay → the
  flow ends with the old status; a new request uses the new one (3).
- Two flows, one delayed 1 s → the other completes first (4).
- Cancel the task of a delaying flow → `CancelledError` propagates, flow has no response (4).
- Flow killed during the delay → no response set afterwards (5).
- Paths `/../../etc/passwd`, `/a//b`, `/./x`, and a symlink in the mocks folder pointing
  outside → no mock (6).
- Invalid filter / status 99 / status 600 / negative delay → `OptionsError`, old snapshot
  still applied (7).
- Request ID from request header; from response header when the request has none; cut
  to 128 characters; comment parts in the documented order.
- Integration (skipped when mitmdump is not in the venv): real `mitmdump -s
  addons/qa_tools.py` in regular mode with `--set` options, a local HTTP backend that
  counts hits: a mocked path returns the file and the backend count stays 0; a faulted
  path returns 500 with count 0; `qa_fault_delay_ms=10000` on one request, then SIGINT →
  mitmdump exits within 5 s.
- Launcher: `build_command` contains `-s …/addons/qa_tools.py` and one
  `--set qa_api_hosts=` per host; real-launcher integration from spec 002 still passes
  with a mock file in place and `flows.mitm` contains the marked, commented mocked flow.

## Files expected to change

- `addons/__init__.py` — new, empty (lets tests import the addon).
- `addons/qa_tools.py` — new. Options, snapshot, request/response hooks, mock lookup.
  Imports only mitmproxy and the standard library.
- `cli/preset.py` — `mocks_dir` and `request_id_header` on `Preset`, with validation.
- `cli/start.py` — `build_command` adds the addon arguments; banner line for mocks and
  faults.
- `cli/__init__.py` — version `0.3.0`.
- `presets/example.yaml` — document `mocks_dir` and `request_id_header`.
- `mocks/example/GET/api/v1/profile.json` — new, a sample mock for the example preset.
- `tests/test_qa_tools.py` — new; see Design.
- `tests/test_preset.py`, `tests/test_start.py` — new keys, command line, banner.
- `docs/user-guide.md` — Part 3: "Mock a response" and "Make requests fail or slow"
  replace "Optional — Fake responses and slow networks" (whose `--map-local` recipe moves
  to "Without the launcher").

## Out of scope

- Fault options on the `./wiretrace start` command line, or passing extra mitmproxy
  arguments through. With `--no-ui` there is no Options panel, so faults need mitmweb in
  this spec.
- Mocks with a status other than 200, custom headers, non-JSON bodies, or per-host mocks.
- Matching mocks by query string or body; recording a real response as a mock (Phase 2,
  U5 "copy as mock").
- Using request IDs to match log lines (spec 004 stores logs; matching is Phase 2, U6).
- Log collectors and the in-app log receiver (spec 004); redaction (spec 005).

## Manual test

1. Copy `mocks/example/` to `mocks/<your preset>/` and change the path to an endpoint the
   app calls. `./wiretrace start --preset <name>`; open that screen in the app. The app
   shows the mock's data; mitmweb shows the flow marked 🚧.
2. Edit the mock file, refresh the screen in the app: the new data appears.
3. mitmweb → Options: `qa_fault_filter` = `~u <that path>`, `qa_fault_status` = `500`.
   Refresh: the app shows its error state; the flow is marked 💥. Set
   `qa_fault_filter` to `foo(` → Options rejects it.
4. `qa_fault_status` = `0`, `qa_fault_delay_ms` = `5000`: the screen loads 5 s late,
   other screens are not slower. Press Ctrl+C during a delayed load: Wiretrace stops within
   a few seconds and prints the session folder.
5. If the backend sends `X-Request-ID`, the flow's comment shows it.

## Automated tests

See *Tests derived from the invariants*, plus preset validation for `mocks_dir`
(absolute path, `..`, not a string) and `request_id_header` (empty, contains a space or
`:`).

## Open question

Do our backends send a request ID, and under which header name? `X-Request-ID` is the
default; a preset can override it without a spec change.
