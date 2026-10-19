# Spec: switch the device from the window

- **Summary**: the title bar's target pill becomes a device menu. Choosing another device
  saves the current session and starts a new one for that device, with the same preset,
  mode, ports and `--client` list. It reuses spec 013's switch file and launcher loop; the
  file now names the target as well as the preset. One device per session.
- **Date**: 2026-10-19
- **Repo**: wiretrace
- **Status**: approved (2026-10-19). Extension A (Wiretrace.app starts without dialogs): approved (2026-10-19).
- **Tier**: L (a window action stops the capture process; the launcher's loop changes what
  it restarts with; the switch file's format changes). Gates E, A, B, C, R, P. D n/a (one repo).
- **Branch**: `feature/switch-device`, from `main` after spec 017's merge (`5581416`).
- **Related**: spec 004 (one collector per session, chosen by `--target`); spec 008 (no target
  or mode switch at run time — this spec lifts the target half); spec 013 (switch preset:
  `.switch.json`, the loop in `run`, invariants 1–10); spec 014 (Wiretrace.app maps the device
  choice to `--target`/`--mode`); spec 017 (mode `both`, the new default: Wi-Fi proxy and
  WireGuard in one session)

## Goal

QA test the same build on an iPhone and an Android phone. Today the device is fixed by
`--target` when Wiretrace starts (the app's *Device* dialog), so moving to the other phone
means stopping the session and starting Wiretrace again. The tester should switch from the
window in a few seconds, without the Terminal or the app's dialogs.

Traffic capture does not depend on the device: since spec 017 every device in the app
starts in mode `both`, and both phones can use the same Wi-Fi proxy or the same WireGuard
tunnel keys. What the target decides is the device-log
collector (`pymobiledevice3` or `adb`), the screenshot tool, the setup hints, and the
target recorded in `meta.json` and in bug reports. So the switch is a new session, not a
new tunnel.

## Acceptance criteria

- [ ] With `--ui wiretrace`, the title bar's target pill (today `ios · WireGuard`) is a menu
      button that reads `<device label> · <mode>`. It lists iPhone, Android phone, Android
      emulator, iOS Simulator and Another device. The current one is marked *In use*;
      choosing it does nothing.
- [ ] Each row says whether device logs will be on for the current preset (the app name) or
      off and why (the text `collector_command` gives today: `add app.android_package to the
      preset`, `adb not found`, `--target device has no device log`).
- [ ] In `--mode wireguard`, iOS Simulator is shown disabled with the reason "The iOS
      Simulator needs the Wi-Fi proxy: stop and start Wiretrace for it". Every device is
      allowed in `both` and `proxy`, and every other device in `wireguard`.
- [ ] Choosing another device asks first. The dialog names the device, the device-log line,
      and what to do on the phones:
      - `wireguard`: "Turn the WireGuard tunnel off on the <old device>, then on on the
        <new device>. First time on this phone: scan the QR code in Setup."
      - `proxy`: "Remove the Wi-Fi proxy on the <old device> first: the first device that
        connects is the one accepted." (only when the proxy is pinned, i.e. no `--client`)
      - `both`: "Disconnect the <old device> (Wi-Fi proxy off, or tunnel off), then connect
        the <new device> the same way. First time on this phone: follow Setup." plus the
        pinning sentence above when the proxy is pinned.
      It says the current session is saved. Cancel leaves the session running.
- [ ] Confirm saves the session the way a preset switch does (`flows.har`, `meta.json` status
      `stopped`), then starts a new session with the new target and the same preset, mode,
      proxy port, UI port, `--client` list and `--from-app`. The banner prints the new target.
      The new session has its own folder (named with the new target), collector for the new
      target, window token, menu bar and browser tab. The old tab says "Switching to
      <device>… This session is being saved. A new window will open." and stops reconnecting.
- [ ] In `proxy` or `both` mode with pinning, the new process accepts the first Wi-Fi proxy
      client that connects, so the other phone is no longer refused after a switch.
- [ ] While a previous session is open, the device menu is off with the same reason Setup,
      Rules and the preset menu use; the request is refused with 409.
- [ ] A second switch (device or preset) while one is in flight is refused with 409.
- [ ] Ctrl+C, or **Stop session** in the menu bar, still ends Wiretrace and does not start
      the chosen device, even if the request was already accepted.
- [ ] Switching presets keeps working as in spec 013 and keeps the current target.
- [ ] `--ui mitmweb` and `--no-ui` have no device menu and never start a second session.
- [ ] The switch file holds only the preset name and the target. It is not in the bug-report
      zip. No device serial, UDID or device name is read or written by the switch.

## Approach

Extend spec 013's mechanism instead of building a second one. `POST /api/device` checks the
target and the current preset, writes `.switch.json` with `{"name": <current preset>,
"target": <new target>}`, and shuts mitmdump down. The launcher finalizes the session as
today, reads the file, checks the preset and the target again, and starts the next session
with both. The preset switch writes the same two keys, with the current target.

Rejected:

- Swapping only the collector inside the live session: one session would hold two phones'
  traffic and logs, and `meta.json`'s target (used by reports and screenshots) would be wrong
  for part of it. The collector would also need a restart path mid-RUNNING.
- Capturing both phones at once: the phones cannot share one WireGuard key pair while both
  are on; it needs two tunnels, two QR codes, two collectors and per-device labels. Much
  larger; not what was asked.
- A second switch file for devices: two files means two locks and an order between them.
  One file is one lock (spec 013 invariant 5).
- Changing mode with the device: different ports and a different phone setup (tunnel vs
  Wi-Fi proxy); a restart from the app is clearer for that.
- A switch in the menu bar or in Wiretrace.app: Orchestrator chose the window only.

## Design that needs care

The launcher's per-session machine and spec 013's loop stay as they are. Only what the loop
carries changes: a `(preset, target)` pair instead of a preset name.

| After FINALIZING | Next |
|---|---|
| Child exited on its own (`RUNNING`), no stop signal during the HAR write, `.switch.json` is exactly `{"name": str, "target": str}`, `load_preset` accepts the name, the target is allowed for the mode | Delete the file. `PREPARE` with that preset and target. Same mode. |
| Stop signal before the child exited, or during the HAR write | Delete the file. `DONE`. |
| File missing, unreadable, too large, not JSON, or not exactly those two string keys | `DONE`. A crash is not a switch. |
| File names a preset that fails `load_preset`, or a target not in `TARGETS`, or a target not allowed for the mode | Print the error. `DONE` with exit 1. Do not spawn. |

`take_switch` returns a small `Switch(name, target)` NamedTuple or None. `Outcome.switch_to`
holds that. `target_problem(target, mode) -> str | None` in `cli/start.py` is the one rule for
"allowed for the mode"; the addon and the launcher both call it.

### Invariants

Spec 013's invariants 1–10 still hold. Changed or added:

1. (013 inv. 4, changed) `.switch.json` is `{"name": "<preset>", "target": "<target>"}`
   only, mode `0600`, written by a temporary file and `os.replace`. Both kinds of switch
   write both keys. No token, host list, path, serial or UDID.
2. The target is checked against `TARGETS` and `target_problem` in the addon before the file
   is written, and again in the launcher before anything is spawned. It reaches a folder
   name and the collector's argv only after both checks. The collector argv stays a list
   (no shell).
3. The device switch also loads the current preset in the addon first. A preset file broken
   since the start is refused with 400 and its message; the session keeps running and no
   file is written. (Otherwise the launcher would exit and leave the tester with nothing.)
4. The mode, proxy port, UI port, `--client` list and `--from-app` never change across a
   switch.
5. A device switch to the current target writes nothing and does not shut down (204).
6. Device and preset switches share one lock: the file's presence and `self.switching`.
   No `await` between the in-flight check and the write (`start_switch`).

### The window

`GET /api/devices` returns `{"devices": [{"target", "label", "allowed", "why_not",
"device_logs"}]}` for the current preset and mode, in the order of `TARGETS_SHOWN`
(`ios`, `android`, `android-emu`, `ios-sim`, `device`). `label` comes from `TARGET_LABELS`
in `cli/start.py` (iPhone, Android phone, Android emulator, iOS Simulator, Another device).
`device_logs` is a display string: `<app>` when `collector_command` returns a command,
`off (<reason>)` otherwise. Tool lookups run in a thread. Nothing else from the preset.

`POST /api/device` with `{"target": "<target>"}`, same guards as every mutation (Host, token
cookie, `X-Wiretrace: 1`):

| Case | Result |
|---|---|
| A previous session is open, or no session folder | 409, no file |
| Body is not `{"target": str}`, or target not in `TARGETS` | 400 "Unknown device", no file |
| `target_problem` refuses it for this mode | 400, that message, no file |
| The current preset fails `load_preset` | 400, its message, no file |
| The target is the current one | 204, no file, no shutdown |
| A switch is already in flight | 409, no shutdown |
| Otherwise | Write the file, 202 `{"switching": "<preset>", "target": "<target>"}`, then shut mitmdump down |

The title bar's pill becomes `DeviceMenu` (same popover pattern and classes as
`PresetMenu`, same `seen` tone). Rows: label, `device_logs` as the sub line, *In use* on the
current one, disabled rows show `why_not`. Footer: "Another device saves this session and
starts a new one with the same preset." `SwitchDeviceDialog` mirrors `SwitchPresetDialog`
("Save and switch"). After 202 the store's `switching` state carries the device label so the
old tab's message names it.

### Tests derived from the invariants

Launcher (`tests/test_start.py`):

1. Child exits on its own, file `{"name": A, "target": "android"}` → second session with
   target `android`, same preset and mode, new folder, file gone, collector built for
   `android`.
2. Stop signal with that file present → no second session, file deleted.
3. File with only `{"name"}`, an extra key, or a non-string target → one session, exit as
   today.
4. File with target `"phone"` → exit 1, message, no second child, file deleted.
5. `wireguard` mode, file with target `ios-sim` → exit 1, message, no second child. In
   `both` and `proxy` mode the same file starts an `ios-sim` session.
6. A preset switch (file with the current target) still behaves as spec 013 tests 2 and 14.
7. `mode`, ports, `clients` and `from_app` passed to the second `supervise`/`build_command`
   equal the first.

Addon (`tests/test_wiretrace_ui.py`):

8. POST `{"target": "android"}` from an `ios` session → 202, file body exactly
   `{"name": <preset>, "target": "android"}`, mode `0600`, shutdown called.
9. POST of the current target → 204, no file, no shutdown.
10. POST of an unknown target, a missing key, or a non-string → 400, no file.
11. POST `ios-sim` in `wireguard` mode → 400 with the Wi-Fi proxy message, no file; in
    `both` mode → 202.
12. POST while a previous session is open → 409, no file.
13. POST after a preset switch is in flight (and the reverse) → 409, one file.
14. POST without `X-Wiretrace` → 403, no file.
15. Current preset file broken → 400 with `load_preset`'s message, no file, no shutdown.
16. `GET /api/devices`: five rows in order, labels, `ios-sim` disabled in `wireguard` mode
    only, `device_logs` text for a preset with and without `android_package`; no other
    preset keys.
17. `POST /api/preset` now writes `{"name", "target"}` with the current target.

UI (vitest):

18. Device menu disabled while a previous session is open.
19. Dialog text for `wireguard`, `proxy` and `both`, including the pinning sentence only
    when `/api/state.proxy_pin` is true.
20. (addon) `/api/state.proxy_pin` is true in `proxy` and `both` mode without `--client`,
    false with `--client` and in `wireguard` mode (`qa_proxy_pin` exists only when
    `proxy_guard` is loaded).

## Files expected to change

Order: the launcher, then the addon, then the window, then the docs.

- `cli/start.py` — `TARGET_LABELS`, `TARGETS_SHOWN`, `target_problem`; `Switch` NamedTuple;
  `take_switch` parses and returns both keys; `Outcome.switch_to: Switch | None`; the loop in
  `run` reloads the preset, checks the target, sets `target`; the "Switching…" Terminal line
  names the device when the target changed. Module docstring cites this spec.
- `cli/session.py` — the `SWITCH` comment: `{"name", "target"}`.
- `addons/wiretrace_ui.py` — `write_switch_file(path, name, target)`; `start_switch(name,
  target)`; preset switch and preset edit pass the current target; `GET /api/devices`,
  `POST /api/device` (`DeviceSwitch` handler); refusal texts that say "preset" become neutral
  where shared ("Switching is off while a previous session is open"); `proxy_pin` in
  `/api/state`.
- `ui/src/types.ts`, `ui/src/api.ts` — `DeviceInfo`, `devices()`, `switchDevice(target)`.
- `ui/src/components/TitleBar.tsx` — `DeviceMenu` in place of the target pill.
- `ui/src/components/SwitchDeviceDialog.tsx` — new.
- `ui/src/logic/devices.ts` (+ test) — dialog text per mode; menu state while viewing.
- `ui/src/store.ts` (or where `switching` lives) — carry an optional device label.
- `ui/dist/` — rebuilt and committed.
- `tests/test_start.py`, `tests/test_wiretrace_ui.py` — tests 1–17 and 20.
- `docs/user-guide.md` — under the Wiretrace window: switching device, disconnect one phone
  and connect the other, one session per device.
- `README.md` — the title-bar row: the target pill is a device menu.

## Out of scope

- Changing mode from the window; a device switch in the menu bar or in Wiretrace.app.
- Updating `.app-last` (Extension A adds it).
- Two devices in one session, or two tunnels.
- Choosing which of two connected phones of the same kind the collector reads (it keeps its
  `several` state).
- Resetting the proxy pin without changing device.
- The version number.

## Manual test

About 5 minutes, with an iPhone and an Android phone on the Mac's Wi-Fi (the Android
also with the WireGuard tunnel installed), and a preset with both `ios_process` and
`android_package`.

