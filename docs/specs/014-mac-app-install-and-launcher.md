# Spec: a Wiretrace app icon, made by setup, that starts a session without Terminal

- **Summary**: installation stays as today (unpack, `scripts/setup-mac.sh` in Terminal). Its
  last step builds `~/Applications/Wiretrace.app` on the tester's Mac. Opening that app from
  Launchpad, Spotlight or the Dock asks for a project and a device and starts a session. The
  session menu bar is the way to stop it. The app is built locally, so it carries no
  quarantine flag and Gatekeeper never asks about it.
- **Date**: 2026-10-16 (scoped down the same day from a draft where the `.dmg` held an app
  that installed Wiretrace; that part is now out of scope)
- **Repo**: wiretrace
- **Status**: approved (2026-10-16; bundle identifier `com.safemeet.wiretrace`)
- **Tier**: L (a session can run with no Terminal, so the menu bar becomes the only stop; the
  window token must stay out of every file the app path writes). Gates E, A, B, C, R, P, D.
- **Branch**: `feature/app-launcher` (from `main`)
- **Related**: spec 001 (no-admin setup, `setup-mac.sh`); spec 002 (launcher states); spec 009
  (umask, token handling); spec 011 (menu bar, *Stop session* is a SIGINT to the launcher, the
  token is not on a command line); spec 013 (preset switch loop); `PLAN.md` U1 (the signed
  Tauri app stays the long-term plan).

## Goal

A tester who has installed Wiretrace once opens it later like any other Mac app: from
Launchpad, Spotlight or the Dock. She picks her project and her phone, and the window opens.
Day-to-day use needs no Terminal, no `cd`, and no command line to remember.

## Acceptance criteria

### The app is created by setup

- [ ] `scripts/setup-mac.sh` has a new step, `==> Wiretrace app (~/Applications)`, after the
      iOS tools step and before doctor. It creates `~/Applications/Wiretrace.app` (and
      `~/Applications` when missing) and prints `created: ~/Applications/Wiretrace.app`.
- [ ] Setup's last lines say: open Wiretrace from Launchpad or Spotlight; to keep it in the
      Dock, right-click its Dock icon → Options → Keep in Dock.
- [ ] Running setup again rebuilds the app with the current version. Running it from another
      folder (a moved or newer install) makes the app open that folder, and setup prints
      `Wiretrace.app now opens <new folder> (it opened <old folder>)`.
- [ ] An existing `~/Applications/Wiretrace.app` that Wiretrace did not make (another bundle
      identifier) is left as it is: setup prints a `WARN` line and goes on.
- [ ] If the app cannot be built, setup prints a `WARN` line with the reason and goes on.
      Setup's exit code stays doctor's.
- [ ] No step asks for a password or uses `sudo`. A standard account is enough.
- [ ] Opening the app shows no Gatekeeper dialog ("cannot be opened", *Open Anyway*).

### Start (every opening)

- [ ] The folder the app points to no longer holds Wiretrace → "Wiretrace is not in
      <folder> any more. In Terminal, run scripts/setup-mac.sh from its new folder." Quit.
- [ ] `.venv` is missing or broken → the `wiretrace` script's own message in a dialog
      ("Run scripts/setup-mac.sh first"). Quit.
- [ ] A recording session (from the app or from Terminal) → "Wiretrace is already recording
      <preset>. Use the ● Wiretrace menu at the top right to open the window or stop." Nothing
      else happens.
- [ ] Otherwise a list of projects: the presets `list_presets` accepts, without `example`.
      The last project used is selected. With no project, a dialog says to add one to the
      presets folder (user guide, Part 2) and offers *Open presets folder* and *OK*.
- [ ] Then a list of devices, the last one used selected:

      | Choice | `--target` | `--mode` |
      |---|---|---|
      | iPhone | `ios` | `wireguard` |
      | Android phone | `android` | `wireguard` |
      | iOS Simulator on this Mac | `ios-sim` | `proxy` |
      | Android emulator on this Mac | `android-emu` | `wireguard` |
      | Another device, with a Wi-Fi proxy | `device` | `proxy` |

