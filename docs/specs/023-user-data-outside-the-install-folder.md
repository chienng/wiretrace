# Spec: keep presets, rules, mocks, sessions and the port outside the install folder

- **Summary**: Wiretrace keeps everything the tester creates — presets, rules, mock files,
  sessions and the saved Wi-Fi proxy port — in a per-user data folder,
  `~/Library/Application Support/Wiretrace/`, instead of inside `~/wiretrace`. Installing a new
  version replaces `~/wiretrace` and never touches that data. The first run of the new version
  copies the data that 0.10.0 and older kept in the install folder. No step needs an admin
  password.
- **Date**: 2026-10-23
- **Repo**: wiretrace
- **Status**: implemented (2026-10-23)
- **Tier**: M (one repo; moves the base of the "stays inside the folder" path checks for mock
  files, rules and presets, and moves session folders). Gates A, B (path containment, symlinks,
  file modes), C (no home path with the user name in exports or logs), R, P. E n/a (no new
  screen; one menu item). D n/a (one repo).
- **Branch**: `feature/user-data-folder`, from `main` once `feature/readme-screenshots-0.10`
  is merged.
- **Version**: 0.11.0. Erratum (2026-10-23): ships in 0.10.0, which was not released yet; the
  last release is 0.9.1. Read "0.10.0 and older" below as "0.9.1 and older", and "0.11.0" as
  0.10.0.
- **Related**: spec 007 (rename: users copied presets, mocks and sessions by hand); spec 013
  (preset editor, `rules/<preset>.json`); spec 014 (the Mac app is built by setup and tied to the
  install folder); spec 022 slice B (`.proxy-port`). Decision 2026-10-16 "the Mac app is built
  on the tester's Mac by setup".

## Goal

Today every file the tester creates lives inside the install folder: `presets/*.yaml`,
`rules/<preset>.json`, `mocks/<preset>/…`, `sessions/…` and `.proxy-port`. The update
instructions say to move the old folder aside, unpack the new one and copy those folders back
by hand. Anyone who skips that loses their presets and rules. Anyone who unpacks over the old
folder gets their `presets/default.yaml` replaced by the shipped one. Wiretrace should keep user
data where an update cannot reach it, and an update should be: unpack, run `./install`, done.

The tester is often on a company Mac with a **standard (non-admin) account**. Every folder
Wiretrace creates or writes must be inside the user's home folder and must not need `sudo`, an
admin password, or a macOS privacy permission (Files and Folders, Full Disk Access).

## Acceptance criteria

- [ ] **Location.** User data lives in `~/Library/Application Support/Wiretrace/`:
      `presets/`, `rules/`, `mocks/`, `sessions/` and `.proxy-port`, with the same layout and
      file formats as today. Wiretrace creates the folder and its subfolders when they are
      missing (0700 folders, files 0600 as today), including when
      `~/Library/Application Support` itself is missing.
- [ ] **Standard account.** On a standard macOS account, `./install`, `./wiretrace start`, the
      Wiretrace app, the preset form, the rules editor, *Map local…* and the bug report
      screenshots all save without an admin password and without a macOS permission prompt.
- [ ] **Override.** `WIRETRACE_DATA=<absolute path>` puts the data folder elsewhere (tests,
      or a tester who wants it in another place). A relative path or a path that cannot be
      created stops with: "Wiretrace data folder <path>: <reason>. Set WIRETRACE_DATA to a
      folder you can write, or unset it."
- [ ] **Updates never touch data.** Replacing `~/wiretrace` with a new version (moved aside,
      deleted, or unpacked over) leaves every preset, rule, mock file, session and the saved
      port as it was.
- [ ] **Shipped examples.** The release ships its examples under `examples/` in the install
      folder (`examples/presets/default.yaml`, `examples/presets/example.yaml`,
      `examples/rules/example.json`, `examples/mocks/example/…`), not under `presets/`,
      `rules/` or `mocks/`. At each start, each shipped example that is **missing** from the
      data folder is copied there; one that exists is never overwritten, even if the tester
      changed it.
