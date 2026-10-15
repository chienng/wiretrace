# Spec: log collectors and in-app log receiver

- **Date**: 2026-10-14
- **Risk**: high — the receiver accepts app log lines sent off the phone, and both features
  store app log content. Needs a code, security and privacy review, a runtime check, and
  a maintainer's sign-off before merge.
- **Repo**: wiretrace
- **Status**: implemented
- **Branch**: `feature/log-collectors`
- **Related**: [`PLAN.md`](../../PLAN.md) §8 Phase 1 (F7, F8, F9, F10, F12), §9.5, §9.6,
  §9.7, §7 R6; spec 002 (launcher state machine, which gains a second child); spec 003
  (`addons/qa_tools.py`, untouched)

## Goal

While `./wiretrace start` runs, the app's logs land in the same session folder as its
traffic, with no second Terminal window: the device log through a collector chosen by
`--target`, and lines the QA build sends itself to `https://qa-logs.internal/log` (R6).
Logs are stored only on this Mac; nothing reaches any server.

## Acceptance criteria

- [ ] `--target android` (or `android-emu`) with `app.android_package` in the preset and one
      device in `adb devices`: the app's log lines appear in `<session>/device.log.jsonl`,
      one JSON object per line, including lines logged before the app's first screen.
- [ ] The app is force-stopped and reopened, or crashes and is reopened, during the session:
      the new process's lines keep arriving, including the crash stack trace.
- [ ] `--target ios` with `app.ios_process` and one iPhone connected by USB: the app's
      device log lines appear in `device.log.jsonl`, and keep arriving after the app restarts.
- [ ] `--target ios-sim` with `app.ios_process` and one booted Simulator: same, from the
      Simulator.
- [ ] Unplugging the device and plugging it back in resumes the log without a restart. No
      device, or more than one, prints a status line and waits; capture is unaffected.
- [ ] `--target device`, a missing `app.*` key, or a missing tool (`adb`, `pymobiledevice3`,
      `xcrun`): Wiretrace still starts; the banner says why device logs are off.
- [ ] A QA build sending `POST https://qa-logs.internal/log` with a JSON object or array of
      objects gets `204`; each object is a line in `<session>/app.log.jsonl`. This works in
      WireGuard mode and in Wi-Fi proxy mode.
- [ ] No request to `qa-logs.internal` is ever sent anywhere: not to the internet, not to
      the backend. Its flows are visible in mitmweb but are not saved in `flows.mitm` or
      `flows.har`.
- [ ] A malformed body gets `400`, a body over 1 MiB gets `413`, any other path or method
      gets `404`/`405`; nothing is stored for them.
- [ ] Ctrl+C stops Wiretrace and every collector process within the normal time; a second
      Ctrl+C force-stops all of them. No `adb`, `pymobiledevice3` or `log` process started
      by Wiretrace is left running after it exits, on any path.
- [ ] The Terminal shows collector states only. No log content, device serial or UDID is
      printed, or written to `meta.json`.
- [ ] `meta.json` records which device log source ran and how many lines each log file has.
- [ ] A session that captured log lines but no traffic is kept (it was removed before).

## Approach

### Device log collectors: one child process, in its own process group

`./wiretrace start` runs one collector child, `python -m collectors`, next to mitmweb or
mitmdump. Rejected: running collectors as threads inside the launcher (a hung `adb` call
would block the stop path the launcher exists to guarantee) and as a mitmproxy addon (the
log would stop with mitmproxy and `--no-ui`/mitmweb restarts would lose lines).

The collector is started with `start_new_session=True`, so the launcher can kill it **and
the tools it started** with one `killpg`. The launcher forwards every stop signal to that
group itself, because a Terminal Ctrl+C no longer reaches it. Rejected: keeping it in the
launcher's group (a SIGKILL of the collector would orphan `adb logcat`, which never exits
on its own).

| `--target` | Collector | Needs | Tool command |
|---|---|---|---|
| `android`, `android-emu` | Android | `app.android_package`, `adb` (`doctor.find_adb`) | `adb logcat -v threadtime -v epoch --pid=<pid> -T <start>` |
| `ios` | iOS device | `app.ios_process`, `<venv>/bin/pymobiledevice3` | `pymobiledevice3 syslog live -pn <ios_process> --format json` |
| `ios-sim` | iOS Simulator | `app.ios_process`, `xcrun` | `xcrun simctl spawn booted log stream --style ndjson --level debug --predicate 'process == "<ios_process>"'` |
| `device` | none | — | — |