- [ ] Cancel in either list quits and starts nothing.
- [ ] *Start* shows "Starting Wiretrace…" until the session records. Then the Wiretrace
      window opens in the browser and the menu bar item appears, as with `--ui wiretrace`
      today. A last dialog says "Wiretrace is recording <project>. Stop it from the
      ● Wiretrace menu at the top right." It closes by itself after 15 s, and the app quits.
- [ ] A start that fails (port in use, invalid preset, menu bar unavailable) shows the
      launcher's own message in a dialog. No session folder is left behind (as today).

### Session started from the app

- [ ] The menu bar item has no *Quit*. *Stop session* is in every state, including
      *Starting…* and *No status from Wiretrace*.
- [ ] If the menu bar process ends anyway (a crash, a force quit), the session stops and is
      saved as with Ctrl+C.
- [ ] If the menu bar cannot start, the session does not start: "The menu bar item could
      not start (<reason>). A session started from the app cannot be stopped without it."
- [ ] The window link with its token is not printed. It is in no file the app path writes.
- [ ] Switching the preset from the window (spec 013) works; the next session is also in app
      mode.
- [ ] `./wiretrace start` from Terminal, without the hidden flag, behaves and prints exactly
      as before this spec.

## Approach

**Setup compiles a small AppleScript applet on the tester's Mac.** `osacompile`, `plutil`
and `codesign` are part of macOS; none is an Xcode stub. A file a process creates locally
has no `com.apple.quarantine` flag, so Gatekeeper does not check the app. The installation
path stays exactly as today, and nothing changes in the release files.

**The applet is glue.** It reads the install folder from its own bundle, calls
`wiretrace app state` and `wiretrace app start`, and shows two lists and a few dialogs. The
logic is in Python, in `cli/app.py`, and is tested with pytest.

**Each opening is the launcher.** The applet starts the session detached and quits. While
the session runs, the existing session menu bar (spec 011) is the visible control. No
long-running launcher process.

Rejected:

- **The `.dmg` holds an app that installs Wiretrace** (the earlier draft): an unsigned
  download needs *Open Anyway* in System Settings, which still has to be checked against a
  standard account, plus an install and update flow. Deferred to a later spec; this one
  keeps installation as it is.
- **Tauri or a Swift app** (`PLAN.md` U1): a Rust toolchain or Xcode (admin to install), and
  signing to be worth it. Spec 011 rejected both for the same reasons.
- **A `.command` file or a shell script as the bundle executable**: a `.command` opens
  Terminal, and a shell script has no lists or dialogs.
- **A PyObjC launcher that stays in the menu bar when idle**: a second long-running process,
  a single-instance lock, and two status items to keep apart.
- **Building the app in `build-release.sh`**: the app would come from the download and be
  quarantined, which brings back *Open Anyway*.

## Design that needs care

### Building the app: `scripts/make-app.sh`

`setup-mac.sh` calls `scripts/make-app.sh`. The script uses its own folder's parent as the
install folder (as `setup-mac.sh` does) and `$HOME` from the environment, so tests run it
against a temporary home. The bundle identifier is `com.safemeet.wiretrace`.

1. `dest="$HOME/Applications/Wiretrace.app"`. If `dest` exists and its `CFBundleIdentifier`
   (`plutil -extract … raw`) is not ours, print the `WARN` line and exit 1.
2. Build in a temporary folder under `$HOME/Applications` (the same disk, so the final `mv`
   is a rename): `osacompile -o <tmp>/Wiretrace.app app/Wiretrace.applescript`.
3. Write `Contents/Resources/wiretrace-root`: the install folder's absolute path, one line.
4. `plutil -replace` sets `CFBundleIdentifier`, `CFBundleName` (`Wiretrace`) and
   `CFBundleShortVersionString` (from `cli/__init__.py`, read with `sed` as `build-release.sh`
   does: no Python is needed here).
