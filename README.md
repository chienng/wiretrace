# Wiretrace

Internal macOS tool for mobile QA: see and change the API traffic of iOS and Android
apps, next to the app's logs. Built on [mitmproxy](https://mitmproxy.org).
Installs and runs without a Mac admin account.

## Setup

```bash
cd ~/wiretrace
scripts/setup-mac.sh
```

Add `--skip-android` if you only test iOS. Re-check the setup at any time with
`./wiretrace doctor`.

Capture a session: `./wiretrace start --preset staging --target android` (presets live in
`presets/`; copy `presets/example.yaml` to start one). Ctrl+C stops it and writes `flows.har`.

Step-by-step installation and usage: [`docs/user-guide.md`](docs/user-guide.md).
Details, and what needs IT's help: [`docs/install-without-admin.md`](docs/install-without-admin.md).

## Documents

- [`docs/user-guide.md`](docs/user-guide.md): install, device setup, and daily use, step by step
- [`PLAN.md`](PLAN.md): goals, architecture, phases
- [`docs/install-without-admin.md`](docs/install-without-admin.md): installing as a standard user
- [`docs/diagrams.md`](docs/diagrams.md): workflows and diagrams
- [`docs/specs/`](docs/specs/): approved specs for each piece of work

## Development

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest
```
