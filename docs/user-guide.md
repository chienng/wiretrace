# Wiretrace — Installation and usage guide

For QA engineers. Covers Wiretrace **0.4.0**.

What 0.4.0 gives you: a one-command install that needs no admin rights, a setup
check (`./wiretrace doctor`), project presets, and `./wiretrace start --preset …`, which
captures only your project's API traffic and saves each session in its own folder with a
HAR file, mocks, injected faults, and the app's logs next to the traffic (Part 3).
Redaction and bug-report export are planned ([`PLAN.md`](../PLAN.md) Phase 1) and not in
this version yet.

---

## Part 1 — Install (once per Mac)

### Before you start

- A Mac with macOS. A **standard (non-admin) account is fine**; you will not be asked
  for a password.
- Internet access to `github.com`, `pypi.org`, and `dl.google.com` during the install.
  If the company network blocks one of them, ask IT.
- The release file and its checksum: either `wiretrace-0.4.0-macos.tar.gz` and
  `wiretrace-0.4.0-macos.tar.gz.sha256`, or `wiretrace-0.4.0-macos.dmg` and
  `wiretrace-0.4.0-macos.dmg.sha256`. Both contain the same files.

### Step 1 — Check the download

Open **Terminal**, go to the folder with both files (usually Downloads), and run the line
for the file you have:

```bash
cd ~/Downloads
shasum -a 256 -c wiretrace-0.4.0-macos.tar.gz.sha256
shasum -a 256 -c wiretrace-0.4.0-macos.dmg.sha256
```

It must print `…: OK`. If it prints `FAILED`, download the file again and do not continue.

### Step 2 — Put the wiretrace folder in your home folder

**From the `.tar.gz`:**

```bash
tar -xzf wiretrace-0.4.0-macos.tar.gz -C ~
```

Use this command rather than double-clicking the file in Finder, so the folder ends up in
the right place.

**From the `.dmg`:** double-click it, drag the `wiretrace` folder onto your home folder (in
Finder: **Go → Home**), then eject **Wiretrace 0.4.0**. Wiretrace cannot run from the disk
image itself, because the image is read-only.

Either way you now have `~/wiretrace`.

### Step 3 — Run the setup

```bash
cd ~/wiretrace
scripts/setup-mac.sh
```

If you only test iOS, use `scripts/setup-mac.sh --skip-android`.

The first run takes a few minutes. It installs, all inside your home folder:

| What | Where |
|---|---|
| `uv` 0.13.0 (Python installer) | `~/.local/bin` |
| Python 3.12 | `~/.local/share/uv` |
| mitmproxy, pymobiledevice3 and the other packages | `~/wiretrace/.venv` |
| Android platform-tools r37.0.1 (`adb`) | `~/tools/platform-tools` |
| Two `PATH` lines | `~/.zshrc` |

Every download is checked against a SHA-256 checksum stored in the script; a file that
does not match is never installed. Running the script again is safe and quick.

Do **not** run it with `sudo`. It refuses, because the files in your home folder would
end up owned by root.

### Step 4 — Open a new Terminal window

The `PATH` changes apply only to new windows (or run `exec zsh`).

### Step 5 — Read the setup check

The script ends with `./wiretrace doctor`. You can run it again at any time:

```bash
cd ~/wiretrace && ./wiretrace doctor
```

Each line is `OK`, `INFO`, `WARN`, or `FAIL`. Only `FAIL` must be fixed before you
continue.

| Line | What to do |
|---|---|
| `FAIL Python` / `mitmproxy` / `Python packages` | Run `scripts/setup-mac.sh` again. |
| `FAIL Port … in use` | Another proxy (or an old Wiretrace window) is running. Quit it. |
| `FAIL macOS firewall: blocks all incoming connections` | Ask IT for an allow rule for UDP 51820 and TCP 8080. |
| `WARN macOS firewall: on; macOS will ask …` | Normal. Click **Allow** when macOS asks the first time you start mitmproxy. |
| `WARN adb: not found` | Only matters for Android. Run the setup without `--skip-android`. |
| `WARN Android devices: … unauthorized` | Unlock the phone and accept **Allow USB debugging**. |
| `INFO CA certificate: not created yet` | Normal before the first start. |
| `WARN CA private key: readable by other users` | Run the `chmod 600 …` command shown. |