5. `codesign --force --deep -s -` (ad-hoc). Editing `Info.plist` after `osacompile` breaks
   the applet's seal, which Apple silicon refuses to run.
6. Read the old `wiretrace-root` when `dest` exists, `rm -rf "$dest"`, `mv` the new bundle
   into place, and print `created:` or `now opens`.

The temporary folder is removed on every exit (`trap`). The script never touches extended
attributes: no file is copied into the bundle (the icon's bytes are written with `cat`), so
there is no quarantine flag to remove.

In `setup-mac.sh`, a non-zero exit from `make-app.sh` prints `WARN: Wiretrace app not
created (…)` and setup goes on. The step does not change setup's exit code.

### The applet: `app/Wiretrace.applescript`

1. Read `wiretrace-root` from `path to me`. If `<root>/wiretrace` does not exist → the "not
   in <folder> any more" dialog, quit.
2. `do shell script` `<root>/wiretrace app state`. An error → its text in a dialog, quit.
3. `running <preset>` → the "already recording" dialog, quit.
4. `choose from list` the projects, then the devices, preselecting `last`. Cancel → quit.
5. Show the progress window ("Starting Wiretrace…") and run `wiretrace app start --project …
   --device …`. Exit 0 with `started` or `starting` → the recording dialog (`giving up after
   15`), quit. Non-zero → its output in a dialog, quit.

Every argument goes through `quoted form of`. No notification is used: `display notification`
needs a permission per app.

### Start from the app: `wiretrace app start`

`wiretrace app start --project <name> --device <choice>` spawns
`python -m cli start --preset <name> --target … --mode … --ui wiretrace --from-app` with
`cwd` the install folder, `start_new_session=True`, stdin `/dev/null`, stdout and stderr to
`<root>/app-start.log` (truncated, `0600`). Then it polls every 0.25 s:

| Seen first | Result |
|---|---|
| A session folder created after the spawn has a fresh `.status.json` (`menubar.is_fresh`) | Write `.app-last` (`<project> <device>`), print `started`, exit 0 |
| The child exited | Print the last 15 lines of `app-start.log`, exit 1 |
| 90 s passed | Print `starting`, exit 0. The child keeps running |

It never signals or waits on the child after it returns. The child keeps the applet's
environment. Tools are already found without `PATH`: mitmdump and pymobiledevice3 from
`.venv/bin`, adb by `doctor.find_adb` (`~/tools/platform-tools`), and xcrun in `/usr/bin`.

`wiretrace app state` prints `running <preset>` when any `sessions/*/.status.json` is fresh,
else `idle`; then `project <name>` per preset (without `example`); then `last <project>
<device>` when `.app-last` names a project that still exists and a known device.

`.app-last` and `app-start.log` go into `.gitignore`.

### `start --from-app` in the launcher

A hidden flag. Effects, and nothing else:

1. Without `--ui wiretrace`, or when `menubar.availability()` gives a reason: print the
   message above and exit 1 before any folder exists.
2. mitmdump gets `--set qa_ui_print_link=false`. The addon still opens the browser; it prints
   `Wiretrace UI: opened in the browser` instead of the link.
3. The menu bar is started with `--app`. `render(..., app=True)` drops *Quit* and adds *Stop
   session* to STARTING and STALE.
4. When the menu bar child ends by itself while RUNNING, the launcher takes the stop path:
   it records one SIGINT in `stops`, as `on_stop` does, and prints "Menu bar closed; stopping
   the session (started from Wiretrace.app)."
5. Each session of the spec 013 loop gets the same flag.

### Invariants

1. A session started with `--from-app` is never RUNNING without a live menu bar child for
   more than one poll (`POLL_S`).
2. A menu bar exit is a stop, never a switch: spec 013 invariant 1 applies, because it lands
   in `stops`.
3. Without `--from-app`, `start` builds the same argv, prints the same lines and stops the same
   way as before.
4. The window token is in no file: not `app-start.log`, not `.app-last`, not the bundle.
5. `make-app.sh` writes only `~/Applications/Wiretrace.app` and its own temporary folder,
   and never replaces an app with another bundle identifier.
6. A failed `make-app.sh` never changes setup's exit code or skips doctor.
7. `app start` returns within 91 s and leaves no child it is waiting on.

### Tests derived from the invariants

1. `--from-app` with `--ui mitmweb` → exit 1, no folder.
2. `--from-app` with the menu bar unavailable → exit 1, the message, no folder.
3. `--from-app` → mitmdump argv has `qa_ui_print_link=false`; the menu argv has `--app`.
4. `--from-app`, menu child exits during RUNNING → the session stops, `meta.json` status
   `stopped`, HAR written, no second session even with a `.switch.json` present.
5. Without `--from-app` → argv and banner equal to today's (existing tests unchanged).
6. Addon with `qa_ui_print_link=false` → stdout has no `token=`.
7. `render(app=True)` in each state: no *Quit*; *Stop session* in STARTING, LIVE, STALE.
8. `app start`: status file appears → exit 0, `.app-last` written. Child exits 1 → exit 1,
   log tail printed, `.app-last` unchanged. Timeout (short in the test) → `starting`, exit 0.
9. `app start` device choices map to the table above; an unknown choice → exit 2.
10. `app state`: fresh status → `running`; stale → `idle`; `example` not listed; `.app-last`
    naming a deleted project is not printed.
11. `make-app.sh` with a temporary `HOME`: the app exists; `Info.plist` has the identifier and
    the version; `wiretrace-root` is the repo root; `codesign --verify` passes; `xattr` shows
    no `com.apple.quarantine`.
12. `make-app.sh` over our app made from another root → replaced, prints `now opens`.
13. `make-app.sh` over an app with another identifier → exit 1, the app unchanged.

Tests 11–13 run only on macOS with `osacompile` present; they are skipped elsewhere.

## Files expected to change

Order: the check below, then the launcher flag and the menu bar, then `cli/app.py`, then
`make-app.sh` and the applet, then setup, then the docs.

0. **Check, before any other file** (Gate R evidence, no commit): on this Mac, a hello-world
   applet built with steps 2–5 above into `~/Applications`. It opens with no Gatekeeper
   dialog, shows in Spotlight and Launchpad, and a PyObjC status item started from it with
   `start_new_session=True` survives the applet quitting. Note which firewall or
   local-network prompts appear when mitmdump starts from it. If any of this fails, stop and
   report.
- `cli/start.py` — `from_app` parameter: the refusal, the addon option, the menu argv, the
  menu-exit stop.
- `cli/__main__.py` — hidden `--from-app` on `start`; the `app` subcommand with `state` and
  `start` (help: "used by Wiretrace.app").
- `addons/wiretrace_ui.py` — `qa_ui_print_link` option, default `true`.
- `menubar/__init__.py` — `render(..., app=False)`.
- `menubar/__main__.py` — `--app` argument passed to `render`.
- `cli/app.py` — new: `state`, `start`, the device table.
- `app/Wiretrace.applescript` — new: the start flow above.
- `scripts/make-app.sh` — new: builds `~/Applications/Wiretrace.app`.
- `scripts/setup-mac.sh` — the new step, its `WARN` handling, the closing lines.
- `.gitignore` — `.app-last`, `app-start.log`.
- `tests/test_start.py`, `tests/test_menubar.py`, `tests/test_wiretrace_ui.py` — tests 1–7.
- `tests/test_app.py` — new: tests 8–10.
- `tests/test_make_app.py` — new: tests 11–13.
- `README.md` — Quick start: after setup, "Open Wiretrace from Launchpad"; the Terminal
  `start` stays as the alternative.
- `docs/user-guide.md` — Part 1: the app after setup, with a screenshot of the two lists
  (taken during Gate R); the update section (run setup again from the new folder); the
  uninstall line adds `~/Applications/Wiretrace.app`.
- `docs/install-without-admin.md` — what setup writes now includes
  `~/Applications/Wiretrace.app`.

`scripts/build-release.sh`, the `.tar.gz`, the `.dmg` and the `Makefile` do not change.

## Out of scope

- An app in the `.dmg` that installs or updates Wiretrace, *Open Anyway*, `Read me first.txt`
  (the earlier draft of this spec).
- Signing with a Developer ID and notarization.
- From the app: creating, editing or deleting a project; *Setup check…*; *Open sessions
  folder*; choosing WireGuard or proxy per phone; `--client`; `--no-menu-bar`.
- Starting at login, auto-update, uninstall.
- A doctor check for the app.

## Decided

The bundle identifier is `com.safemeet.wiretrace`. `make-app.sh` uses it to recognise its
own app, and a later signed app should keep it, so it does not change after the first release.

## Errata

- `wiretrace app state` also prints `device <label>` per row of the device table, in order,
  so the applet does not repeat the table. The labels are the `--device` values and the
  device part of `.app-last`.
- `wiretrace app start` prints `started` and `starting` to stdout and every failure to stderr:
  `do shell script` shows stderr as the error text when the exit code is not 0.
- With `--from-app`, a menu bar child that cannot be spawned at all (after the probe passed)
  stops the session as a menu exit does (invariant 1).
- The app shows the Wiretrace mark (added at the Orchestrator's request; it was out of
  scope). `app/icon.svg` is `ui/src/assets/mark.svg` on the macOS icon grid; `make icon`
  (`scripts/build-icon.sh`, needs `rsvg-convert`) builds the committed `app/Wiretrace.icns`.
  `make-app.sh` writes its bytes to `Contents/Resources/applet.icns` and removes
  `CFBundleIconName`, which would otherwise select the default script icon in `Assets.car`.
- 2026-10-16, before 0.9.0, at the Orchestrator's request: setup opens the app when it was
  created and doctor passed, unless `--no-open` is given or stdout is not a terminal; when
  `open` fails it prints the Launchpad line instead. The last lines no longer tell everyone to
  open a new Terminal window: Wiretrace finds `adb` in `~/tools` without the `PATH` lines, so
  that line now says it is only for typing `adb` or `uv`. The closing lines are
  `finish()` in `setup-mac.sh`, tested with a stub `open` in `tests/test_doctor.py`.
  Tested: the icon is the committed file, and a quarantined source folder gives an app with
  no quarantine flag.

## Manual test

About 10 minutes on a **standard** account, with an Android phone or the iOS Simulator.

1. Unpack the `.tar.gz` (or drag the folder from the `.dmg`) into the home folder, run
   `scripts/setup-mac.sh`. The `==> Wiretrace app` step prints `created:`. No password.
2. Close Terminal. Open Wiretrace from Spotlight: no Gatekeeper dialog. Choose the project
   and the device. The window opens, ● Wiretrace shows in the menu bar, the recording
   dialog closes by itself. Traffic arrives.
3. Open Wiretrace from Launchpad while recording → "already recording".
4. *Stop session* in the menu bar. `flows.har` is in the session folder. Open Wiretrace
   again: the last project and device are selected.
5. Start with the Wi-Fi proxy port taken (run a Terminal session first): the dialog shows
   the port message, and no new session folder exists.
6. Force quit the menu bar's Python process during a session: the session stops and is saved.
7. `grep -c 'token=' ~/wiretrace/app-start.log` prints `0`.
8. Rename `~/wiretrace` to `~/wiretrace-2`, open Wiretrace → the "not in … any more" dialog.
   Run `scripts/setup-mac.sh` there → `now opens`; the app works again.

## Automated tests

The list in **Tests derived from the invariants**: `pytest` for `tests/test_start.py`,
`tests/test_menubar.py`, `tests/test_wiretrace_ui.py`, `tests/test_app.py` and
`tests/test_make_app.py`. No device, no network and no live mitmproxy are needed. The applet
and Gatekeeper are covered only by the check before implementation and the manual test.
