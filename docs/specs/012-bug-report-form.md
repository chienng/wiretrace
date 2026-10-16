# Spec: a bug report form to copy into YouTrack or Jira

- **Summary**: the *Report bug* dialog becomes a form shaped like a YouTrack or Jira issue,
  with Title, Description, Screenshots and Logs, filled in from a failed request. The tester
  reviews it, then copies the title and description and downloads the screenshots and logs to
  paste or upload into whichever tracker she uses. Wiretrace itself sends nothing anywhere and
  stores no tracker token. Mockup screen 5, without the integration.
- **Date**: 2026-10-16
- **Repo**: wiretrace
- **Status**: approved (2026-10-16; no tracker integration in this version; screenshots on
  Android, the emulator and the iOS Simulator; a Markdown / Jira wiki switch)
- **Tier**: M (one repo; nothing leaves the Mac through Wiretrace; no token stored). Gates B
  and C still run, because what the tester copies is captured traffic. Gates E, A, B, C, R, P.
- **Branch**: `feature/bug-report-form` (from `main`)
- **Related**: [`PLAN.md`](../../PLAN.md) F13, U10, section 9.8 (the integration, later); spec
  005 (report zip and masking); spec 009 (masking names, file modes); spec 008 (screen 5 out
  of scope); the mockup for this version is
  [`mockups/screens/05a-bug-report-form.png`](../../mockups/screens/05a-bug-report-form.png)
  (screen 5a in `mockups/wiretrace-mockup.html`); screen 5 shows the later integration

## Goal

Today a tester writes the report zip, opens the tracker, retypes the failing request, takes a
screenshot on the phone, and drags files in. With the form, she clicks *Report* on the failed
request, reviews a pre-filled title and description, and takes a screenshot from the same
dialog. Four clicks put the title, description, screenshot and logs into her tracker. Every
captured value in the form is masked, and nothing is sent until she pastes it herself.

## Acceptance criteria

### Opening the form

- [ ] *Report* on a request (detail panel) opens the form for that request. *Report bug* (title
      bar) opens it for the selected request, or else for the most recent failed one. With no
      failed request, it opens for the whole session.
- [ ] The lead line shows the request (`POST /api/v1/orders → 500 at 19:41:18`) and the device
      model and OS when the collector reported them. With no request, it shows the session name.
- [ ] A previous session that is open in the window can be reported the same way, except that
      taking screenshots is off (see Screenshots).

### Title

- [ ] Pre-filled `<METHOD> <path> returns <status>`, or `… gets no response`, with the path
      masked and without the query. It is editable, 1 to 200 characters. A **copy icon** next
      to it copies the current text and shows "Copied" for 2 seconds.

### Description

- [ ] A **Format** switch: *Markdown (YouTrack, Jira Cloud)* or *Jira wiki (Jira Data Center)*.
      The default is Markdown, and the window remembers the choice per preset in the browser.
- [ ] Pre-filled, editable text in the chosen format:
      - *Steps to reproduce* with `1. ` for the tester to fill in, then *Expected* and *Actual*,
        both empty;
      - *Environment*: preset, target, mode, device model and OS when known, Wiretrace version;
      - *Failed request*: method, host, path with the query masked as in the HAR, status or
        error, duration, request ID;
      - *Response body*: masked, at most 4 KB, in a code block, cut at a character boundary
        with `… (cut, full body in the HAR)`;
      - *Log lines*: up to 20 lines that carry the request ID, masked by pattern, in a code
        block;
      - the line `Log lines are masked by pattern only; check them before sharing.`
- [ ] A **copy icon** copies the description as it is now, edits included.
- [ ] Changing the format, a box under *Logs*, or the request regenerates the text. If the
      tester has edited it, she is asked first: `Replace your edits with a new description?`
- [ ] Captured text can't break out of its code block. In Markdown the fence is longer than
      any run of backticks inside. In Jira wiki, `{code}` and `{noformat}` inside the content
      are escaped.

### Screenshots

- [ ] **Take screenshot** captures the phone's screen now: `adb exec-out screencap -p` for
      `--target android` and `android-emu`, and `xcrun simctl io booted screenshot` for
      `ios-sim`. It shows a thumbnail within about 3 seconds. The tester can take up to 5 per
      form, and remove any of them.
- [ ] Each thumbnail has a **download icon** that saves the PNG
      (`<session>-screenshot-<HHMMSS>.png`).
- [ ] With `--target ios`, the section says: `Take the screenshot on the iPhone (side button and
      volume up) and add it in the tracker yourself.` With `--target device`, while viewing a
      previous session, or with no device connected, the button is off and the reason is shown
      next to it. Examples: `No Android device connected`, `More than one device connected;
      connect only one`, `No Simulator booted`.
- [ ] A screenshot that fails shows the reason (`adb: device unauthorized`, `timed out after 10
      seconds`), and the form keeps working.
- [ ] Screenshots are saved in the session folder under `screenshots/` (folder `0700`, files
      `0600`) and listed again when the form reopens for that session.

### Logs

