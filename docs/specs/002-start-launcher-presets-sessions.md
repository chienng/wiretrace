# Spec: `wiretrace start` — presets, host allowlist, session folder, launcher

- **Date**: 2026-10-13
- **Tier**: M
- **Repo**: wiretrace
- **Status**: approved
- **Branch**: `feature/start-launcher`
- **Related**: [`PLAN.md`](../../PLAN.md) §8 Phase 1 (F1, F2, F10, F12), §9.1, §9.2, §9.7;
  spec 001 (doctor, whose port check is reused)

## Goal

Replace the hand-typed mitmproxy commands in the user guide with one command. A QA
engineer runs `./wiretrace start --preset staging --target android`, gets mitmweb (or
mitmdump) decrypting only that project's API hosts, and finds every session saved in its
own folder, with a HAR file written when they press Ctrl+C.

This is the first of five Phase 1 specs, all in this repo:

| Spec | Scope | Tier |
|---|---|---|
| **002** (this) | Presets (F1), host allowlist (F2), session folder (F10), launcher (F12) | M |
| 003 | QA addon: mocks (F3), fault injection (F4), request ID tagging (F6) | M |
| 004 | Log collectors (F7, F8) and in-app log receiver (F9) | M |
| 005 | Redaction (F5), bug report zip (F11), old-session cleanup | M |
| 006 | Post bug to YouTrack (F13) — personal tokens | **L** |

## Acceptance criteria

- [ ] `./wiretrace start --preset <name>` loads `presets/<name>.yaml` and starts **mitmweb** in
      WireGuard mode, decrypting only the preset's `api_hosts` and their subdomains.
      Traffic to any other host passes through undecrypted.
- [ ] `--mode proxy` starts a regular HTTP proxy on TCP 8080 (the Wi-Fi proxy route)
      instead of WireGuard.
- [ ] `--no-ui` runs **mitmdump** instead of mitmweb, printing flows in the Terminal.
- [ ] The preset's `default_filter` is the initial view filter (mitmweb) or print filter
      (mitmdump). It never limits what is **saved**.
- [ ] Each run creates `sessions/<YYYY-MM-DD_HHMMSS>_<preset>_<target>/` under the
      wiretrace folder (not the current directory), containing `meta.json` and `flows.mitm`.
- [ ] One Ctrl+C stops mitmproxy cleanly, then writes `flows.har` next to `flows.mitm`
      and prints the session folder path. A second Ctrl+C while stopping force-stops.
- [ ] If the run captured nothing (`flows.mitm` absent or empty), the session folder is
      removed and the launcher says so.
- [ ] If a needed port is in use, the launcher says which one and exits `1` without
      starting mitmproxy or creating a session folder.
- [ ] An unknown preset name lists the available presets. An invalid preset file
      names the file and the problem (missing `api_hosts`, a URL instead of a hostname, …).
- [ ] `meta.json` holds no device identifiers, user names, or Mac host names.
- [ ] `./wiretrace doctor` and `scripts/setup-mac.sh` behave exactly as before.

## Approach

**The launcher is a thin Python wrapper that builds a mitmproxy command line and
supervises one child process.** Every QA feature that needs to see flows (mocks, faults,
redaction, log receiver) goes into mitmproxy addons in later specs; the launcher only
adds `-s addons/…` arguments. A custom `mitmproxy.tools.main` embedding lost: it ties us
to mitmproxy's internal API and gives nothing the CLI does not.

**Allowlist regex per host:** `(^|\.)<re.escape(host)>(:\d+)?$`, one `--allow-hosts` per
host. mitmproxy matches allow patterns against `host:port` strings
(`addons/next_layer.py`, `_ignore_connection`, read in mitmproxy 12.2.3), so a pattern
ending in `\.com$` matches nothing and decrypts nothing. This error was in `PLAN.md` and
`docs/user-guide.md`; it is already fixed there, uncommitted on `main`.

**Filters:** `default_filter` is passed as `--set view_filter=…` (mitmweb) or
`--set dumper_filter=…` (mitmdump), never as mitmdump's positional filter argument, so
that it cannot also apply to saving.

**HAR after exit, not during:** `flows.har` is produced by
`mitmdump -n -r flows.mitm --set hardump=flows.har` once the main process has exited
(verified working in mitmproxy 12.2.3). Setting `hardump` on the live process lost: mitmdump
then keeps every flow in memory for the whole session, and the file is only written on a
clean exit, so a crash loses it; `flows.mitm` is streamed to disk as flows complete.

**Preset format** (YAML, one file per project/environment, committed to this repo):

```yaml
name: staging                 # required; must equal the file name without .yaml
api_hosts:                    # required; hostnames only, no scheme, port, path or wildcard
  - api-staging.mycompany.com
  - auth-staging.mycompany.com
default_filter: "!~t image"   # optional
app:                          # optional; used by spec 004
  android_package: com.mycompany.myapp
  ios_process: MyApp
```

Unknown keys are accepted and ignored, so presets written for later specs (`mocks_dir`,
`redact`, `tracker`) load today.

**`--target`** is one of `android`, `ios`, `android-emu`, `ios-sim`, `device` (default). In
this spec it only names the session folder, goes into `meta.json`, and selects the
setup hints printed at start; spec 004 uses it to pick a log collector.

## Design that needs care

The launcher supervises a child process across Ctrl+C, terminal close, and child crash.

