# Wiretrace — UI mockups

Mockups for the Phase 2 desktop app described in [`PLAN.md`](../PLAN.md) (feature IDs U1–U10). All data shown is illustrative.

- Source: [`wiretrace-mockup.html`](wiretrace-mockup.html). Open it in any browser (`open mockups/wiretrace-mockup.html`); it is a single static file with no dependencies. Buttons are not clickable.
- Images: [`screens/`](screens/), rendered at 2× from the HTML.

To regenerate the images after editing the HTML:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1480,4950 \
  --screenshot=/tmp/full.png "file://$PWD/mockups/wiretrace-mockup.html"
# then crop each screen: its .window box plus 20 px left/right and 16 px top/bottom, at 2x, e.g.:
sips --cropOffset 380 40 -c 1712 2800 /tmp/full.png --out mockups/screens/01-main-window.png
```

---

## 1. Main window — traffic, details, and logs (U3–U7)

![Main window](screens/01-main-window.png)

| Area | What it does |
|---|---|
| Title bar | **Traffic / Logs** view switch (with crash count), recording state, pause/clear, active preset, device connection, rules (with active count), device setup, **Report bug**. |
| Left sidebar | Current and previous sessions; quick filters with live counts (errors, slow, mocked, faulted, WebSocket); hosts from the preset; saved filters. |
| Traffic list | One row per request: time, method, status, path, duration, size. Errors are red; mocked, faulted, and slow requests get badges. |
| Detail panel | Selected request with request ID; **Copy cURL**, **Copy as mock**, **Replay**, **Compare**, **Report**; tabs for request, response (pretty JSON), headers, timing, and linked logs. |
| Log strip | Quick view of recent logs; lines with the same `X-Request-ID` as the selected request are highlighted. |

## 2. Device & app logs (U6, U7)

![Device and app logs](screens/02-device-app-logs.png)

The full log view, opened with **Logs** in the title bar.

| Area | What it does |
|---|---|
| Source tabs | **Device logs** (system log from the phone over USB), **App logs** (sent by the QA build to `qa-logs.internal`, no cable needed), **Crashes**. |
| Device picker (shown open) | Choose the log source: Android device (`adb logcat`), iPhone (`pymobiledevice3 syslog`), iOS Simulator (`simctl log stream`), or app logs over the network, with live connection status. |
| App filter | Limits logs to the app under test (package / process name from the preset). The collector re-attaches automatically when the app restarts or crashes (see the "App restarted · new PID" line). |
| Level chips and search | Toggle Verbose/Debug/Info/Warning/Error/Fatal with counts; text or regex search; tag filter; "only lines linked to requests". |
| Timeline | Requests (dots coloured by status) and log lines (ticks; errors red, crash marked) on one time axis. The shaded area is the part shown in the list; the blue line is the selected log line. |
| Log list | Time, level, PID/TID, tag, message. A 🔗 icon means the line contains a request ID that matches captured traffic. Crashes show the stack trace inline. |
| Detail panel | Full message and metadata, the **linked request** (open it in Traffic), requests around the same time, **Copy ±50 lines**, **Add to bug report**. |

## 3. Device setup wizard (U2)

![Device setup wizard](screens/03-device-setup-wizard.png)

Five steps: choose the device type, connect the WireGuard tunnel by scanning a QR code, install the CA certificate, verify that traffic arrives, and optionally connect USB for logs. The wizard waits for the first packet and shows troubleshooting hints if nothing arrives. "Use Wi-Fi proxy instead" is the fallback path.

## 4. Mock & fault rules (U8)

![Mock and fault rules](screens/04-mock-fault-rules.png)

Left: rules for the current preset, each with an on/off toggle and a summary. Right: the editor.

- **Match** by method, host, path pattern, and optionally body content.
- **Action**: mock response, status code, delay, or drop connection.
- **Apply**: always, once per app launch, or every Nth call. This covers cases like "token refresh fails every 3rd time".
- Shows how often the rule matched in this session. **Test against last request** previews the result without using the app.

## 5. Bug report → YouTrack (U10)

![Bug report](screens/05-bug-report.png)

Opened from a failed request or log line. It pre-fills the title and context (device, OS, app build) and includes surrounding requests, device and app logs from the same time window, and a device screenshot. Sensitive headers and fields are masked before anything is uploaded.

The default destination is **YouTrack**: pick the project, type, and priority, and the tool creates the issue, attaches the redacted report and screenshot, adds the `wiretrace` tag, and shows the issue link. The QA engineer's personal YouTrack token is stored in the macOS Keychain. Jira and "Save .zip" are alternative destinations. Details: `PLAN.md` section 9.8.

## 5a. Bug report form — copy and download (U10, first version)

![Bug report form](screens/05a-bug-report-form.png)

The first version of screen 5 ([spec 012](../docs/specs/012-bug-report-form.md)), without the tracker integration. Wiretrace sends nothing anywhere.

| Area | What it does |
|---|---|
| Title | Pre-filled from the failed request, editable; the copy icon copies it. |
| Description | Pre-filled with steps, expected, actual, environment, the failed request, the masked response body and linked log lines; editable. **Markdown** (YouTrack, Jira Cloud) or **Jira wiki** (Data Center) changes what the copy icon copies. |
| Logs | Boxes for the requests and log lines within ±30 s; each file (masked HAR, device log, app log) has a download icon. |
| Screenshots | **Take screenshot** through `adb` (Android phone or emulator) or `simctl` (iOS Simulator), up to 5, each with a download icon. On a real iPhone, the tester takes it on the phone. |
| Footer | **Download all (.zip)**: the files above plus `summary.md`. |

## 6. Menu-bar status (U1)

![Menu-bar status](screens/06-menu-bar.png)

Shows recording state and error count in the macOS menu bar, with shortcuts to open the app, pause, report the last error, or stop the session.