Every tool child runs with `stdin=DEVNULL` (pymobiledevice3 prompts when several devices
are connected) and is started with an argument list, never a shell.

**Android PID tracking.** `adb logcat --pid` does not exit when the process dies, so the
collector polls `adb shell pidof -s <package>` every second and restarts `logcat` when the
PID changes. `-T <start>` is the device's own clock (`adb shell date +%s`) when the
collector first sees the device, the same value for every restart: lines a new process
logged before the next poll are still read from the ring buffer, lines from before the
session are not. Device clock, not Mac clock, because they can differ by seconds.
Rejected: `logcat --uid` (survives restarts, but not on every Android version we test) and
PLAN §9.5's "wait for logcat to exit" (it never does).

**Device count.** Android: `adb devices`, rows in state `device`. iOS: `pymobiledevice3
usbmux list` (the doctor already parses it). Simulator: `xcrun simctl list devices booted
-j`. Exactly one → stream; zero or several → status line, check again every 2 s. Choosing
one of several devices is out of scope.

**Record format** (`device.log.jsonl`, PLAN §9.5), one object per line:

```json
{"ts": "2026-10-14T09:30:12.481+07:00", "source": "android", "level": "E", "tag": "OkHttp", "message": "..."}
```

| Field | Android (`threadtime`+`epoch`) | iOS device (`--format json`) | Simulator (`ndjson`) |
|---|---|---|---|
| `ts` | epoch seconds → ISO 8601, Mac's time zone | `timestamp` | `timestamp` → ISO 8601 |
| `source` | `android` | `ios` | `ios-sim` |
| `level` | `V D I W E F` as printed (`A` → `F`) | `DEBUG`→`D`, `INFO`/`NOTICE`→`I`, `ERROR`→`E`, `FAULT`→`F`, other → `I` | `Debug`→`D`, `Info`/`Default`→`I`, `Error`→`E`, `Fault`→`F`, other → `I` |
| `tag` | tag | `label.category`, else `label.subsystem`, else `image_name`, else `""` | `category`, else `subsystem`, else `""` |
| `message` | rest of the line | `message` | `eventMessage` |

Lines that do not parse (logcat's `--------- beginning of main`, `log stream`'s header,
broken JSON) are skipped and counted. Messages are stored as received: redaction is an
export step (spec 005).

### In-app log receiver: `addons/app_logs.py`

A second addon, loaded by the launcher next to `qa_tools.py`. Every request to
`qa-logs.internal` is answered inside mitmproxy, in the `request` hook.

**Contract for QA builds (R6)** — `POST https://qa-logs.internal/log`,
`Content-Type: application/json`, fire-and-forget (ignore every failure):

```json
[{"message": "Order list loaded", "level": "I", "tag": "Orders", "ts": "2026-10-14T09:30:12.481+07:00", "request_id": "6f1c…"}]
```

A single object or an array of up to 1,000. `message` (string) is required; `level`, `tag`
(strings, ≤ 64 chars), `ts` (string, ≤ 64 chars) and `request_id` (string, ≤ 128 chars)
are optional; other keys are dropped. A batch is stored completely or not at all.

| Request | Answer | Stored |
|---|---|---|
| `POST /log`, valid body | `204` | one line per object |
| `POST /log`, not JSON / wrong shape / wrong type | `400`, one-line JSON error | nothing |
| `POST /log`, body > 1 MiB | `413` | nothing |
| other path | `404` | nothing |
| `/log` with another method | `405` | nothing |

Stored line: `{"ts": <app ts, else received>, "received": <Mac time, ISO 8601>, "source":
"app", "level", "tag", "message", "request_id"}` — absent optional fields are omitted.

**Making `qa-logs.internal` reachable without contacting anything.** The name does not
exist, and mitmproxy's default connection strategy (`eager`) connects to the server
*before* the request reaches any addon: in WireGuard mode a failed connect closes the
phone's connection (`TransparentProxy.finish_start`), in proxy mode the `CONNECT` gets
`502` (`handle_connect_regular`). Both read in mitmproxy 12.2.3's source. So:

1. `dns_request` (WireGuard mode; the phone resolves names through mitmproxy at
   `10.0.0.53`, which `--allow-hosts` never filters): a query for `qa-logs.internal` →
   `A 192.0.2.10` (TEST-NET-1, never routed), TTL 60; `AAAA` and other types → `NOERROR`
   with no answers. Other names are untouched.