- [ ] **Migration from 0.10.0 and older.** At the first start of 0.11.0 (and from
      `./install`), Wiretrace looks for old data in the install folder (`presets/`, `rules/`,
      `mocks/`, `sessions/`, `.proxy-port` next to the code — the "unpacked over the old folder"
      case and a developer checkout). It copies presets, rules, mock files and the port, and
      moves sessions. A file that already exists in the data folder is kept and the old one is
      skipped. The Terminal prints one summary line: "Moved your data to ~/Library/Application
      Support/Wiretrace: 3 presets, 2 rule files, 5 mock files, 12 sessions, the proxy port.
      Kept 1 existing file: presets/default.yaml." It runs once: a `.migrated` marker in the
      data folder records it.
- [ ] **Import from another folder.** `./wiretrace import-data <folder>` does the same from
      an older Wiretrace folder somewhere else, for example `~/wiretrace-old`, which is the
      name the 0.10.0 update instructions told testers to use. It can be run again; it never
      overwrites and prints the same summary.
- [ ] **Old folders are not read.** After migration, a `presets/`, `rules/`, `mocks/` or
      `sessions/` left in the install folder is ignored. `./wiretrace doctor` warns: "The
      install folder still has presets/ from an older version; Wiretrace now reads
      ~/Library/Application Support/Wiretrace. Delete presets/ there once you have checked
      your presets."
- [ ] **Finding the folder.** Finder hides `~/Library`, so:
      - `./wiretrace doctor` prints a "Data folder: ~/Library/Application Support/Wiretrace"
        line, and names it in its "not writable" failure;
      - `./wiretrace data` prints the path, and `./wiretrace data --open` opens it in Finder;
      - the menu-bar item gets **Show data folder**;
      - the Wiretrace app's "No project yet" dialog opens the data folder's `presets/`.
- [ ] **Paths shown to the tester.** The window, the Terminal banner and error texts show
      files inside the data folder relative to it (`rules/staging.json`,
      `mocks/staging/GET/api/v1/profile.json`), as they show install-folder paths today.
      "Must be inside the wiretrace folder" texts say "inside the Wiretrace data folder".
- [ ] **Downgrade.** Copied presets, rules, mock files and the port stay in the old install
      folder, so 0.10.0 still finds them. Moved sessions are not visible to 0.10.0 (noted in
      the user guide).
- [ ] **Docs.** The user guide's install, preset, rules, mocks, sessions and *Updating and
      removing* sections use the data folder; the update is "unpack, run `./install`". The
      README's paths match.

## Approach

One module, `cli/datadir.py`, answers "where is user data" and does creation, seeding and
migration. Every constant that today is `Path(__file__).parent.parent / "<name>"` for user
data (`PRESETS_DIR`, `SESSIONS_DIR`, the rules folder, `.proxy-port`, the mocks base and the
containment base) comes from it. Code, `.venv`, `ui/dist`, `examples/`, `app-start.log` and
`.app-last` stay in the install folder: they belong to that install.

**Why `~/Library/Application Support/Wiretrace`** — it is the macOS place for per-user app
data, it is in the home folder (no admin), it needs no privacy permission, Time Machine backs it
up, and iCloud does not sync it. Rejected:
- `~/Documents/Wiretrace`: macOS asks the app or Terminal for permission to access Documents,
  and with *Desktop & Documents* in iCloud it would upload captured traffic and tokens.
- `~/.wiretrace`: works the same technically, but is not the Mac convention and is just as
  hidden in Finder.
- `/Users/Shared` or `/Library`: needs admin rights, or shares one user's captured traffic with
  every account on the Mac.
- A subfolder of the install folder: still lost when the folder is moved aside or deleted.

**Why copy, and move only sessions** — presets, rules, mocks and the port are small, and
copying leaves a working 0.10.0 behind for a downgrade. Sessions can be hundreds of MB; moving
them (`os.rename`, the same volume as the home folder) is instant and needs no second copy. When
the rename fails across volumes, the session is copied and the original is left in place.

**Why examples move to `examples/`** — if the release kept `presets/default.yaml` in the
install folder, a tester would edit that copy and see no effect. With no `presets/` folder in a
new install, there is only one copy to edit.