1. Start from Wiretrace.app with that project and *iPhone* (mode `both`). Set the iPhone's
   Wi-Fi proxy, open the app: requests and iPhone device logs arrive.
2. Open the device menu: five devices, iPhone *In use*, all enabled. Choose Android phone,
   cancel: capture continues.
3. Choose Android phone, confirm. The old tab says it is switching. A new tab opens with
   `Android phone · Proxy + WireGuard`. Remove the iPhone's proxy, turn the tunnel on on
   the Android: requests and Android device logs arrive. `sessions/` has two folders, the
   first `stopped` with target `ios`, the second with target `android`.
4. Switch back to iPhone and set its proxy again: it is accepted (the pin was reset). Then
   **Stop session** in the menu bar: one session ends, nothing starts again.
5. `./wiretrace start --preset <p> --target ios --mode wireguard --ui wiretrace`: iOS
   Simulator is disabled with the Wi-Fi proxy reason. Ctrl+C.
6. Start with `--ui mitmweb`: no device menu; Ctrl+C ends the one session.

## Automated tests

The list in **Tests derived from the invariants**. `pytest` for `tests/test_start.py` and
`tests/test_wiretrace_ui.py`, vitest for the UI logic. No device and no live mitmproxy.

---

## Extension A: Wiretrace.app starts without dialogs

