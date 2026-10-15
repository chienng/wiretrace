# Installing Wiretrace without a Mac admin account

Companion to [`PLAN.md`](../PLAN.md).

## Short answer

**Yes.** Everything Wiretrace needs for testing **physical iOS and Android devices** can be installed and run from the user's home folder by a standard (non-admin) macOS user:

- mitmproxy runs as a normal user process.
- Its WireGuard mode is built into mitmproxy and needs no system network extension on the Mac.
- All ports it uses are above 1024.
- The CA certificate is generated per user in `~/.mitmproxy`.
- The certificate is installed on the **phone**, not in the Mac's system keychain.

There are three exceptions, all optional, which need **one-time help from IT**:

1. **Xcode and the iOS Simulator**, only for teams that test on the simulator.
2. **Changing the Mac's system proxy**, only needed to send iOS Simulator traffic through Wiretrace.
3. **A firewall rule**, only if the company firewall policy blocks incoming connections.

The main thing to avoid is **Homebrew**: its standard installation requires an admin account. The setup below uses `uv` and plain downloads instead.

---

## What needs admin and what doesn't

| Item | Admin needed? | Notes |
|---|---|---|
| Homebrew | **Yes** (initial install into `/opt/homebrew`) | Not used. Replaced by `uv` and direct downloads. |
| `uv` (Python package/version manager) | No | Installs into `~/.local/bin`. |
| Python 3.12 | No | `uv python install` puts it in `~/.local/share/uv`. |
| mitmproxy, pyyaml, pymobiledevice3 | No | Installed into a project virtual environment. |
| mitmproxy CA certificate | No | Generated in `~/.mitmproxy` on first run. |
| Listening on UDP 51820, TCP 8080, TCP 8081 | No | Only ports below 1024 need root. |
| mitmproxy **WireGuard mode** | No | WireGuard server runs inside the mitmproxy process; the phone runs the WireGuard client. |
| mitmproxy **local mode** (`--mode local`) | **Yes** (system extension approval) | Not used by this plan. |
| Android platform-tools (`adb`) | No | Unzip into `~/tools`. |
| `adb` access to a phone over USB | No | Enable USB debugging on the phone. |
| `pymobiledevice3 syslog live` / `crash pull` (iOS device logs) | No* | Uses the built-in `usbmuxd`; the phone must "Trust This Computer". *Confirm in Phase 0 on a standard account. |
| `pymobiledevice3` iOS 17+ developer tunnel (`remote tunneld`) | **Yes** (sudo) | Not needed for logs or crash reports; not used by this plan. |
| Installing the CA on phones | No (Mac admin not involved) | Done on the phone. |
| Xcode + iOS Simulator | **Yes** for install | IT installs once, only if the simulator is used. |
| `xcrun simctl keychain booted add-root-cert` | No | Adds the CA to the simulator, not the Mac. |
| Changing the Mac's system proxy | **Usually yes** | Only for simulator traffic; see options below. |
| Trusting the CA in the Mac's System keychain | Not needed | Only required to intercept the Mac's own browser traffic, which is out of scope. |
| macOS firewall "Allow incoming connections" prompt | **Depends on company policy** | If the firewall is managed by MDM, IT adds an allow rule. |
| Phase 2 `Wiretrace.app` in `~/Applications` | No | Must be signed and notarized, or distributed via IT Self Service. |

---

## Installation steps (Phase 1, standard user)

### 1. Get Wiretrace

