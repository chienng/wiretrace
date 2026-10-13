# Wiretrace — Installation and usage guide

For QA engineers. Covers Wiretrace **0.2.0**.

What 0.2.0 gives you: a one-command install that needs no admin rights, a setup
check (`./wiretrace doctor`), project presets, and `./wiretrace start --preset …`, which
captures only your project's API traffic and saves each session in its own folder with a
HAR file (Part 3). Mocks, redaction, log collection, and bug-report export are planned
([`PLAN.md`](../PLAN.md) Phase 1) and not in this version yet.

---

## Part 1 — Install (once per Mac)

### Before you start

- A Mac with macOS. A **standard (non-admin) account is fine**; you will not be asked
  for a password.
- Internet access to `github.com`, `pypi.org`, and `dl.google.com` during the install.
  If the company network blocks one of them, ask IT.
- The release file and its checksum: either `wiretrace-0.2.0-macos.tar.gz` and
  `wiretrace-0.2.0-macos.tar.gz.sha256`, or `wiretrace-0.2.0-macos.dmg` and
  `wiretrace-0.2.0-macos.dmg.sha256`. Both contain the same files.

### Step 1 — Check the download

Open **Terminal**, go to the folder with both files (usually Downloads), and run the line
for the file you have:

```bash
cd ~/Downloads
shasum -a 256 -c wiretrace-0.2.0-macos.tar.gz.sha256
shasum -a 256 -c wiretrace-0.2.0-macos.dmg.sha256
```

It must print `…: OK`. If it prints `FAILED`, download the file again and do not continue.

### Step 2 — Put the wiretrace folder in your home folder

**From the `.tar.gz`:**

```bash
tar -xzf wiretrace-0.2.0-macos.tar.gz -C ~
```

Use this command rather than double-clicking the file in Finder, so the folder ends up in
the right place.

**From the `.dmg`:** double-click it, drag the `wiretrace` folder onto your home folder (in
Finder: **Go → Home**), then eject **Wiretrace 0.2.0**. Wiretrace cannot run from the disk
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
  names the session folder and picks the setup reminders printed at start.
- `--no-ui` runs in the Terminal only (mitmdump) instead of opening mitmweb.
- `--mode proxy` runs a regular proxy on port 8080 instead of WireGuard. Set the phone's
  Wi-Fi proxy to `<Mac IP>:8080`.
- The preset's `default_filter` is the starting filter: in mitmweb's search box, or what
  is printed with `--no-ui`. It never limits what is saved. Common filters:
  `~c 500` (status 500), `~m POST`, `~u /api/v1/orders`, `~bs "SOME_TEXT"` (response body).
  More in [`PLAN.md` Appendix B](../PLAN.md#appendix-b--mitmweb-filter-expressions-for-qa).
- If a port is in use, Wiretrace says which one and does not start. Usually another Wiretrace or mitmproxy window is still open: quit it.

### Step 2 — Collect app logs (second Terminal window)

Connect the phone by USB, and `cd` into the session folder printed at start, so the
log file ends up next to `flows.mitm`.

Android (replace `com.mycompany.myapp` with your app's package name):

```bash
adb logcat --pid=$(adb shell pidof -s com.mycompany.myapp) | tee android.log
```

iPhone (replace `MyApp` with your app's process name):

```bash
source ~/wiretrace/.venv/bin/activate
pymobiledevice3 syslog live -pn MyApp | tee ios.log
```

On Android, start the app first; if the app restarts, run the command again (its process
ID changes).

### Step 3 — Reproduce the problem

Use the app as usual. Note the time when the problem happens; it makes it easier to find
the request and the log lines.

### Step 4 — Stop

Press **Ctrl+C** once in the Wiretrace window. It stops mitmproxy, writes `flows.har` next to
`flows.mitm`, and prints the session folder. If it says *still stopping*, press Ctrl+C
again to force it. If nothing was captured, the session folder is removed.

Press **Ctrl+C** in the log window too.

For an iOS crash, also pull the crash reports into the session folder:

```bash
source ~/wiretrace/.venv/bin/activate
pymobiledevice3 crash pull ./crashes
```

### Step 5 — Export for the bug ticket

Attach `flows.har` from the session folder. It opens in Chrome DevTools, Charles,
Proxyman, …

To look at the session again later: `mitmweb -r flows.mitm`. In mitmweb you can also
copy a single request as cURL.

> **Important: exports are not redacted yet.** `flows.mitm`, `flows.har` and the log
> files contain access tokens, cookies, and whatever the test account sent. Attach them only
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

### Optional — Fake responses and slow networks

mitmproxy can already do this with built-in options. The launcher does not pass them on
yet, so add them to the mitmproxy command in [Without the launcher](#without-the-launcher).

Return a local JSON file instead of the real response:

```bash
--map-local '|api-staging.mycompany.com/api/v1/profile|./profile.json'
```

Add a request header:

```bash
--modify-headers '/~d api-staging.mycompany.com/X-Debug/1'
```

More in [`PLAN.md` Appendix A](../PLAN.md#appendix-a--command-cheat-sheet).

---

## Part 4 — After testing

- Turn the WireGuard tunnel off when you are not testing.
- When a device leaves testing: delete the tunnel, and remove the **mitmproxy** profile /
  certificate (iPhone: VPN & Device Management; Android: Security → Trusted credentials → User).
- Delete old session folders in `~/wiretrace/sessions/`; they contain tokens.
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
| `adb logcat --pid=…` prints an error | The app is not running. Start it, then rerun the command. |
| iOS logs are empty or show `<private>` | The app logs with `print()` or private values. Ask the mobile team (R4). |
| `Port … in use by another program` when starting | Another Wiretrace or mitmproxy is still running, often the `mitmweb` from Part 2. Quit it (Ctrl+C in its window). |
| `Unknown preset '…'. Available presets: …` | Check the spelling; the name is the file name in `presets/` without `.yaml`. To add one, see Part 1, Step 6. |
| `presets/<name>.yaml: …` | The preset file has a mistake; the message says which field. Fix the file and start again. |
| `Nothing was captured; the session folder was removed.` | No request reached Wiretrace before you stopped. See *No requests appear at all*. |
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