2. `server_connect`: a connection to `qa-logs.internal` (proxy mode) or `192.0.2.10`
   (WireGuard mode), any port → address rewritten to a **sink**: a TCP listener the addon
   opens on `127.0.0.1`, port chosen by the OS, that accepts, reads nothing and closes when
   mitmproxy does. mitmproxy reads the address after this hook (`proxy/server.py`), so the
   eager connect succeeds locally.
3. `tls_clienthello`: SNI `qa-logs.internal` → `establish_server_tls_first = False`, so no
   TLS is attempted with the sink; the phone gets a certificate for the SNI from the
   mitmproxy CA it already trusts.
4. `request`: `pretty_host == "qa-logs.internal"` → answer per the table. The request is
   never forwarded, so the sink never receives a byte.

The launcher adds `--allow-hosts '^qa-logs\.internal(:\d+)?$'` (that host only, no
subdomains) so the HTTPS request is decrypted, and `--set
save_stream_filter='!~d ^qa-logs\.internal$'` so receiver flows stay out of `flows.mitm`
and therefore `flows.har` (they would duplicate the app log and widen what spec 005 must
redact). They remain visible in mitmweb, which shows whether the app is sending.

Rejected: `--set connection_strategy=lazy` (one line, but for **all** traffic it turns an
unreachable backend into a `502` from mitmproxy instead of a failed connection, and an
invalid backend certificate into a later error — the app under test would see different
failures than in production); a path on an API host such as `/__wiretrace/log` (without DV
Lens running, the QA build would send its logs to the real backend).

**Options** (registered in `load`):

| Option | Type | Default | Meaning |
|---|---|---|---|
| `qa_app_log_file` | str | `""` | Absolute path of `app.log.jsonl`. Empty: requests are still answered (`204` for a valid body) but nothing is stored. Never forwarded either way. |