### Goal

Once the window can switch project (spec 013) and device (this spec), the app's two lists
at startup, *Project* then *Device*, only pick the first session. QA open the app many
times a day and almost always accept what is preselected. The app should start straight
away with the last project and device used, and the tester changes either from the window.
A first-time tester picks their phone in the Setup wizard instead of in an app dialog.

### Acceptance criteria

- [ ] Opening Wiretrace.app shows no list. It starts a session at once (the progress
      window "Starting Wiretrace…" with `<project>, <device>`), then the window opens.
- [ ] The project is the last one used if it is still in the project list, else `default`
      if listed, else the first listed. With no project at all, the app shows today's "No
      project yet" dialog. (`example` stays hidden, as today.)
- [ ] The device is the last one used if it is still in the app's device table, else
      iPhone.
- [ ] The last project and the last device are remembered separately: a deleted project
      does not forget the device, and the other way round.
- [ ] A switch in the window (project or device) in a session started from the app updates
      what the app remembers, so the next start uses it. A session started from the Terminal
      never changes it.
- [ ] Already recording: today's "Wiretrace is already recording …" dialog, unchanged.
- [ ] The closing dialog reads "Wiretrace is recording <project> on <device>. Change either
      from the window's title bar. Stop it from the Wiretrace menu (the W icon at the top
      right)." It still closes itself after 15 s.
