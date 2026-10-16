# Spec: Wiretrace in the menu bar

- **Summary**: while `./wiretrace start --ui wiretrace` runs, a status item in the
  macOS menu bar (on by default, off with `--no-menu-bar`) shows that Wiretrace is recording and how many requests failed, and its menu
  opens the window, shows the last failed request, or stops the session. Mockup screen 6.
- **Date**: 2026-10-16
- **Repo**: wiretrace
- **Status**: implemented (2026-10-16; on by default with `--ui wiretrace`)
- **Tier**: L (the window's token is handed to a second process; a new process may stop the
  session). Gates E, A, B, C, R, P, D.
- **Branch**: `feature/menu-bar-status` (from `main`)
- **Related**: [`PLAN.md`](../../PLAN.md) U1 and the launcher row; spec 002 (launcher
  invariants); spec 006 (the token, "Tauri later"); spec 008 (screen 6 out of scope);
  [`mockups/screens/06-menu-bar.png`](../../mockups/screens/06-menu-bar.png)

## Goal

A tester who has hidden the Terminal and the browser can still see, at a glance, that
Wiretrace is recording and whether requests are failing. From the menu bar, without finding the
Terminal or the link, they can open the window, jump to the latest failure, or stop the session
cleanly so `flows.har` is written.

## Acceptance criteria

- [ ] `./wiretrace start --preset P --target T --ui wiretrace` puts **● Wiretrace**
      in the menu bar within 3 seconds of the window link being printed. With failed requests
      it reads **● Wiretrace · N**, where N counts the requests that the window's *Errors 4xx / 5xx*
      quick filter counts. No Dock icon, no window of its own.
- [ ] Its menu shows, like the mockup: the title and a **Recording** pill; *Preset*, *Device*
      (target, mode, and the device model when the collector reports one, for example
      `Android · WireGuard · Pixel 8`), *Duration* counting up; three tiles *requests*,
      *errors* (red when above 0) and *rules on*. The values agree with the window's
      `flow_count`, *Errors* count and `rules_on` within 2 seconds.
- [ ] **Open Wiretrace** (⌘O) opens the window in the default browser, even after the browser
      was quit. Each click opens a new tab.
- [ ] **Show last error** (⌘R) opens the window with the most recent failed request selected
      in Traffic. It is greyed out while N is 0.
- [ ] **Stop session** stops the session exactly as Ctrl+C in the Terminal does: the Terminal
      prints "Stopping…", `flows.har` is written, `meta.json` ends `stopped`, the item goes away.
      While stopping, the item reads **Wiretrace · stopping** and the menu shows only that.
- [ ] **Quit** removes the item only. Capture goes on, and the Terminal prints once:
      `Menu bar: closed; capture continues (Ctrl+C here to stop)`.
- [ ] If the window has sent no status for 5 seconds while the session runs, the item reads
      **Wiretrace · ?** and the menu says "No status from Wiretrace"; it recovers by itself.
- [ ] Ctrl+C in the Terminal, a crash of mitmdump, or a force stop removes the item: no menu
      process is left behind on any exit path.
- [ ] If the menu bar cannot start (PyObjC missing, no logged-in desktop such as an SSH
      session), the start banner says `Menu bar: off (<reason>)` and capture runs as with
      `--no-menu-bar`. With `--no-menu-bar` the banner says `Menu bar: off (--no-menu-bar)`.
      With `--ui mitmweb` or `--no-ui` there is no menu bar and no banner line, and
      `--no-menu-bar` is accepted and changes nothing.
- [ ] `./wiretrace doctor` prints `INFO Menu bar: available` or `INFO Menu bar: PyObjC not
      installed (run scripts/setup-mac.sh)`.
- [ ] The token still never appears on a command line (`ps -o args`), in a file, in the
      Terminal other than the one printed link, or in a log line. The status file holds no
      token, no host, no path, no header and no body.
- [ ] With `--no-menu-bar`, `--ui mitmweb` or `--no-ui`, `./wiretrace start` behaves, prints and
      saves exactly as in 0.8.0, apart from where the window's token is made (see Approach) and
      the one banner line above.

## Approach

### A Python status item, started by the launcher