### Step 6 — Create a preset for your project

A preset tells Wiretrace which API hosts to decrypt. It is one file per project and
environment in `~/wiretrace/presets/`. Start from the example:

```bash
cd ~/wiretrace
cp presets/example.yaml presets/staging.yaml
open -e presets/staging.yaml
```

Set `name: staging` (it must match the file name) and list your API hosts under
`api_hosts`: host names only, such as `api-staging.mycompany.com`, without `https://`,
port, or path. Each host's subdomains are included. The comments in the file explain the
other fields. If the file has a mistake, `./wiretrace start` names the file and the problem.

---

## Part 2 — Prepare a test device (once per device)

You need a **QA build** of the app: certificate pinning off, and on Android, user CAs
trusted (requirements R1 and R2 in [`PLAN.md`](../PLAN.md#7-requirements-for-the-mobile-development-team)).
With a store or release build, HTTPS traffic cannot be decrypted.

### Step 1 — Start Wiretrace with its web UI

```bash
cd ~/wiretrace && source .venv/bin/activate
mitmweb --mode wireguard
```

Use this plain command here, not `./wiretrace start`: the launcher decrypts only your
preset's hosts, so the `mitm.it` page in Step 3 would not load through the tunnel.

A browser tab opens with mitmweb. The first time, macOS may ask whether to allow
incoming connections: click **Allow**.

`source .venv/bin/activate` puts `mitmweb`, `mitmdump`, `mitmproxy` and
`pymobiledevice3` on your `PATH` for that Terminal window. Do it in every new window.

### Step 2 — Connect the phone

1. Install the **WireGuard** app (App Store / Google Play).
2. In WireGuard, add a tunnel by scanning the QR code that mitmweb shows.
3. Turn the tunnel on.

The tunnel keys are stored in `~/.mitmproxy/wireguard.conf` and reused on every start, so
you only scan the QR code once per device.

No browser? `mitmdump --mode wireguard` prints the same configuration as text
(`[Interface] … [Peer] … Endpoint = <Mac IP>:51820`); enter it in WireGuard with
**Create from scratch**.

### Step 3 — Install and trust the Wiretrace certificate

With the tunnel on, open `http://mitm.it` on the phone. This page is served by Wiretrace on
your Mac, not by the internet. If it says *"traffic is not going through mitmproxy"*, the
tunnel is off or not connected.

**iPhone**

1. On `mitm.it`, tap **Get mitmproxy-ca-cert.pem** under iOS, and allow the download.
2. Settings → General → VPN & Device Management → install the **mitmproxy** profile.
3. Settings → General → About → Certificate Trust Settings → turn on full trust for
   **mitmproxy**. Without this step, HTTPS still fails.

**Android**

1. On `mitm.it`, download the Android certificate.
2. Settings → Security → Encryption & credentials → Install a certificate → **CA certificate**
   (the menu names vary by vendor).

**If `mitm.it` does not load**, install the certificate file directly. It is on your Mac at
`~/.mitmproxy/`:

- iPhone: AirDrop or email `~/.mitmproxy/mitmproxy-ca-cert.pem` to the phone, then do
  steps 2 and 3 above.
- Android (USB debugging on):

  ```bash
  adb push ~/.mitmproxy/mitmproxy-ca-cert.cer /sdcard/Download/
  ```

  then Settings → Security → Install a certificate → CA certificate → pick the file.

### Step 4 — Check

Open the app on the phone. Its requests appear in mitmweb. If HTTPS requests show
errors, see [Troubleshooting](#part-5--troubleshooting).

Then press **Ctrl+C** in the mitmweb window. `./wiretrace start` needs the same ports and
does not start while this mitmweb is still running.

---

## Part 3 — Test with Wiretrace (every session)

The examples use a preset named `staging` (Part 1, Step 6).

### Step 1 — Start capturing

```bash
cd ~/wiretrace
./wiretrace start --preset staging --target android
```

mitmweb opens in a browser tab, in WireGuard mode. Wiretrace prints where the session is
saved, for example `sessions/2026-10-13_143005_staging_android/`.

- Only the preset's `api_hosts` and their subdomains are decrypted. Other apps and
  third-party traffic pass through untouched.
- Every request and response is saved to `flows.mitm` in the session folder as it
  happens, so nothing is lost if you close the window.
- `--target` is `android`, `ios`, `android-emu`, `ios-sim`, or `device` (the default). It
  names the session folder, picks the setup reminders printed at start, and picks which
  device log is collected (Step 2).
- `--no-ui` runs in the Terminal only (mitmdump) instead of opening mitmweb.
- `--mode proxy` runs a regular proxy on port 8080 instead of WireGuard. Set the phone's
  Wi-Fi proxy to `<Mac IP>:8080`.
- The preset's `default_filter` is the starting filter: in mitmweb's search box, or what
  is printed with `--no-ui`. It never limits what is saved. Common filters:
  `~c 500` (status 500), `~m POST`, `~u /api/v1/orders`, `~bs "SOME_TEXT"` (response body).
  More in [`PLAN.md` Appendix B](../PLAN.md#appendix-b--mitmweb-filter-expressions-for-qa).
- If a port is in use, Wiretrace says which one and does not start. Usually another Wiretrace or mitmproxy window is still open: quit it.

### Step 2 — See the app's logs

Wiretrace collects the app's log for you, in the same Terminal and the same session folder.
You do not open a second window. It needs the app's name in your preset (Part 1, Step 6):

```yaml
app:
  android_package: com.mycompany.myapp   # for --target android or android-emu
  ios_process: MyApp                      # for --target ios or ios-sim
```

| `--target` | Where the log comes from | What you need |
|---|---|---|
| `android`, `android-emu` | `adb logcat`, only the app's process | `app.android_package`; one phone connected by USB with USB debugging on, or one running emulator |
| `ios` | `pymobiledevice3 syslog live`, only the app's process | `app.ios_process`; one iPhone connected by USB that trusts this Mac |
| `ios-sim` | the Simulator's `log stream`, only the app's process | `app.ios_process`; one booted Simulator; Xcode's command line tools (`xcrun`) |
| `device` | none | Use one of the targets above to get a device log. |

Wiretrace prints one line at start, for example
`Device logs: Android, com.mycompany.myapp → device.log.jsonl`. If a device log is off,
the same line says why: `--target device`, a missing `app.android_package` or
`app.ios_process` in the preset, or a missing tool (`adb`, `pymobiledevice3`, `xcrun`).
Wiretrace still starts, and the traffic is captured as usual.

The log goes to `device.log.jsonl` in the session folder: one JSON object per line.

```json
{"ts": "2026-10-14T09:30:12.481+07:00", "source": "android", "level": "E", "tag": "OkHttp", "message": "…"}
```

| Field | Meaning |
|---|---|
| `ts` | When the line was logged, in this Mac's time zone. |
| `source` | `android`, `ios`, or `ios-sim`. |
| `level` | `V`, `D`, `I`, `W`, `E`, or `F`. iOS logs use only `D`, `I`, `E`, and `F`. |
| `tag` | Android: the log tag. iOS: the log category, or the subsystem. |
| `message` | The text, as the app logged it. |

Watch it while you test: `tail -f sessions/<session folder>/device.log.jsonl`.

What to expect:

- Wiretrace prints the state of the log on the Terminal, starting with `Device logs:`.
  It never prints the log lines themselves, or the phone's serial number.
- **Android:** you can start Wiretrace before or after the app. Lines the app logged before
  its first screen are included, but not lines from before you ran `./wiretrace start`. If you
  force-stop the app, or it crashes, and you open it again, the new process is followed,
  and the crash stack trace is in the file.
- **iPhone and Simulator:** the log keeps going after the app restarts.
- Unplug the phone and plug it back in: the log resumes by itself. Nothing is lost from the
  traffic capture in the meantime.
- The log needs exactly **one** device. With none, or with more than one, Wiretrace says so
  (`waiting for a device`, `more than one device connected; connect only one`) and checks
  again every 2 seconds. Disconnect the extra phone or quit the extra emulator.
- Ctrl+C stops the log with everything else. No `adb`, `pymobiledevice3` or `log` process
  is left behind.

The log stays on your Mac. Nothing is sent to any server.

**Logs the app sends itself** go to `app.log.jsonl` in the same folder. That needs a QA
build that supports it; see *Logs from the app* below. In WireGuard mode the phone must
look up names through Wiretrace, so turn off **Private DNS** on Android (Settings → Network
& internet → Private DNS → Off; the menu names vary by vendor), and remove any encrypted
DNS profile on the iPhone (Settings → General → VPN & Device Management). With the Wi-Fi
proxy (`--mode proxy`) you do not need this.

### Step 3 — Reproduce the problem

Use the app as usual. Note the time when the problem happens; it makes it easier to find
the request and the log lines.

### Step 4 — Stop

Press **Ctrl+C** once in the Wiretrace window. It stops mitmproxy and the device log, writes
`flows.har` next to `flows.mitm`, and prints the session folder. If it says *still
stopping*, press Ctrl+C again to force it. If nothing was captured (no requests and no log
lines), the session folder is removed. If only log lines were captured, the folder is kept
and Wiretrace says that `flows.har` was not written.

`meta.json` in the session folder says which device log ran (`device_logs`) and how many
lines each log file has (`device_log_lines`, `app_log_lines`).

For an iOS crash, also pull the crash reports into the session folder (the launcher does
not do this for you yet; see *Without the launcher*).

### Step 5 — Export for the bug ticket

Attach `flows.har` from the session folder. It opens in Chrome DevTools, Charles,
Proxyman, …

To look at the session again later: `mitmweb -r flows.mitm`. In mitmweb you can also
copy a single request as cURL.

> **Important: exports are not redacted yet.** `flows.mitm`, `flows.har`,
> `device.log.jsonl` and `app.log.jsonl` contain access tokens, cookies, request IDs, and
> whatever the test account sent or the app logged. Attach them only
> to internal tickets, never to public places or chats. Automatic redaction is planned
> (feature F5). Use test accounts only.

### Without the launcher

`./wiretrace start` runs mitmproxy for you. To run it yourself, for example to add options
the launcher does not pass on yet:

```bash
cd ~/wiretrace && source .venv/bin/activate
mkdir -p sessions/my-session && cd sessions/my-session
mitmweb --mode wireguard \
  --allow-hosts '(^|\.)api-staging\.mycompany\.com(:\d+)?$' \
  -w flows.mitm
```

- Repeat `--allow-hosts` for each host. mitmproxy matches the pattern against `host:port`
  (e.g. `api-staging.mycompany.com:443`), so keep the `(:\d+)?` before the `$`; without it
  nothing is decrypted.
- Use `mitmdump` instead of `mitmweb` for the Terminal only; add `--flow-detail 3` to also
  print headers and bodies.
- After stopping, make the HAR file yourself:
  `mitmdump -n -r flows.mitm --set hardump=flows.har`

Fake a response with a local JSON file, using mitmproxy's own option:

```bash
--map-local '|api-staging.mycompany.com/api/v1/profile|./profile.json'
```

Add a request header:

```bash
--modify-headers '/~d api-staging.mycompany.com/X-Debug/1'
```

Add these to the mitmproxy command above. More in
[`PLAN.md` Appendix A](../PLAN.md#appendix-a--command-cheat-sheet).

To collect a device log without the launcher, use a second Terminal window and `cd` into
the session folder, so the file ends up next to `flows.mitm`:

Android (start the app first; its process ID changes when it restarts, so run the command
again then):

```bash
adb logcat --pid=$(adb shell pidof -s com.mycompany.myapp) | tee android.log
```

iPhone:

```bash
source ~/wiretrace/.venv/bin/activate
pymobiledevice3 syslog live -pn MyApp | tee ios.log
```

For an iOS crash, also pull the crash reports into the folder:

```bash
pymobiledevice3 crash pull ./crashes
```

### Mock a response

Wiretrace can answer a request with a JSON file from your Mac, so the app gets that data and
the real backend is not contacted. Put one file per request under `mocks/<preset>/`, in a
folder named after the request method, and then the request path:

```text
mocks/staging/GET/api/v1/profile.json    answers GET /api/v1/profile
mocks/staging/POST/api/v1/orders.json    answers POST /api/v1/orders
mocks/staging/GET/index.json             answers GET /
```

- Copy `mocks/example/` to `mocks/staging/` to start from a sample.
- The answer is always status `200` with the file's content as JSON. A query string
  (`?page=2`) is ignored. Use a fault (next section) for error statuses.
- Edit, add, or delete a file while Wiretrace runs: the next request uses the change. You do
  not restart anything.
- No file for a request means the request goes to the backend as usual.
- A mocked flow is marked 🚧 in mitmweb, and its comment names the file.
- The folder comes from the preset's `mocks_dir`; the default is `mocks/<preset name>`.
  Wiretrace prints at start where it reads mocks from and how many files it found.

### Make requests fail or slow

To see how the app handles a failing or slow backend, start with mitmweb (the default, not
`--no-ui`; faults are set in mitmweb's **Options** panel, which `--no-ui` does not have).
Open **Options** and search for `qa_fault`:

| Option | What it does |
|---|---|
| `qa_fault_filter` | Which requests to affect. Empty means none. |
| `qa_fault_status` | Answer with this status (100 to 599) instead of contacting the backend. `0` is off. |
| `qa_fault_delay_ms` | Wait this many milliseconds before the request continues. |
| `qa_fault_drop` | Close the connection without any answer. |

For example, to make every call to the orders endpoint fail with a server error, set
`qa_fault_filter` to `~u /api/v1/orders` and `qa_fault_status` to `500`. The app gets
status `500` with the body `{"error": "injected by Wiretrace"}`, and the flow is marked 💥.
To make the same calls slow instead, leave `qa_fault_status` at `0` and set
`qa_fault_delay_ms` to `3000`.

- `qa_fault_filter` uses the same expressions as mitmweb's search box: `~u /orders`
  (URL contains), `~m POST` (method), and `&` to combine them, for example
  `~m POST & ~u /orders`. Use `~all` for every request.
- The filter looks at the request only, because it is checked when the request arrives.
  Filters about the response, such as `~c 500`, never match.
- Only the preset's API hosts are affected. Other traffic is never delayed or failed.
- Changes apply to requests that arrive after you press Enter; a request already waiting
  keeps the settings it started with. To stop, clear `qa_fault_filter`.
- If you type an invalid filter, a status outside 100 to 599, or a negative delay, mitmweb
  shows a message and keeps the previous value.
- A delay can be combined with a status, a drop, or a mock: the wait comes first.
- Ctrl+C while requests are waiting still stops Wiretrace within a few seconds.

When the request or the answer has an `X-Request-ID` header, mitmweb shows it as the flow's
comment (`request-id: …`), and it is saved in `flows.mitm`. A preset can use another header
name with `request_id_header`.

### Logs from the app (for the mobile team)

A QA build can send its own log lines to Wiretrace, so they land in the session folder next
to the traffic. This is requirement R6 in [`PLAN.md`](../PLAN.md#7-requirements-for-the-mobile-development-team).
It works only while `./wiretrace start` is running, and the lines stay on the QA engineer's Mac.

Send a `POST` to `https://qa-logs.internal/log` with `Content-Type: application/json`. The
body is one JSON object, or an array of up to 1,000 objects:

```json
[{"message": "Order list loaded", "level": "I", "tag": "Orders", "ts": "2026-10-14T09:30:12.481+07:00", "request_id": "6f1c…"}]
```

| Field | Required | Limit |
|---|---|---|
| `message` | yes | a string |
| `level` | no | a string, up to 64 characters (for example `V`, `D`, `I`, `W`, `E`) |
| `tag` | no | a string, up to 64 characters |
| `ts` | no | a string, up to 64 characters. Without it, Wiretrace uses the time it received the line. |
| `request_id` | no | a string, up to 128 characters, for example the `X-Request-ID` of the request |

Other keys are ignored. Each object becomes one line in `app.log.jsonl`, together with the
time Wiretrace received it.

| Wiretrace answers | When |
|---|---|
| `204` | The body is valid. The lines are stored. |
| `400` | The body is not JSON, has the wrong shape, a missing `message`, a field of the wrong type or too long, or more than 1,000 objects. Nothing from that request is stored. |
| `413` | The body is larger than 1 MiB. |
| `404` / `405` | Another path, or another method than `POST` on `/log`. |

Rules for the app:

- Send it fire-and-forget and ignore every failure. When Wiretrace is not running, the name
  `qa-logs.internal` does not exist, and the request just fails. Nothing is ever sent to the
  internet or to the backend.
- The request goes through the same proxy and trusts the same certificate as the API calls
  (R1), in WireGuard mode and in Wi-Fi proxy mode. In WireGuard mode, the phone's Private DNS
  must be off (Part 3, Step 2).
- mitmweb shows these requests, so you can see whether the app is sending, but they are not
  saved in `flows.mitm` or `flows.har`.

---

## Part 4 — After testing

- Turn the WireGuard tunnel off when you are not testing.
- When a device leaves testing: delete the tunnel, and remove the **mitmproxy** profile /
  certificate (iPhone: VPN & Device Management; Android: Security → Trusted credentials → User).
- Delete old session folders in `~/wiretrace/sessions/`; they contain tokens and log lines.
- Never copy or share `~/.mitmproxy/mitmproxy-ca.pem`. It is the private key that lets
  your Mac decrypt traffic from every device that trusts it.

---

## Part 5 — Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| No requests appear at all | Tunnel off, or the phone cannot reach the Mac. Check WireGuard shows a recent handshake. Corporate or guest Wi-Fi often blocks device-to-device traffic: try a QA Wi-Fi or the Mac's hotspot. Check the firewall line in `./wiretrace doctor`. |
| `mitm.it` says traffic is not going through mitmproxy | The tunnel is off or not connected, or Wiretrace was started with `./wiretrace start`, which does not serve `mitm.it` through the tunnel. Use the plain `mitmweb` command from Part 2, Step 1. |
| App shows "network error" or HTTPS requests fail, other apps work | The certificate is not trusted (iPhone: full trust step), the app pins certificates, or the Android build does not trust user CAs. Ask for a QA build (R1, R2). |
| Requests show up but are not decrypted | The host is not in the preset's `api_hosts` (or, without the launcher, in `--allow-hosts`). Check the spelling. |
| Some app's traffic is missing | That app ignores the phone's proxy settings: WireGuard mode normally catches it; if not, ask the mobile team (R7). |
| `mitmweb: command not found` | Run `cd ~/wiretrace && source .venv/bin/activate` in this window. |
| `adb: command not found` | Open a new Terminal window, or run setup without `--skip-android`. |
| `Device logs: off (add app.android_package to the preset)`, or `app.ios_process` | Add the key to the preset's `app:` section (Part 3, Step 2), then start again. |
| `Device logs: off (adb not found)`, `pymobiledevice3`, or `xcrun` | The tool is missing. For `adb` or `pymobiledevice3`, run `scripts/setup-mac.sh`. For `xcrun`, install Xcode's command line tools. |
| `Device logs: off (--target device has no device log)` | Start with `--target android`, `ios`, `android-emu` or `ios-sim`. |
| `Device logs: waiting for a device` | No phone is connected, or it is not ready. Connect it by USB; on Android accept **Allow USB debugging**; on iPhone tap **Trust**. For the Simulator, boot one. Check `./wiretrace doctor`. |
| `Device logs: more than one device connected; connect only one` | Disconnect the other phone or quit the other emulator or Simulator. Choosing a device is not supported yet. |
| `Device logs: waiting for the app to start` (Android) | Open the app. The log follows it from then on. |
| `Device logs: adb failed (exit code …); retrying in 2 s` (or `pymobiledevice3`, `xcrun`) | The tool stopped or could not run. Wiretrace retries by itself. If it keeps repeating, run `./wiretrace doctor`. |
| `Device logs: collector stopped (exit code …); capture continues` | The log collector ended. Traffic capture is not affected. Stop and start Wiretrace to get the device log back. |
| `device.log.jsonl` is empty, or missing | The app wrote nothing while Wiretrace ran, or the process name or package in the preset is wrong. A file is created with the first line only. |
| iOS logs show `<private>` | The app logs with `print()` or private values. Ask the mobile team (R4). |
| `app.log.jsonl` is missing | The app sent nothing. Check in mitmweb whether requests to `qa-logs.internal` appear, and with which answer (`400`: the body is wrong). Check that Private DNS is off (WireGuard mode). The QA build must implement R6. |
| `Port … in use by another program` when starting | Another Wiretrace or mitmproxy is still running, often the `mitmweb` from Part 2. Quit it (Ctrl+C in its window). |
| `Unknown preset '…'. Available presets: …` | Check the spelling; the name is the file name in `presets/` without `.yaml`. To add one, see Part 1, Step 6. |
| `presets/<name>.yaml: …` | The preset file has a mistake; the message says which field. Fix the file and start again. |
| `Nothing was captured; the session folder was removed.` | No request and no log line reached Wiretrace before you stopped. See *No requests appear at all*. |
| `No traffic was captured; flows.har was not written.` | The session has log lines but no requests, so there is no HAR file. The session folder is kept. See *No requests appear at all*. |
| `flows.har was not written (…)` | `flows.mitm` is kept. Make the HAR yourself: `cd` into the session folder, `source ~/wiretrace/.venv/bin/activate`, then `mitmdump -n -r flows.mitm --set hardump=flows.har`. |
| Endpoint security quarantines mitmproxy | Ask IT to allowlist Wiretrace ([`install-without-admin.md`](install-without-admin.md#company-managed-macs-what-to-ask-it-for)). |

---

## Updating and removing

**Update to a new version:** move the old folder aside, extract the new one, run setup.
Your device setup (CA and tunnel in `~/.mitmproxy`) stays valid.

```bash
mv ~/wiretrace ~/wiretrace-old
tar -xzf wiretrace-<version>-macos.tar.gz -C ~
cd ~/wiretrace && scripts/setup-mac.sh
```

Copy the presets you created from `~/wiretrace-old/presets/` to `~/wiretrace/presets/`, and any
sessions you want to keep from `~/wiretrace-old/sessions/`. Then delete `~/wiretrace-old`.

**Remove Wiretrace completely:**

```bash
rm -rf ~/wiretrace ~/tools/platform-tools ~/.local/share/uv
rm -f ~/.local/bin/uv ~/.local/bin/uvx
```

Then delete the two `export PATH=…` lines Wiretrace added to `~/.zshrc`. Deleting
`~/.mitmproxy` as well removes the CA and the tunnel keys; every device then needs a new
certificate and a new tunnel.