- [ ] Boxes, each with its count, that update when a box changes:
      - *Other requests ±30 s* (on);
      - *Device logs (same window)* (on);
      - *App logs (same window)* (on).
      The window is ±30 s around the request, or the whole session when there is no request.
- [ ] One row per file, each with a **download icon** and its size:
      - `<session>-requests.har`: the masked HAR, the selected request plus the others when
        that box is on;
      - `<session>-device-log.txt` and `<session>-app-log.txt`: masked lines, one per line as
        `time level tag message`;
      - **Download all** `<session>-report.zip`: these files plus `summary.md`, the spec 005
        report limited to the boxes and the window.
      A file with no content isn't offered.
- [ ] **Masked before export** lists the header and field names the preset's rules mask, as
      chips, like the mockup.

### Safety and no regression

- [ ] Wiretrace makes no network request beyond 127.0.0.1 for this feature, and stores no
      tracker setting or token.
- [ ] Every captured value in the title, description and downloads has gone through the spec
      005/009 masking. A fixture with `Authorization`, `password` and `?token=` shows none of
      the values in any of them.
- [ ] No title, description, body, log line or screenshot appears in the Terminal or in a
      Wiretrace log. Errors name the step and the reason only.
- [ ] Downloads never contain `flows.mitm`, `.status.json` or anything outside the report's
      files.
- [ ] `./wiretrace report` is unchanged. With all boxes on and no request, *Download all*
      gives the same members as the 0.8.0 report.

## Approach

### The form is the existing Report dialog, rebuilt

`ReportDialog.tsx` is replaced by the form. The page asks the server for a draft and for the
files. It builds no captured text itself; it only shows what the server returns and keeps the
tester's edits. Rejected:
- building the description in the page from flows it already has. The window's flow
  summaries aren't masked the way the report is, so the masking would have to be written
  twice.
- the YouTrack and Jira APIs, which are deferred to a later spec. They need a stored personal
  token and send captured traffic to an outside server (tier L); copy and download work with
  any tracker today.

### Server: read-only drafts and downloads, one write for screenshots

- `GET /api/report/draft?flow=&session=&format=&include=` returns:
  - the title;
  - the description;
  - the counts per box;
  - the masked names;
  - the files offered, with sizes;
  - the screenshot state: `available`, or `off` with the reason;
  - the session's screenshots.
- `GET /api/report/file/<kind>?flow=&session=&include=` returns the file, built in memory, with
  `Content-Disposition: attachment`. `<kind>` is one of `har`, `device-log`, `app-log` or
  `zip`. These handlers write nothing, so they're plain guarded GETs.
- `POST /api/report/screenshot` (`X-Wiretrace: 1`, like every mutation) runs the capture with a
  10 s timeout, in `asyncio.to_thread`. It accepts the output only if it starts with the PNG
  signature and is at most 20 MB, saves it, and returns its name. One capture runs at a time;
  a second one gets 409.
- `GET /api/report/screenshot/<name>` (thumbnail, `?download=1` for the file) and
  `DELETE /api/report/screenshot/<name>`. The name must match
  `\d{8}-\d{6}(-\d)?\.png` and must be listed in that session's `screenshots/`. A path from the
  page is never used.

`report.build` gains optional `window=(start, end)` and `include=` arguments. Without them it
behaves as today, so `./wiretrace report` and the 0.8.0 zip stay the same. The description,
the HAR and the text logs come from the same masked data (`bodies.py`, `redact.py`).

### Screenshots: the tools Wiretrace already installs

`adb` is found the way `doctor` finds it (`find_adb`), and `xcrun` comes from Xcode's command
line tools. Neither needs admin rights. The capture follows the device rules the collectors
use: exactly one device, otherwise the reason. Rejected:
- iPhone screenshots through `pymobiledevice3`. On iOS 17 and later they need the developer
  tunnel, which needs `sudo` (`install-without-admin.md`).
- a screenshot of the Wiretrace window. It isn't the bug.
- pasting or dropping the tester's own images into the form. She can add those in the tracker
  directly.

### Copying

Copying uses the existing `ui/src/clipboard.ts` (used by *Copy cURL*), which works on
`127.0.0.1`. The copy icons copy what is in the field at that moment.

## Design that needs care

### Form states

| State | Entered when | Notes |
|---|---|---|
| LOADING | the form opens, or a box, format or request changes | the draft is requested; a newer request cancels an older one (last one wins) |
| READY | draft received | `edited = false` |
| EDITED | the tester types in the description | regenerating asks first; *No* keeps the text and reverts the change that asked |
| CAPTURING | Take screenshot | the button is busy; the rest of the form stays usable |

The title's edits are kept across regenerations unless the request changes.

### Invariants

1. No captured value reaches the page, the clipboard or a download without the server's
   masking.
2. Nothing is written except screenshots, inside the session's `screenshots/` folder, with
   `0700` and `0600` modes and server-made names.
3. No network request beyond 127.0.0.1, and no tracker setting or token anywhere.
4. A screenshot command never runs for a previous session, for `--target ios` or `device`, or
   with zero or several devices. It never runs more than once at a time, and it never runs
   longer than 10 s.