## Design

### Data folder resolution

`data_dir()`:
1. `WIRETRACE_DATA` when set and non-empty: must be absolute, else the error above.
2. Otherwise `Path.home() / "Library" / "Application Support" / "Wiretrace"`.

The result is resolved once per process. `ensure()` creates it and its four subfolders with
`os.makedirs(mode=0o700, exist_ok=True)`, and fails with the error above when a path component
is not a directory or not writable. The launcher passes the data folder to the add-ons as
`qa_data_dir`, replacing `qa_wiretrace_dir`. Add-ons started without it (mitmweb used directly)
call `data_dir()` themselves.

### Start-up order

`./wiretrace start`, `./wiretrace app …`, `./wiretrace doctor`, `./wiretrace import-data` and
`./install` all go through `datadir.prepare()`:

1. `ensure()`.
2. If there is no `.migrated` marker: migrate from the install folder, then write `.migrated`
   (0600, the version number only). The marker is written even when nothing was found.
3. Seed the missing shipped examples.

`prepare()` runs before any preset is loaded. It is idempotent, and two processes running it at
once are safe: every copy is "create the destination exclusively, or skip it".

### Migration and import rules (invariants)

- Only these are taken from the source folder:
  - `presets/<name>.yaml` where `<name>` passes the preset name rule;
  - `rules/<name>.json` with the same name rule;
  - regular files under `mocks/`, keeping their relative path;
  - session folders that `session.list_sessions()` accepts;
  - `.proxy-port` when it holds a valid port.
- Symlinks are never followed or copied: a symlinked file or folder in the source is skipped
  and counted as "skipped". No file outside the source folder is read; no file outside the data
  folder is written.
- A destination that exists is never overwritten (`O_CREAT | O_EXCL`); it is listed under "Kept".
- Copied files are written 0600 and folders created 0700, whatever the source modes were.
- A failure on one file (unreadable, disk full) skips that file, names it in the summary, and
  goes on. The marker is written only when the whole pass ran, so a crash mid-way retries next
  time; the never-overwrite rule makes the retry safe.
- The summary names counts and file paths relative to the data folder, never an absolute path,
  a host or a file's contents.

### Containment

`mocks_dir_problem()`, `_mocks_root()`, `resolve_mock()` and `mock_dir_for_write()` use the
data folder as their base instead of the install folder, with the same checks: relative, no
`..`, resolved path inside the base, `O_NOFOLLOW` where it is used today. A preset's
`mocks_dir: mocks/staging` therefore means `<data>/mocks/staging`. `display_dir()` shows paths
relative to the data folder.

### Privacy

The data folder's absolute path contains the macOS user name. It may appear in the local
Terminal and in the window (doctor, `./wiretrace data`), as install-folder paths do today. It
must not appear in report exports (HAR, log files, the description draft, `meta.json`) or in
anything a report zips. Any path written there is relative to the data folder.

### Tests derived from the invariants

- `data_dir()`: the default under a fake home; the `WIRETRACE_DATA` override; a relative
  override is refused; an unwritable parent gives the error text.
- `ensure()` creates `~/Library/Application Support` when it is missing; modes are 0700.
- Seeding: a missing example is copied; an existing, changed example is not overwritten.
- Migration:
  - copies presets, rules, mocks and the port, and moves sessions;
  - keeps existing destinations and lists them;
  - skips symlinks, including a symlinked `mocks/` folder pointing outside;
  - skips invalid preset names and non-session folders;
  - writes the marker and runs once;
  - is retried after a simulated failure and stays idempotent;
  - copies a session when the rename fails across volumes (a simulated `EXDEV`).
- `import-data`: the same rules from an arbitrary folder; a repeated run copies nothing new.
- Containment: a preset `mocks_dir` resolving outside the data folder is refused; a mock file
  symlinked out of the data folder is refused.
- `rules_file()`, `.proxy-port`, `SESSIONS_DIR` and `PRESETS_DIR` all resolve under the data
  folder.
