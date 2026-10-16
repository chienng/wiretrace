# Spec: switch the preset from the window

- **Summary**: the title bar's preset label becomes a menu. Choosing another preset saves
  the current session and starts a new one with that preset, the same target and mode, and
  the phone's tunnel left up. One preset per session. The window does not edit a preset
  in place. The extension at the end adds editing and creating presets from the window.
- **Date**: 2026-10-16
- **Repo**: wiretrace
- **Status**: approved (2026-10-16). Extension A (edit and create presets): approved (2026-10-16).
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
- Editing, creating, or deleting a preset file from the window. Extension A adds editing and
  creating; deleting stays out.
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

---

## Extension A: edit and create presets

- **Status**: approved (2026-10-16)
- **Tier**: L, like the spec it extends: a new write path from the window into `presets/`,
  which decides what is decrypted, and a save that restarts the session. Gates E, A, B, C,
  R, P, D.
- **Branch**: `feature/preset-editor` (from `feature/app-launcher`, which is not merged yet)
- **Related**: mockup screen 7 (`mockups/README.md`, *Presets — switch, edit, or add*);
  spec 014 (the Wiretrace app lists `presets/*.yaml` except `example`); the shipped
  `presets/default.yaml`

### Goal

Setup ships `presets/default.yaml`, and the Wiretrace app starts it. Its `api_hosts` are
the example's, so nothing of the tester's app is decrypted until the file is edited, and
today that needs TextEdit and YAML. The tester should be able to put in the app's hosts,
and create a preset for another environment, from the window.

### Acceptance criteria

- [ ] The preset menu gets two rows under the list: **Edit presets…** opens the *Presets*
      sheet with the preset in use selected; **New preset…** opens it on a blank form. Both
      are off while a previous session is open, as the menu is.
- [ ] The sheet follows mockup screen 7: the presets on the left (*In use* marked,
      `example` marked *Template*), the form on the right: Name, API hosts (one per line,
      add and remove), Android package, iOS process, Request ID header, Starting filter,
      Extra headers to hide, Extra fields to hide. The mockup's single *Extra names to
      hide* becomes the two lists the file has (`redact.headers`, `redact.json_fields`).
- [ ] Every value is checked by the rules the file already has: the message is the one
      `parse_preset` gives, shown above the buttons, and the field it names is marked.
      The starting filter must also parse as a mitmproxy filter. Nothing is written when a
      check fails.
- [ ] **Create preset** writes `presets/<name>.yaml` and leaves this session running. The
      name follows the file-name rule (letters, digits, `_` and `-`, first a letter or a
      digit, at most 64 characters). A name that already exists, including one that
      differs only in capital letters, is refused and nothing is overwritten. The new
      preset is in the menu at once, and in the Wiretrace app's list.
- [ ] **Save** on a preset that is not in use rewrites its file. This session keeps
      running.
