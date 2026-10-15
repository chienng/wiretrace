# Spec: security fixes before publishing

- **Date**: 2026-10-15
- **Risk**: high — file permissions on captured tokens, what the proxy accepts from the
  network, and which secrets leave the Mac in bug reports. Needs a code, security and privacy
  review and a runtime check.
- **Repo**: wiretrace
- **Status**: approved (2026-10-15)
- **Branch**: `fix/security-findings`
- **Related**: spec 002 (launcher, sessions), spec 003 (mocks), spec 005 (redaction, report),
  spec 006 (the window's server and its bounded body decoding)

## Goal

Fix the one high and four medium findings of the security audit of 2026-10-15, and take the
fixed versions of four dependencies, before the repo is published. Version 0.7.2.

## Acceptance criteria

### 1. Captured sessions are private to the Mac user (high)

- [ ] Every file and folder Wiretrace creates is readable only by its owner: `sessions/` and
      each session folder `0700`; `meta.json`, `flows.mitm`, `.flows.har.tmp`, `flows.har`,
      both log files and the report zip `0600`. This also holds for files mitmdump and the
      collectors write.
- [ ] Starting Wiretrace sets an existing `sessions/` folder to `0700`, so sessions recorded by
      older versions are no longer readable by other users either.

### 2. Proxy mode accepts only this Mac and the device under test (medium)

- [ ] In proxy mode, connections from the Mac itself (`127.0.0.0/8`, `::1`) are always
      accepted; this is how the iOS Simulator and the Android emulator connect.
- [ ] Without `--client`, the first other device that connects is the only other device
      accepted for the rest of the session. A connection from any other address is closed
      before a request is read. The first refusal prints one Terminal line (no address):
      `Proxy: refused a connection from another device. Only the first device that connected
      is accepted; restart Wiretrace, or pass --client <its IP address>.`
- [ ] `./wiretrace start … --client 192.168.1.20` (repeatable) accepts exactly those devices
      plus the Mac, and nothing is pinned. An invalid IP address is refused by the launcher.
- [ ] A device other than the Mac cannot reach the Mac's own loopback services through the
      proxy: a server connection to a loopback, link-local or unspecified address (an IP
      literal, `localhost`, or a name that resolves to one) is refused for such a client.
- [ ] WireGuard mode is unchanged (only the device holding the tunnel key can connect).

### 3. A mocks folder cannot point outside the wiretrace folder (medium)

- [ ] A preset whose `mocks_dir` resolves, through symlinks, outside the wiretrace folder is
      refused at start with `'mocks_dir' must be a folder inside the wiretrace folder`.
- [ ] The QA addon serves a mock file only when its mocks folder resolves inside the
      wiretrace folder, and only for the methods `GET`, `HEAD`, `POST`, `PUT`, `PATCH`,
      `DELETE` and `OPTIONS`, spelled in capitals.
- [ ] The window's mock file list walks at most `MAX_MOCK_FILES` files, does not follow
      symlinked folders, and returns the files it found sorted.

### 4. A compressed body cannot exhaust memory in the HAR or the report (medium)

- [ ] Before a HAR is built (the masked `flows.har` when a session stops, and the report's),
      each request and response body whose decoded size is over 16 MiB, counted without
      holding it in memory, is replaced by the text
      `Wiretrace: body left out, it decodes to more than 16 MiB.` with its
      `Content-Encoding` removed. A body that does not decode is kept as it travelled.
- [ ] A session with a 10 MB gzip response that decodes to 1 GiB gives a report and a
      `flows.har`, and the capture process stays up when the report is made from the window.

### 5. Redaction catches the common secret names, headers and tokens (medium)

- [ ] JSON fields, form fields and query parameters are masked when their name (normalized
      as today: lower case, no `_` or `-`) is one of today's defaults or `otp`, `pin`,
      `codeverifier` or `sessionid`, **or contains** one of `password`, `passwd`,
      `passphrase`, `secret`, `token`, `apikey`, `privatekey`, `recoverykey`, `credential`.
      Example: `newPassword`, `current_password`, `auth_token`, `sessionToken`, `x-api-key`.
- [ ] Headers are masked when their name is in today's list or `X-Api-Key`, `X-Auth-Token`,
      `X-Amz-Security-Token`, or contains one of the stems above.
- [ ] `Referer` and `Content-Location` URLs have their query masked like `Location`.
- [ ] A `multipart/form-data` request body is replaced by
      `Wiretrace: multipart body left out; parts: <names>` (part names only).
- [ ] Log text masks JSON Web Tokens (`eyJ…​.…​.…`) and Matrix tokens (`syt_`, `syr_`, `mat_`,
      `mar_`, `mct_`, `mcr_` followed by token characters) wherever they appear.
- [ ] `code` stays unmasked by default (error bodies use it for error codes); a preset can add
      it to `redact.json_fields`. The user guide says so.

### 6. Dependencies with known vulnerabilities

- [ ] `scripts/setup-mac.sh` installs with `--overrides overrides.txt` under mitmproxy
      12.2.3. The ceilings are the limits its `main` branch already tests (2026-10-15):
      `cryptography` ≤ 50.0.2, `h2` ≤ 4.4.1, `tornado` ≤ 6.5.10. The floors are the first
      releases that close the advisories (`cryptography` ≥ 50.0.0, `h2` ≥ 4.4.1,
      `tornado` ≥ 6.5.9), so an existing install is upgraded. `msgpack` ≥ 1.2.1 stays in
      that file: 12.2.3 declares `msgpack` ≤ 1.1.2 and neither mitmproxy nor pymobiledevice3
      imports it; `main` dropped the dependency.
- [ ] `uvx pip-audit` on the installed environment reports none of the 15 advisories found
      on 2026-10-15.

### All

- [ ] Version 0.7.2. User guide: sessions are private; proxy mode accepts the first device
      or `--client`; the redaction list. All Python and frontend tests pass; `ui/dist` is
      unchanged unless the frontend changes (it should not).

## Approach

1. `cli/__main__.py` sets `os.umask(0o077)` first thing, so the launcher and every process
   it starts create private files. `session.create` makes folders with mode `0o700` and
   sets `sessions/` to `0o700`.
2. A new `-s` addon, `addons/proxy_guard.py`, loaded only in proxy mode, with options
   `qa_proxy_clients` (addresses always accepted) and `qa_proxy_pin` (pin the first other
   client). The launcher passes `127.0.0.1`, `::1` and any `--client` addresses, and pins
   only when no `--client` is given.
3. `mocks_dir` is checked with `resolve()` against the wiretrace folder, in the preset and
   again in the addon. Methods come from a fixed set.
4. The bounded decoding now in `addons/wiretrace_ui.py` moves to `cli/bodies.py`, with a new
   `trim_oversized(flow, limit)`. The report calls it on copies of the flows before
   `make_har`. The stop-time HAR run (`mitmdump -n -r flows.mitm --set hardump=…`) loads a
   new `addons/har_guard.py`, whose `response`, `error` and `websocket_end` hooks trim each
   flow. Flows read with `-r` pass through every addon hook, and `-s` scripts run before
   mitmproxy's own `savehar`, so the HAR is built from trimmed flows.
5. Redaction rules gain stems (substring match) next to exact names; the rest as listed.
6. `overrides.txt` at the repo root; `git archive` ships it in the release.

Rejected:
- **Proxy:** listening only on loopback (a phone could not connect); `proxyauth` (Android's
  Wi-Fi proxy setting has no password field); requiring `--client` always (QA rarely know the
  phone's IP; pinning plus the refusal line covers the attack, which needs another device to
  connect first and is visible).
- **Bombs:** building the stop-time HAR in the launcher process (Ctrl+C handling while it
  runs is tested around the subprocess today).
- **Redaction:** masking `code` (hides error codes, the most useful line of a failed response);
  masking multipart parts one by one (file parts are binary; part names are enough for a bug).
- **Dependencies:** forking mitmproxy (the fixes are already upstream and unreleased).

## Design that needs care

### Proxy guard (`client_connected`, `server_connect`, on the event loop)

State: `pinned: str | None`, set at most once per process; `refused: int`.

1. `client_connected(client)`: `ip = normalize(client.peername[0])` (IPv4-mapped IPv6 to
   IPv4). If `ip` is in `qa_proxy_clients`, or `ip == pinned`: accept. Else if
   `qa_proxy_pin` and `pinned is None`: `pinned = ip`, accept. Else: set `client.error`
   (mitmproxy closes the connection), `refused += 1`, print the line once when `refused == 1`.
2. `server_connect(data)`: if the client's address is loopback, allow. Else resolve
   `data.server.address[0]` (IP literal, or `loop.getaddrinfo`); if any result is loopback,
   link-local or unspecified, set `data.server.error`.

Invariants:
1. A connection from an address not accepted in step 1 never reaches a request hook.
2. `pinned` changes from `None` to an address once and never again.
3. A client that is not loopback never gets a server connection opened to a loopback,
   link-local or unspecified address that was known when `server_connect` ran.

Known limit: a name whose DNS answer changes between the check and mitmproxy's own lookup
(DNS rebinding) is not caught.

Value types are `NamedTuple`, not `@dataclass` (a dataclass in a `-s` script fails at load).

### Tests derived

- `client_connected`: listed address accepted; first other address pinned; second other
  address refused and counted; refusal line printed once and without the address; with
  `qa_proxy_pin` off nothing is pinned; IPv4-mapped IPv6 matches its IPv4 form.
- `server_connect`: loopback client may reach `127.0.0.1`; other client refused for
  `127.0.0.1`, `::1`, `localhost`, `169.254.1.1`, `0.0.0.0`, and a name resolving to
  `127.0.0.1` (resolver stubbed); allowed for a public name.
- A real `mitmdump -s addons/proxy_guard.py` in regular mode with `qa_proxy_clients` not
  containing `127.0.0.1` and pinning off refuses a request from `127.0.0.1` (proves the
  script loads and `client.error` closes the connection).
- `bodies.trim_oversized`: gzip, deflate, br and zstd bombs replaced; under-limit bodies and
  bodies that do not decode unchanged; `Content-Encoding` removed only when replaced.
- A real `mitmdump -n -r` with `har_guard.py` on a flow file holding a gzip bomb writes a
  HAR with the placeholder (proves hooks run before `savehar`).
- `report.create` on a session with a bomb succeeds; its HAR has the placeholder.
- Permissions: under `umask 022`, `session.create` gives `0700` folders; `main()` sets the
  umask to `0o077`; an existing `0755` `sessions/` becomes `0700`; a real start writes
  `flows.mitm` as `0600`.
- Mocks: symlinked `mocks_dir` to `/` refused by the preset check and ignored by the addon;
  lower-case and non-standard methods give no mock; `list_mocks` stops at the cap and skips a
  symlinked folder.
- Redaction: each new name, stem and header masked; `code` unmasked; a non-secret field that
  contains a stem (`tokenCount`) masked, an accepted over-match; `Referer` query masked;
  multipart replaced with part names; JWT and `syt_` tokens masked in log lines and in log
  JSON values.
- Launcher: `--client` adds addresses and turns pinning off; invalid IP refused; proxy guard
  loaded only in proxy mode; `har_command` loads `har_guard.py`.

## Files expected to change

- `cli/__main__.py`: `os.umask(0o077)`; `--client` option for `start`.
- `cli/session.py`: folder modes; `sessions/` tightened.
- `cli/start.py`: proxy guard and its options in proxy mode; `har_guard.py` in `har_command`.
- `cli/preset.py`: `mocks_dir_problem` resolves against the wiretrace folder.
- `cli/bodies.py` (new): bounded decoding moved from `addons/wiretrace_ui.py`, `trim_oversized`.
- `cli/report.py`: trim before `make_har`.
- `cli/redact.py`: names, stems, headers, `Referer`/`Content-Location`, multipart, token patterns.
- `addons/proxy_guard.py` (new), `addons/har_guard.py` (new).
- `addons/qa_tools.py`: method set; mocks root inside the wiretrace folder.
- `addons/wiretrace_ui.py`: imports from `cli/bodies.py`; capped `list_mocks`.
- `overrides.txt` (new); `scripts/setup-mac.sh`: `--overrides overrides.txt`.
- Version 0.7.2: `cli/__init__.py`, `ui/package.json`, `ui/package-lock.json`,
  `ui/dev/fixtures/state.json`, and the tests that check the version.
- `docs/user-guide.md`; tests: `tests/test_{session,start,preset,qa_tools,redact,report,wiretrace_ui}.py`,
  new `tests/test_{proxy_guard,bodies,har_guard}.py`.

## Out of scope

- The low and informational findings of the audit (request-ID labels, rule wildcards, cookie
  and token in history, hashed lock file, `--globoff`, Markdown in `summary.md`, the receiver
  save filter, `RecursionError` in the receiver, `curl --proto`, checking `ui/dist`).
- Permissions of `~/.mitmproxy` (mitmproxy's own CA files) and of the zip's members.
- Base64 bodies (still accepted as is, spec 005).
- Removing `overrides.txt` once mitmproxy releases the new limits.

## Manual test (about 10 minutes)

1. `scripts/setup-mac.sh`, then `uvx pip-audit` on the environment: no advisories from the list.
2. `./wiretrace start --preset <dev preset> --target android --mode proxy`; set the phone's
   Wi-Fi proxy to the Mac: traffic appears. From a second device with the same proxy setting:
   no page loads, and the Terminal shows the refusal line once.
3. From the phone's browser, open `http://127.0.0.1:8081/`: refused.
4. Stop, then `ls -l sessions/` and the new session folder: `drwx------` and `-rw-------`.
5. `./wiretrace report <session>`: a request with `X-Api-Key` and a `newPassword` field shows
   `***` in `flows.har` inside the zip.
6. WireGuard mode on an iPhone: traffic and the certificate page as before (h2 4.4.1).

## Automated tests

`.venv/bin/python -m pytest` (the list above plus the existing tests), `npm --prefix ui test`.
Runtime check: the manual test steps 2–6 on a real device, and a real start with the
`mitmdump -r` HAR on a session containing a gzip bomb.
