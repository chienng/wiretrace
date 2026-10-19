# Spec: the app's closing dialog becomes a hint in the window

- **Summary**: Wiretrace.app stops showing a dialog after every successful start. The
  window of a session started from the app shows the same advice once, as a strip under the
  title bar, until the tester dismisses it; after that, the *Recording* label keeps it as a
  tooltip. (Without that dialog the app quit within seconds of the start; spec 020 keeps it
  open while the session records.)
- **Date**: 2026-10-19
- **Repo**: wiretrace
- **Status**: approved (2026-10-19)
- **Tier**: M (one feature in one repo: the applet, one launcher option, one `/api/state`
  field, one window strip). No token, file format or capture change. Gates E, A, C, R, P.
- **Branch**: `feature/app-hint-in-window`, from `main` (`a29f2f9`).
- **Related**: spec 014 (Wiretrace.app, the menu bar is the only stop of an app session);
  spec 018 Extension A (the closing dialog's current text, the switch loop keeps `from_app`).

## Goal

Every start from Wiretrace.app ends with a dialog: "Wiretrace is recording default on
iPhone. Change either from the window's title bar. Stop it from the Wiretrace menu (the W
icon at the top right)." It must be clicked away (or waits 15 seconds) each time, although
the advice matters only until the tester knows it. The advice belongs in the window, where
the title bar it points to is, and it should go away for good once read.

## Acceptance criteria

- [ ] A start from the app that reports `started` shows no dialog: the progress bar ends
      and the window opens.
- [ ] The app's other dialogs stay as they are: incomplete or moved install, no project,
      already recording, start failed. A start that reports `starting` (the window is not
      up yet) keeps a dialog, without the advice: "Wiretrace is still starting <project> on
      <device>. The window opens when it is ready."
- [ ] The window of a session started from the app shows a strip under the title bar:
      "Started from the Wiretrace app. Change the preset or the device here in the title
      bar. To stop and save the session, use the Wiretrace menu (the W icon at the top right
      of the screen)." with a **Got it** button.
- [ ] **Got it** hides the strip in this browser for good, in every later session and after
      every switch (the window's origin does not change). Nothing is sent to the server.
- [ ] After a preset or device switch, the new session is still an app session: the strip
      shows unless dismissed.
- [ ] A session started in Terminal never shows the strip (Ctrl+C is printed there).
- [ ] While a previous session is open, the viewing banner shows instead of the strip.
- [ ] In an app session, the *Recording · mm:ss* label has the tooltip "Stop and save from
      the Wiretrace menu (the W icon at the top right of the screen)", dismissed or not.
- [ ] The user guide's app section says where the advice is.

## Out of scope

- A Stop button in the window (the menu bar stays the only stop, spec 014).
- Notification Center banners from the applet (they need a permission prompt: one more
  dialog).
- The "already recording" dialog.

## Design

| Piece | Change |
|---|---|
| `app/Wiretrace.applescript` | On `started`: no `display dialog`. On `starting`: the dialog above, no `giving up` change. |
| `cli/start.py` `wiretrace_command` | With `from_app`: `--set qa_ui_from_app=true`, next to `qa_ui_print_link=false`. The switch loop already passes `from_app` to every restart. |
| `addons/wiretrace_ui.py` | New option `qa_ui_from_app` (bool, default false); `/api/state` gains `"from_app": bool`. |
| `ui/src/types.ts` | `AppState.from_app: boolean`. |
| `ui/src/logic/appHint.ts` (+ test) | `showAppHint(state, viewing, dismissed)`; `loadDismissed` / `storeDismissed` on localStorage key `wiretrace.appHint`, value `"dismissed"`, through the existing `browserStorage()`; a refused storage reads as not dismissed. |
| `ui/src/App.tsx` | `AppHint` strip after the title bar (class `banner viewing`, the existing blue strip), **Got it** as `btn small`. |
| `ui/src/components/TitleBar.tsx` | `Recording` gets the tooltip when `from_app`. |

A separate option rather than reading `qa_ui_print_link`: "do not print the link" is a
privacy rule for `app-start.log`, not a statement about who started the session, and a
later caller could turn it off for another reason.

Rejected:

- Keep the dialog, shown only the first time (a marker file next to `.app-last`): the
  advice is still away from the title bar it describes, and a tester who clicks it away
  unread never sees it again.
- A strip for Terminal sessions too: their stop is Ctrl+C, printed in the banner.

## Invariants

1. The strip shows only when `from_app` is true, no previous session is open, and the
   browser has not stored the dismissal.
2. Dismissal is local to the browser and holds only the word `dismissed`.
3. `from_app` in `/api/state` is a boolean from the launcher's option; the window cannot set
   it.

## Tests

`tests/test_make_app.py`:
1. The applet's source has no dialog after a `started` start, still has the `starting`
   dialog, and no longer contains "Change either from the window's title bar".

`tests/test_start.py`:
2. `wiretrace_command(from_app=True)` has `qa_ui_from_app=true`; without `from_app`, no
   `qa_ui_from_app`.
3. After a switch in an app session, the second command still has `qa_ui_from_app=true`.

`tests/test_wiretrace_ui.py`:
4. `/api/state` has `from_app` false by default and true with `qa_ui_from_app=True`.

UI (vitest, `logic/appHint.test.ts`):
5. Shown for an app session not dismissed; hidden when dismissed, for a Terminal session, and
   while viewing.
6. `storeDismissed` then `loadDismissed` is true; a refusing or empty storage reads false;
   the stored value is only `dismissed`.

## Files to change

`app/Wiretrace.applescript`, `cli/start.py`, `addons/wiretrace_ui.py`, `ui/src/types.ts`,
`ui/src/logic/appHint.ts` (+ test), `ui/src/App.tsx`, `ui/src/components/TitleBar.tsx`,
`ui/dev/fixtures/state.json` (`from_app`), `ui/dist` (rebuilt), the four test files above,
`docs/user-guide.md` (the app section), and spec 018's closing-dialog line (one-line note).

## Manual test

1. Open Wiretrace.app: no dialog; the window shows the strip. Switch the device: the new
   window shows it too. Click **Got it**, switch the preset: no strip; hover *Recording*:
   the tooltip.
2. Start in Terminal with `--ui wiretrace`: no strip, no tooltip.