**Process model.** `./wiretrace` `exec`s Python, so the launcher *is* the shell's foreground
process. The child (mitmweb / mitmdump) is started in the **same process group**, so a
Terminal Ctrl+C or a closed window reaches both directly. Starting the child in its own
session lost: if the launcher were killed, the child would survive, keep the ports, and
keep capturing.

**States**

| State | Entered when | Exits to |
|---|---|---|
| `PREPARE` | launch | `RUNNING` (child spawned); `ABORTED` (bad preset, port in use — no folder created) |
| `RUNNING` | child spawned | `STOPPING` (SIGINT/SIGTERM/SIGHUP to launcher); `FINALIZING` (child exited by itself) |
| `STOPPING` | first stop signal | `FINALIZING` (child exited); `KILLED` (second stop signal) |
| `KILLED` | second stop signal while stopping | `FINALIZING` after SIGKILL and wait |
| `FINALIZING` | child has exited | `DONE` |

In `STOPPING` the launcher sends the child exactly one SIGINT of its own (needed when the
signal did not come from the Terminal, e.g. `kill`). The child may then have received two
SIGINTs, one from the Terminal and one from the launcher; this relies on mitmproxy's
shutdown being idempotent, which is checked by an integration test, not assumed. After
15 seconds in `STOPPING` the launcher prints "still stopping — press Ctrl+C again to
force".

`FINALIZING`: if `flows.mitm` is absent or empty, delete the session folder. Otherwise
convert to HAR (a failure is reported, `flows.mitm` is kept) and write `meta.json` with
`ended_at` and `status` (`stopped` | `exited` | `killed`).

**Invariants**

1. The launcher never exits while the child is running. Every exit path waits for the
   child first.
2. The launcher never writes, moves, or truncates `flows.mitm`.
3. HAR conversion starts only after the child has exited.
4. A session folder exists only if the child was started, and is kept only if
   `flows.mitm` is non-empty.
5. The launcher's exit code is `0` after a user stop with a successful HAR conversion,
   `1` otherwise (startup abort, child exited by itself with an error, HAR failure, killed).

**Tests derived from the invariants** (fake child: a small Python script that records the
signals it receives and writes a non-empty `flows.mitm`):

- SIGINT to the launcher → child gets SIGINT, launcher waits for it, then runs HAR
  conversion (invariants 1, 3).
- Two SIGINTs → child is SIGKILLed, status `killed`, exit code 1.
- Child exits on its own with code 1 → status `exited`, exit code 1, no signal sent.
- Child writes nothing → session folder removed (invariant 4).
- Port in use → no child spawned, no folder created, exit 1.
- Integration (skipped when mitmdump is not in the venv): real `mitmdump` in regular
  mode on a free port, one request through it, two SIGINTs, then `flows.mitm` is readable
  by `mitmproxy.io.FlowReader` and `flows.har` has one entry.

## Files expected to change

- `cli/__init__.py` — version `0.2.0`.
- `cli/__main__.py` — `start` subcommand: `--preset` (required), `--target`, `--mode`
  (`wireguard` default, `proxy`), `--no-ui`.
- `cli/preset.py` — new. Load and validate a preset, list presets, build the allow-hosts
  regexes. Pure functions apart from file reads.
- `cli/session.py` — new. Create the session folder, write and update `meta.json`, remove
  empty sessions.
- `cli/start.py` — new. Port pre-check (reusing `doctor.check_port`), command building,
  start banner, the state machine above, HAR conversion.
- `presets/example.yaml` — new; placeholder hosts, every field documented.
- `tests/test_preset.py`, `tests/test_start.py` — new; see Design.
- `docs/user-guide.md` — Part 3 uses `./wiretrace start`; the raw mitmproxy commands move to
  a short "Without the launcher" subsection. Part 1 mentions creating a preset.
- `README.md` — one-line usage of `./wiretrace start`.

## Out of scope

- Mocks, fault injection, request ID tagging (spec 003); log collectors and the in-app
  log receiver (spec 004); redaction, report zip, session cleanup (spec 005); YouTrack
  (spec 006); Phase 2 UI.
- `./wiretrace sessions` (listing sessions).
- Real presets for our apps. They need the API host names; `presets/example.yaml` is the
  template. See the open question below.
- Changing `doctor` or `setup-mac.sh`.

## Manual test

1. `./wiretrace start --preset example` with `api_hosts` set to a host you can reach from the
   phone. Connect the phone via WireGuard. Requests to that host are decrypted; others
   (for example the App Store) appear as passed-through connections only.
2. Ctrl+C once. The Terminal prints the session folder; it contains `meta.json`,
   `flows.mitm` and `flows.har`; open `flows.har` in Chrome DevTools.
3. `./wiretrace start --preset example --no-ui --mode proxy`, set the phone's Wi-Fi proxy to
   `<Mac IP>:8080`, repeat step 2.
4. Start, then stop immediately without traffic. No session folder is left behind.
5. Run two `./wiretrace start` at once. The second says which port is in use and exits.

## Automated tests

See *Tests derived from the invariants*, plus preset validation: missing `api_hosts`,
empty list, `https://` URL, host with path or port, wildcard, `name` not matching the file
name, unknown keys accepted, and the allow-hosts regex accepting `host:443` and
`sub.host:443` and rejecting `evilhost:443` and `host.evil.io:443`.

## Open question

Which API hosts should the first real presets cover (app, environment)? The preset
files can be added later without a spec change.