The file is opened in append mode on the first stored line, flushed after every request,
and closed in `done`. Addon log lines (mitmweb's event log) carry counts and states only:
`Wiretrace app logs: on` / `off (qa_app_log_file empty)`, and at `done`
`Wiretrace app logs: <n> lines stored, <m> requests rejected`.

### Launcher (`cli/start.py`)

- `build_command` adds `-s addons/app_logs.py`, `--set qa_app_log_file=<folder>/app.log.jsonl`,
  the `qa-logs.internal` allow-hosts regex and the `save_stream_filter`.
- `collector_command(preset, target, bin_dir, out)` returns the argument list, or `None`
  plus a reason shown in the banner.
- Banner gains two lines, e.g. `Device logs: Android, com.example.myapp → device.log.jsonl`
  (or `Device logs: off (add app.android_package to the preset)`) and
  `App logs: POST https://qa-logs.internal/log → app.log.jsonl`.
- `meta.json` gains `device_logs` (`android` | `ios` | `ios-sim` | `null`) at start, and
  `device_log_lines`, `app_log_lines` (line counts) at the end.
- "Nothing was captured" (folder removed, exit 1) now means: no flows **and** no line in
  either log file. With log lines but no flows, the folder is kept, the HAR step is skipped
  with `No traffic was captured; flows.har was not written.`, and the exit code follows the
  stop status as before.

### Collector status lines

Printed by the collector to the Terminal on a state change only, prefixed `Device logs:`:
`waiting for a device`, `more than one device connected; connect only one`, `waiting for
the app to start`, `streaming`, `app restarted, following the new process`, `device
disconnected, waiting`, `<tool> failed (exit code <n>); retrying in 2 s`. Writes that fail
(window closed) are ignored, as in `start.say`.

### Preset (`cli/preset.py`)

`app` is validated when present (it was free-form): `android_package` must be a Java
package name (`[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+`); `ios_process` must match
`[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}` — it is placed inside a `log stream` predicate, so
quotes and backslashes are rejected, not escaped. Unknown `app` keys are still ignored.

## Design that needs care

### Launcher states (spec 002) with a second child

States are unchanged: PREPARE → RUNNING → STOPPING → KILLED → FINALIZING → DONE, or
ABORTED. The mitmproxy child still decides the state; the collector is a secondary child
that never ends the session.

| Event | RUNNING | STOPPING | KILLED |
|---|---|---|---|
| first stop signal | → STOPPING; SIGINT to mitm child **and** collector group | — | — |
| next stop signal | — | → KILLED; SIGKILL mitm child and collector group | ignored |
| collector exits by itself | one status line; stays RUNNING | nothing | nothing |
| mitm child exits | stop collector (below); → FINALIZING, status `exited` | stop collector; status `stopped` | collector already killed; status `killed` |

**Stopping the collector** after the mitm child is gone: send SIGINT to its group if not
yet sent, wait up to `COLLECTOR_STOP_S = 3` s from that signal, then SIGKILL the group and
wait. FINALIZING starts only after the collector has been reaped.

**Launcher invariants**

1. No return path from `supervise` leaves the mitm child or any process in the collector's
   group running (`finally`: `kill`, `killpg(SIGKILL)` ignoring `ProcessLookupError`, wait).
2. The collector starts only after the mitm child started; a collector that fails to start
   prints one line and the session continues without it.
3. A collector exiting, crashing or never finding a device never changes the launcher
   state or exit code.
4. The launcher sends at most one SIGINT to each child; the second stop signal is SIGKILL
   for both.
5. Line counts in `meta.json` are taken after the collector is reaped and after mitmproxy
   exited, so both log files are complete.

### Collector states

Android (polls every 1 s, device count every 2 s while waiting):

| State | Event | Next state, action |
|---|---|---|
| WAIT_DEVICE | exactly one device | WAIT_APP; read the device clock for `-T` (first time only) |
| WAIT_APP | `pidof` returns a PID | STREAMING(pid); start `logcat --pid=<pid>` |
| STREAMING(pid) | `pidof` returns another PID | STREAMING(new); stop old `logcat`, then start the new one |
| STREAMING(pid) | `pidof` returns nothing | stay; keep `logcat` until a new PID appears |
| WAIT_APP, STREAMING | device gone, or `logcat` exits | WAIT_DEVICE; stop `logcat` |

iOS device and Simulator: WAIT_DEVICE → (exactly one) → STREAMING → (tool exits) → wait
2 s → WAIT_DEVICE. In every state, SIGINT / SIGTERM / SIGHUP → STOPPING → exit 0.

**Collector invariants**

1. On SIGINT, SIGTERM or SIGHUP the collector terminates its tool child (SIGTERM, 1 s, then
   SIGKILL), writes what it already read, and exits 0 within 2 s.
2. No exit path, including an exception, leaves its tool child running (`finally`).
3. Each record is written as one complete line in one `write` call and flushed, so a reader
   (or a kill) never sees half a record except possibly the last line.
4. The output file is opened in append mode on the first record; no record, no file.
5. Nothing it prints or stores contains a device serial, UDID or log content outside
   `device.log.jsonl`. The package / process name in status lines is allowed (it names the
   app, not a person).
6. Android: every `logcat` run uses the same `-T` value; a PID change stops the old `logcat`
   before the new one starts, so two never write at once.

### Receiver invariants

1. Every flow to `qa-logs.internal` gets its response in the `request` hook; none is
   forwarded. The sink receives zero bytes.
2. Only connections to `qa-logs.internal` or `192.0.2.10` are redirected; only DNS queries
   for `qa-logs.internal` are answered; only that SNI changes `establish_server_tls_first`.
3. A batch is stored entirely or not at all; a rejected request stores nothing.
4. Flows to other hosts are untouched by this addon, and `qa_tools.py` never sees
   `qa-logs.internal` as an API host.
5. The sink listens on `127.0.0.1` only and is closed in `done`.
6. Addon log lines contain no log content, request IDs or file paths.

### Tests derived from the invariants

Collectors (`tests/test_collectors.py`; fake `adb`, `pymobiledevice3`, `xcrun` scripts like
spec 002's fake mitmdump, driven by a scenario file):

- Parsers: recorded-format samples for each source → records; level mapping table; lines
  that do not parse are skipped and counted.
- Android: zero devices → waits; two → status line, waits; one → `logcat` started with
  `--pid=<pid>` and `-T <device time>`; PID changes → old `logcat` gone before the new one
  starts, same `-T` (collector 6); device gone → back to WAIT_DEVICE.
- iOS / Simulator: tool exits → restarted after the delay; device count ≠ 1 → waits.
- SIGINT while streaming → exit 0 within 2 s, fake tool's PID gone (collector 1, 2).
- Status output contains no serial / UDID from the fakes' output (collector 5).
- No record → no file (collector 4).

Receiver (`tests/test_app_logs.py`, `taddons` / `tflow` / `tdnsflow`):

- Valid object → `204`, one stored line with `source: app`, `received`, known fields only.
- Array of 3 → 3 lines; array with one bad item → `400`, nothing stored (receiver 3).
- Not JSON, `message` missing or not a string, too-long field, 1,001 items → `400`.
- Body > 1 MiB → `413`; `GET /log` → `405`; `POST /other` → `404`; nothing stored.
- Response always set in `request` (receiver 1); other hosts untouched (receiver 4).
- `qa_app_log_file` empty → `204`, no file.
- DNS: `A` for `qa-logs.internal` → `192.0.2.10`; `AAAA` → no answers; other names → no
  response set (receiver 2).
- `server_connect` rewrites only the two addresses to the sink; `tls_clienthello` changes
  only that SNI (receiver 2).
- Addon log records contain no message text or path (receiver 6).

Launcher (`tests/test_start.py`, fake collector command that writes lines, spawns a
grandchild `sleep` and records PIDs):

- SIGINT → both children stop, collector group gone, `meta.json` counts match the files
  (launcher 1, 5).
- Two SIGINTs with a collector that ignores SIGINT → collector group, including the
  grandchild, killed (launcher 1, 4).
- Collector crashes during RUNNING → session continues, exit code unchanged (launcher 3).
- Collector command missing → one line, session continues (launcher 2).
- No flows but log lines → folder kept, HAR skipped; no flows and no lines → removed.
- `build_command` contains the receiver arguments; `collector_command` per target and
  missing key / tool reasons.

Integration (real mitmdump, proxy mode, temporary `confdir`): `curl --cacert <that CA> -x
http://127.0.0.1:<port> -X POST https://qa-logs.internal/log -d '[{"message":"hi"}]'` →
`204`; one line in `app.log.jsonl`; the sink received 0 bytes; `flows.mitm` has no
`qa-logs.internal` flow; DNS was never asked for the name.

## Files expected to change

- `collectors/__init__.py`, `collectors/__main__.py` — new. CLI (`--target`, `--app`,
  `--out`, tool paths), signal handling, writer, status lines.
- `collectors/android.py` — new. Device count, PID tracking, `logcat` parsing.
- `collectors/ios.py` — new. iOS device and Simulator: device count, streaming, parsing.
- `addons/app_logs.py` — new. Options, DNS answer, connect redirect and sink, TLS flag,
  receiver.
- `cli/start.py` — collector command, second-child supervision, receiver arguments,
  banner lines, meta counts, "nothing captured" rule.
- `cli/session.py` — `DEVICE_LOG`, `APP_LOG` names; `count_lines`.
- `cli/preset.py` — `app.android_package` / `app.ios_process` validation.
- `cli/__init__.py` — version `0.4.0`.
- `presets/example.yaml` — comments on the `app` keys.
- `tests/test_collectors.py`, `tests/test_app_logs.py` — new; `tests/test_start.py`,
  `tests/test_preset.py` — updated.
- `docs/user-guide.md` — Part 3: "See the app's logs" (targets, what `device.log.jsonl`
  contains, Private DNS note); a section for the mobile team with the R6 contract;
  troubleshooting rows for the status lines.

## Out of scope

- Choosing one of several connected devices (`--serial`), and apps with several processes.
- iOS crash-report pulling at the end of a session (PLAN §9.5 table).
- Matching log lines to flows by request ID (Phase 2, U6), and showing logs in mitmweb.
- Redaction of log content and the bug-report zip (spec 005).
- Restarting a collector from the launcher (the collector retries internally).
- Doctor checks for `xcrun` or a booted Simulator.

## Manual test

1. `./wiretrace start --preset <name> --target android` with the Android device connected,
   then open the app: `device.log.jsonl` grows (`tail -f`); force-stop and reopen the app:
   lines keep coming. Unplug and replug: `Device logs: device disconnected, waiting`, then
   `streaming`.
2. Same with `--target ios` on an iPhone, and `--target ios-sim` on a booted Simulator.
3. With a QA build that implements R6 (or `curl` through the proxy in proxy mode): lines
   appear in `app.log.jsonl`; mitmweb shows the `qa-logs.internal` flows answered `204`.
   In WireGuard mode, the same from the phone.
4. Ctrl+C: Wiretrace stops; `ps -ax | grep -E 'adb logcat|syslog live|log stream'` shows
   nothing left. Repeat with two quick Ctrl+C.
5. `meta.json` has `device_logs` and both line counts; no serial or UDID anywhere in the
   session folder outside the log files themselves.

## Automated tests

See *Tests derived from the invariants*, plus preset validation for `app.android_package`
and `app.ios_process` (quote, backslash, too long, not a string).

## Open question

Does the mobile team accept the R6 contract above (HTTPS, JSON object or array, the field
names, fire-and-forget), and will Android QA builds trust the mitmproxy CA for
`qa-logs.internal` like the API hosts (R1)? Phones with Private DNS (Android) or an
encrypted-DNS profile (iOS) resolve names outside the tunnel, so in WireGuard mode the
receiver needs those turned off; the guide will say so.
