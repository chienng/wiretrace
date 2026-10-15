# Spec: No-admin install script and `wiretrace doctor`

- **Date**: 2026-10-13
- **Repo**: wiretrace
- **Status**: approved
- **Branch**: n/a — `wiretrace/` is not a git repository yet (`PLAN.md` targets
  `gitlab.mycompany.com/qa/wiretrace`)
- **Related**: [`PLAN.md`](../../PLAN.md) §5, §9.1, §9.7, §10;
  [`docs/install-without-admin.md`](../install-without-admin.md) steps 1–4

## Goal

A QA engineer with a **standard (non-admin)** macOS account can turn a fresh copy of
the `wiretrace/` folder into a working environment with one command, and can check
that environment with `./wiretrace doctor`. This implements the "Installation steps
(Phase 1, standard user)" section of `docs/install-without-admin.md`. It contains
none of the Phase 1 features (F1–F13); those get their own specs.

## Acceptance criteria

- [ ] `scripts/setup-mac.sh`, run from a zip-extracted copy of `wiretrace/` (no `git`,
      no Xcode Command Line Tools), completes **without a password prompt** and
      without writing anything outside `$HOME` and the `wiretrace/` folder.
- [ ] Afterwards `uv` is in `~/.local/bin`, Python 3.12 is managed by `uv`,
      `wiretrace/.venv` contains everything in `requirements.txt`, and `adb` is in
      `~/tools/platform-tools`.
- [ ] Running the script a second time changes nothing: no duplicate lines in
      `~/.zshrc`, no re-download of platform-tools, and `uv` is not reinstalled.
- [ ] `--skip-android` skips the platform-tools download.
- [ ] Run with `sudo` (EUID 0), the script refuses to start and explains why.
- [ ] The script ends by running `./wiretrace doctor`, and exits with doctor's exit code.
- [ ] `./wiretrace doctor` prints one line per check with a status of `OK`, `WARN`,
      `FAIL` or `INFO`. It exits `0` when there is no `FAIL`, `1` otherwise.
- [ ] `./wiretrace` without `.venv` prints "run `scripts/setup-mac.sh` first" and exits
      `1`. It never falls back to `/usr/bin/python3`.
- [ ] Neither the script nor doctor runs a command that can open the macOS
      "install Command Line Tools" dialog (`git`, `python3`, `xcrun`, `cc`, `make`).
- [ ] Doctor output never contains device serial numbers or iOS UDIDs, only counts
      and states.

## Approach

**`uv` and plain downloads, installed under `$HOME`**, as `install-without-admin.md`
already decides. Homebrew lost because its standard install needs admin.
`pip install --user` lost because it can't install the Python version itself.

**`./wiretrace` is a POSIX `sh` shim** that `exec`s `.venv/bin/python -m cli "$@"`.
- A Python file with `#!/usr/bin/env python3` lost: without the Command Line Tools,
  `python3` resolves to Apple's `/usr/bin/python3` stub, which opens the CLT install
  dialog instead of running the script.
- A `uv run --script` shebang lost: it needs `uv` on `PATH` at every run and would
  re-resolve dependencies, while the shim works with only `.venv`.

This differs from `PLAN.md` §9.1, which lists `wiretrace` as a Python executable. The
Python code moves into a `cli/` package next to the shim, where `start`, `report`
and the other subcommands will go later.

**Doctor uses only the standard library.** It must run, and say what is missing,
when the `pip install` step failed halfway. Package presence and versions are
read with `importlib.metadata`, not by importing the package.

**Port checks bind and release a socket** on `0.0.0.0` (UDP 51820, TCP 8080) and
`127.0.0.1` (TCP 8081), the addresses mitmweb uses. A failed bind is `FAIL` and
names the port, not the other process. Finding the other process needs `lsof`
permissions that are not worth requiring.

**The firewall is read with `/usr/libexec/ApplicationFirewall/socketfilterfw`**
(`--getglobalstate`, `--getblockall`, `--getappblocked <python>`). These read-only
queries work without sudo; this was checked on an admin account running without
sudo, and a standard account still needs to confirm it (Phase 0). The per-app
query uses the resolved real path of `.venv/bin/python`, because the firewall
judges the actual binary and not the venv symlink.

### Check list