- [ ] **Save and restart** on the preset in use asks first ("This session is saved and a
      new one starts with these settings. The phone stays connected."). Confirm writes
      the file, then switches exactly as choosing another preset does, to the same name:
      the session is saved, a new one starts with the new hosts, the same target and
      mode. Cancel writes nothing.
- [ ] If the file changed on disk after the sheet loaded it, the save is refused, the
      sheet says the file changed and loads it again. Nothing is written.
- [ ] A preset that does not load opens with its error at the top and the values
      Wiretrace could read. A valid form saved over it replaces the file.
- [ ] `example` opens read-only (the release replaces it): no Save button, and the sheet
      says to use **New preset**.
- [ ] Saving writes the file in Wiretrace's own layout. Keys the form does not show
      (`mocks_dir`, keys for later features, other `app:` keys) keep their values;
      comments are not kept. The sheet says so under the buttons.
- [ ] Hosts and other preset values are not written to the Terminal, a log line, or the
      bug-report zip by this feature.
- [ ] `--ui mitmweb` and `--no-ui` are unchanged.

### Approach

The form edits fields, not YAML text. The server renders the whole file from the fields,
parses the rendered text with `parse_preset` (the same check `./wiretrace start` runs), and
writes it only if that passes and reads back to the same values. The existing switch path
does the restart.

API, all behind the existing guards (Host, token cookie, `X-Wiretrace: 1` on writes):

| Request | Answer |
|---|---|
| `GET /api/presets/<name>` | `{name, revision, fields, in_use, read_only, error}`. `revision` is the SHA-256 of the file's bytes. `error` is the `load_preset` message or null. |
| `POST /api/presets` `{name, fields}` | 201 `{name, revision}`. 409 if the name exists. |
| `PUT /api/presets/<name>` `{revision, fields}` | 200 `{revision}`. For the preset in use the body must also have `"restart": true`, and the answer is 202 `{switching}`, then mitmdump shuts down as in spec 013. |

`fields` is `{api_hosts: [], android_package, ios_process, request_id_header,
default_filter, redact_headers: [], redact_fields: []}`; an empty string or list means the
key is left out of the file. A 400 is `{error, field}`, `field` naming the form field or
null.

The rendered file: a two-line header comment (written by the Wiretrace window; every key
is explained in `presets/example.yaml`), then `name`, `api_hosts`, `default_filter`,
`request_id_header`, `app`, `redact`, in that order, then every other key from the old file
under a `# Kept from the file:` line. Strings are written as JSON strings (a JSON string is
a valid YAML double-quoted scalar), so no value can start a new key; the kept keys are
written with `yaml.safe_dump`.

Rejected:

- **Keeping comments with `ruamel.yaml`**: a new package on every QA Mac, through the
  pinned install, for comments that `example.yaml` already carries. Hand-written comments
  are rare; the sheet says they are not kept.
- **A YAML text box**: no per-field checks, and indentation mistakes are the reason
  testers avoid the file.
- **Applying the new hosts to the running session**: rejected by this spec already (one
  HAR would hold two environments).
- **Renaming**: the name is the key for the session folder, `rules/<name>.json` and
  `mocks/<name>`.

### Design that needs care

The restart reuses spec 013's machine unchanged; the new part is the order of checks and
writes for the preset in use.

`PUT` on the preset in use:

| Step | On failure |
|---|---|
| 1. The spec 013 refusals: a previous session open, no session folder, a switch already in flight | 409, nothing written |
| 2. `restart` is not true | 409 "This preset is in use: saving it restarts the session", nothing written |
| 3. The revision matches the file on disk | 409 "The file changed", nothing written |
| 4. Render, `parse_preset`, read back, filter check | 400 `{error, field}`, nothing written |
| 5. Replace `presets/<name>.yaml` | 500, the old file is still whole |
| 6. Write `.switch.json` with the same name | 500 "Saved, but the session could not restart: stop and start again" |
| 7. 202, then `ctx.master.shutdown()` | — |

Invariants (A1–A9, beside spec 013's 1–10, which hold unchanged):

- **A1.** Nothing is written unless the rendered text passes `parse_preset` and reads back
  to the submitted fields.
- **A2.** A preset file is replaced whole: a temporary file in `presets/` opened with
  `O_CREAT | O_EXCL | O_NOFOLLOW`, then `os.replace`. The temporary file is removed on
  every failure.
- **A3.** A new preset is created with `os.link(tmp, path)`, which fails if the name exists,
  so an existing file, or its case-insensitive twin on APFS, is never overwritten.
- **A4.** A save rewrites only when the SHA-256 of the file now equals the revision the
  sheet loaded. A missing file is a mismatch. The window of time between that check and
  the replace is accepted: one tester, one Mac.
- **A5.** For the preset in use, steps 1–3 run before step 5, so a refused restart writes
  nothing. Once step 5 has run, a failure says the file is saved.
- **A6.** Saving a preset that is not in use never shuts mitmdump down.
- **A7.** `POST` and `PUT` are refused with 409 while a previous session is open, and `PUT`
  on `example` is refused with 409.
- **A8.** The name comes from the path or body and must match the file-name rule before any
  path is built. Bodies are at most 64 KiB; at most 50 hosts and 50 names per hide list; a
  starting filter is at most 512 characters with no control characters.
- **A9.** Log lines for this feature name only the exception type, never a host, a name to
  hide, or a filter.

### Tests derived from the invariants

1. Render then `parse_preset` round-trips every field; empty fields leave their keys out.
2. A value with a quote, `#`, `: ` or a newline cannot add a key (rejected or kept as text).
3. Kept keys (`mocks_dir`, an unknown key, another `app:` key) survive a save.
4. An invalid host, package, process, header or hide name → 400 with `field`, file unchanged.
5. An invalid starting filter → 400, `field` is `default_filter`.
6. Create writes the file; creating the same name again, or the same name in other
   capitals, → 409 and the first file is unchanged.
7. A wrong or stale revision → 409, file unchanged.
8. Save of a preset not in use → 200, no switch file, shutdown not called.
9. Save of the preset in use without `restart` → 409, nothing written.
10. Save of the preset in use with `restart` → the file is new, `.switch.json` names the
    preset, 202, shutdown called.
11. Save of the preset in use while a switch is in flight, or while a previous session is
    open → 409, file unchanged.
12. `PUT` on `example` → 409.
13. A name with `/`, `..` or a dot in the path or body → 400 or 404, nothing written.
14. A body over 64 KiB, or 51 hosts → 400.
15. Writes without `X-Wiretrace` → 403.
16. A symlink at the temporary path is not followed; a failed replace leaves no temporary
    file.
17. `GET` on a preset that does not load → its error and the values that could be read.
18. UI: the button reads *Create preset*, *Save*, or *Save and restart*; read-only for
    `example`; the menu rows are off while a previous session is open.

### Files expected to change

Order: the file format, then the API, then the window, then the docs.

- `cli/preset.py`: the form's field list, reading fields from a file's data, rendering a
  file, the file revision, and the create / replace writes (A1–A4).
- `addons/wiretrace_ui.py`: `GET` and `PUT /api/presets/<name>`, `POST /api/presets`; the
  spec 013 refusals shared between `switch_preset` and the in-use save; the filter check.
- `ui/src/types.ts`, `ui/src/api.ts`: the preset detail and the three calls.
- `ui/src/logic/presets.ts` (+ `presets.test.ts`): the form state, the button label,
  read-only, the menu rows.
- `ui/src/components/PresetSheet.tsx` (new): the list, the form, the restart confirmation.
- `ui/src/components/TitleBar.tsx`: the two menu rows; opens the sheet.
- `ui/src/styles.css`: the sheet's layout from mockup screen 7, from existing tokens.
- `ui/dist/`: rebuilt and committed.
- `tests/test_preset.py`, `tests/test_wiretrace_ui.py`: the tests above.
- `docs/user-guide.md`: Part 1, Step 6 and the Wiretrace window part: edit or create a
  preset from **Preset → Edit presets…**.
- `README.md`: *Your own preset* says it can be done in the window; the design table's
  main-window row no longer says editing is not built.
- `mockups/README.md`: screen 7 is built, with the two hide lists as the difference.

### Out of scope

- Deleting or renaming a preset; editing `example`.
- Editing `mocks_dir` in the form (it is kept as it is).
- Keeping hand-written comments.
- A preset editor in mitmweb, the menu bar, or the Wiretrace app.

### Manual test

About 5 minutes, with an Android phone or emulator connected and `--ui wiretrace`.

1. Start with `--preset default`. **Preset → Edit presets…**. Replace the hosts with the
   app's API host, **Save and restart**, confirm. A new tab opens; the Terminal prints the
   new host; the app's requests are decrypted.
2. **New preset…**, name `qa2`, one host, **Create preset**. The session keeps running.
   `presets/qa2.yaml` exists and loads with `./wiretrace start --preset qa2`.
3. Edit `presets/qa2.yaml` in TextEdit while the sheet shows it, then save in the sheet:
   it says the file changed and reloads.
4. Enter `https://api.example.com` as a host: the message names the host, nothing is
   written.

### Automated tests

The list in **Tests derived from the invariants**: `pytest` for `tests/test_preset.py` and
`tests/test_wiretrace_ui.py`, `vitest` for `ui/src/logic/presets.test.ts`, `tsc --noEmit`.
No device and no live mitmproxy are required.
