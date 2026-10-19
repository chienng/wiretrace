# Spec: Wiretrace.app stays in the Dock while a session records

- **Summary**: Wiretrace.app no longer quits as soon as its session starts. It stays open,
  with its Dock icon, while a session records, and quits by itself shortly after none does.
  The tester can then keep it in the Dock the usual way: right-click the icon → **Options**
  → **Keep in Dock**.
- **Date**: 2026-10-19
- **Repo**: wiretrace
- **Status**: approved (2026-10-19)
- **Tier**: M (one feature in one repo: the applet, its build flag, docs). No token, file
  format, window or capture change. Gates A, C, R, P.
- **Branch**: `feature/app-stays-in-dock`, from `main` (`975b046`, spec 019 merged).
- **Related**: spec 014 (Wiretrace.app; the menu bar is the only stop of an app session);
  spec 018 Extension A (the app starts the last choice, no dialogs); spec 019 (no dialog
  after a successful start).

## Goal

Since spec 019 the app shows no dialog after a successful start, so it quits within about 5
seconds, and its Dock icon goes with it. The tester cannot right-click the icon to keep it in
the Dock: the icon is gone before the menu opens, and a click that lands as the app quits
can untick **Keep in Dock** on a pin that already exists. The Dock icon should also show
whether Wiretrace is running, as other Mac apps do.

## Acceptance criteria

- [ ] After a start from the app (`started` or `starting`), the app stays open: its icon
      stays in the Dock with the running dot while the session records.
- [ ] Right-click → **Options** → **Keep in Dock** on that icon keeps Wiretrace in the Dock
      after the app quits, after a Dock restart, and after `./install` runs again.
- [ ] A preset or device switch in the window does not make the app quit.
- [ ] When the session stops (menu bar **Stop session**, Ctrl+C on a Terminal session, or a
      crash), the app quits by itself within 20 seconds.
- [ ] A click on the Dock icon while the app is open shows the existing dialog "Wiretrace is
      already recording <preset>. Use the Wiretrace menu (the W icon at the top right) to
      open the window or stop." and the app stays open.
- [ ] Opening the app while a session already records (from Terminal, or after quitting the
      app) shows that same dialog, then the app stays open until the session stops.
- [ ] Quitting the app (Dock → **Quit**, or ⌘Q) never stops the session: the menu bar stays
      the only stop.
- [ ] A start that fails, a missing or moved install, and "No project yet" show their
      dialogs as today, then the app quits.
- [ ] No progress window stays on screen after the start.
- [ ] The README, the user guide and the setup's closing line say: while Wiretrace records,
      right-click its Dock icon → **Options** → **Keep in Dock** (or drag it from
      `~/Applications` onto the Dock at any time).

## Out of scope

- A Dock click that opens the window directly. The window's token lives only in the
  launcher and the menu bar process; handing it to the applet needs a new channel in a
  sensitive area. The dialog points to the menu's **Open Wiretrace** instead.
- Quit from the Dock stopping the session (it would need a second stop path besides the
  menu bar, spec 014).
- A Dock menu with Stop or Switch items.

## Design

The applet becomes a stay-open applet (`osacompile -s`, which sets `OSAAppletStayOpen`). Its
`run` handler does what it does today; the paths that end with no session call `quit`
explicitly. An `idle` handler checks `wiretrace app state` every 5 seconds and quits after
the state has been `idle` for three checks in a row.

States of the applet, after `run`:

| State | Entered when | Leaves when |
|---|---|---|
| Watching | `run` started a session (`started` / `starting`) or found one recording | `idle` sees no recording session 3 times in a row → Quit |
| Quit | `run` ended without a session (error, no project), or Watching ended, or the user quits | — |

Why three checks of 5 seconds: a status file counts as fresh for 5 seconds
(`menubar.FRESH_S`), and a switch saves one session and starts the next one in a new
folder, so `app state` can read `idle` for a few seconds during a switch. Three idle checks
(10–15 seconds of `idle`) cover that gap and still quit within 20 seconds of a real stop. A
check that fails (the CLI errors) counts as idle, so a moved or broken install cannot keep
the app open for ever.

`reopen` (a Dock click while open) shows the "already recording" dialog when a session
records. The idle handler's counter is reset by any check that sees a recording session.

The progress bar is cleared (`progress total steps` 0, empty descriptions) before `run`
returns, so the stay-open applet does not leave its progress window up.

Rejected:

- A `wiretrace app wait` command that blocks until the session ends: a blocking
  `do shell script` makes the applet "not responding" in the Dock, and it cannot answer
  `reopen` or ⌘Q.
- Watching the launcher's process ID: the applet would need it from `app start`, and a
  session started in Terminal has none to give; `app state` already answers "is anything
  recording" for both.
- Docs only (drag from `~/Applications`): it works, but every tester first tries the Dock
  icon, and the running dot is lost.

## Invariants

1. The applet never stops, signals or writes to a session: it only runs `app state` and
   `app start`, as today.
2. The applet quits within 20 seconds after `app state` stops reporting a recording session,
   and never during a switch that completes within 10 seconds.
3. No path leaves the applet open without a recording session for more than 20 seconds.
4. The applet logs nothing; the token is never passed to it.

## Tests

`tests/test_make_app.py`:
1. `make-app.sh` compiles with `-s`, and the built `Info.plist` has `OSAAppletStayOpen`
   true (the existing temporary-HOME build).
2. The applet source has `on idle` and `on reopen` handlers, calls `quit` on each
   error / no-project path, and clears the progress bar before `run` returns.

`tests/test_doctor.py`:
3. The setup's closing lines mention **Keep in Dock** on the Dock icon while Wiretrace
   records (and the drag from `~/Applications`).

## Files to change

`app/Wiretrace.applescript`, `scripts/make-app.sh` (`-s`), `tests/test_make_app.py`,
`scripts/setup-mac.sh` (closing line), `tests/test_doctor.py`, `README.md` (step 4),
`docs/user-guide.md` (the app section), spec 014's Keep in Dock criterion and spec 019's
summary (a one-line note each pointing here).

## Manual test (Gate R, ~5 minutes)

Build into a temporary HOME (`HOME=$(mktemp -d) scripts/make-app.sh`) and open that bundle,
so the installed app is left alone.

1. Open the app: the session starts, the icon stays in the Dock with a dot, no progress
   window remains. Right-click → Options → Keep in Dock.
2. Switch the device in the window: the icon stays.
3. Click the Dock icon: the "already recording" dialog; OK; the icon stays.
4. Stop the session from the menu bar: the app quits within 20 seconds; the pinned icon
   stays without a dot. Restart the Dock: still there.
5. Start a session in Terminal, then open the app: the dialog, and the app stays until
   Ctrl+C.
6. ⌘Q the app during a session: the session keeps recording.