- [ ] A start that fails shows today's error dialog with the log's last lines. For a project
      that no longer loads, that is `load_preset`'s message, as today.
- [ ] Setup wizard, *Choose device*: when the chosen card is not the session's device, a box
      under the cards says "This session collects <current device> logs." with a **Use
      <device> for this session** button. It opens the same confirm dialog as the title-bar
      menu and sends the same `POST /api/device`. The button is disabled, with the reason,
      when `/api/devices` marks that device not allowed, and while a previous session is
      open. The *Device logs* step's "started with `--target …`" note becomes the same button.
- [ ] After a switch started from the wizard, the new tab opens the Setup wizard on
      *Connect to this Mac* for the new device. A switch from the title bar opens the new tab
      as today.

### Approach

`wiretrace app state` gains one line, `next <project> <device>`: the choice `app start`
should get, computed in Python (`next_choice`). The applet drops both `choose from list`
calls and passes that line's values to `app start --project … --device …`, whose contract
does not change. The other `state` lines stay (tests and older applets read them).

`.app-last` keeps its format, `<project> <device label>`, written by `app start` on success
as today. The launcher also writes it in the switch loop when `from_app` is set: after the
preset and target re-checks pass and the ports are free, before the spawn. It maps the
target back to the device label through the app's device table (targets are unique in it).

The wizard's resume uses a one-shot localStorage entry on the window's origin (the UI port
does not change across a switch): `{"step": "connect", "at": <ms>}`, written just before the
`POST /api/device` from the wizard, read and removed by the new tab on load, ignored when
older than 2 minutes.

Rejected:

- `app start` with no arguments choosing by itself: the applet's progress line needs the
  names before the start, and `app start`'s contract and tests stay as they are.
