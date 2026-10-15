# Wiretrace

A macOS tool that shows and changes the API traffic of iOS and Android apps, next to the
app's logs. Built on [mitmproxy](https://mitmproxy.org). Installs without a Mac admin account.

Current version: **0.7.2**.

## Features

- **Setup check.** `./wiretrace doctor` checks Python, mitmproxy, the ports, the macOS
  firewall, `adb` and connected devices, and the CA certificate, and says what to fix.
- **Capture.** `./wiretrace start` runs mitmproxy in WireGuard mode (UDP 51820, the
  default) or as a Wi-Fi proxy (`--mode proxy`, TCP 8080). `--target` is `android`, `ios`,
  `android-emu`, `ios-sim` or `device`. Each session is saved in its own folder under
  `sessions/`, as it happens.
- **Presets.** One YAML file per project and environment. Only the listed API hosts are
  decrypted; all other traffic passes through untouched. A preset also sets the starting
  filter, the mocks folder, the request ID header, the app to collect logs from, and extra
  names to mask.
- **Mocks from files.** A file `mocks/<preset>/<METHOD>/<path>.json` answers that request
  instead of the backend. Changes apply to the next request, without a restart.
- **Rules.** Per request: answer with a mock or a status code, wait a number of
  milliseconds, or drop the connection, always, once, or every Nth call. Edited in the
  Wiretrace window's *Rules* view and saved in `rules/<preset>.json`. The older
  `qa_fault_*` options still work in mitmweb.
- **Device logs.** The app's own process log, collected next to the traffic: `adb logcat`
  for Android devices and emulators, `pymobiledevice3` for iPhones, `simctl` for the iOS
  Simulator. The log follows the app across restarts and reconnects.
- **In-app logs.** A test build can `POST` its own log lines to `https://qa-logs.internal/log`;
  Wiretrace answers that name itself and stores the lines in the session. Nothing leaves the Mac.
- **Request IDs.** The `X-Request-ID` header (or another one set in the preset) links a
  request to the log lines that carry the same ID.
- **Masked HAR.** When a session stops, Wiretrace writes `flows.har` with passwords, tokens
  and cookies replaced by `***`.
- **Bug report zip.** `./wiretrace report` packs a session into one zip: a summary with the
  failed requests, the masked HAR, and the masked logs.
- **Wiretrace window (preview).** `--ui wiretrace` opens Wiretrace's own window, with traffic
  and logs on one screen and the Rules view. It is only reachable from the same Mac, with a new
  token at every start. mitmweb stays the default, so without `--ui wiretrace` you get mitmweb
  and no Rules view; `--no-ui` runs in the Terminal only.
- **Release files.** `make tarball` (or `make release`, which also makes the `.dmg`) runs
  `scripts/build-release.sh`, which builds a `.tar.gz` and a `.dmg`, each with a
  SHA-256 checksum, from one commit.

