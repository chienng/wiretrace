# Spec: switch the preset from the window

- **Summary**: the title bar's preset label becomes a menu. Choosing another preset saves
  the current session and starts a new one with that preset, the same target and mode, and
  the phone's tunnel left up. One preset per session. The window does not edit a preset
  in place.
- **Date**: 2026-10-16
- **Repo**: wiretrace
- **Status**: approved (2026-10-16)
- **Tier**: L (a window action stops the capture process; the next process gets a new
  token; the launcher's stop/start loop changes). Gates E, A, B, C, R, P, D.
- **Branch**: `feature/switch-preset` (from `main`)
- **Related**: spec 002 (one session, then exit); spec 006 (the window is inside mitmdump,
  token, `X-Wiretrace`); spec 008 (no target or mode switch at run time; live actions are
  off while a previous session is open); spec 011 (menu-bar Stop is a SIGINT to the
  launcher; the token is not on a command line)

## Goal

A tester who has the phone connected should be able to point Wiretrace at another
environment without finding the Terminal and without scanning the QR code again. Today
the preset is fixed by `./wiretrace start --preset …`, and the title bar only prints
the name.

## Acceptance criteria

- [ ] With `--ui wiretrace`, the title bar's preset label opens a menu of the presets in
      `presets/*.yaml` (the same names `list_presets` accepts). The current name is
      marked. Choosing it does nothing.
- [ ] Choosing a different name asks first. The dialog names the new preset, the hosts it
      will decrypt, and whether device logs will be on (the app name from the preset) or
      off (the preset has no `android_package` / `ios_process` for this target, or the
      target is `device`). It says the current session will be saved and the phone stays
      connected. Cancel leaves the session running.
- [ ] Confirm saves the session the way Ctrl+C does (`flows.har`, `meta.json` status
      `stopped` when the stop was clean), then starts a new session with the new preset
      and the same target, mode, proxy port, UI port, and `--client` list. The banner
      prints the new preset and its hosts. The WireGuard tunnel is not restarted.
- [ ] The new session has its own folder, its own `rules/<preset>.json`, its own mocks
      folder, its own device-log collector, and its own window token. The menu bar comes
      back on the new session. A new browser tab opens. The old tab says it is switching
      and does not keep reconnecting.
- [ ] An unknown or invalid preset is refused before anything stops. The message is the
      one `load_preset` already shows. The current session keeps running.
- [ ] While a previous session is open, the menu is off, with the same reason Setup and
      Rules already use. The request is refused with 409.
- [ ] A second confirm while a switch is already under way is refused with 409. One
      switch, then the new session.
- [ ] Ctrl+C, or **Stop session** in the menu bar, still ends Wiretrace. It does not
      start the preset that was just chosen, even if the request was already accepted.
- [ ] A session that captured nothing is still removed, and the new preset still starts.
      If `flows.har` cannot be written, the warning is the one printed today, `flows.mitm`
      is kept, and the new preset still starts.
- [ ] `--ui mitmweb` and `--no-ui` start, run, and stop as they do today. They have no
      preset menu and they never start a second session.
- [ ] The switch file holds only the preset name. It is not in the bug-report zip. The
      new token is passed the same way as today (environment for mitmdump, stdin for the
      menu bar) and is not written into the switch file, the Terminal, or a log line.

## Approach

The window lives inside mitmdump, and `cli/start.py` runs that one child and then
exits. A switch is a clean exit of that child plus a loop in the launcher, not a change
to the running proxy's `--allow-hosts`, rules, or save file.

The window asks over `POST /api/preset`. The addon checks the preset, writes
`sessions/<session>/.switch.json`, and then shuts mitmdump down (`ctx.master.shutdown()`).
The launcher finalizes the session as it already does. Only when that child exited
without a stop signal, and no stop signal arrived during the HAR write, does the
launcher read the file, delete it, and start the named preset.

Rejected:

- Changing `allow_hosts`, the mocks dir, and the rules file inside the open session.
  One HAR would then hold two environments, and the masking list in `meta.json` was
  copied at the start.
- Using SIGINT as the switch signal. SIGINT is already Ctrl+C and **Stop session**, and
  both must still exit.
- Keeping the same window token across the restart. The token is the capability for
  that process. The new process gets a new one, as every start does today.
- A native Mac app that keeps the window open. That is the shell around this loop, and
  it is not part of this spec.

## Design that needs care

The launcher already has one machine per session: `PREPARE → RUNNING → STOPPING →
KILLED → FINALIZING → DONE`. This spec adds a loop around it, only for
`--ui wiretrace`.

| After FINALIZING | Next |
|---|---|
| Child exited on its own (`RUNNING`), no stop signal during the HAR write, `.switch.json` names a preset `load_preset` accepts | Delete the file. `PREPARE` for that preset. Same target and mode. |
| Stop signal before the child exited (`STOPPING` or `KILLED`), or a stop signal during the HAR write | Delete the file. `DONE`. Do not start another session. |
| Child exited on its own and the file is missing, unreadable, or not a single preset name | `DONE`. A crash is not a switch. |
| File names a preset that fails `load_preset` the second time | Print that error. `DONE` with exit 1. Do not spawn. |

`supervise` keeps returning its exit code as an int. It also reports the child state
and whether a stop signal arrived during finalize, through a result the loop reads.
The test double in `tests/test_start.py` returns `0`; `run` treats that as "no switch"
so those tests stay one session.

### Invariants

1. A stop signal never starts another session. Ctrl+C and **Stop session** win over a
   switch file that is already on disk.
2. The preset is loaded and rejected in the addon before mitmdump is asked to exit. A
   failed check leaves the current session running and writes no file.
3. The launcher loads the preset again before the next process is spawned. A file that
   fails that check does not spawn, and the file is deleted.
4. `.switch.json` is `{"name": "<preset>"}` only, mode `0600`, written by a temporary
   file and `os.replace`. No token, no host list, no path.
5. At most one switch is in flight. The file's presence is that lock. A second POST
   gets 409.
6. The file is read before an empty session folder is removed, and it is deleted on
   every path, including stop and a failed re-check.
7. Each new session gets a new folder, a new token, a new menu bar, and a new
   collector. The old server is gone, so the old token no longer works.
8. Ports are checked before every spawn, including the second. A busy port prints the
   message `run` already prints and exits 1. No folder is left without a child.
9. `--ui mitmweb` and `--no-ui` do not read a switch file and do not loop.
10. The report zip is still built by member name, so `.switch.json` is not a member.

The signal handlers stay installed for the whole loop, as they are today: one install
before the first folder, restored when `run` returns. If the new folder name already
exists (the same second and the same preset name), `run` waits one second and tries
once more, then exits with the message it already prints.

### The window

`GET /api/presets` returns `{"presets": [{"name", "api_hosts", "device_logs", "app"}]}`
for the current target. `device_logs` is true when this target has a collector and the
preset has the matching app key. `app` is that package or process name, or null.
Nothing else from the YAML.

`POST /api/preset` with `{"name": "<preset>"}` uses the same checks as every other
mutation: Host, the token cookie, `X-Wiretrace: 1`. Then:

| Case | Result |
|---|---|
| A previous session is open | 409, no file |
| `load_preset` fails | 400, its message, no file |
| The name is the current preset | 204, no file, no shutdown |
| `.switch.json` already exists | 409, no shutdown |
| Otherwise | Write the file, respond 202 `{"switching": "<name>"}`, then shut mitmdump down |

The dialog is shown before the POST. After 202 the page shows "Switching to <name>…
This session is being saved. A new window will open." and stops reconnecting.

### Tests derived from the invariants

1. Stop signal, switch file present → file deleted, `run` does not spawn a second child.
2. Child exits on its own, file names a valid preset, no stop signal → second session,
   new folder, file gone, same target and mode.
3. Child exits on its own, no file → one session, as today.
4. File present, stop signal during finalize → no second session, file deleted.
5. File names an unknown preset → exit 1, the `load_preset` message, no second child,
   file deleted.
6. POST of an unknown preset → 400, shutdown not called, no file.
7. POST of the current name → 204, no file, no shutdown.
8. POST while a previous session is open → 409, no file.
9. Two POSTs → the second is 409, one file.
10. The file is mode `0600` and its body is only `{"name": "<preset>"}`.
11. POST without `X-Wiretrace` → 403, no file.
12. `GET /api/presets` lists names, hosts, and the device-log flag for this target, and
    no other preset keys.
13. `--ui mitmweb` and `--no-ui` do not loop when a switch file is left in the folder.
14. An empty capture still removes the folder, and a valid switch file still starts the
    next preset.
15. The title-bar control is off while a previous session is open.

## Files expected to change

Order: the decision and the loop, then the API, then the window, then the docs.

- `cli/session.py` — `SWITCH = ".switch.json"`.
- `cli/start.py` — the loop in `run` for `--ui wiretrace` only; read and delete the
  file; load the preset again; check ports again; one retry when the folder name
  exists. `supervise` still returns an int and also reports the child state.
- `addons/wiretrace_ui.py` — `GET /api/presets`, `POST /api/preset`, the file write,
  shutdown after the 202.
- `ui/src/types.ts`, `ui/src/api.ts` — the list and the POST.
- `ui/src/components/TitleBar.tsx` — the menu, disabled while viewing.
- `ui/src/components/SwitchPresetDialog.tsx` — the confirm dialog and the "Switching…"
  line. New file.
- `ui/src/App.tsx` (or the connection module that reconnects) — stop reconnecting after
  a 202.
- `tests/test_start.py` — invariants 1–5, 13, 14. The existing double that returns `0`
  stays "no switch".
- `tests/test_wiretrace_ui.py` — invariants 6–12.
- `ui/src` test for invariant 15.
- `ui/dist/` — rebuilt and committed, as with the other window specs.
- `docs/user-guide.md` — a short part under the Wiretrace window: the menu saves this
  session and starts the next, and the phone stays connected.
- `README.md` — the title-bar row in the design table: the preset label is a menu.

## Out of scope

- A Mac app, Tauri, or a window that stays open across the restart. The old tab stops
  and a new tab opens.
- Editing, creating, or deleting a preset file from the window.
- Changing target or mode from the window.
- A preset menu in the menu bar.
- Applying the new hosts to the session that is already open.
- The version number. Whichever release carries this sets it.

## Manual test

About 5 minutes, with two presets and an Android phone or emulator already connected.

1. `./wiretrace start --preset <A> --target android --ui wiretrace`. Open the preset
   menu, choose `<B>`, cancel. Traffic from A still arrives.
2. Choose `<B>` and confirm. The Terminal saves A's session and prints B's hosts. A new
   tab opens. A's tab says it is switching. The phone is still on the tunnel. A request
   from B's hosts appears in the new tab.
3. Ctrl+C. One session ends. Wiretrace does not start again.
4. Start with `--ui mitmweb`. There is no preset menu, and Ctrl+C ends the one session.

## Automated tests

The list in **Tests derived from the invariants**. `pytest` for `tests/test_start.py`
and `tests/test_wiretrace_ui.py`, and the UI unit test for the disabled control. No
device and no live mitmproxy are required for those.