| # | Check | OK | WARN | FAIL | INFO |
|---|---|---|---|---|---|
| 1 | Python ≥ 3.12 (the running interpreter) | yes | — | older | — |
| 2 | `mitmproxy` ≥ 11 installed, `mitmweb` in `.venv/bin` | yes | — | missing / older | — |
| 3 | `pyyaml`, `pymobiledevice3`, `httpx`, `keyring` installed | all | — | any missing | — |
| 4 | `adb` on `PATH` or in `~/tools/platform-tools` | found | not found (Android testing unavailable) | — | — |
| 5 | Ports UDP 51820, TCP 8080, TCP 8081 free | each free | — | each in use | — |
| 6 | `~/.mitmproxy/mitmproxy-ca-cert.pem` | exists | — | — | absent: "created on first start" |
| 7 | `~/.mitmproxy/mitmproxy-ca.pem` (private key) permissions | owner-only | readable by group/others | — | absent |
| 8 | Firewall global state, block-all, per-app state for the venv Python | off, or on with Python permitted | on and Python unknown to the firewall (a prompt will appear on first start) | block-all on, or Python blocked | — |
| 9 | Android devices (`adb devices`) | ≥ 1 in `device` state | any `unauthorized` (accept the prompt on the phone) | — | none connected / adb missing |
| 10 | iOS devices (`pymobiledevice3 usbmux list`) | ≥ 1 | — | — | none connected / command failed |

Each external command runs with a 10-second timeout; a timeout is reported as
`WARN` for that check and does not stop the others.

## Design that needs care

None. The work is sequential and runs once, with no concurrency or lifecycle
state. Two invariants still hold everywhere:

- **No privilege escalation**: the script and doctor never call `sudo`, never write
  outside `$HOME` and `wiretrace/`, and never call a CLT shim (`git`, `python3`,
  `xcrun`, `cc`, `make`).
- **Idempotent**: every step of `setup-mac.sh` checks before it acts. The `PATH`
  line is added to `~/.zshrc` only if that exact line is not already there.

## Files expected to change

- `wiretrace/requirements.txt` — new; the list in `PLAN.md` §5, unchanged.
- `wiretrace/requirements-dev.txt` — new; `-r requirements.txt` plus `pytest`. QA
  installs do not get test tools.
- `wiretrace/wiretrace` — new, executable `sh` shim (see Approach).
- `wiretrace/cli/__init__.py` — new, holds `__version__ = "0.1.0"`.
- `wiretrace/cli/__main__.py` — new; `argparse` with a `doctor` subcommand only.
- `wiretrace/cli/doctor.py` — new; the check list above. Parsers for `adb devices`
  and `socketfilterfw` output are pure functions so they can be tested.
- `wiretrace/scripts/setup-mac.sh` — new, executable. Flags: `--skip-android`,
  `--help`. Order: refuse root → install `uv` if absent (official installer,
  `UV_NO_MODIFY_PATH=1`; the script edits `~/.zshrc` itself) →
  `uv python install 3.12` → `uv venv --python 3.12` if `.venv` is absent →
  `uv pip install -r requirements.txt` → platform-tools unless skipped (download,
  `unzip`, remove the zip) → add `~/.local/bin` and `~/tools/platform-tools` to
  `~/.zshrc` idempotently → `./wiretrace doctor`.
- `wiretrace/tests/test_doctor.py` — new; see Automated tests.
- `wiretrace/.gitignore` — new; `.venv/`, `sessions/`, `__pycache__/`, `.pytest_cache/`.
- `wiretrace/README.md` — new and short: what Wiretrace is, the two setup commands, and
  links to `PLAN.md` and `docs/install-without-admin.md`.
- `wiretrace/docs/install-without-admin.md` — make the doctor list match the check list
  above, and mention `--skip-android`. Also fix the Gatekeeper example, which says
  `QA Proxy.app` where the rest of the docs say `Wiretrace.app`.

## Out of scope

- `start`, `report`, `sessions`, `login` subcommands and every Phase 1 feature (F1–F13).
- Doctor checks for Xcode / `simctl` and the YouTrack token (`PLAN.md` §9.7 lists them;
  each belongs to the spec of the feature that needs it).
- A dependency lock file / pinned versions. `requirements.txt` stays as `>=` ranges, as
  in `PLAN.md`; pinning is decided after Phase 0 shows which versions work.
- Shells other than zsh (the macOS default). bash users add the `PATH` line by hand;
  the script prints it.