Follow steps 1 and 2 of the [README quick start](../README.md#quick-start): download the release `.tar.gz` and its `.sha256` from the Releases page, check the checksum, and unpack it into your home folder. This gives you `~/wiretrace`. It needs neither `git` nor the Xcode Command Line Tools (which need admin).

### 2. Run the setup

```bash
cd ~/wiretrace
scripts/setup-mac.sh                 # add --skip-android if you only test iOS
```

All inside your home folder, it installs `uv` into `~/.local/bin`, Python 3.12, the Python packages into `~/wiretrace/.venv`, and Android platform-tools into `~/tools/platform-tools`, then adds the `PATH` lines to `~/.zshrc`. It installs fixed versions of `uv` and platform-tools, downloaded from their GitHub / Google release URLs, and checks each file against a SHA-256 checksum stored in the script before installing it; no downloaded script is executed. It can be run again safely. It never asks for a password; do not run it with `sudo`. Open a new Terminal window afterwards so the `PATH` changes apply.

Do not install the Python packages by hand with `uv pip install -r requirements.txt`. The setup also applies `overrides.txt`, which installs fixed versions of `cryptography`, `h2`, `tornado` and `msgpack` in place of releases with known vulnerabilities.

### 3. Check the setup

```bash
cd ~/wiretrace
./wiretrace doctor
```

`doctor` prints one line per check, marked `OK`, `WARN`, `FAIL` or `INFO`, and exits with `1` if any check is `FAIL`:

- Python 3.12 or newer, mitmproxy 11 or newer (with `mitmweb`), and the other packages in `requirements.txt` are installed.
- `adb` is found on `PATH` or in `~/tools/platform-tools` (`WARN` if not: Android testing is unavailable).
- Ports 51820/udp, 8080/tcp, and 8081/tcp are free.
- `~/.mitmproxy` contains a CA (`INFO` until mitmproxy creates it on first start), and its private key is readable by you only.
- Whether the macOS firewall is on, blocks all incoming connections, or blocks Wiretrace's Python.
- How many phones are visible over USB (`adb devices`, `pymobiledevice3 usbmux list`). Only counts are shown, never serial numbers or UDIDs.

The setup runs this check at the end; run `./wiretrace doctor` again after fixing a `FAIL` line.

### Gatekeeper ("app can't be opened")

Files downloaded through a browser get a quarantine flag. A standard user can remove it from files they own:

```bash
xattr -dr com.apple.quarantine ~/tools/platform-tools
xattr -dr com.apple.quarantine ~/Applications/Wiretrace.app
```

The second line applies to the Phase 2 app. Files downloaded with `curl` or installed with `uv` are not quarantined.

---

## iOS Simulator without admin

The iOS Simulator uses the Mac's network settings. Sending its traffic through Wiretrace normally means setting the Mac's system HTTP/HTTPS proxy, and on most company Macs that requires admin rights. Options, from most to least recommended:

| Option | Who does it | Notes |
|---|---|---|
| **A. Test on physical iPhones** | QA | Uses WireGuard mode; no Mac changes at all. |
| **B. IT grants standard users permission to change network settings** | IT, once | e.g. `security authorizationdb write system.preferences.network allow` plus `system.services.systemconfiguration.network`, or an MDM setting. Wiretrace can then switch the proxy on/off with `networksetup`. |
| **C. IT deploys a proxy configuration profile** | IT, once | MDM profile pointing to `127.0.0.1:8080`; QA enables it only while testing. |
| **D. QA build supports a debug proxy setting** | Mobile dev team | e.g. a launch argument or debug menu that sets `connectionProxyDictionary` on the app's `URLSessionConfiguration`. Only affects the app under test. |

The CA certificate is installed into the simulator with `xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem`, which does not need admin. Xcode itself must be installed by IT.

---

## Company-managed Macs: what to ask IT for

Even when no admin rights are needed, a tool that intercepts HTTPS traffic should be **approved by IT/security** first. Some company security tools (EDR such as CrowdStrike, Microsoft Defender, Jamf Protect) may flag or block mitmproxy, and MDM policies may block unsigned binaries.

Recommended request to IT:

1. **Approve Wiretrace** (mitmproxy-based) for the QA team, with this plan as the description.
2. **Allowlist it in endpoint security** (EDR) so it is not quarantined.
3. **Publish it in Self Service** (Jamf Self Service, Intune Company Portal, or Munki). QA can then install and update it with one click, without admin rights. This is the best option for Phase 2.
4. **Firewall**: if the firewall is managed, add an allow rule for incoming connections to Wiretrace (UDP 51820, TCP 8080). Rules per app work best with a **signed app bundle**, which is another reason for the Phase 2 signed app.
5. **Optional**: install Xcode and allow network-settings changes on Macs used for iOS Simulator testing.
6. **Optional**: allow a dedicated **QA Wi-Fi** where phones and Macs can reach each other. Guest/corporate Wi-Fi often blocks device-to-device traffic.

---

## Phase 0 check

Before rolling out, test the complete flow on a **standard (non-admin) account** on a company Mac:

- [ ] Steps 1–3 complete without any password prompt.
- [ ] `mitmweb --mode wireguard` starts and the macOS firewall does not block it (or IT rule works).
- [ ] An iPhone and an Android phone connect via WireGuard and show decrypted API traffic.
- [ ] `adb logcat` streams Android app logs.
- [ ] `pymobiledevice3 syslog live` streams iOS device logs.
- [ ] `pymobiledevice3 crash pull` retrieves crash reports.
- [ ] Endpoint security does not quarantine mitmproxy.