- Always starting `default` and forgetting the last project: a tester on staging would
  switch after every start.
- Detecting the phone over USB: QA testing both phones often have both plugged in, so it
  falls back to the last device anyway.
- Keeping the lists behind a modifier key (Option-click): hidden, and the window already
  switches both.
- Opening the window from the app when a session is already recording: the token lives in
  the menu-bar process; out of scope.

### Invariants

A1. The applet shows no `choose from list`. Its only dialogs are: incomplete or moved
    install, no project, already recording, start failed, and the closing dialog.
A2. `next_choice` uses only `projects()` and the app's device table. A name not in those is
    never passed to `app start`.
A3. `.app-last` is written only for sessions started from the app: by `app start` after the
    status file appears (as today), and by the launcher after a switch passes its re-checks.
    Same format, temporary file and `os.replace`, never a token. An `OSError` while writing
    is ignored: the session matters more.
A4. Reading `.app-last` takes the project and the device independently; an unknown or
    missing part falls back on its own.
A5. The wizard's button reuses `POST /api/device` and the confirm dialog: no new endpoint,
    no switch without confirmation.
A6. The resume entry holds only a step name and a time. A missing, malformed or old entry
    means the new tab opens as today.
A7. `cli/start.py` imports from `cli/app.py` inside the function that writes `.app-last`:
    `cli/app.py` already imports `cli/start.py` at module level.

### Tests derived from the invariants

`tests/test_app.py`:

A-1. `next_choice`: last project listed → it; last project deleted → `default`; no
     `default` → first listed; none → no `next` line.
A-2. Last device unknown or missing → iPhone; last project deleted → the device is kept.
A-3. `app state` prints `next <project> <device>` after the existing lines; `example` is
     never chosen.

`tests/test_start.py`:

A-4. `from_app`, device switch → `.app-last` holds the same project and the new device label,
     written before the second spawn.
A-5. `from_app`, preset switch → `.app-last` holds the new project and the same device.
A-6. Not `from_app` → `.app-last` untouched after a switch.
A-7. Switch refused by a re-check (exit 1) → `.app-last` untouched.
A-8. `.app-last` not writable → the second session still starts.

`tests/test_make_app.py`:

A-9. The compiled applet's source has no `choose from list` and calls `app start` with the
     values of the `next` line.

UI (vitest):

A-10. Wizard box shown only when the chosen card's target differs from the session's;
      button disabled with `why_not`, and while viewing.
A-11. Resume entry: fresh → open Setup at Connect and remove it; older than 2 minutes,
      malformed or absent → nothing.

### Files expected to change

- `cli/app.py` — `next_choice`, independent reads of `.app-last`, `next` line in `state`,
  a target → label lookup for the launcher.
- `cli/start.py` — in the switch loop, when `from_app`, write `.app-last` before the spawn.
- `app/Wiretrace.applescript` — no lists; parse `next`; new closing text. Rebuilt by
  `scripts/make-app.sh` on the tester's Mac, as today.
- `ui/src/components/SetupWizard.tsx`, `ui/src/logic/setup.ts` (+ test) — the box and
  button on *Choose device* and *Device logs*; writing and reading the resume entry.
- `ui/src/App.tsx` — open Setup at Connect when a fresh resume entry is found.
- `ui/dist/` — rebuilt and committed.
- `tests/test_app.py`, `tests/test_start.py`, `tests/test_make_app.py` — A-1 to A-9.
- `docs/user-guide.md`, `README.md` — the app starts at once with the last project and
  device; change them from the window.
- `docs/specs/014-mac-app-install-and-launcher.md` — one line under Status: the lists were
  removed by spec 018 Extension A.

### Out of scope

- A device or project switch in the menu bar.
- Opening the window from the app while a session is recording.
- Terminal `./wiretrace start` defaults (`--preset` stays required, `--target` stays
  `device`).

### Manual test

About 5 minutes, after `scripts/setup-mac.sh` rebuilt the app.

1. Delete `.app-last`. Open Wiretrace.app: no list; it starts `default` on iPhone; the
   window opens.
2. In Setup, choose Android: the box offers **Use Android for this session**. Use it and
   confirm. The new tab opens Setup on *Connect to this Mac* for Android.
3. Switch the project to another preset from the title bar. Stop from the menu bar.
4. Open the app again: it starts that preset on Android phone, with no list.
5. Delete that preset file. Open the app: it starts `default` on Android phone.
6. With a session running, open the app: the "already recording" dialog.

### Automated tests

A-1 to A-11 above, with `pytest` and vitest. No device and no live mitmproxy.
