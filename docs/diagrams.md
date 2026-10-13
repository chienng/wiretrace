# Wiretrace — Workflows and Diagrams

Companion to [`PLAN.md`](../PLAN.md). All diagrams are Mermaid and render in GitLab, GitHub, and Cursor's markdown preview.

Contents:

1. [QA daily testing workflow](#1-qa-daily-testing-workflow)
2. [One-time setup workflow](#2-one-time-setup-workflow)
3. [Choosing how to connect a device](#3-choosing-how-to-connect-a-device)
4. [Troubleshooting flow](#4-troubleshooting-flow)
5. [Sequence: intercepting an API call](#5-sequence-intercepting-an-api-call)
6. [Sequence: mock and fault injection](#6-sequence-mock-and-fault-injection)
7. [Sequence: collecting logs and linking them to requests](#7-sequence-collecting-logs-and-linking-them-to-requests)
8. [Sequence: creating a bug report](#8-sequence-creating-a-bug-report)
9. [Component diagram](#9-component-diagram)
10. [Deployment diagram](#10-deployment-diagram)
11. [Network ports and connections](#11-network-ports-and-connections)
12. [Session lifecycle](#12-session-lifecycle)
13. [Session data model](#13-session-data-model)
14. [Delivery timeline](#14-delivery-timeline)

---

## 1. QA daily testing workflow

What a QA engineer does during a normal test task.

```mermaid
flowchart TD
    A([Start test task]) --> B["Open Wiretrace and pick a preset<br/>(e.g. staging)"]
    B --> C{Device already<br/>set up?}
    C -- No --> D["Run device setup wizard<br/>(see diagram 2)"]
    C -- Yes --> E[Turn on WireGuard tunnel on the phone]
    D --> E
    E --> F["Plug in USB cable<br/>(for device logs, optional)"]
    F --> G[Start session]
    G --> H[Run test cases in the app]
    H --> I{Unexpected<br/>behaviour?}
    I -- No --> J{More test<br/>cases?}
    J -- Yes --> H
    I -- Yes --> K["Filter traffic<br/>(errors, endpoint, text search)"]
    K --> L["Open the request:<br/>request, response, related logs"]
    L --> M{Need to reproduce<br/>an edge case?}
    M -- Yes --> N["Add a mock or fault rule<br/>(500, timeout, empty list)"]
    N --> H
    M -- No --> O["Report bug<br/>(redacted traffic + logs + screenshot)"]
    O --> P["Post to YouTrack<br/>(or save zip)"]
    P --> J
    J -- No --> Q[Stop session]
    Q --> R[Turn off WireGuard tunnel on the phone]
    R --> S([Done])
```

---

## 2. One-time setup workflow

Done once per Mac and once per test device.

```mermaid
flowchart TD
    subgraph Mac["Once per Mac"]
        M1["Install Wiretrace<br/>(IT Self Service or setup script, no admin needed)"] --> M2["First launch creates this Mac's own CA<br/>in ~/.mitmproxy"]
        M2 --> M3["Run wiretrace doctor<br/>(checks tools, ports, firewall)"]
    end

    subgraph Device["Once per test device"]
        D1[Install WireGuard app] --> D2[Scan QR code shown by Wiretrace]
        D2 --> D3[Install and trust the CA certificate]
        D3 --> D4[Install the QA build of the app]
        D4 --> D5{Platform}
        D5 -- Android --> D6[Enable USB debugging]
        D5 -- iOS --> D7["Tap 'Trust This Computer'"]
    end

    subgraph DevTeam["Once per app (mobile dev team)"]
        R1["QA build: trust user CAs (Android)"]
        R2[QA build: certificate pinning off]
        R3[QA build: X-Request-ID header + public logs]
    end

    Mac --> Device
    DevTeam --> D4
```

---

## 3. Choosing how to connect a device

```mermaid
flowchart TD
    S{Which target?}
    S --> IOSD[iOS device]
    S --> AD[Android device]
    S --> AE[Android emulator]
    S --> IOSS[iOS Simulator]

    IOSD --> W["WireGuard mode<br/>(recommended)"]
    AD --> W
    AE --> WE["WireGuard mode<br/>or emulator proxy 10.0.2.2:8080"]

    IOSS --> SIM{Can the Mac's system<br/>proxy be changed?}
    SIM -- "Yes (admin or IT-granted right)" --> SP["Regular mode +<br/>Mac system proxy 127.0.0.1:8080"]
    SIM -- No --> SN["QA build with a debug proxy setting<br/>or test on a physical device"]

    W --> CA[Install CA on the device]
    WE --> CA
    SP --> CAS["simctl keychain add-root-cert<br/>(no admin)"]
    SN --> CAS
```

WireGuard mode is the default because it works the same on every Wi-Fi network and also captures apps that ignore the phone's proxy setting (Flutter, some React Native libraries).

---

## 4. Troubleshooting flow

```mermaid
flowchart TD
    P([Problem]) --> Q1{Any traffic in<br/>Wiretrace at all?}

    Q1 -- No --> N1{WireGuard tunnel<br/>on and connected?}
    N1 -- No --> F1[Turn on tunnel / rescan QR code]
    N1 -- Yes --> N2{Mac and phone can<br/>reach each other?}
    N2 -- No --> F2["Same Wi-Fi? Guest Wi-Fi often blocks<br/>device-to-device traffic. Try QA Wi-Fi or Mac hotspot"]
    N2 -- Yes --> F3["macOS firewall blocking Wiretrace?<br/>Run wiretrace doctor / ask IT"]

    Q1 -- Yes --> Q2{Our API calls<br/>visible?}
    Q2 -- No --> N3{Host in the<br/>preset allowlist?}
    N3 -- No --> F4[Add host to preset api_hosts]
    N3 -- Yes --> F5["App ignores proxy?<br/>Use WireGuard mode, not Wi-Fi proxy"]

    Q2 -- "Yes, but TLS errors" --> N4{Platform}
    N4 -- iOS --> F6["CA installed AND full trust enabled<br/>in Certificate Trust Settings?"]
    N4 -- Android --> F7["QA build trusts user CAs?<br/>(network_security_config debug-overrides)"]
    F6 --> F8{Still failing?}
    F7 --> F8
    F8 -- Yes --> F9["Certificate pinning is on.<br/>Ask dev team for a QA build without pinning"]

    Q2 -- "Yes, but no logs" --> N5{Platform}
    N5 -- Android --> F10["USB debugging on? 'adb devices' lists phone?<br/>Package name in preset correct?"]
    N5 -- iOS --> F11["'Trust This Computer' accepted?<br/>App uses os_log, not only print()?"]
```

---

## 5. Sequence: intercepting an API call

```mermaid
sequenceDiagram
    autonumber
    participant App as Mobile app (QA build)
    participant WG as WireGuard tunnel
    participant P as mitmproxy core
    participant A as QA addons
    participant B as Backend API
    participant UI as Wiretrace UI

    App->>WG: HTTPS request to api-staging.mycompany.com
    WG->>P: Encrypted packets (UDP 51820)

    alt Host is on the preset allowlist
        P->>P: TLS handshake with a certificate<br/>signed by this Mac's CA
        P->>A: request hook
        A->>A: Read X-Request-ID, check mock/fault rules
        A-->>P: No rule matched, continue
        P->>B: Forward request (new TLS connection)
        B-->>P: Response
        P->>A: response hook
        A->>UI: Stream flow (WebSocket)
        P-->>WG: Response, re-encrypted
        WG-->>App: Response
    else Host not on allowlist (analytics, ads, Apple/Google services)
        P->>B: Pass through encrypted, not decrypted
        B-->>App: Response unchanged
    end
```

---

## 6. Sequence: mock and fault injection

```mermaid
sequenceDiagram
    autonumber
    actor QA
    participant UI as Wiretrace UI
    participant A as Rule engine (addon)
    participant App as Mobile app
    participant B as Backend API

    QA->>UI: Create rule "GET /api/v1/orders → 500, always"
    UI->>A: Update active rules
    App->>A: GET /api/v1/orders

    alt Mock rule matches
        A-->>App: Local JSON file as response
        A->>UI: Flow marked "mocked"
    else Fault rule matches
        A-->>App: Forced status / delay / dropped connection
        A->>UI: Flow marked "fault"
    else No rule matches
        A->>B: Forward request
        B-->>A: Real response
        A-->>App: Real response
    end

    QA->>UI: Disable rule after testing
    UI->>A: Update active rules
```

---

## 7. Sequence: collecting logs and linking them to requests

```mermaid
sequenceDiagram
    autonumber
    participant App as Mobile app
    participant OS as Device OS log
    participant C as Log collector (Mac)
    participant R as App-log receiver (addon)
    participant S as Session store
    participant UI as Wiretrace UI

    App->>OS: Log "OrderRepo: req=7f3a… failed: HTTP 500"
    OS-->>C: Over USB: adb logcat / pymobiledevice3 syslog
    C->>C: Filter by package / process, parse level + tag
    C->>S: Append device.log.jsonl

    opt In-app logging enabled in QA build (R6)
        App->>R: POST https://qa-logs.internal/log
        R-->>App: 204 No Content (never forwarded)
        R->>S: Append app.log.jsonl
    end

    S->>UI: New log lines
    UI->>UI: Link to request with same X-Request-ID,<br/>otherwise by timestamp ±3 s
```

---

## 8. Sequence: creating a bug report

```mermaid
sequenceDiagram
    autonumber
    actor QA
    participant UI as Wiretrace UI
    participant E as Report exporter
    participant S as Session store
    participant K as macOS Keychain
    participant T as YouTrack REST API

    QA->>UI: Select failed request(s) → Report bug
    UI->>E: Build report (flows, time window, options)
    E->>S: Read flows + logs in the time window
    E->>E: Redact Authorization, cookies, configured JSON fields
    E->>E: Write flows.har, logs.txt, summary.md, screenshot.png
    E-->>UI: report_<date>_<endpoint>.zip

    alt Destination = YouTrack
        UI->>K: Read personal YouTrack token
        K-->>UI: token
        UI->>T: POST /api/issues (project, summary, Markdown description)
        T-->>UI: MOB-1234
        UI->>T: POST /api/issues/MOB-1234/attachments (zip, screenshot)
        UI->>T: POST /api/commands "Type Bug Priority Major tag wiretrace"
        UI-->>QA: Link to https://mycompany.youtrack.cloud/issue/MOB-1234
    else Destination = zip, or upload failed
        UI-->>QA: Reveal zip in Finder
    end
```

The same flow is available from the CLI in Phase 1: `./wiretrace report <session> --youtrack`.

---

## 9. Component diagram

```mermaid
flowchart TB
    subgraph Presentation["Presentation"]
        MW["mitmweb UI<br/>(Phase 0–1, in browser)"]
        APP["Wiretrace desktop app<br/>(Phase 2, Tauri + React)"]
        CLI["wiretrace CLI / launcher"]
    end

    subgraph Backend["Wiretrace backend (Python, user space)"]
        API["Local API<br/>REST + WebSocket"]
        SM[Session manager]
        PM[Preset manager]
        RE["Rule engine<br/>mocks, faults, delays"]
        RID[Request-ID tagger]
        RD[Redactor]
        EX[Report exporter]
        LR[App-log receiver]
        LC["Log collectors<br/>Android · iOS device · iOS Simulator"]
    end

    subgraph Engine["mitmproxy (library)"]
        MP["Proxy core<br/>HTTP/1.1 · HTTP/2 · WebSocket"]
        WGS["WireGuard server<br/>(user space)"]
        CA["Certificate authority"]
    end

    subgraph Files["Local files (~/wiretrace)"]
        PR["presets/*.yaml"]
        MK["mocks/**"]
        SS["sessions/{session-id}/"]
    end

    subgraph External["External tools"]
        ADB[adb]
        PMD[pymobiledevice3]
        SIMCTL[xcrun simctl]
    end

    CLI --> SM
    APP --> API
    MW --> MP
    API --> SM
    API --> RE
    API --> EX

    SM --> PM
    SM --> LC
    SM --> MP
    PM --> PR
    RE --> MK

    WGS --> MP
    MP --> CA
    MP -- "addon hooks" --> RE
    MP -- "addon hooks" --> RID
    MP -- "addon hooks" --> LR

    LC --> ADB
    LC --> PMD
    LC --> SIMCTL

    LC --> SS
    LR --> SS
    MP -- "flows" --> SS
    EX --> RD
    EX --> SS
```

| Component | Responsibility |
|---|---|
| Session manager | Starts/stops proxy and collectors, creates the session folder and `meta.json` |
| Preset manager | Loads `presets/*.yaml`, builds `--allow-hosts` list and default filter |
| Rule engine | Mock responses, forced status codes, delays, dropped connections |
| Request-ID tagger | Reads `X-Request-ID`, stores it on the flow for log matching |
| App-log receiver | Accepts `POST qa-logs.internal/log`, stores it, answers `204` |
| Log collectors | Wrap `adb`, `pymobiledevice3`, `simctl`; write JSON lines |
| Redactor | Masks sensitive headers and JSON fields in exports |
| Report exporter | Builds HAR, logs, summary, zip; posts the issue to YouTrack (token from macOS Keychain) |

---

## 10. Deployment diagram

Everything Wiretrace needs runs in the user's home folder, so it works on standard (non-admin) accounts. Items in the "IT-managed" box are optional and only needed for the features listed. See [`install-without-admin.md`](install-without-admin.md).

```mermaid
flowchart LR
    subgraph Dist["Distribution"]
        GIT["Internal GitLab repo<br/>(source, presets, shared mocks)"]
        SSV["IT Self Service<br/>(Jamf / Intune / Munki)"]
    end

    subgraph Mac["QA engineer's Mac (standard user)"]
        subgraph Home["User space (~), no admin"]
            QAP["Wiretrace<br/>~/Applications/Wiretrace.app (Phase 2)<br/>or ~/wiretrace + uv venv (Phase 1)"]
            CAF["~/.mitmproxy<br/>(this Mac's CA)"]
            SES["~/wiretrace/sessions"]
            PT["~/tools/platform-tools<br/>(adb)"]
            BRW["Browser<br/>(mitmweb UI, Phase 1)"]
            KC["Login Keychain<br/>(personal YouTrack token)"]
        end
        subgraph ITM["IT-managed (optional)"]
            XC["Xcode + iOS Simulator"]
            FW["Firewall allow rule<br/>for Wiretrace"]
        end
        USBM["usbmuxd<br/>(built into macOS)"]
    end

    subgraph Devices["Test devices"]
        IPH["iPhone<br/>WireGuard app · CA · QA build"]
        AND["Android phone<br/>WireGuard app · CA · QA build"]
    end

    subgraph Envs["Backend environments"]
        DEVAPI["dev APIs"]
        STGAPI["staging APIs"]
    end

    TRK["YouTrack<br/>(Cloud or self-hosted)"]

    GIT -- "git clone / pull" --> QAP
    SSV -- "one-click install" --> QAP

    IPH -- "WireGuard UDP 51820" --> QAP
    AND -- "WireGuard UDP 51820" --> QAP
    IPH -- USB --> USBM --> QAP
    AND -- "USB (adb)" --> PT --> QAP

    QAP -- "HTTPS 443" --> DEVAPI
    QAP -- "HTTPS 443" --> STGAPI
    BRW -- "localhost:8081" --> QAP
    QAP --> CAF
    QAP --> SES
    QAP --> KC
    QAP -- "HTTPS 443: create issue + attachments" --> TRK
    XC -. "simulator traffic via<br/>Mac system proxy" .-> QAP
```

### Deployment options compared

| Option | Phase | Admin needed? | Updates | Best for |
|---|---|---|---|---|
| Setup script + `uv` venv in `~/wiretrace` | 1 | No | `git pull` + `uv pip install -r requirements.txt` | Pilot, technical QA |
| Signed `.app` copied to `~/Applications` | 2 | No | Built-in updater | Small teams without MDM |
| IT Self Service package | 1 or 2 | No (IT installs) | Pushed by IT | Company-managed Macs (recommended) |

---

## 11. Network ports and connections

```mermaid
flowchart LR
    Phone["Phone<br/>(WireGuard client)"] -- "UDP 51820" --> WGP
    Emu["Android emulator /<br/>Wi-Fi proxy clients"] -- "TCP 8080" --> HP

    subgraph Mac["Mac"]
        WGP["mitmproxy WireGuard listener<br/>0.0.0.0:51820/udp"]
        HP["mitmproxy HTTP proxy listener<br/>0.0.0.0:8080/tcp"]
        WEB["mitmweb / local API<br/>127.0.0.1:8081/tcp"]
    end

    WGP --> OUT(("Outbound"))
    HP --> OUT
    OUT -- "TCP 443 / 80" --> BE["Backend APIs"]
    UIc["Browser / desktop app"] -- "localhost only" --> WEB
```

| Port | Protocol | Bound to | Purpose | Admin needed? |
|---|---|---|---|---|
| 51820 | UDP | all interfaces | WireGuard from phones | No (port > 1024) |
| 8080 | TCP | all interfaces | Regular HTTP proxy (emulator, simulator, fallback) | No |
| 8081 | TCP | `127.0.0.1` only | mitmweb UI / local API | No |

The UI port is bound to localhost so other people on the Wi-Fi cannot see captured traffic.

---

## 12. Session lifecycle

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Starting: Start session (preset, target)
    Starting --> WaitingForDevice: Proxy + collectors running
    Starting --> Error: Port busy / tool missing
    Error --> Idle: Fix (wiretrace doctor)
    WaitingForDevice --> Recording: First flow received
    Recording --> Paused: Pause
    Paused --> Recording: Resume
    Recording --> Stopping: Stop
    Paused --> Stopping: Stop
    Stopping --> Saved: HAR written, crash logs pulled
    Saved --> Exported: Report bug
    Exported --> Saved
    Saved --> Idle: New session
    Saved --> Deleted: Auto cleanup after N days
    Deleted --> [*]
```

---

## 13. Session data model

```mermaid
erDiagram
    SESSION ||--o{ FLOW : contains
    SESSION ||--o{ LOG_LINE : contains
    SESSION }o--|| PRESET : uses
    SESSION ||--o{ REPORT : produces
    PRESET ||--o{ RULE : defines
    FLOW }o--o| RULE : "matched by"
    FLOW |o--o{ LOG_LINE : "linked by request_id or time"

    SESSION {
        string id
        datetime started_at
        datetime ended_at
        string target "ios-device | ios-sim | android-device | android-emu"
        string device_name
        string app_version
        string tool_version
    }
    PRESET {
        string name
        string android_package
        string ios_process
        string api_hosts "list of hosts"
        string default_filter
    }
    RULE {
        string id
        string type "mock | status | delay | drop"
        string method
        string path_pattern
        int status
        int delay_ms
        string mock_file
        string apply "always | once | nth"
        bool enabled
    }
    FLOW {
        string id
        datetime ts
        string method
        string host
        string path
        int status
        int duration_ms
        string request_id
        string marked "mocked | fault | none"
    }
    LOG_LINE {
        datetime ts
        string source "android | ios | app"
        string level
        string tag
        string message
        string request_id
    }
    REPORT {
        string file
        datetime created_at
        string tracker_issue
    }
```

---

## 14. Delivery timeline

Durations are working days and approximate (1 developer).

```mermaid
gantt
    title Wiretrace delivery timeline
    dateFormat YYYY-MM-DD
    excludes weekends

    section Phase 0
    Evaluate mitmproxy, setup guide draft   :p0, 2026-10-19, 2d
    Test install on a standard (non-admin) account :p0b, after p0, 1d

    section Mobile dev team
    QA build changes R1–R7                  :dev, 2026-10-19, 3d

    section Phase 1
    Presets, allowlist, mocks, faults       :p1a, after p0b, 5d
    Log collectors + app-log receiver       :p1b, after p1a, 4d
    Launcher, sessions, report export       :p1c, after p1b, 4d
    Docs + IT packaging                     :p1d, after p1c, 2d
    Pilot with 2–3 QA engineers             :pilot, after p1d, 5d

    section Phase 2 (optional)
    Desktop app (Tauri + React)             :p2, after pilot, 25d
    Signing, notarization, Self Service     :p2b, after p2, 3d
```
