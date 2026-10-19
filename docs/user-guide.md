# Wiretrace — Installation and usage guide

For QA engineers. Covers Wiretrace **0.9.1**, on Intel and Apple silicon Macs.

What 0.9.1 gives you: a one-command install (`./install`) that needs no admin rights, a setup
check (`./wiretrace doctor`), project presets, and `./wiretrace start --preset …`, which
captures only your project's API traffic and saves each session in its own folder with a
HAR file (passwords, tokens and cookies masked), mocks, injected faults, and the app's logs
next to the traffic (Part 3). `./wiretrace report` turns a session into a zip for the bug
ticket. The Wiretrace window (`--ui wiretrace`) is a preview, with a setup wizard, rules that
make requests fail or slow, a log timeline with the device's status, earlier sessions, saved
filters, search in headers and bodies, replay and compare. New in 0.9.0: the **Wiretrace
app** that setup puts in `~/Applications`, a `default` preset to start with, and editing or
creating presets from the window. New in 0.9.1: one session accepts the phone's Wi-Fi proxy
(now on port 8888) and the WireGuard tunnel at the same time; the setup wizard shows the Wi-Fi
proxy first.

Using 0.8.0 or 0.7.2? Those versions have no `./install` and no Wiretrace app; follow the
guide that came with them: [0.8.0](https://github.com/chienng/wiretrace/blob/v0.8.0/docs/user-guide.md),
[0.7.2](https://github.com/chienng/wiretrace/blob/v0.7.2/docs/user-guide.md), or
`~/wiretrace/docs/user-guide.md` in your download.

New to Wiretrace? Do Part 1 once per Mac, Part 2 once per phone, then Part 3 every time
you test. Run each command in **Terminal** (Applications → Utilities → Terminal).

---

## Part 1 — Install (once per Mac)

### Before you start

- A Mac with macOS. A **standard (non-admin) account is fine**; you will not be asked
  for a password.
- Internet access to `github.com`, `pypi.org`, and `dl.google.com` during the install.
  If the company network blocks one of them, ask IT.
- The release file and its checksum, from the Releases page, saved in Downloads: either
  [wiretrace-0.9.1-macos.tar.gz](https://github.com/chienng/wiretrace/releases/download/v0.9.1/wiretrace-0.9.1-macos.tar.gz)
  and [its `.sha256`](https://github.com/chienng/wiretrace/releases/download/v0.9.1/wiretrace-0.9.1-macos.tar.gz.sha256)
  (the faster one), or
  [wiretrace-0.9.1-macos.dmg](https://github.com/chienng/wiretrace/releases/download/v0.9.1/wiretrace-0.9.1-macos.dmg)
  and [its `.sha256`](https://github.com/chienng/wiretrace/releases/download/v0.9.1/wiretrace-0.9.1-macos.dmg.sha256).
  Both contain the same files and work on Intel and Apple silicon Macs.

### Step 1 — Check the download

Open **Terminal**, go to the folder with both files (usually Downloads), and run the line
for the file you have:

```bash
cd ~/Downloads
shasum -a 256 -c wiretrace-0.9.1-macos.dmg.sha256
shasum -a 256 -c wiretrace-0.9.1-macos.tar.gz.sha256
```

It must print `…: OK`. If it prints `FAILED`, download the file again and do not continue.

### Step 2 — Put the wiretrace folder in your home folder

**From the `.tar.gz`:** double-click it in Downloads; a `wiretrace` folder appears next to
it. Drag that folder onto your home folder (in Finder: **Go → Home**). Moving it is
instant. Do not run Wiretrace from Downloads: the app then needs macOS's permission to
access that folder, and cleaning up Downloads would delete it. If Downloads already had a
`wiretrace` folder, the new one is called `wiretrace 2`; drag that one and rename it
`wiretrace`. In Terminal, the same in one step:

```bash
tar -xzf ~/Downloads/wiretrace-0.9.1-macos.tar.gz -C ~
```

**From the `.dmg`:** double-click it, drag the `wiretrace` folder onto your home folder (in
Finder: **Go → Home**), then eject **Wiretrace 0.9.1**. Wiretrace cannot run from the disk
image itself, because the image is read-only.

Either way you now have `~/wiretrace`.

### Step 3 — Run the setup

In Finder, open the `wiretrace` folder in your home folder and double-click **install**. A
Terminal window opens and runs the setup; when it ends, the window shows the setup check and
can be closed. To pass an option such as `--skip-android`, or if macOS says it cannot verify
**install**, run it in Terminal instead:

```bash
cd ~/wiretrace
./install
```

If you only test iOS, use `./install --skip-android`. (`./install` runs
`scripts/setup-mac.sh`; either command works.) When the setup check at the end passes, the
setup opens the Wiretrace app, so you can start testing at once; `--no-open` skips that.

The first run takes a few minutes. It installs, all inside your home folder:

| What | Where |
|---|---|
| `uv` 0.13.0 (Python installer) | `~/.local/bin` |
| Python 3.12 | `~/.local/share/uv` |
| mitmproxy, pymobiledevice3 and the other packages | `~/wiretrace/.venv` |
| Android platform-tools r37.0.1 (`adb`) | `~/tools/platform-tools` |
| Two `PATH` lines | `~/.zshrc` |
| The Wiretrace app | `~/Applications/Wiretrace.app` |

Every download is checked against a SHA-256 checksum stored in the script; a file that
does not match is never installed. Running the script again is safe and quick.

Do **not** run it with `sudo`. It refuses, because the files in your home folder would
end up owned by root.

### The Wiretrace app

The setup also builds **Wiretrace** in `~/Applications`, on your Mac, so macOS opens it
without asking. You can start every session from it instead of Terminal:

1. The setup opens **Wiretrace** the first time. Later, open it (the blue **W** icon) from
   Launchpad or Spotlight. The app stays open, with its icon in the Dock, while the session
   records, and closes by itself within 20 seconds after it stops. To keep the icon in the
   Dock, right-click it → **Options** → **Keep in Dock** (or drag **Wiretrace** from
   **Go → Home → Applications** in Finder onto the Dock).
2. The app asks nothing. It starts the project (a preset) and the device you used last; the
   first time, the project `default` on an iPhone. If that project was deleted, it starts
   `default`.
3. After a few seconds the Wiretrace window opens in your browser and the **Wiretrace** menu
   (the W icon at the top right of the screen) appears. The app shows no message when the
   start works; only when the window takes longer than usual does it say it is still
   starting.
4. To use another project or device, switch from the window's title bar (*Switching the
   preset* and *Switching the device* under *The Wiretrace window (preview)*). The app
   remembers the switch for next time.

A blue strip under the window's title bar says the same, until you click **Got it**; that
browser then stops showing it. Quitting the app (⌘Q, or **Quit** in its Dock menu) does not
stop the session. To stop it and save `flows.har`, use **Stop session** in the **Wiretrace**
menu (the W icon at the top right; pointing at *Recording* in the window reminds you): a
session started from the app has no Terminal window. If Wiretrace is already recording,
opening the app or clicking its Dock icon says so and starts nothing.
Every device in the app accepts both ways to connect, the Wi-Fi proxy and the WireGuard tunnel
(Part 2, Step 2).

The app opens the folder the setup ran in. If you move that folder, the app says so: run
`scripts/setup-mac.sh` again from the new place.

### Step 4 — Only to type `adb` or `uv`: open a new Terminal window

Wiretrace works right after the setup, from the app or with `./wiretrace` in the same
window. The `PATH` lines only matter when you type `adb` or `uv` yourself, and they apply
only to new windows (or run `exec zsh`).

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
| `FAIL macOS firewall: blocks all incoming connections` | Ask IT for an allow rule for UDP 51820 and TCP 8888. |
| `WARN macOS firewall: on; macOS will ask …` | Normal. Click **Allow** when macOS asks the first time you start mitmproxy. |
| `WARN adb: not found` | Only matters for Android. Run the setup without `--skip-android`. |
| `WARN Android devices: … unauthorized` | Unlock the phone and accept **Allow USB debugging**. |
| `INFO CA certificate: not created yet` | Normal before the first start. |
| `WARN CA private key: readable by other users` | Run the `chmod 600 …` command shown. |

### Step 6 — Optional: create a preset for your project

A preset tells Wiretrace which API hosts to decrypt: only the hosts under its `api_hosts:`
are decrypted. It is one file per project and environment in `~/wiretrace/presets/`.
Wiretrace comes with the `default` preset (`presets/default.yaml`), so you can skip this step
and start with `--preset default`. With `--ui wiretrace` you can also do this in the window:
**Preset → Edit presets…** to put your app's hosts into `default`, or **New preset…** (see
*Editing and creating presets* under the Wiretrace window). In Terminal, start from the
example:

```bash
cd ~/wiretrace
cp presets/example.yaml presets/staging.yaml
open -e presets/staging.yaml
```

The file opens in TextEdit. Change the lines marked `CHANGE`, then save with **Cmd+S**:

1. `name: example` → `name: staging`. It must be the file name without `.yaml`.
2. Under `api_hosts:`, replace the two example hosts with your app's API hosts, one per
   line, each starting with `  - `. Host names only, such as `api-staging.mycompany.com`:
   no `https://`, port, or path. Each host's subdomains are included. If you do not know
   the hosts, ask the app's developers which ones the test build calls.
3. Under `app:`, set `android_package` (Android) and/or `ios_process` (iOS). They let
   Wiretrace collect the app's log. To find an Android package name, connect the phone and
   run `adb shell pm list packages | grep -i <part of the app name>`; use the text after
   `package:`.

Leave the other lines as they are; the comments in the file explain them. Keep the spaces
at the start of each line: YAML uses them.

If the file has a mistake, `./wiretrace start` names the file and the problem. The most
common one, *name is 'example', but must equal the file name*, means the file was not
changed or not saved.

Wiretrace always hides passwords, tokens and cookies in the files you attach to a ticket
(see Part 3, Step 5). If your app sends other secrets, name them in an optional `redact:`
section of the preset. The names you add are hidden in addition to the built-in ones; you
cannot switch the built-in ones off:

```yaml
redact:
  headers: [X-Api-Key]          # extra header names
  json_fields: [otp, login_token]   # extra field names in JSON bodies, forms and URLs
```

A header name has letters, digits and `-` only. A field name starts with a letter or digit
and may also contain `_`, `.` and `-`. Capital letters, `_` and `-` do not matter, so
`login_token` also hides `loginToken` and `Login-Token`. A name is also hidden when it
contains `password`, `passwd`, `passphrase`, `secret`, `token`, `apikey`, `privatekey`,
`recoverykey` or `credential`, so `newPassword`, `auth_token` and `X-Custom-Token` are
hidden without being listed. `otp`, `pin`, `code_verifier` and `session_id` are hidden
too. `code` is not: error responses use it for an error code. If the app sends a one-time
code under `code`, add `code` to `json_fields`. If `redact:` has a key other than
`headers` or `json_fields`, or a name that is not valid, `./wiretrace start` stops and names it.

---

## Part 2 — Prepare a test device (once per device)

You need a **QA build** of the app: certificate pinning off, and on Android, user CAs
trusted (requirements R1 and R2 in [`PLAN.md`](../PLAN.md#7-requirements-for-the-mobile-development-team)).
With a store or release build, HTTPS traffic cannot be decrypted.

### Step 1 — Start Wiretrace

Copy the block for your phone.

iPhone:

```bash
cd ~/wiretrace
./wiretrace start --preset default --target ios --ui wiretrace
```

Android phone:

```bash
cd ~/wiretrace
./wiretrace start --preset default --target android --ui wiretrace
```

Wiretrace listens for the phone's Wi-Fi proxy (TCP 8888) and for the WireGuard tunnel
(UDP 51820) at the same time, so the phone can connect either way without a restart.
`--mode proxy` or `--mode wireguard` starts one of the two only.

With a preset you created, change `default` to its name. For the Android emulator use
`--target android-emu`; for the iOS Simulator use `--target ios-sim` (see
[Part 3, Step 1](#step-1--start-capturing)). The Wiretrace window opens in your browser: click **Setup**
in its title bar. The setup wizard walks you through Steps 2 to 4 below for the device you pick
(*Choose device*, *Connect to this Mac*, *Trust Wiretrace*, *Check the app*, and the optional
*Device logs*), says what you need before you start, and ticks each step as soon as Wiretrace
sees it work. When a step does not turn green, it says what to try. Without `--ui wiretrace`
you get mitmweb instead, which shows the same QR code. The first time, macOS may ask whether to allow incoming
connections: click **Allow**.

### Step 2 — Connect the phone

The wizard's *Connect to this Mac* step has a switch, **Wi-Fi proxy** | **WireGuard**. It
starts on Wi-Fi proxy and remembers your last choice in this browser. It only changes the
steps shown: the session keeps recording, and Wiretrace accepts both at any time. The iOS
Simulator always uses the proxy and has no switch.

**Wi-Fi proxy** (try this first):

1. Connect the phone to the same Wi-Fi network as the Mac.
2. Set the network's proxy to **Manual**, server `<Mac IP>`, port **8888**. The wizard shows
   the address with a copy button, and where the setting is on your phone.
3. *Waiting for the device…* turns to *Connected* as soon as the phone sends a request.

The Wi-Fi proxy accepts this Mac and the **first other device** that connects, until
Wiretrace stops. Anyone else on the same Wi-Fi network who connects first takes that place:
your phone then gets no page, and the Terminal (or `app-start.log`) prints one line telling
you to restart Wiretrace or to pass `--client <its IP address>`. Apps that ignore the proxy
setting (Flutter, some React Native libraries) are not captured this way: use WireGuard.

**WireGuard** (for apps that ignore the proxy):

1. Install the **WireGuard** app (App Store / Google Play).
2. In WireGuard, add a tunnel by scanning the QR code: step *Connect to this Mac* of the setup
   wizard, or the WireGuard panel in mitmweb.
3. Turn the tunnel on. In WireGuard, tap the tunnel: *Endpoint* is your Mac's address with
   port 51820, and *Latest handshake* shows a time a few seconds ago. In the wizard,
   *Waiting for the device…* turns to *Connected* as soon as the phone sends anything through
   the tunnel. If it still waits after 30 seconds, the Wi-Fi network may block devices from
   reaching each other (guest networks often do): try another network.

The tunnel keys are stored in `~/.mitmproxy/wireguard.conf` and reused on every start, so
you only scan the QR code once per device. Use one way at a time: remove the Wi-Fi proxy
before you turn the tunnel on.

**When you are done testing**, set the phone's Wi-Fi proxy back to **Off** (or turn the
tunnel off). Without Wiretrace running, a phone still set to the proxy has no internet on
that network.

No browser? `mitmdump --mode wireguard` prints the same configuration as text
(`[Interface] … [Peer] … Endpoint = <Mac IP>:51820`); enter it in WireGuard with
**Create from scratch**.

### Step 3 — Install and trust the Wiretrace certificate

With the Wi-Fi proxy set (or the tunnel on), open `http://mitm.it` on the phone. This page is
served by Wiretrace on your Mac, not by the internet, and it is not saved in the session. If it
says *"traffic is not going through mitmproxy"*, or does not load, the phone is not connected:
check the proxy address and port, or the tunnel's *Latest handshake* (Step 2). For the iOS Simulator and the Android emulator, the wizard's
*Trust Wiretrace* step shows the one command to run on your Mac instead, with a copy button.

For a phone, the wizard's *Trust Wiretrace* step ticks *Page opened on the phone* when
`mitm.it` loads, *Certificate downloaded* when you tap the download, and *Trusted* when the
first request to an API host arrives. If the phone is connected but `mitm.it` has not loaded
after a minute, type `http://mitm.it` exactly (not https), in Safari on an iPhone.

**iPhone**

1. Open `mitm.it` in **Safari** (other browsers cannot install a profile), tap
   **Get mitmproxy-ca-cert.pem** under iOS, and allow the download. The profile is only
   downloaded at this point.
2. Settings → General → VPN & Device Management → **mitmproxy** under *Downloaded Profile* →
   **Install**, and enter the passcode. The trust switch in step 3 appears only after this.
3. Settings → General → About → Certificate Trust Settings → turn on full trust for
   **mitmproxy**. Without this step, HTTPS still fails.

**Android**

1. On `mitm.it`, in Chrome, tap **Get mitmproxy-ca-cert.cer** under Android. Tapping the
   downloaded file does not install it; use Settings (step 2).
2. Open the certificate menu. The names depend on the phone maker:
   - Most phones (Pixel and others): Settings → Security → Encryption & credentials →
     Install a certificate → **CA certificate**.
   - Samsung: Settings → **Security and privacy** → **More security settings** → **Install from
     device storage** → **CA certificate**. On older Samsung phones, the first two are
     **Biometrics and security** → **Other security settings**.
   - Not there? Search Settings for **CA certificate**.
3. Tap **Install anyway** at the warning, then pick `mitmproxy-ca-cert.cer` in **Downloads**.
   If the phone has no screen lock, it asks you to set a PIN, pattern or password first.
4. Check: in the same menu, **Trusted credentials** (Samsung: **View security certificates**) →
   **User** lists **mitmproxy**.

**If `mitm.it` does not load**, install the certificate file directly. It is on your Mac at
`~/.mitmproxy/`:

- iPhone: AirDrop or email `~/.mitmproxy/mitmproxy-ca-cert.pem` to the phone, then do
  steps 2 and 3 above.
- Android (USB debugging on):

  ```bash
  adb push ~/.mitmproxy/mitmproxy-ca-cert.cer /sdcard/Download/
  ```

  then do steps 2 to 4 above.

### Step 4 — Check

Open the app on the phone. Its requests to the preset's hosts appear in the Traffic list (or in
mitmweb), and the wizard's *Check the app* step turns green. If the phone refuses Wiretrace's
certificate for an API host, that step says the certificate is not trusted yet and points back
to *Trust Wiretrace* (Step 3); on Android it adds that a store build never trusts it. If nothing
arrives after 30 seconds, it lists what to check: a QA build for the preset's environment, the
preset's API hosts, a screen of the app that loads data, and the tunnel still on. If HTTPS
requests show errors, see [Troubleshooting](#part-5--troubleshooting).

The wizard's last button, **Done — open Traffic**, sums up what is set up. Next time, switch the
WireGuard tunnel on (or set the Wi-Fi proxy), then start Wiretrace. You can keep this session
running and go on with Part 3, or press **Ctrl+C** and start again later.

---

## Part 3 — Test with Wiretrace (every session)

The examples use a preset named `staging` (Part 1, Step 6). With the preset that comes with
Wiretrace, use `--preset default`.

### Step 1 — Start capturing

```bash
cd ~/wiretrace
./wiretrace start --preset staging --target android
```

mitmweb opens in a browser tab; Wiretrace accepts the Wi-Fi proxy and the WireGuard tunnel. Wiretrace prints where the session is
saved, for example `sessions/2026-10-13_143005_staging_android/`.

- Only the preset's `api_hosts` and their subdomains are decrypted. Other apps and
  third-party traffic pass through untouched.
- Every request and response is saved to `flows.mitm` in the session folder as it
  happens, so nothing is lost if you close the window. The session folder and `sessions/`
  are readable only by your macOS user (`drwx------`). `meta.json`, `flows.mitm`,
  `flows.har`, the log files, a bug-report zip and the screenshots taken from *Report bug*
  (in `screenshots/`) are `-rw-------`. Another account on
  this Mac cannot read them. A `sessions/` folder left by an older Wiretrace is tightened
  the next time you start.
- `--target` is `android`, `ios`, `android-emu`, `ios-sim`, or `device` (the default). It
  names the session folder, picks the setup reminders printed at start, and picks which
  device log is collected (Step 2).
- `--no-ui` runs in the Terminal only (mitmdump) instead of opening mitmweb.
- `--ui wiretrace` opens Wiretrace's own window instead of mitmweb (a preview; see *Wiretrace
  window (preview)* below). The Rules view is only in that window. It cannot be combined with
  `--no-ui`. While that window runs, Wiretrace also puts an item in the menu bar (see *Menu bar*
  below). `--no-menu-bar` leaves the item out; the banner says `Menu bar: off (--no-menu-bar)`.
  With `--ui mitmweb` or `--no-ui` there is no menu bar, and `--no-menu-bar` changes nothing.
- `--mode` is `both` (the default), `proxy` or `wireguard`. `both` runs a Wi-Fi proxy on
  TCP 8888 and the WireGuard tunnel on UDP 51820 in one session: set the phone's Wi-Fi proxy to
  `<Mac IP>:8888`, or turn its tunnel on, and both are saved in the same session folder and
  HAR. `--mode proxy` runs the Wi-Fi proxy only, `--mode wireguard` the tunnel only; the setup
  wizard then shows only that way, and the command to restart in the other mode where you need
  it. Apps that ignore the system proxy (Flutter, some React Native libraries) are not
  captured through the proxy; use WireGuard for them.
- **Who may use the Wi-Fi proxy** (`both` and `proxy`): the Mac itself is always accepted (the
  iOS Simulator and the Android emulator connect that way). The first other device that
  connects is the only other device accepted until you stop Wiretrace. A later device gets no
  page, and the Terminal prints one line telling you to restart or to pass `--client`. To allow
  a known phone instead of pinning the first one, repeat `--client` with its IP address:
  `./wiretrace start --preset staging --ui wiretrace --client 192.168.1.20`. A phone cannot
  open the Mac's own addresses (for example `http://127.0.0.1:8081/`) through this proxy.
  A phone on the WireGuard tunnel is never pinned or refused: the tunnel's key is its
  permission.
- **iOS Simulator:** it uses the Mac's own network, so WireGuard does not apply. Start with
  `--target ios-sim --ui wiretrace`, set the Mac's HTTP and HTTPS proxy to `127.0.0.1:8888`
  (this usually needs admin rights; see
  [`install-without-admin.md`](install-without-admin.md#ios-simulator-without-admin)), and
  install the certificate in the booted Simulator once:
  `xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem`.
  Ignore the "set the Wi-Fi proxy" reminder Wiretrace prints; it is meant for phones.
- **A browser or Burp Suite on this Mac:** start with `--ui wiretrace`, point the
  browser's proxy (or Burp's upstream proxy) at `127.0.0.1:8888`, and make it trust
  `~/.mitmproxy/mitmproxy-ca-cert.pem`. Only the preset's `api_hosts` are decrypted.
- The preset's `default_filter` is the starting filter: in mitmweb's search box, or what
  is printed with `--no-ui`. It never limits what is saved. Common filters:
  `~c 500` (status 500), `~m POST`, `~u /api/v1/orders`, `~bs "SOME_TEXT"` (response body).
  More in [`PLAN.md` Appendix B](../PLAN.md#appendix-b--mitmweb-filter-expressions-for-qa).
- If a port is in use, Wiretrace says which one and does not start. Usually another
  Wiretrace or mitmproxy window is still open: quit it.

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
proxy you do not need this.

### Step 3 — Reproduce the problem

Use the app as usual. Note the time when the problem happens; it makes it easier to find
the request and the log lines.

### Step 4 — Stop

Press **Ctrl+C** once in the Wiretrace window. It stops mitmproxy and the device log, writes
`flows.har` (with passwords, tokens and cookies hidden) next to `flows.mitm`, and prints
the session folder and the command for the bug report. If it says *still
stopping*, press Ctrl+C again to force it. If nothing was captured (no requests and no log
lines), the session folder is removed. If only log lines were captured, the folder is kept
and Wiretrace says that `flows.har` was not written.

`meta.json` in the session folder says which device log ran (`device_logs`) and how many
lines each log file has (`device_log_lines`, `app_log_lines`).

For an iOS crash, also pull the crash reports into the session folder (the launcher does
not do this for you yet; see *Without the launcher*).

### Step 5 — Export for the bug ticket

Run this in the Wiretrace folder:

```bash
cd ~/wiretrace
./wiretrace report
```

It uses the most recent session. For an older one, add its folder name, for example
`./wiretrace report 2026-10-13_143005_staging_android` (the launcher prints this command
when it saves a session). You can run it while a session is still running, or after
a crash.

The command writes `<session folder name>-report.zip` inside the session folder and prints
its path. **Attach that zip to the bug ticket.** It holds one folder with:

- `summary.md`: the session (preset, target, start and end, Wiretrace version), counts of
  requests, failed requests, requests Wiretrace mocked or made fail, and log lines, the
  names that were hidden, and a table of the failed requests (status 400 or higher, or no
  answer). The table shows time, method, host, path, status, duration, request ID, and a
  note when Wiretrace itself caused the failure. A line such as `Wiretrace fault: status 500`
  means *you* injected that error with `qa_fault_*`; it is not a backend bug. The table
  has at most 100 rows.
- `flows.har`: all requests, built again from `flows.mitm`. It opens in Chrome
  DevTools, Charles, Proxyman, …
- `device.log.jsonl` and `app.log.jsonl`, when they have lines; the time in each line
  (`ts`) helps match it to the request.
- `meta.json`: how the session ran.

The zip never contains `flows.mitm`. If `flows.mitm` was cut off because the session was
killed, the report uses the requests that could be read and says so.

To look at the session again later: `mitmweb -r flows.mitm`. In mitmweb you can also
copy a single request as cURL.

**What is hidden (replaced by `***`).** In `flows.har` and in the zip's `flows.har`:

- the headers `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`,
  `X-Auth-Token` and `X-Amz-Security-Token`, any other header whose name contains one of
  the words below, and every cookie value;
- the fields `password`, `access_token`, `refresh_token`, `id_token`, `client_secret`,
  `token`, `api_key`, `secret`, `otp`, `pin`, `code_verifier` and `session_id`, any name
  that contains `password`, `passwd`, `passphrase`, `secret`, `token`, `apikey`,
  `privatekey`, `recoverykey` or `credential` (so `newPassword` and `sessionToken` are
  hidden), and any names you added with `redact:`, wherever they appear in JSON request
  and response bodies (at any depth), in forms, in URLs (query and `#` part), in the
  `Location`, `Referer` and `Content-Location` headers, and in WebSocket text messages;
- Capital letters, `_` and `-` do not matter: `accessToken` and `access-token` are hidden too.
  `code` is not hidden, because error bodies use it for an error code. Add it under
  `redact.json_fields` when the app sends a secret under that name.
- A `multipart/form-data` request body is replaced by a line that lists the part names only.
- A body that looks like JSON but is cut off or broken is searched like a log line (below).

In the log files of the zip, every text in each line is searched for the same header
names, for `Bearer <token>`, for a JSON Web Token (`eyJ….….…`), for a Matrix token
(`syt_`, `syr_`, `mat_`, `mar_`, `mct_` or `mcr_` plus the token), and for `"field": "value"`,
`field=value` and `field: value`. JSON keys in a log line follow the same field rules,
including a name that only contains one of those words.

**What is not hidden. Read this before you share anything.**

- Files in the session folder itself: `flows.mitm` and the log files there keep every
  value. Only the zip's log files are changed.
- The **File menu and export in mitmweb** save the original, unmasked data. For a ticket,
  use `./wiretrace report`, not mitmweb's export.
- A body that is not JSON, a URL-encoded form or multipart (for example XML,
  GraphQL text, binary data) is left as it is, even if it holds a password. So are
  parts of the URL path, and binary WebSocket messages. A body larger than 16 MiB after
  decompression is replaced by a short note; the original stays in `flows.mitm`.
- Logs are hidden by pattern only. A secret that does not look like one of the
  patterns above stays in the log. The command says this every time; open the zip's log files
  and check them before you share.
- A secret under a name nobody listed stays visible. Add the name to `redact:` in the preset.

Use test accounts only, and attach the zip only to internal tickets, never to public places
or chats.

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

The easiest way is a rule in the Wiretrace window (`--ui wiretrace`): open *Rules* in the
title bar, see *Rules* under *The Wiretrace window (preview)*. Rules are saved in
`rules/<preset>.json` and apply with every UI, including mitmweb and `--no-ui`; you can also
edit that file by hand, and Wiretrace picks up the change within a second. Rules are checked
first, then the `qa_fault_*` options below, then mock files.

With mitmweb (the default) you can still use its **Options** panel instead. Open
**Options** and search for `qa_fault`:

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

### Wiretrace window (preview)

Wiretrace has its own window, which shows the traffic and the app's logs on one screen, and
where you edit rules (*Rules* in its title bar). It is a preview. mitmweb stays the default, so
nothing changes unless you ask for the new window: a plain `./wiretrace start` opens mitmweb.

To open it, start Wiretrace with `--ui wiretrace`:

```bash
cd ~/wiretrace
./wiretrace start --preset staging --target android --ui wiretrace
```

`--ui mitmweb` does the same as leaving `--ui` out. You cannot use `--ui` together with
`--no-ui`. The window needs port 8081 to be free, like mitmweb does; Wiretrace says so and does
not start if it is not.

**The link and the token.** Wiretrace prints one line in the Terminal, for example
`Wiretrace UI: http://127.0.0.1:8081/?token=…`, and opens that link in your default browser.
The token in the link is new every time you start Wiretrace. It lives only in that Terminal line,
in your browser's cookie and in the running Wiretrace; it is never saved to a file. Open the
link once and the browser remembers it, so you can reload the page. A page opened without the
token is refused: this includes a private window, another browser, and another computer. The
window only answers on this Mac and cannot be reached from the network. If you closed the tab,
copy the link from the Terminal again. Do not paste the link into a chat or a ticket: the
window shows requests with their tokens, and the phone's WireGuard configuration.

**Menu bar.** With `--ui wiretrace`, the Wiretrace icon (a W in a square) appears in the macOS
menu bar (no Dock icon). It is dimmed while the session starts, and when Wiretrace stops
answering (a **?** then shows next to it). After a request fails a number N shows next to it,
the same count as the window's *Errors* filter. The menu shows the preset, the device (target, mode, and the
phone's model when logs are streaming), how long the session has been running, and the request,
error and rules-on counts. **Open Wiretrace** (⌘O) opens the window again, including after you
quit the browser; each click opens a new tab. **Show last error** (⌘R) opens the window with
the latest failed request selected; it is greyed out when N is 0. **Stop session** is the same
as Ctrl+C in the Terminal: Wiretrace prints "Stopping…", writes `flows.har` and the item goes
away. **Quit** removes the item only; the Terminal prints
`Menu bar: closed; capture continues (Ctrl+C here to stop)` and capture goes on until you
press Ctrl+C. If the menu cannot start (PyObjC is missing, or there is no logged-in desktop,
such as an SSH session), the banner says `Menu bar: off (<reason>)` and capture runs as usual.
`./wiretrace doctor` prints `Menu bar: available` or tells you to run `scripts/setup-mac.sh`.

**Switching the preset.** Click *Preset: …* in the title bar to see every file in `presets/`;
the one in use is marked. Choose another and Wiretrace asks first: the dialog lists the hosts
that preset decrypts and says whether device logs will be on. Click *Save and switch*: this
session is saved as if you had pressed Ctrl+C (`flows.har`, then the session folder), and a new
session starts with the other preset, the same target and mode. The Terminal prints the new
preset and its hosts, and a new browser tab opens; the old tab says it is switching. The phone
stays connected: the WireGuard tunnel (or the Wi-Fi proxy) does not need to be set up again.
Each session has one preset, so the new one gets its own session folder, rules
(`rules/<preset>.json`) and mocks. The menu is off while a previous session is open. Ctrl+C,
or *Stop session* in the menu bar, still ends Wiretrace and never starts the chosen preset.

**Switching the device.** The label next to the preset, for example *iPhone · Proxy +
WireGuard*, is a menu of the devices: iPhone, Android phone, Android emulator, iOS Simulator
and Another device. Each row says whether device logs will be on with the preset in use (the
app name) or why not. Choose another device and Wiretrace asks first, with what to do on the
phones: disconnect the old one (Wi-Fi proxy off, or tunnel off) and connect the new one the
same way. Click *Save and switch*: this session is saved as for a preset switch, and a new
session starts for that device, with the same preset, mode and ports. It has its own session
folder and device log, and a new browser tab opens. The Wi-Fi proxy accepts the first phone
that connects to it (unless you started with `--client`), so remove the proxy from the old
phone first. With `--mode wireguard`, the iOS Simulator is off in the menu: it needs the Wi-Fi
proxy, so stop and start Wiretrace for it. The menu is off while a previous session is open.
The Setup wizard offers the same switch: when the card you pick is not the session's device,
*Use <device> for this session* opens the same dialog, and the new tab goes on with *Connect
to this Mac*.

**Editing and creating presets.** In the same menu, *Edit presets…* opens the *Presets* sheet
with the preset in use selected, and *New preset…* opens it on a blank form. The form has the
API hosts (one per line), the Android package, the iOS process, the request ID header, the
starting filter, and the extra header and field names to hide. Each value is checked the way
`./wiretrace start` checks the file; a refused value is marked and nothing is written.

- *Create preset* writes `presets/<name>.yaml`. This session keeps running; choose the new
  preset from the menu to switch to it.
- *Save* on another preset rewrites its file. This session keeps running.
- *Save and restart* on the preset in use asks first, then saves the file and switches to it
  as above: this session is saved, a new one starts with the new settings, and the phone stays
  connected.

The sheet writes the file in its own layout. Settings the form does not show, such as
`mocks_dir`, are kept; comments in the file are not. `example` is the template and opens
read-only: use *New preset*. If the file was changed in TextEdit while the sheet showed it,
the save is refused and the sheet loads the new file. The name of a preset cannot be changed.

**What each area does.**

- **Title bar.** It starts with the Wiretrace mark and name, with the version under the name
  (for example *v0.9.1*); the browser tab shows the same mark. *Traffic* and *Logs* switch
  between the two views; *Logs* shows the number of
  crashes. It shows how long the session has been recording. *Pause* freezes the list while
  you read it and counts the new requests; meanwhile the title bar shows *List paused*
  instead of the recording time. Wiretrace keeps recording; *Resume* lists what came in. *Clear* hides what is in the list now; everything is
  still saved to the session folder. It also shows the preset (a menu, see *Switching the
  preset* above), the device and mode (a menu, see *Switching the device*), and the
  device pill: the phone's model, OS version and connection (for example *Pixel 8 · Android 15
  · USB*), green while its logs stream in, or *Device logs off* with the reason when you point
  at it. Then come the buttons *Rules* (with the number of rules that are on), *Setup* and
  *Report bug*.
- **Sidebar.** *Current session* and *Previous sessions* (see *Earlier sessions* below). Quick
  filters with live counts: *All*, *Errors* (status 400 or higher, or no answer), *Slow* (over
  one second), *Mocked*, *Faulted* and *WebSocket*. The preset's hosts with their counts.
  *Saved filters*: type a search, click *+ Save current search* and give it a name; click the
  name to use it again, or *Rename* and *Delete* next to it. Saved filters belong to the
  preset and are kept by your browser, not in a file: another browser, a private window or
  clearing the browser's data starts with none.
- **Search box.** Plain text matches the method, the URL and the status. From three
  characters, it also looks in header names and values and in the request and response
  bodies, ignoring case; those matches appear a moment later. Text that starts with `~` or `!`
  is a mitmweb filter expression, such as `~u /orders` or `!~t image`, checked by Wiretrace; if
  it is not valid, the window shows the message. The preset's `default_filter` is typed in for
  you at the start. It never limits what is saved. The active filters (host, quick filter, the
  search or the preset's filter) show as chips above the list; click a chip to remove it.
- **Traffic list.** One row per request to the preset's hosts, as it happens: time, method,
  status (coloured by class, errors in red), path, duration and size. A row can carry the
  badges *MOCK*, *FAULT*, *SLOW* and *REPLAY*. The log receiver `qa-logs.internal` is not
  listed. The window keeps the newest 10,000 requests; older ones are only in `flows.mitm`.
- **Detail panel.** Click a row. The tabs are *Request*, *Response* (JSON is shown folded and
  easy to read, a binary body only as a size), *Headers*, *Timing* and *Logs* (the log lines
  that carry this request's ID, with their number). *Copy cURL* copies the request as a `curl`
  command. *Copy as mock* copies the response body and shows the file to create under
  `mocks/<preset>/` (see *Mock a response*). Wiretrace does not write that file for you.
  *Replay* sends the request to the backend again; it appears as a new row with the *REPLAY*
  badge and a link back to the original. Any method other than GET, HEAD and OPTIONS asks you
  to confirm first, because the backend does the action again (another order, another
  payment). *Compare…* shows this request next to another one, by default the previous request
  with the same method and path: status and headers side by side, and the body as a list of
  changed JSON keys, or line by line when it is not JSON. *New rule* opens the Rules view with
  a rule for this request's method, host and path. *Report* opens *Report bug* for this
  request.
- **Logs.** A strip at the bottom of the Traffic view and the full *Logs* view show the
  *Device logs*, *App logs* and *Crashes* tabs with line counts, level chips, a text filter
  and auto-scroll. Lines that carry the selected request's ID are highlighted. The window keeps
  the newest 50,000 lines of each log; the files in the session folder keep all of them. The
  full view adds:
  - the device picker: what is being collected now and its state, the other log sources with
    the `--target` that collects them (the picker does not switch: use the device menu in the
    title bar), and the app logs sent by the QA build;
  - *Pause logs* (with the number of new lines), *Clear* (hides the lines, the files keep
    them), *Export .txt* (the lines shown now, **not masked**: check them before you share),
    a tag filter, and *Only lines linked to requests*;
  - a timeline: requests as dots coloured by status, log lines as ticks (errors in red),
    crashes marked, and the part shown in the list shaded. Click it to jump to that time;
  - a crash's stack trace folded after four lines (*Show N more lines*);
  - the line detail: *Copy line*, *Copy ±50 lines*, the linked request with *Open in Traffic*,
    the requests within 5 seconds of the line, and *Show only this tag*.
- **Setup.** A wizard in five steps, each of which you can open from the list on the left:
  *Choose device* (iPhone, Android, iOS Simulator or Android emulator, picked from `--target`;
  another card offers *Use <device> for this session*),
  *Connect to this Mac* (the address `<Mac IP>:<port>` and the Wi-Fi proxy steps, or the QR code
  and WireGuard steps; in the default `both` mode a **Wi-Fi proxy** | **WireGuard** switch picks
  which, and the later steps follow it; with `--mode wireguard`, the command to restart in proxy
  mode where you need it),
  *Trust Wiretrace*, *Check the app* and *Device logs*. See Part 2. The WireGuard
  configuration holds the phone's private key; do not share it.
- **Rules.** A list of rules on the left and the selected rule on the right. A rule matches a
  method (or *ANY*), one of the preset's API hosts (or any of them), a path where `*` stands
  for any text (`/api/*`; the query is ignored unless the path has a `?`), and optionally text
  the request body contains. It then answers with a mock (a file from `mocks/<preset>/` or a
  body you type in), answers with a status code, adds a delay, or drops the connection; a mock,
  status or drop can also wait first. *Apply* is *Always*, *Once* (until it has applied; then
  *Re-arm*) or *Every Nth* matching request. Rules are checked top to bottom: every rule that
  is on and matches counts the request, and the first one that applies decides. The switch on
  each row turns a rule on or off. *Test* checks the rule against the request selected in
  Traffic without counting it. Each rule shows how often it matched and applied, and when it
  last matched; the counters start again at zero when Wiretrace restarts or the rule changes.
  *Import…* and *Export…* read and write a rules file. Saving checks every field and keeps the
  previous rules if something is not valid; if the file changed in the meantime, the window
  loads it again instead of overwriting it. A flow changed by a rule carries the comment
  `rule: <name>` and the *FAULT* or *MOCK* badge.
- **Report bug.** A form shaped like a YouTrack or Jira issue, for the request selected in
  Traffic, or the most recent failed request when none is selected, or the whole session when
  nothing failed. It works on the session shown: the one running now (the requests saved so
  far) or the earlier session you opened. Nothing is sent anywhere: you copy and download, then
  add everything to your issue yourself.
  - *Title*: for example `POST /api/v1/orders returns 500`, with the path masked and without
    the query. Edit it if you like (1 to 200 characters); the copy icon copies it and shows
    *Copied*.
  - *Description*: *Steps to reproduce*, *Expected* and *Actual* for you to fill in, then the
    environment, the failed request, its masked response body (the first 4 KB) and up to 20
    log lines that carry its request ID. The copy icon copies the text as it is now, your edits
    included. Changing the format or a box under *Logs* writes the text again; if you edited
    it, Wiretrace asks *Replace your edits with a new description?* first.
  - *Format*: *Markdown (YouTrack, Jira Cloud)* or *Jira wiki (Jira Data Center)*. In
    YouTrack or Jira Cloud, paste into the issue's description and check the preview before you
    save. In Jira Data Center, switch the description editor to
    *Text* mode before you paste the Jira wiki text, or the markup shows as plain characters.
    The window remembers the format per preset, in your browser.
  - *Logs*: *Other requests ±30 s*, *Device logs (same window)* and *App logs (same window)*,
    each with its count, decide what goes into the files: the masked HAR
    (`<session>-requests.har`), the device and app logs as text (`<session>-device-log.txt`,
    `<session>-app-log.txt`), and *Download all*, a zip with those plus `summary.md`
    (`<session>-report.zip`). With all boxes on and no request, the zip is the same as
    `./wiretrace report`'s. *Masked before export* lists the header and field names that are
    hidden. Log lines are masked by pattern only: check them before you share.
  - *Screenshots*: *Take screenshot* saves the phone's screen now, up to 5, through `adb` for
    `--target android` and `android-emu` or from the booted Simulator for `ios-sim`; connect
    exactly one device. Each thumbnail can be downloaded or removed. They are kept in the
    session folder under `screenshots/` and listed again when you reopen the form. On a real
    iPhone (`--target ios`), take the screenshot on the phone (side button and volume up) and
    add it in the tracker yourself. For `--target device` and for an earlier session, the
    button is off and says why.
  - Downloads go to your browser's Downloads folder, which other programs and accounts may be
    able to read, unlike the protected session folder. Attach them to the issue, then delete
    them.

**Earlier sessions.** Click *Previous sessions* in the sidebar to list the session folders,
newest first, with their start time, preset, target and counts. Click one to open it: the
window shows its traffic and logs, read-only, under the banner *Viewing <session>*. Recording
of the current session goes on meanwhile. *Report bug* and *Compare…* work on the session you
opened; Rules, Replay, Setup, Pause and Clear are off. *Back to live* (or *Current session*)
returns to the session running now. As for the live session, the window shows the newest
10,000 requests and 50,000 lines of each log. If the session's `flows.mitm` ends early (for
example because the Mac shut down while recording), the banner says so and shows the requests
that could be read. Only one earlier session is open at a time, in every tab of the window.

Reloading the page, or a short break in the connection, loses nothing: the window shows
*Reconnecting…* and loads everything again. mitmweb's own Options panel is not part of this
window; use *Rules* instead. If `qa_fault_*` options are set anyway, the Rules view says so.

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
- Wiretrace keeps the **5 newest** previous sessions in `~/wiretrace/sessions/`, none older
  than 14 days (counted from the date in its name). When you start a session, or switch the
  preset or the device, it deletes the others and tells you how many. **To keep a session, move its folder out of `sessions/`**
  (for example to `~/Documents/bugs/`) before then. Only folders that Wiretrace created are
  deleted; other files and folders in `sessions/` stay. Delete sessions you no longer need
  earlier by hand: `flows.mitm` and the log files contain tokens and log lines.
- Never copy or share `~/.mitmproxy/mitmproxy-ca.pem`. It is the private key that lets
  your Mac decrypt traffic from every device that trusts it.

---

## Part 5 — Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| No requests appear at all | Tunnel off, or the phone cannot reach the Mac. Check WireGuard shows a recent handshake. Corporate or guest Wi-Fi often blocks device-to-device traffic: try a QA Wi-Fi or the Mac's hotspot. Check the firewall line in `./wiretrace doctor`. |
| `mitm.it` says traffic is not going through mitmproxy, or does not load | The tunnel is off or not connected. In WireGuard, tap the tunnel: *Endpoint* must be the Mac's current address with port 51820 (it changes when the Mac joins another network; scan the QR code again), and *Latest handshake* must be recent. An older `wiretrace` folder serves `mitm.it` only with a plain `mitmweb --mode wireguard`, not with `./wiretrace start`; update it. |
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
| `Device logs: adb failed (exit code …); retrying in 2 s`, or `adb did not run or answer; retrying in 2 s` (or `pymobiledevice3`, `xcrun`) | The tool stopped, could not be started, or did not answer within 10 seconds. Wiretrace retries by itself. If it keeps repeating, run `./wiretrace doctor`. |
| `Device logs: could not start the collector` | Wiretrace could not run its own log collector. Traffic is still captured. Run `scripts/setup-mac.sh` again, then start again. |
| `Device logs: stopped after an internal error (…)` | A bug in Wiretrace's log collector; the traffic capture goes on. Report it with the name in brackets, and stop and start Wiretrace to get the device log back. |
| `Device logs: collector stopped (exit code …); capture continues` | The log collector ended. Traffic capture is not affected. Stop and start Wiretrace to get the device log back. |
| `device.log.jsonl` is empty, or missing | The app wrote nothing while Wiretrace ran, or the process name or package in the preset is wrong. A file is created with the first line only. |
| iOS logs show `<private>` | The app logs with `print()` or private values. Ask the mobile team (R4). |
| `app.log.jsonl` is missing | The app sent nothing. Check in mitmweb whether requests to `qa-logs.internal` appear, and with which answer (`400`: the body is wrong). Check that Private DNS is off (WireGuard mode). The QA build must implement R6. |
| `Port … in use by another program` when starting | Another Wiretrace or mitmproxy is still running, for example a session from Part 2 or a `mitmweb` you started yourself. Quit it (Ctrl+C in its window). |
| `Unknown preset '…'. Available presets: …` | Check the spelling; the name is the file name in `presets/` without `.yaml`. To add one, see Part 1, Step 6. |
| `presets/staging.yaml: name is 'example', but must equal the file name without .yaml ('staging')` | The copied preset was not changed, or not saved. Open it (`open -e presets/staging.yaml`), set `name: staging`, your `api_hosts` and the `app:` names (Part 1, Step 6), save with Cmd+S, and start again. |
| `presets/<name>.yaml: …` | The preset file has a mistake; the message says which field. Fix the file and start again. |
| `Nothing was captured; the session folder was removed.` | No request and no log line reached Wiretrace before you stopped. See *No requests appear at all*. |
| `No traffic was captured; flows.har was not written.` | The session has log lines but no requests, so there is no HAR file. The session folder is kept. See *No requests appear at all*. |
| `flows.har was not written (could not mask it); flows.mitm is kept.` | Wiretrace could not hide the secrets in the HAR, so it did not write it. `flows.mitm` is kept. Run `./wiretrace report` to get the masked HAR in the zip, and report the problem to the Wiretrace maintainers. |
| `flows.har was not written (…)` (another reason) | `flows.mitm` is kept. Run `./wiretrace report` to get the HAR, masked, in the zip. Do not make a HAR with `mitmdump` yourself for a ticket: it has no masking. |
| `Unknown session '…'` (from `./wiretrace report`) | The name is not a folder in `sessions/`. Check the spelling, or run `./wiretrace report` without a name for the latest one. You can also give the path of a session folder. |
| `No sessions to report` or `… is not a Wiretrace session: it has no meta.json` | `sessions/` has no session yet, or the folder you named is not one Wiretrace saved. |
| `Nothing to report: the session has no traffic and no log lines.` | The session captured nothing, so there is nothing to put in a zip. See *No requests appear at all*. |
| `Warning: the preset of this session cannot be loaded (…)` (from `./wiretrace report`) | The preset was renamed, deleted or has a mistake. The report still hides the built-in names and the names the preset had when the session was captured, but not names added to the preset since. Fix or restore the preset file and run the report again. |
| `Could not write the report: …` | The zip could not be saved, for example because the disk is full. No partial zip is left. Free some space and run the command again. |
| `Deleted … old session(s): Wiretrace keeps the 5 newest, none older than 14 days.` | Normal, when you start Wiretrace or switch the preset or the device. It removed old session folders. To keep a session, move its folder out of `sessions/` before then (Part 4). |
| `redact.… is not a known key`, or `'redact.headers' entry …` (in `presets/<name>.yaml: …`) | The `redact:` section of the preset has an unknown key or an invalid name. Use only `headers` and `json_fields`, each a list (Part 1, Step 6). |
| mitmweb opens instead of the Wiretrace window, or there is no *Rules* button | Start with `--ui wiretrace`; without it you get mitmweb. If the Terminal banner has no `Rules:` line, the `wiretrace` folder is from before rules: update it (see *Updating and removing*). |
| The Rules view shows a red message about the rules file | `rules/<preset>.json` was edited by hand and has a mistake; the message says which rule and field. The previous rules stay in effect. Fix the file, or save from the window, which writes a valid file. |
| The Wiretrace window says "Open the link printed in the Terminal." | The page was opened without the token, or from an earlier start. Copy the newest `Wiretrace UI:` link from the Terminal and open it. |
| `Port TCP 8081 (Wiretrace UI): in use by another program` when starting with `--ui wiretrace` | Another Wiretrace or mitmweb window is still open. Quit it (Ctrl+C in its window) and start again. |
| The Wiretrace window stays on "Reconnecting…" | Wiretrace is no longer running, or the Mac was asleep. Look at the Terminal. If it is still running, reload the page; if not, start it again and open the new link. |
| The browser did not open the Wiretrace window | Copy the `Wiretrace UI:` link from the Terminal and open it by hand. |
| `Wiretrace UI: cannot listen on 127.0.0.1:…`, and Wiretrace stops | Another program took the port in the moment between the check and the start. Quit it and start again. |
| The Traffic list is empty but the phone works | The window lists only requests to the preset's `api_hosts`, and *Clear* or the search box may be hiding them. Check the search box, the quick filter and *Pause*. |
| *Report bug* offers no file to download | The session has no saved request and no log line yet, or the boxes under *Logs* leave nothing in. Make a request or tick a box, then try again. |
| *Report bug* says `That request is not in flows.mitm yet` | The request is still waiting for its answer. Wait until it finishes (or fails), then open *Report bug* again. |
| *Take screenshot* is off | The reason is next to the button: no device or more than one connected (`adb devices` lists them), no Simulator booted, `--target device`, or an earlier session open. A real iPhone's screenshot is taken on the phone. |
| Endpoint security quarantines mitmproxy | Ask IT to allowlist Wiretrace ([`install-without-admin.md`](install-without-admin.md#company-managed-macs-what-to-ask-it-for)). |

---

## Updating and removing

**Update to a new version:** move the old folder aside, extract the new one, run setup.
Your device setup (CA and tunnel in `~/.mitmproxy`) stays valid.

```bash
mv ~/wiretrace ~/wiretrace-old
tar -xzf wiretrace-<version>-macos.tar.gz -C ~
cd ~/wiretrace && ./install
```

The setup also updates the Wiretrace app, which then opens the new folder.

Copy the presets you created from `~/wiretrace-old/presets/` to `~/wiretrace/presets/`, your mock
files from `~/wiretrace-old/mocks/` to `~/wiretrace/mocks/`, your rules from
`~/wiretrace-old/rules/` to `~/wiretrace/rules/`, and any sessions you want to keep from
`~/wiretrace-old/sessions/`. If you changed `presets/default.yaml`, copy it too: the new
version comes with its own. Then delete `~/wiretrace-old`.

Stop Wiretrace (Ctrl+C, or **Stop session** in the **Wiretrace** menu) before you update: it reloads its add-on files when they change. Two
builds can carry the same version number, so to check which one you run, look at the Terminal
banner: a build with rules prints a `Rules:` line.

**Remove Wiretrace completely:**

```bash
rm -rf ~/wiretrace ~/tools/platform-tools ~/.local/share/uv ~/Applications/Wiretrace.app
rm -f ~/.local/bin/uv ~/.local/bin/uvx
```

Then delete the two `export PATH=…` lines Wiretrace added to `~/.zshrc`. Deleting
`~/.mitmproxy` as well removes the CA and the tunnel keys; every device then needs a new
certificate and a new tunnel.