5. A file name from the page is matched against the listing, never joined to a path.
6. Nothing captured is printed or logged.
7. Without the form being opened, the window and `./wiretrace report` behave as in 0.8.0.

### Tests derived from them

- Invariant 1: a fixture with `Authorization`, `password`, `?token=` and a JWT in a log line.
  The draft (both formats), the HAR, both text logs and the zip contain none of the values.
- Invariant 2: a screenshot folder made under `umask 022` is still `0700`, and its file `0600`.
  A capture that returns non-PNG bytes or more than 20 MB saves nothing.
- Invariant 4: a fake `adb` that lists two devices, none, or `unauthorized`, or that hangs
  past 10 s, gives the reason and saves nothing. Two concurrent captures give one 409. A
  previous session gives `off`.
- Invariant 5: `../meta.json`, `x.png`, a valid-looking name that isn't listed, and
  URL-encoded traversal all get 404.
- Invariant 6: `caplog` and captured stdout/stderr hold no body, log text or description after
  a full draft, download and capture.
- Invariant 7: the existing report and window tests pass unchanged. `report.build` without
  `window`/`include` gives the 0.8.0 members.
- Rendering: bodies containing ```` ``` ````, a long run of backticks, `{code}` and
  `{noformat}` stay inside one block in both formats. The 4 KB cut doesn't split a multi-byte
  character.
- Window: a flow exactly at ±30 s is in, one just outside is out; log lines likewise.
- Page: the reducer asks before replacing edits; a stale draft answer is ignored; copy calls
  the clipboard with the current text; the 5-screenshot limit holds.

## Files expected to change

- `cli/report.py`:
  - `window` and `include` in `build`;
  - the draft model (title, description sections, counts);
  - the text log renderer.
- `cli/report_text.py` (new): the Markdown and Jira wiki renderers, with fence and macro
  escaping.
- `cli/screenshot.py` (new): the capture per target, with device checks, timeout and PNG
  check. It reuses `doctor.find_adb`.
- `cli/session.py`: `SCREENSHOTS = "screenshots"`.
- `addons/wiretrace_ui.py`: the draft, file and screenshot endpoints; `screenshot_running`.
- `ui/src/components/ReportDialog.tsx`: the form.
- `ui/src/logic/report.ts` (new): the form reducer and the edit guard.
- `ui/src/api.ts`, `ui/src/types.ts`, `ui/src/styles.css` (the mockup's sheet, chip, copy and
  download icon styles), and the vitest files next to them.
- `ui/dist/`: rebuilt.
- `ui/dev/fixture-plugin.mjs`, `ui/dev/fixtures/`: a draft answer and a sample PNG, so
  `npm run dev` shows the form.
- Tests:
  - `tests/test_report.py`: window, include, renderers, text logs;
  - `tests/test_screenshot.py` (new): fake `adb` and `xcrun` scripts on `PATH`;
  - `tests/test_wiretrace_ui.py`: the endpoints, names, 409, previous session.
- Docs:
  - `docs/user-guide.md`: *Report a bug* rewritten as the form, plus how to paste into
    YouTrack and Jira, and that downloads go to the browser's Downloads folder, outside the
    protected session folder;
  - `README.md`: Features; the Design table's row 5 becomes "Built: form to copy into
    YouTrack or Jira … Not built: sending directly".

Order: `report.build` window and include, with tests; the renderers; the screenshots; the
endpoints; the form; the docs.

## Out of scope

- Creating issues in YouTrack or Jira through their APIs, signing in, tokens and the
  `tracker:` preset section. That's a later spec, which will start from `PLAN.md` 9.8 and
  this form.
- iPhone screenshots, screen recordings, annotating screenshots.
- Crash reports.
- Adding the tester's own images or files to the form.
- "Add to bug report" from a single log line.
- The menu bar's *Report last error* (spec 011 shows the request instead).

## Manual test (about 5 minutes, Android phone or emulator)

1. Start with `--ui wiretrace --target android`, make a request fail, and click *Report*. The
   title and description are filled, and the masked chips match the preset.
2. Copy the title and paste it into a text editor. Copy the description and paste it into a
   YouTrack or Jira test issue's description. It renders as headings and code blocks, and
   `Authorization` and token fields read `***`.
3. Switch to *Jira wiki* and copy again; it renders in a Jira Data Center test issue, if one is
   available.
4. Click *Take screenshot*: a thumbnail appears; download it, and it opens as the phone's
   screen. Take two more and remove one.
5. Untick *Device logs*: its row disappears, and the counts and description change after the
   "Replace your edits?" question if you edited.
6. Download the HAR, the app log and *Download all*. Each opens, and the zip holds the listed
   files.
7. Start with `--target ios`: the iPhone note shows instead of the button.

## Automated tests

All of "Tests derived from them", plus:
- The draft for a whole session (no request) lists every failed request, as `summary.md` does.
- File sizes in the draft match the downloaded bytes.
- Format `jira` for a request with no response renders `gets no response` and no body block.