`menubar/` is a small package run as `python -m menubar` from the Wiretrace venv, using
**PyObjC** (`AppKit.NSStatusItem`, `NSMenu`, accessory activation policy, so there's no Dock icon). The
launcher starts it after mitmdump started and stops it on every exit path, the same way it
already handles the device log collector (spec 002 invariants 1 and 2).

Rejected:
- **Tauri** (`PLAN.md` U1): needs a Rust toolchain, a Developer ID and notarization (IT and
  an Apple account; `install-without-admin.md`), and a sidecar for the Python backend. That's
  right for the full app later, but too much for a status item.
- **A Swift app**: building it needs Xcode, which needs admin rights to install. An unsigned
  build is quarantined.
- **SwiftBar or xbar plugin**: the tester would have to install a third-party app.
- **Inside mitmdump**: AppKit needs the main thread's run loop, and mitmproxy's asyncio loop
  already owns it.
- **`rumps`**: a thin wrapper over the same PyObjC with infrequent releases; one more
  dependency for little code saved.

### Status: a file the window writes, not the API

The addon writes `sessions/<session>/.status.json`, `0600` in the `0700` session folder,
atomically (temporary file + `os.replace`). It writes when a value changed, at most once a
second, and at least every 2 seconds so the menu can tell a frozen session from a quiet one.
It deletes the file in `done`. The contents, version 1:

```json
{"v": 1, "updated_at": 1791900000.0, "started_at": 1791899000.0, "preset": "staging",
 "target": "android", "mode": "wireguard", "device_state": "streaming", "device_model": "Pixel 8",
 "requests": 248, "errors": 6, "rules_on": 2, "last_error": "<mitmproxy flow id or null>"}
```

The menu reads it once a second. Rejected: polling `/api/state` with the token. That answer
carries the WireGuard private key and needs the token for every read, but the menu only needs
counts. A file the report never packs (`cli/report.py` builds its members by name) exposes less.

### The token: made by the launcher, passed only to the two children

Today the addon makes the token at `running` and only prints it (spec 006). The menu needs it
for **Open Wiretrace**. With `--ui wiretrace`, the launcher now makes it
(`secrets.token_urlsafe(32)`) and passes it:
- to mitmdump in the environment variable `WIRETRACE_UI_TOKEN`. The addon reads it at
  `running`, accepts it only if it has the length and alphabet of a 32-byte urlsafe token
  (otherwise it makes its own, as now), and removes it from `os.environ` so nothing mitmdump
  starts (`open -R` for *Show in Finder*) inherits it;
- to the menu process as the first line on its **stdin pipe**, then the pipe is closed. The
  token is not passed in argv or the environment.

On macOS, other users cannot read a process's environment. The same user can already read
`flows.mitm`, which holds every captured token, so this adds nothing for them. Rejected:
- writing the link to a file, which leaves the token on disk after a force stop;
- the menu asking the addon for a one-time link over a socket, which is a new listener to
  secure;
- opening `http://127.0.0.1:8081/` without the token, which fails once the browser drops the
  session cookie.

### Stop: the launcher's own stop path

**Stop session** sends one `SIGINT` to the launcher. The launcher's process ID is given in argv
(not secret). Before signalling, the menu checks that `os.getppid()` still equals it, so it
never signals another process. The launcher already turns that into the single SIGINT to
mitmdump and the collector, HAR export and `stopped` in `meta.json` (`STOP_SIGNALS`, `_wait`).
The menu sends it once; it does not offer a force stop. The Terminal's second Ctrl+C remains
the force stop.

### Show last error: a fragment the window understands

The menu opens `http://127.0.0.1:<port>/?token=<T>#flow=<id>`. The server's token redirect to
`/` keeps the fragment, because browsers carry a fragment over a redirect whose `Location` has
none. On first load the page reads `#flow=<id>`, dispatches the existing `openFlow`, selects
that request and clears the fragment. An unknown ID is ignored.

### Not in the mockup's menu

- **Pause recording** is left out: nothing on the server pauses recording today (the window's
  Pause only freezes its list), and pausing capture changes what a session contains.
- **Report last error…** becomes **Show last error**; the report is one click away in the
  window.
- The mockup's "WireGuard + USB" becomes target · mode · model, which is what Wiretrace knows.

## Design that needs care

The lifecycle (two processes, stop, orphaning) is the risky part. A strong model has to agree
with this section before a cheaper one builds it.

### Menu process states

| State | Entered when | Title | Menu |
|---|---|---|---|
| STARTING | process start | `Wiretrace` | "Starting…", Open, Quit |
| LIVE | status file read, `updated_at` ≤ 5 s old | `● Wiretrace` / `● Wiretrace · N` | full menu |
| STALE | LIVE, then `updated_at` > 5 s old, or the file vanished | `Wiretrace · ?` | "No status from Wiretrace", Open, Stop, Quit |
| STOPPING | Stop clicked and SIGINT sent | `Wiretrace · stopping` | that line only |
| gone | Quit; SIGTERM from the launcher; parent changed | none | none |

STALE → LIVE when a fresh file is read. STOPPING never goes back. Each tick (1 s) first checks
`os.getppid() == launcher_pid`; if it no longer does, the process exits.

### Launcher additions

- The menu child is started after the mitmdump child, like the collector, in its own session
  (`start_new_session=True`), so a Terminal Ctrl+C reaches the launcher, not the menu.
- On every exit path, after `_finalize`: SIGTERM, wait up to 2 s, SIGKILL, reap. This sits in
  the same `finally` as the collector, so it holds when the start fails halfway.
- If the menu child ends by itself while RUNNING (Quit, a crash), the launcher prints the
  closed line once and does not start it again.

### Invariants

1. No exit path of `./wiretrace start` leaves a menu process running.
2. The menu signals only its launcher, only SIGINT, at most once.
3. A stop from the menu takes the launcher's Ctrl+C path: same messages, same HAR, same
   `stopped` status.
4. The token is never in argv, never in a file, never in a log, and not in the environment of
   anything but mitmdump before `running`. The menu holds it in memory only.
5. A menu bar that cannot start or dies never stops or slows capture.
6. `.status.json` holds only the fields above; it is removed when the addon stops, and the
   report never includes it.
7. With `--no-menu-bar` (or another UI), nothing changes except where the token is made and
   the banner line.

### Tests derived from them

- Invariant 1: fake menu commands that exit, hang, or ignore SIGTERM. After `supervise`
  returns on a normal stop, a child exit, a force stop and a failed HAR, the process is gone
  and reaped.
- Invariant 2: the model's stop action returns "signal" once, then "none"; with
  `getppid() != launcher_pid` it returns "exit" and never "signal".
- Invariant 3: a SIGINT coming from the menu child gives the same Terminal lines and
  `meta.json` as one from the Terminal (existing stop tests, parametrised).
- Invariant 4: the token is absent from the menu argv and from the env of both children after
  `running`, and present on the menu's stdin. The addon rejects a short or non-urlsafe
  `WIRETRACE_UI_TOKEN` and makes its own.
- Invariant 5: a menu command that exits at once with code 1 gives `Menu bar: closed …` once
  and the session still records.
- Invariant 6: the status file keys are exactly the version-1 set, its mode is `0600`, and it
  is gone after `done`. A report zip of that session doesn't contain it.
- The model: status + now → title and enabled items for every state in the table, including
  N = 0 (no "· 0", Show last error greyed), missing `device_model`, and `updated_at` exactly
  5 s old.

## Files expected to change

- `menubar/__init__.py`: the model. Pure functions from (status dict or None, now, stopping)
  to the title, the rows and the enabled actions, and from an action to what to do. No AppKit
  import, so pytest runs it anywhere.
- `menubar/__main__.py`: the AppKit shell. Reads the token from stdin, the launcher process ID,
  port and status path from argv; a 1 s `NSTimer` drives the model; menu actions call
  `webbrowser.open` or `os.kill`. It exits 2 with one line on stderr when AppKit can't be
  imported or no window server is available.
- `addons/wiretrace_ui.py`: the token from `WIRETRACE_UI_TOKEN` (check, use, remove from
  `os.environ`); the status writer in `_flush_updates`, deleted in `done`; the errors count with
  the same rule as `isError` in `ui/src/logic/filters.ts`.
- `cli/start.py`: `make_token()`, the env for mitmdump, `_MenuBar` (start, notice exit, stop),
  the banner line; the menu starts only with `--ui wiretrace` and without `--no-menu-bar`.
- `cli/__main__.py`: `--no-menu-bar`.
- `cli/session.py`: `STATUS = ".status.json"`.
- `cli/doctor.py`: the INFO line.
- `requirements.txt`: `pyobjc-framework-Cocoa>=11` (macOS universal2 wheels, which brings in
  `pyobjc-core`). The setup installs wheels only; check that both Intel and Apple silicon get
  one.
- `ui/src/App.tsx` (or wherever the first load is handled) and a vitest: `#flow=<id>` on first
  load. `ui/dist/` is rebuilt and committed.
- Tests: `tests/test_menubar.py` (new), `tests/test_start.py`, `tests/test_wiretrace_ui.py`,
  `tests/test_doctor.py`, `tests/test_report.py` (the status file is never packed).
- Docs: `docs/user-guide.md` (a *Menu bar* part under the Wiretrace window section, and the
  flag in the `start` options); `README.md` (Features; Design table row 6 becomes "Built:
  status item … Differences: …"); `docs/install-without-admin.md` (PyObjC needs no admin).

Order: the model and its tests; the addon token and status file; the launcher; the AppKit
shell; the UI fragment; the docs.

## Out of scope

- The full Tauri app, signing, notarization, Self Service (U1 as `PLAN.md` describes it).
- Pausing capture; the report or YouTrack / Jira from the menu (spec 012 will cover screen 5).
- Starting a session from the menu bar, choosing a preset there, or a login item that keeps it
  running between sessions.
- Notifications ("new 5xx"), sounds, badges on the Dock.
- A menu bar for `--ui mitmweb` or `--no-ui`.
- The version number: set by whichever release carries this.

## Decision

The menu bar is **on by default** with `--ui wiretrace`, and `--no-menu-bar` turns it off
(approved 2026-10-16). It helps someone who forgets the Terminal. The cost is one more process
that could fail on a managed Mac, so a menu bar that can't start only prints `Menu bar: off
(<reason>)` and never stops capture (invariant 5).

## Manual test (about 5 minutes, Apple silicon and, if available, an Intel Mac)

1. `scripts/setup-mac.sh` on an existing install picks up PyObjC; `./wiretrace doctor` says
   `Menu bar: available`.
2. `./wiretrace start --preset <name> --target android --ui wiretrace`: the item
   appears; no Dock icon. Use the app until a request fails: `● Wiretrace · 1`; the tiles match
   the window.
3. Quit the browser. *Open Wiretrace* opens the window again. *Show last error* selects
   the failed request.
4. *Stop session*: the Terminal prints "Stopping…", the item reads "stopping" and goes away;
   `flows.har` exists; `ps -ax | grep menubar` shows nothing.
5. Start again, then Ctrl+C in the Terminal: the item goes away. Start again, then *Quit* in
   the menu: the Terminal prints the closed line once; capture continues; Ctrl+C stops it.
6. `ps -o args= -p <mitmdump pid>` and the menu process's args show no token.
7. Start with `--no-menu-bar`: no item; the banner says `Menu bar: off (--no-menu-bar)`.

## Automated tests

All of the tests listed under "Tests derived from them", plus:
- `--ui wiretrace` starts the menu child; with `--no-menu-bar`, `--ui mitmweb` or `--no-ui`
  no menu child is started and no token goes to anything but mitmdump.
- The banner shows `Menu bar: on`, `Menu bar: off (--no-menu-bar)` or
  `Menu bar: off (<reason>)`; there's no such line with mitmweb or `--no-ui`.
- The addon without `WIRETRACE_UI_TOKEN` behaves as in 0.8.0; the existing token tests pass.
- The page with `#flow=<known id>` selects it; with an unknown ID nothing changes; the
  fragment is removed after reading.

## Errata

2026-10-16, for 0.9.0, after a tester could not find the item:

- **An icon replaces "● Wiretrace".** The item is the app icon's tile with the W cut out
  (`app/menubar-icon.svg`), 16 pt, as a template image so macOS tints it for a light or dark
  menu bar. Next to it: N when LIVE with errors, `?` when STALE, nothing otherwise
  (`MenuView.badge`). Tooltip and accessibility description: "Wiretrace".
- **A TIFF, not a PDF.** `make icon` writes `menubar/icon.tiff` (16 and 32 px) and it is
  committed. AppKit drew rsvg's PDF of the cut-out W as blank.
- **When the icon can't be loaded**, the item shows the old titles without the ●
  (`Wiretrace`, `Wiretrace · N`, `Wiretrace · ?`, `Wiretrace · stopping`), so it is never empty.
- **Dimmed unless LIVE.** The ● was the only difference between STARTING and LIVE, so the
  item now uses the system's dimmed look in every state but LIVE.
- Docs and dialogs say "the Wiretrace menu (the W icon at the top right)". The criteria and
  the state table above keep the old titles as a record of what shipped in 0.8.0.