Masking has limits (for example, bodies that are neither JSON nor forms are not changed).
Read [what is and is not masked](docs/user-guide.md#step-5--export-for-the-bug-ticket)
before you share a report.

## Requirements

- A Mac with macOS, Intel or Apple silicon. A standard (non-admin) account is enough.
  On an Intel Mac, setup installs `cryptography` 48.0.1, the last release with an Intel
  wheel, so its three advisories of 2026 (fixed in 49.0.0 and 50.0.0) stay open there. Apple
  silicon gets the fixed release.
- Internet access to `github.com`, `pypi.org` and `dl.google.com` during setup.
- A test build of the app that trusts user-installed CA certificates and has certificate
  pinning turned off. Store builds cannot be decrypted.
- The WireGuard app on the phone (for WireGuard mode).
- For Android: a phone with USB debugging, or an emulator. For iOS: an iPhone that trusts
  the Mac, or the iOS Simulator (needs Xcode's command line tools).

Use Wiretrace only with apps, devices and accounts you are allowed to test.

## Quick start

Download `wiretrace-0.7.2-macos.tar.gz` and its `.sha256` file from the Releases page, then:

```bash
cd ~/Downloads
shasum -a 256 -c wiretrace-0.7.2-macos.tar.gz.sha256
tar -xzf wiretrace-0.7.2-macos.tar.gz -C ~

cd ~/wiretrace
scripts/setup-mac.sh                 # add --skip-android if you only test iOS
./wiretrace doctor                   # re-check the setup at any time
```

Create a preset with your API hosts, then capture a session:

```bash
cp presets/example.yaml presets/staging.yaml     # set name: staging and api_hosts
./wiretrace start --preset staging --target android
```

This opens mitmweb. For Wiretrace's own window, with the Rules view, add `--ui wiretrace`:

```bash
./wiretrace start --preset staging --target android --ui wiretrace
```

Use the app, then press Ctrl+C. Wiretrace writes `flows.har` (secrets masked) into the
session folder. For a bug ticket:

```bash
./wiretrace report
```

The first time, connect each phone to Wiretrace and install its certificate. The
[user guide](docs/user-guide.md) covers this and everything else, step by step.

## Design

The images below are **design mockups**, not screenshots of the current product. All data
in them is illustrative. They show where Wiretrace is going; the Wiretrace window (preview)
already covers part of screens 1 to 3. Source and notes: [`mockups/`](mockups/README.md).

| Mockup | Status |
|---|---|
| 1. Main window | Partly built in the preview window: traffic list, filters, detail panel, log strip. |
| 2. Device and app logs | Partly built: log tabs, levels and search. Not yet: device picker, timeline. |
| 3. Device setup wizard | Partly built: the preview's Setup panel shows the QR code and certificate steps. |
| 4. Mock and fault rules editor | Built in the preview window: rule list, editor, test against a request, live counters, import and export. |
| 5. Send a bug report to YouTrack or Jira | Not built yet. Today: `./wiretrace report` writes a zip. |
| 6. Menu-bar app | Not built yet. |

**1. Main window** (design mockup)

![Design mockup: main window](mockups/screens/01-main-window.png)

**2. Device and app logs** (design mockup)

![Design mockup: device and app logs](mockups/screens/02-device-app-logs.png)

**3. Device setup wizard** (design mockup)

![Design mockup: device setup wizard](mockups/screens/03-device-setup-wizard.png)

**4. Mock and fault rules editor** (design mockup)

![Design mockup: mock and fault rules editor](mockups/screens/04-mock-fault-rules.png)

**5. Bug report to YouTrack or Jira** (design mockup, not built yet)

![Design mockup: bug report to YouTrack or Jira](mockups/screens/05-bug-report.png)

**6. Menu-bar app** (design mockup, not built yet)

![Design mockup: menu-bar app](mockups/screens/06-menu-bar.png)

## Documents

- [`docs/user-guide.md`](docs/user-guide.md): install, device setup, and daily use, step by step
- [`docs/install-without-admin.md`](docs/install-without-admin.md): what needs admin rights and what does not
- [`docs/diagrams.md`](docs/diagrams.md): workflows and diagrams
- [`PLAN.md`](PLAN.md): goals, architecture, phases
- [`docs/specs/`](docs/specs/): the spec for each piece of work

## Development

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest
```

Release files (`.tar.gz` and `.dmg`, with checksums) are built from a commit into `dist/`:
`make tarball` (the `.tar.gz` only), `make release` (both), with `COMMIT=<ref>` for another
commit than `HEAD`. They run `scripts/build-release.sh [--tar-only] [<commit>]`. Commit first,
including `ui/dist/` after `make ui`: uncommitted changes are never in a release.

## License

Wiretrace is licensed under the [Apache License 2.0](LICENSE). See [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE).

Third-party software:

- [mitmproxy](https://mitmproxy.org) is MIT-licensed.
- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) is licensed under
  GPL-3.0-or-later. `scripts/setup-mac.sh` installs it from PyPI, and Wiretrace runs it as a
  separate command. Wiretrace does not import it, and the release archive does not include it.