- `git init` / creating the GitLab repository.
- Machine-readable doctor output (`--json`).

## Manual test

1. On a **standard (non-admin)** account on a company Mac: download `wiretrace/` as a
   zip, unzip into `~/wiretrace`, run `cd ~/wiretrace && ./scripts/setup-mac.sh`. No
   password prompt and no CLT dialog appear; doctor ends with no `FAIL`.
2. Run `./scripts/setup-mac.sh` again. It finishes quickly, and `~/.zshrc` has no
   duplicate lines.
3. Start `nc -lu 51820` in another terminal, run `./wiretrace doctor`. Port 51820 is `FAIL`, exit code `1`.
4. Connect an Android phone with USB debugging and an iPhone that trusts the Mac.
   Doctor shows one of each, with no serials or UDIDs.
5. `mv .venv .venv.off && ./wiretrace doctor` prints the setup hint and exits `1`.

## Automated tests

`tests/test_doctor.py`, `pytest`, no device or network needed:

- `adb devices` parser: empty list, one `device`, one `unauthorized`, mixed,
  daemon start-up noise lines.
- `socketfilterfw` parser: enabled / disabled global state, block-all on / off,
  per-app permitted / blocked / not listed.
- Port check: free port → `OK`; a port held by a test socket → `FAIL`.
- CA checks against a temporary `~/.mitmproxy`: absent → `INFO`; key `0600` → `OK`;
  key `0644` → `WARN`.
- Exit code: any `FAIL` → `1`; only `OK` / `WARN` / `INFO` → `0`.
- Privacy: doctor's rendered output for a parsed device list containing a serial does
  not contain that serial.

## Runtime check

On the maintainer's Mac (Intel, admin account, no `uv` installed): run
`setup-mac.sh` with `HOME` pointed at a fresh temporary folder, so `uv`, Python,
platform-tools and `.zshrc` all land there and the real home is untouched. Run it a
second time to check idempotence, then run `pytest`. A standard-account run on a
company Mac (manual test step 1) is not part of this check; it is part of
the `install-without-admin.md` Phase 0 check.

## Risks

- A dependency of `pymobiledevice3` or `mitmproxy` without a prebuilt wheel for the
  Mac's Python and CPU would need a compiler, which on a Mac without CLT opens the
  install dialog or fails. The runtime check on Intel and the Phase 0 run on Apple silicon
  show whether that happens; if it does, the fix is a version constraint, decided then.

## Errata

- 2026-10-13, runtime check: the risk above happened. `argon2-cffi-bindings` 26.1.0 (via
  `mitmproxy` → `argon2-cffi`) ships macOS wheels for arm64 only, so Intel Macs built
  it from source. Also, the first doctor run after setup timed out on the iOS check
  because the Python files had not been compiled to bytecode yet. Fix:
  `setup-mac.sh` installs with `uv pip install --only-binary :all: --compile-bytecode`.
  `uv` then picks the newest version that has a wheel (25.1.0 on Intel), and any
  future dependency that exists only as source stops the install with an error
  instead of starting a build.
- 2026-10-13, runtime check re-run: `--only-binary :all:` fixed the build (25.1.0 installed
  from a wheel). `--compile-bytecode` did not fix the iOS timeout: the first
  `pymobiledevice3 usbmux list` after install took 21.5 s wall clock for 1.6 s of
  CPU, and the next run took 3.4 s. That pattern suggests macOS scanning newly
  installed native libraries on first load (unconfirmed). Second fix:
  `setup-mac.sh` runs `pymobiledevice3 usbmux list` once before
  `doctor`. `--compile-bytecode` stays.
- 2026-10-13, after a run on the maintainer's own home: Astral's `install.sh` failed
  because `~/.config` there is owned by root, so its update receipt could not be
  written (the binary itself was in place). Separately, piping a downloaded script
  into `sh` runs unverified, unpinned code. Decision: `setup-mac.sh`
  downloads the pinned `uv` 0.13.0 release archive from GitHub and the pinned
  platform-tools r37.0.1 zip from Google, checks each against a SHA-256 stored in the
  script (cross-checked against the vendor's published `.sha256` / SHA-1), and
  unpacks them itself. No installer script runs and nothing is written to
  `~/.config`. A `~/.local/bin/uv` of another version is replaced by the pinned one.
  Downloads go to a `wiretrace/.download.*` folder, which is removed on exit.