- Report export: no absolute data-folder path in `meta.json`, the description draft or the zip.
- Test isolation: an autouse fixture in `tests/conftest.py` sets `WIRETRACE_DATA` to a temp
  folder, and a guard test fails if any test would resolve the real `~/Library/Application
  Support/Wiretrace`.

## Files expected to change

1. `cli/datadir.py` (new): `data_dir()`, `ensure()`, `prepare()`, `seed_examples()`,
   `migrate(source)`, summary text.
2. `cli/preset.py`: `PRESETS_DIR` from the data folder; `mocks_dir_problem()` base and texts.
3. `cli/session.py`: `SESSIONS_DIR` from the data folder.
4. `cli/start.py`: `rules_file()`, `.proxy-port`, `qa_mocks_dir`, `qa_data_dir` (replacing
   `qa_wiretrace_dir`), banner paths, `prepare()` before loading the preset.
5. `cli/doctor.py`: `.proxy-port` path; "Data folder" line; writability check; the warning
   about legacy folders.
6. `cli/app.py`: defaults follow the data folder; `prepare()`; a `data-dir` subcommand for the
   applet.
7. `cli/__main__.py`: `data [--open]` and `import-data <folder>` commands.
8. `addons/qa_tools.py`: containment base from `qa_data_dir` or `data_dir()`; option renamed.
9. `addons/wiretrace_ui.py`: `display_dir()` relative to the data folder; option renamed.
10. `menubar/__init__.py`: **Show data folder** item.
11. `app/Wiretrace.applescript`: "Open presets folder" opens `<data>/presets` (asks
    `wiretrace app data-dir`).
12. `scripts/setup-mac.sh`: runs `prepare()` at the end, so the migration summary appears
    during `./install`.
13. Repository layout: `presets/default.yaml`, `presets/example.yaml`, `rules/example.json`
    and `mocks/example/` move to `examples/…`; `.gitignore` drops what no longer applies.
    `presets/default.yaml` holds the Orchestrator's local edits: move only the committed
    version, and keep the working copy untouched until the Orchestrator decides.
14. `tests/conftest.py` (autouse `WIRETRACE_DATA`), `tests/test_datadir.py` (new); updates
    in `tests/test_start.py`, `test_app.py`, `test_doctor.py`, `test_app_logs.py`,
    `test_wiretrace_ui.py` and the qa_tools tests.
15. `docs/user-guide.md`, `README.md`, `cli/__init__.py` (0.11.0).

## Out of scope

- Moving the window's saved filters. They are in the browser's storage, per preset, and
  unaffected.
- Moving `~/.mitmproxy` (the CA). It is already outside the install folder.
- A Settings screen to pick the data folder. `WIRETRACE_DATA` covers the rare case.
- Merging a changed shipped example into the tester's edited copy.
- Searching the disk for old Wiretrace folders. Only the install folder is migrated
  automatically; other folders go through `import-data`.

## Manual test (~10 min)

1. On a **standard (non-admin) account**, with 0.10.0 in `~/wiretrace`: create a preset
   `qa1`, a rule, a mock file via *Map local…*, and one session, and change the port to
   8890.
2. `mv ~/wiretrace ~/wiretrace-old`, unpack 0.11.0 to `~/wiretrace`, run `./install`. Expect
   no password prompt and no macOS permission prompt.
3. `./wiretrace import-data ~/wiretrace-old`. Expect the summary line with `qa1`, the rule,
   the mock, the session and the port.
4. Start from the Wiretrace app. Expect `qa1` in its list; the window shows the rule, the
   mock, the previous session, and port 8890.
5. Edit `default` in the preset form, then unpack 0.11.0 again **over** `~/wiretrace` and run
   `./install`. Expect the edit to still be there.
6. Menu bar → **Show data folder** opens Finder at the data folder.
7. `WIRETRACE_DATA=/tmp/wt-data ./wiretrace doctor` prints that folder; unset it again.

## Decided

`./install` does **not** import from `~/wiretrace-old` automatically (Orchestrator,
2026-10-23). Only the install folder is migrated on its own; any other folder goes through
`./wiretrace import-data <folder>`, and the 0.11.0 update notes print that command.
