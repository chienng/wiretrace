# Spec: more devices on one port, port 8889, encrypted hosts, breakpoints, rewrite, map local, map remote

- **Summary**: four slices for QA who test several phones the way they use Charles.
  **A** — up to 4 phones share the Wi-Fi proxy port: the tester allows each one from spec 021's
  banner and can remove it again; the window shows the proxy address, the accepted devices by IP
  and a Device column. **B** — the default port becomes 8889 and the window can change it.
  **C** — connections Wiretrace does not decrypt show as Encrypted rows; one right-click adds
  their host to the preset's API hosts without a restart. **D** — a rule can pause a request or
  its response at a breakpoint, to edit it and continue or abort. **E** — a Rewrite rule changes
  headers and JSON fields of requests or responses without pausing. **F** — Map local from a
  request in Traffic: save its response as a mock file and answer with it. **G** — a Map remote
  rule sends matching requests to another server (not this Mac or the LAN). Rewrite and Map
  remote stack with other rules.
- **Date**: 2026-10-23
- **Repo**: wiretrace
- **Status**: approved (2026-10-23)
- **Tier**: L (A and B change who the Wi-Fi proxy accepts and on which port; C changes which
  hosts are decrypted; D holds live connections; F writes files; G sends requests, tokens
  included, to another server). Gates E, A, B, C, R, P. D n/a (one repo).
- **Branch**: `feature/accept-several-devices`, from `main` (`24c7e2f`, 0.9.1).
- **Mockups**: `mockups/README.md` section 10, screens 10a–10o
  (`mockups/proxy-and-breakpoints-mockup.html`).
- **Related**: spec 009 §2 (proxy accepts this Mac and the first other device); spec 013
  (`.switch.json`, preset editor, rules); spec 018 (device switch); spec 021 (banner, waiting
  list, client switch, invariants). Decision 2026-10-20 (two phones by listener port,
  `feature/two-phones`) is not built here; that branch used 8889 for Phone 2 and must pick
  another port if it is revived. Supersedes slice 1 of the unmerged
  `feature/022-multi-device-wifi-proxy` (accept every device while the window is open) and takes
  its device list, Traffic filter and per-device TLS count, with addresses instead of numbers.
  Both unmerged branches also number their spec 022; whichever merges after this one renumbers.

## Goal

QA test several phones at once, often with Charles open on the same Mac. In 0.9.1 the Wi-Fi
proxy on 8888 accepts this Mac and one other device per session; a second phone only gets in
by ending the session. Charles uses 8888 too. Hosts outside the preset's API hosts are invisible,
so QA cannot tell which host to add, and adding one restarts the session. There is no way to
hold a request and change it before the server or the app sees it, to change a header or a JSON
field on every matching request, to turn a response into a mock in one step, or to point an
endpoint at another server, all of which QA do daily in Charles (Breakpoints, Rewrite, Map
Local, Map Remote).

The proxy must stay closed to everyone else on a shared Wi-Fi: a device gets in only when it is
the first to connect (as today), or when the tester saw its address in the window and allowed it.

Version **0.10.0** once all seven slices are in (the default port changes). The slices can be
implemented, reviewed and merged one at a time, in the order A, B, C, D, E, F, G; E comes before
G because G relies on the rule order E introduces.

---

## Slice A — more devices on one port (screens 10a–10c)

### Acceptance criteria

- [ ] With `--ui wiretrace`, pinning on (mode `proxy` or `both`, no `--client`) and a device
      accepted, spec 021's banner shows **Allow…**, **Switch to it…** and **Ignore**. With one
      accepted device its text is unchanged; with more it ends "Accepted in this session:
      192.168.1.31, 192.168.1.42."
- [ ] The banner is hard to miss: solid amber with dark text, a phone icon and **Allow…** as
      the primary button, `role="alert"`. When an address appears that was not waiting before,
      the background pulses 3 times (1.2 s each) and then stays amber; with Reduce motion
      (`prefers-reduced-motion: reduce`) it does not pulse. It never blinks continuously.
      While devices are waiting, the tab title starts with their count, "(1) Wiretrace", and
      goes back to "Wiretrace" when none is.
- [ ] **Allow…** opens a dialog: "Allow the device at 192.168.1.63?", "It can use the Wi-Fi
      proxy until this session ends, like 192.168.1.31.", the warning "Any device on this
      network can ask. Check the address in the phone's Wi-Fi settings before you allow it.",
      and, when it is the 4th, "This session accepts 4 devices besides this Mac. This one is
      the last." **Cancel** changes nothing.
- [ ] **Allow** accepts that address within 1 s in the same session: the session folder, the
      other devices' connections and the device-log collector are untouched. The address
      leaves the waiting list; its next connection is accepted.
- [ ] At most **4** devices besides this Mac are accepted at any time. With 4, **Allow…** is
      disabled with the title "This session accepts 4 devices at most. Switch to it to start a
      session with only this device."
- [ ] The sidebar starts with a **Wi-Fi proxy** box in modes `proxy` and `both`: this Mac's
      address and port (`192.168.1.20:8889`), **Copy** and **Change…** (slice B). Below it,
      **Devices**: **All devices**, then each accepted device by its IP address in the order it
      was accepted, with its request count. Choosing a device filters Traffic to it and adds a
      removable chip with the address; choosing it again or **All devices** clears it. A device
      whose TLS handshakes with API hosts fail shows "⚠ N" and the title "Does not trust the
      certificate yet". With `--client`, the list shows the listed addresses that connected,
      without Allow or remove.
- [ ] Hovering a device row shows **×**; right-clicking it offers **Remove from this
      session…**. The dialog: "Remove 192.168.1.57 from this session?", "The Wi-Fi proxy
      refuses it from now on: its next requests fail. The requests it already made stay in
      Traffic.", "It can ask again: it then shows in the banner, where you can allow it. Still
      accepted: …". **Remove** applies within 1 s.
- [ ] After a removal the address is refused on new connections, and every further request on
      a connection it already has open is killed. Encrypted tunnels it opened before end when
      the phone closes them. Any accepted device can be removed, the first one included; its
      place becomes free. With no device left, no device is accepted automatically: each one
      has to be allowed from the banner.
- [ ] Traffic has a **Device** column right after Time, in modes `proxy` and `both`, live and in
      previous sessions: the client's IP address, "This Mac" for loopback (simulator,
      emulator), "WireGuard" for a tunnel client. The detail header shows "Device <address>".
- [ ] Setup's *Connect to this Mac* line and the device pill's tooltip list every accepted
      address: "Wi-Fi proxy: accepting 192.168.1.31, 192.168.1.42".
- [ ] **Switch to it…** behaves as in spec 021; its dialog names every device that will be
      refused. A device, preset, client or port switch, a restart, `--ui mitmweb`, `--no-ui`,
      `--client` and mode `wireguard` behave as in 0.9.1: the next session starts with nothing
      allowed.
- [ ] Allow and remove requests are refused with 409 and change nothing: while a previous
      session is open, while a switch is in flight, without pinning (`--client`, mode
      `wireguard`), an allow for an address not in the waiting list or with 4 accepted, a remove
      for an address not accepted. A value that is not an IP address, or one a session may not
      pin (loopback, link-local, unspecified, multicast), is refused with 400.
- [ ] The Terminal line printed at the first refusal has no address: "Proxy: refused a
      connection from a device this session does not accept. Allow it in the Wiretrace window,
      restart Wiretrace, or pass --client <its IP address>."
- [ ] No accepted, allowed, removed or waiting address is written to `meta.json`,
      `.status.json`, the Terminal, the menu bar, `flows.har` or a bug report.

### Approach

1. `addons/proxy_guard.py`
   - `MAX_ACCEPTED = 4`. `pinned` stays; `allowed: list[str]` keeps the order; `accepted()`
     returns `[pinned, *allowed]` without `None`. `pin_used: bool` becomes true when the first
     device is pinned (or `qa_proxy_pinned` is set) and never goes back.
   - `client_connected`: accept a listed or accepted address; pin the first other address only
     while `pin_used` is false; otherwise refuse and record, as today.
   - `allow(address) -> str | None` and `remove(address) -> str | None`: `None` on success,
     otherwise the reason. Checks are in the design section. `remove` drops the address from
     `pinned` or `allowed` (`pinned` becomes `None` when it was the pinned one).
   - `requestheaders(flow)`: on the regular listener, a client that is neither listed nor
     accepted gets `flow.kill()`. Only a removed device's open connections reach this.
   - New `REFUSAL` text; docstring describes allow, remove and `pin_used`.
2. `addons/client_stats.py` (new; adapted from the 022 branch's `client_slots.py`): per accepted
   address, first seen, request count and TLS failures. `payload(accepted)` returns
   `{address, seen_at, requests, tls_failures}` in `accepted()` order.
3. `addons/wiretrace_ui.py`
   - `POST /api/proxy/allow` and `POST /api/proxy/remove`, body exactly `{"client": <string>}`,
     behind the usual token, cookie, Host and `X-Wiretrace` checks. Checks in invariant 3's
     order, then the guard; success is 200 `{"accepted": [...]}` and an immediate state push.
   - State gains `proxy_clients` (the payload; empty unless pinning is on or `--client` is used,
     and the live session is shown), `proxy_max` (4) and `proxy_address` (`mac_ip:port`, null in
     mode `wireguard`).
   - Flow summaries, live and previous, carry `client`: the normalized peer address, `"mac"`
     for loopback, `"wireguard"` for a WireGuard client, or null.
   - `client_connected` and `tls_failed_client` feed `client_stats` for accepted clients.
4. Window
   - `ui/src/logic/proxyDevices.ts`: banner text with several addresses, `allowState`,
     `removeText`, dialog texts, `acceptingLine` and `switchLead` with a list.
   - New `ui/src/components/AllowDeviceDialog.tsx` and `RemoveDeviceDialog.tsx` on `Modal`;
     `ProxyDeviceBanner.tsx` gets **Allow…**, the amber style and the pulse, restarted only
     when the set of waiting addresses gains one; `document.title` carries the waiting count.
   - `ui/src/components/Sidebar.tsx`: the Wi-Fi proxy box, the device list, × on hover, the
     right-click menu.
   - `ui/src/logic/filters.ts`: `client` filter and chip (from the 022 branch, by address);
     `ui/src/store.tsx`: `client` in the UI state, reset when a session is opened or closed.
   - `ui/src/components/TrafficList.tsx`: the Device column; `DetailPanel.tsx`: "Device" in the
     header; `TrafficView.tsx`: chip removal.
   - `ui/src/api.ts`, `ui/src/types.ts`.

Rejected:
- **Accept every device while the window is open** (022 branch, slice 1): undoes spec 009 §2 on
  a shared Wi-Fi.
- **Accept the Mac's own subnet automatically**: on an office or café Wi-Fi that is everyone.
- **A second port per phone** (decision 2026-10-20): each phone has to move to its own port, and
  it stops at two.
- **Allow or remove without a dialog**: the confirm step keeps spec 021's rule that a new address
  comes only from a refusal the tester saw and confirmed.
- **Re-pin the next device once the list is empty**: removing everyone would reopen the proxy to
  whoever connects first.
- **Device numbers instead of addresses** (022 branch): the tester has to map numbers back to
  phones; the address is what the phone's Wi-Fi settings show.

### Design that needs care

The accepted list is the Wi-Fi proxy's access control. This slice replaces spec 021's
invariant 1.

#### Invariants

1. With pinning on, a session accepts this Mac and at most `MAX_ACCEPTED` (4) other addresses at
   any time.
2. An address becomes accepted in only three ways: it is the first to connect while `pin_used`
   is false (spec 009); it is `qa_proxy_pinned` at start (spec 021); `allow` accepts it while it
   is in the waiting list. `pin_used` never goes back to false, so the first way happens at most
   once per process.
3. The window calls `allow` or `remove` only after these checks, in this order: no previous
   session open; no switch in flight; pinning on and mode not `wireguard`; the client parses as
   an IP address; it passes `pinnable`; then, for allow, the normalized address is in the
   waiting list and fewer than 4 are accepted; for remove, it is accepted. There is no `await`
   between the first check and the guard call: the window's HTTP server and mitmproxy's hooks
   share one event loop.
4. `allow` and `remove` re-check their own conditions and never trust the caller. They are the
   only code that changes `allowed`, and `remove` the only code that clears `pinned`.
5. A removed address is refused by `client_connected` and its flows are killed by
   `requestheaders` from the moment `remove` returns. A refused address is recorded in the
   waiting list, so it can be allowed again.
6. Addresses live in process memory and are dropped with it. They reach only the window's
   token-protected API and WebSocket (spec 021 invariant 5); flow summaries read the peer address
   from the flow, which `flows.mitm` already holds.
7. Every next session starts with spec 021's rules and an empty `allowed`.
8. WireGuard clients are never accepted, refused, allowed, removed, killed or counted here.

#### Tests derived from the invariants

- proxy_guard: `allow` accepts a waiting address, which then connects; refusals (pinning off,
  not `pinnable`, already accepted, not waiting, 4 accepted) change nothing. `remove` of the
  pinned and of an allowed address; the removed address is refused and recorded as waiting;
  `requestheaders` kills its flow and leaves an accepted client's alone; after removing every
  device the next new address is refused, not pinned; a place freed by `remove` can be allowed.
  WireGuard clients untouched. `REFUSAL` has no address.
- window API: each 409/400 in invariant 3's order (a previous session open wins over a bad
  address); IPv4-mapped IPv6 matches its IPv4 form; extra or missing keys are 400; two allows
  when 3 are accepted give one 200 and one 409; success pushes state.
- state and summaries: `proxy_clients` empty without pinning or `--client`, in mode `wireguard`
  and in a previous session; `client` is `mac` for loopback and `wireguard` for a tunnel client.
- privacy: after allow and remove, `meta.json`, `.status.json`, the Terminal output,
  `flows.har` and a bug report contain none of the addresses.
- next session: after an allow, each kind of switch starts with `allowed` empty.
- window logic: banner text with one and several addresses; Allow disabled at 4; dialog texts;
  pulse restarts for a new waiting address but not for a repeat push of the same one; tab
  title with 0, 1 and 2 waiting;
  `applyFilters` with `client`; Device column text for an address, `mac`, `wireguard`, null.

### Files expected to change

`addons/proxy_guard.py`; `addons/client_stats.py` (new); `addons/wiretrace_ui.py`;
`ui/src/api.ts`, `types.ts`, `store.tsx`; `ui/src/logic/proxyDevices.ts`, `filters.ts` and their
tests; `ui/src/components/ProxyDeviceBanner.tsx`, `AllowDeviceDialog.tsx` (new),
`RemoveDeviceDialog.tsx` (new), `Sidebar.tsx`, `TrafficList.tsx`, `TrafficView.tsx`,
`DetailPanel.tsx`, `SwitchDeviceDialog.tsx`; `ui/src/styles.css`; `ui/dist/`;
`tests/test_proxy_guard.py`, `tests/test_client_stats.py` (new), `tests/test_wiretrace_ui.py`;
`docs/user-guide.md`.

---

## Slice B — port 8889, and changing it from the window (screens 10f, 10g)

### Acceptance criteria

- [ ] With no saved port and no `--port`, the Wi-Fi proxy listens on **8889**. The Terminal
      banner, Setup, the sidebar box, `./wiretrace doctor` (port check and the firewall advice),
      `--help`, the README and the user guide say 8889. WireGuard stays on UDP 51820.
- [ ] `./wiretrace start --port N` listens on N for that run and does not save it.
- [ ] **Change…** in the sidebar box and **Change port…** in Setup's *Connect to this Mac* step
      open a dialog: the port field, "1024–65535. Not 8081 (this window) or a port another app
      uses.", a line saying whether the typed port is free, and "This session is saved and a new
      one starts on port N. Then set the Wi-Fi proxy on every phone to <Mac IP>:N. Wiretrace
      keeps this port for the next sessions." **Change port and restart** is enabled only for a
      valid, free port that differs from the current one.
- [ ] Confirming saves the session the way spec 018 does and starts a new one with the same
      preset, target, mode and `--from-app` on the new port. The port is saved for the next
      `start` and for Wiretrace.app.
- [ ] Refused with 400 and nothing changed: not an integer, outside 1024–65535, 8081, 51820, the
      current port. Refused with 409: a previous session open, a switch in flight, mode
      `wireguard`, the port in use. If the port is taken between the dialog and the restart,
      Wiretrace ends with the message today's busy-port check prints.
- [ ] The release notes and the user guide tell existing testers to set their phones to 8889,
      or to change the port back to 8888 in the window.

### Approach

1. `cli/start.py`: `PROXY_PORT = 8889`. `proxy_port(wiretrace_dir, override)` returns `--port`,
   else a valid `.proxy-port`, else 8889. `.switch.json` gains a third shape
   `{name, target, proxy_port}`; the loop re-validates it (invariant 2), runs the busy check,
   writes `.proxy-port` (0600, atomic replace, one integer), then spawns on the new port. A
   switch without `proxy_port` keeps the current port.
2. `cli/__main__.py`: `--port` on `start`; help text says 8889. `cli/app.py` starts with the
   saved port (it calls `start` without `--port`). `cli/doctor.py`: checks and advises the port
   `proxy_port` returns.
3. `addons/wiretrace_ui.py`: `GET /api/proxy/port-check?port=N` (validation, then a TCP bind
   test on `0.0.0.0:N`, closed at once) and `POST /api/proxy/port` `{"port": N}` (the same
   checks, then `start_switch` with `proxy_port`); the fallback `8888` becomes the option value.
4. Window: `ui/src/components/ChangePortDialog.tsx` (new), `ui/src/logic/port.ts` (validation
   texts) and test, entry points in `Sidebar.tsx` and `SetupWizard.tsx`; `api.ts`, `types.ts`.

Rejected: keep 8888 (it collides with Charles on the same Mac); change the port live inside the
running process (the banner, the status file, the menu bar and the busy check all assume one
port per run; a restart is the tested path); a port per preset (phones are set up once per Mac,
not per project).

#### Invariants

1. A session listens on exactly one Wi-Fi proxy port for its whole life.
2. The launcher re-checks a port from `.switch.json` (integer, 1024–65535, not the UI or
   WireGuard port) before it writes `.proxy-port` or spawns; a failed check ends Wiretrace with a
   message (spec 013, invariant 3).
3. `.proxy-port` is written only after the check and the busy check pass; an unreadable or
   invalid file means 8889.
4. Spec 013, 018 and 021 switch invariants hold: one switch in flight, a stop signal wins,
   `.switch.json` is read once and deleted.

#### Tests

`take_switch` with the three shapes, an extra key, a non-integer port; the re-check refuses each
bad port; `.proxy-port` written only after a successful check, 0600; `proxy_port` precedence
(`--port` > file > 8889) and an invalid file; doctor uses the resolved port; window API 400/409
cases in order; port-check reports a bound port as in use; `port.ts` texts.

### Files expected to change

`cli/start.py`, `cli/__main__.py`, `cli/app.py`, `cli/doctor.py`, `addons/wiretrace_ui.py`;
`ui/src/components/ChangePortDialog.tsx` (new), `Sidebar.tsx`, `SetupWizard.tsx`;
`ui/src/logic/port.ts` (new) and test; `ui/src/api.ts`, `types.ts`; `ui/dist/`;
`tests/test_start.py`, `tests/test_app.py`, `tests/test_doctor.py`, `tests/test_wiretrace_ui.py`;
`README.md`, `docs/user-guide.md`.

---

## Slice C — encrypted hosts, and decrypting one from the window (screens 10d, 10e)

### Acceptance criteria

- [ ] With `--ui wiretrace`, each connection Wiretrace passes through without decrypting (its
      host is not an API host) appears in Traffic as a grey row: method `CONNECT` (Wi-Fi proxy)
      or `TLS` (WireGuard), the Device column, a 🔒 status, host and port in the path column,
      the time it opened, how long it stayed open ("open" while it is), no size, and the tag
      **Encrypted**. A passed-through connection that is not TLS is tagged **Passed through**.
- [ ] The host is the CONNECT target on the Wi-Fi proxy, the TLS server name (SNI) on WireGuard,
      and the IP address when neither is known. Wiretrace's own hosts (`qa-logs.internal`,
      `mitm.it`) are never listed.
- [ ] The sidebar's quick filters gain **Encrypted** with its count; the filter bar gains **Show
      encrypted** (on by default, remembered by the browser). Search and the host filter match
      encrypted rows by host.
- [ ] Selecting an encrypted row shows: "Not decrypted", "<host> is not one of the API hosts of
      preset <name>, so Wiretrace passes this connection through without reading it. Decrypt the
      host to see its requests and responses.", **Decrypt this host…**, the CONNECT request
      headers the phone sent (Wi-Fi proxy only; `Proxy-Authorization` is masked), and the answer
      line.
- [ ] Right-clicking an encrypted row offers **Decrypt <host>…** and, when the parent domain is
      allowed, **Decrypt <parent>…** (both "and subdomains"), **Copy host**, **Show only
      <host>**, **Hide encrypted connections**.
- [ ] The Decrypt dialog offers the host and its parent domain, says the choice is added to the
      API hosts of the preset in use and applied now, that open connections stay encrypted until
      the app opens new ones, and that an app pinning its certificates fails these requests.
      **Decrypt** writes the preset file and, within 1 s, new connections to that host and its
      subdomains are decrypted in the same session: their requests appear as normal rows and
      rules apply to them.
- [ ] Refused with 409 and nothing changed: a previous session open, a switch in flight, the
      preset is the `example` template, the host is already covered, the preset already has 50
      API hosts, the file changed since the window read it. Refused with 400: not a valid host
      name, a parent domain that is not offered. If the file is saved but the running session
      cannot apply it, the window says "Saved. Restart the session to decrypt <host>."
- [ ] Encrypted rows live in memory for the live session only, at most 2,000 (the oldest are
      dropped). They are not in `flows.mitm`, `flows.har`, a bug report, the menu bar counts or a
      previous session.

### Approach

1. `addons/tunnels.py` (new): a bounded list of passthrough connections. `next_layer` (scripts
   run after mitmproxy's own `NextLayer`, so the decision is made) records a connection whose
   layer is mitmproxy's passthrough TCP layer: client connection id, device, host, port, TLS or
   not, opened at. The host comes from the CONNECT flow (`http_connect`, which also gives the
   headers) or from the ClientHello mitmproxy peeked (`parse_client_hello` on the client's first
   bytes). `client_disconnected` / `server_disconnected` set the close time. No payload is read
   or kept.
2. `addons/wiretrace_ui.py`: pushes tunnel rows on the WebSocket as `tunnels` messages, batched
   like flows; `GET /api/tunnels` for a reload; `POST /api/api-hosts` `{"host"}`: the checks
   above, then under `preset_lock` read the preset file, append the host, write it with the
   revision check (spec 013's helpers), then `ctx.options.update(allow_hosts=…, qa_api_hosts=…)`
   with the full lists.
3. `cli/start.py`: `allow_hosts_args(preset)` returns the `allow_hosts` list the launcher passes
   today (API hosts, receiver, onboarding); the window builds the live update from the same
   function, so a live update and a restart produce the same list.
4. `cli/preset.py`: `decrypt_choices(host)`: the host and its parent domain when the parent has
   at least two labels and is not a two-label name whose first label is a common second-level
   suffix (`co`, `com`, `net`, `org`, `gov`, `edu`, `ac`).
5. Window: `ui/src/types.ts` (`TunnelRow`), `store.tsx` (tunnel rows, `showEncrypted`),
   `logic/filters.ts` (quick filter `encrypted`, rows merged by time), `TrafficList.tsx` (grey
   rows, context menu), `DetailPanel.tsx` (the encrypted detail), `DecryptHostDialog.tsx` (new),
   `Sidebar.tsx` (quick filter), `logic/hosts.ts` (choices, texts) and test.

Rejected: keep passthrough connections as TCP flows in `flows.mitm` (every byte of every other
app's traffic on disk); decrypt everything and hide non-API rows (breaks pinned apps and system
services on the phone); apply a new host by restarting the session (the in-use preset save does
that today; this one only appends a host, and mitmproxy reads `allow_hosts` per connection).

#### Invariants

1. Nothing in this slice reads, stores or forwards the payload of a passthrough connection; a
   row holds host, port, device, times and the CONNECT headers.
2. Tunnel rows exist only in process memory and only the window's token-protected API and
   WebSocket see them.
3. The running session's `allow_hosts` and `qa_api_hosts` change only after the preset file was
   written, and only to the lists `allow_hosts_args` builds from that file.
4. A decrypt request never removes a host, and never touches a preset other than the one in use.

#### Tests

tunnels: a passthrough connection is recorded with the CONNECT host, a WireGuard one with the
SNI, one with neither with the IP; Wiretrace's own hosts are skipped; close time set; the list is
capped at 2,000; no payload attribute exists. Window API: each refusal in order; a successful
decrypt writes the file then updates both options with `allow_hosts_args`' list; an options error
after the write returns the "Saved. Restart…" message; `Proxy-Authorization` is masked.
`decrypt_choices`: `cdn.example.net` → itself and `example.net`; `cdn.example.co.uk` → itself and
`example.co.uk`, never `co.uk`; `example.net` → itself only. Privacy: tunnel hosts are absent from
`flows.mitm`, `flows.har` and a bug report. Window logic: merge order, quick filter, toggle.

### Files expected to change

`addons/tunnels.py` (new), `addons/wiretrace_ui.py`, `cli/start.py`, `cli/preset.py`;
`ui/src/types.ts`, `store.tsx`, `api.ts`, `logic/filters.ts`, `logic/hosts.ts` (new) and tests,
`components/TrafficList.tsx`, `DetailPanel.tsx`, `DecryptHostDialog.tsx` (new), `Sidebar.tsx`,
`TrafficView.tsx`; `ui/src/styles.css`; `ui/dist/`; `tests/test_tunnels.py` (new),
`tests/test_wiretrace_ui.py`, `tests/test_preset.py`; `docs/user-guide.md`.

---

## Slice D — breakpoints (screens 10h–10j)

### Acceptance criteria

- [ ] The rule editor's action list gains **Pause at a breakpoint**, with **Pause**: *The
      request*, *The response* or *Both*. It matches and applies (always, once, every Nth) like
      any rule and takes part in the rule order: like any rule, it ends the search.
- [ ] With `--ui wiretrace` and a window open, a request a pause rule matches waits before it is
      sent (or its response waits before the app gets it). Its row turns orange with a
      **PAUSED** tag and its waiting time; the title bar shows "⏸ N paused" with **Continue
      all**.
- [ ] Selecting a paused request opens **Edit request**: method, path and query, headers, and the
      body as text; Host, Content-Length and Transfer-Encoding are shown but not editable.
      **Original** shows it as it arrived; **Undo edits** restores it. A paused response offers
      status, headers and the body as text. A body that is binary or larger than 1 MiB decoded
      is not editable ("Body not editable: binary" or "…: over 1 MiB").
- [ ] **Continue** (or **Send to app** for a response) sends it with the edits. **Abort** kills
      it: the app sees a network error. **Continue all** continues every paused request
      unchanged.
- [ ] After 20 s paused the row and the editor say "Apps usually give up after 30–60 s".
- [ ] At most **10** requests are paused at once; a match beyond that passes through unpaused with
      the comment "breakpoint: not paused, 10 already paused". Replays and WebSocket messages are
      never paused.
- [ ] No pause happens with `--ui mitmweb`, `--no-ui` or no window open; such a match passes
      through with "breakpoint: not paused, no window". When no window has been connected for
      30 s, every paused request continues unchanged.
- [ ] Stopping the session, or any switch, aborts every paused request before the session is
      saved.
- [ ] A request paused at a breakpoint keeps "breakpoint: request" or "breakpoint: response" in
      its comment, plus "edited" when it changed; its row shows **EDITED**, and the comment
      reaches the HAR and the bug report as comments do today.
- [ ] Edits are refused with 409 when the request is no longer paused (continued, aborted, the
      app left) or another tab changed it first (revision), and with 400 for an invalid method,
      a path that does not start with `/`, a header name or value with a line break, an edit to
      a fixed header, a status outside 100–599, or a body for a non-editable one.

### Approach

1. `addons/qa_tools.py`: action `pause` with action key `pause_at` (`request`, `response`,
   `both`); `delay_ms` must be 0. Option `qa_breakpoints` (bool; the launcher sets it with `--ui
   wiretrace`). In `request`, a picked pause rule calls `flow.intercept()` when pausing is
   allowed (option on, the window addon's `pause_allowed()` true, fewer than 10 paused); it
   records the phase in `flow.metadata["wiretrace_pause"]` for the response hook. mitmproxy holds
   an intercepted flow until `flow.resume()` or `flow.kill()`.
2. `addons/wiretrace_ui.py`: a paused registry (`flow id → phase, since, revision, original
   copy`); flow summaries carry `paused` and `paused_since`; state carries `paused_count`.
   `POST /api/flows/<id>/breakpoint` `{"action": "continue"|"abort", "edits": {…}|null,
   "revision": n}` and `POST /api/breakpoints/continue-all`. `pause_allowed()` is true while a
   page is connected. The flush loop runs the 30 s watchdog; `done()` and `start_switch` abort
   every paused flow first.
3. `cli/start.py`: `--set qa_breakpoints=true` with `--ui wiretrace`.
4. Window: `logic/rules.ts` and `RuleEditor.tsx` (the action and its phase), `RulesView.tsx`
   (list text), `BreakpointEditor.tsx` (new) inside `DetailPanel.tsx`, `TitleBar.tsx` (count and
   Continue all), `TrafficList.tsx` (paused rows, EDITED tag), `logic/breakpoint.ts` (validation,
   texts, timer) and test, `api.ts`, `types.ts`.

Rejected: a separate breakpoint list outside the rules (two matchers to learn and test; rules
already have match, order and apply modes); pause without a window (nobody can continue it); no
limit (a matching rule on a chatty endpoint would hold the whole app).

#### State machine (one flow, one phase)

```
            pause rule matches, pausing allowed
  (none) ─────────────────────────────────────▶ PAUSED ──edit (revision+1)──┐
                                                 │  ▲─────────────────────────┘
       Continue / Continue all / watchdog        │        Abort / stop / switch
            ┌────────────────────────────────────┼──────────────────────────────┐
            ▼                                     │ app left (error hook)         ▼
       CONTINUED ── phase was "both" and         ▼                           ABORTED
                    response arrives ──▶ PAUSED (response)   GONE
```

#### Invariants

1. At most 10 flows are PAUSED at any time.
2. A flow leaves PAUSED exactly once per phase, to CONTINUED, ABORTED or GONE; any action on a
   flow that is not PAUSED is a 409 and changes nothing.
3. An edit applies only in PAUSED and only with the current revision; each edit raises it.
4. Every PAUSED flow is continued or aborted before the process exits or a switch shuts it down.
5. No flow is paused while no window is connected; after 30 s without one, all PAUSED flows are
   continued unchanged.
6. Edits never change the scheme, host or port: the request still goes to the API host it was
   sent to, and `proxy_guard`'s server checks still run.
7. Pausing, editing and resuming run on mitmproxy's event loop; no lock is held while a flow
   waits.

#### Tests

qa_tools: a pause rule intercepts at the request, at the response, at both; the 11th match passes
with its comment; replays and WebSocket messages are not paused; no window or option off passes
with its comment; `delay_ms` with `pause` is a rule error. Window API: continue, abort, continue
all; 409 on a flow that is not paused and on a stale revision; each 400 case; edits applied
(method, path, headers, text body, status) and fixed headers refused; the watchdog continues after
30 s without a page; `done()` and a switch abort paused flows. Comments: "breakpoint: request
edited" reaches the HAR. Window logic: validation texts, the 20 s hint, non-editable bodies.

### Files expected to change

`addons/qa_tools.py`, `addons/wiretrace_ui.py`, `cli/start.py`; `ui/src/logic/rules.ts`,
`logic/breakpoint.ts` (new) and tests; `ui/src/components/RuleEditor.tsx`, `RulesView.tsx`,
`DetailPanel.tsx`, `BreakpointEditor.tsx` (new), `TitleBar.tsx`, `TrafficList.tsx`;
`ui/src/api.ts`, `types.ts`, `styles.css`; `ui/dist/`; `tests/test_qa_tools.py`,
`tests/test_wiretrace_ui.py`, `tests/test_start.py`; `docs/user-guide.md`.

---

## Rule order with change rules (slices E and G)

Slices E and G add two actions that **change** a request instead of answering it: **Rewrite**
and **Map remote**. They stack; every other action **answers** (mock, status, delay, drop,
pause) and still ends the search.

1. Rules are walked in order. Every enabled rule that matches has its match counted, as today.
2. A matching change rule whose apply mode says so is collected. Only the first collected Map
   remote takes effect; a later Map remote that matches is counted but not applied.
3. The first matching answer rule that applies ends the walk.
4. If the request is then answered without the server (a mock or status rule, a drop, a fault, a
   mock file from `mocks/<preset>/<METHOD>/…`), the collected change rules are **not** applied
   and not counted as applied. Otherwise (no answer rule, a delay, a pause) they are applied in
   rule order: Map remote first, then request rewrites; response rewrites when the response
   arrives.
5. A rules file without change rules behaves exactly as in 0.9.1.

The rule list says so in its header: "Map remote and Rewrite rules apply in order. Then the first
other rule that matches answers." Change rules show a **Changes** label in the list; answer rules
show **Answers**.

---

## Slice E — Rewrite: change headers and JSON fields without pausing (screens 10k, 10m)

### Acceptance criteria

- [ ] The rule editor's action list gains **Rewrite**. A Rewrite rule has 1–20 changes; each is
      one row: **On** (*Request* or *Response*), **Change** and its fields:
  - *Set header* (name, value): replaces every value of that header, or adds it.
  - *Add header* (name, value): adds one more value.
  - *Remove header* (name).
  - *Set JSON field* (path, value): `data.user.isPremium` = `true`. The path uses `.` between
    keys and `[n]` for array items (`items[0].price`), or `["a.b"]` for a key with a dot. The value
    is JSON: `true`, `12`, `"text"`, `null`, `{"a": 1}`.
  - *Remove JSON field* (path).
- [ ] Save refuses, with the field named: a header name that is not a token or is one of Host,
      Content-Length, Transfer-Encoding, Connection, Keep-Alive, TE, Trailer, Upgrade, or starts
      with `Proxy-` or `:`; a value with a line break or NUL, or over 4,096 characters; a path
      that does not parse, over 20 parts or 256 characters; a value that is not JSON or over
      64 KiB; a delay with Rewrite.
- [ ] Request changes apply before the request is sent; response changes before the app gets
      the response. A JSON change applies when the body is JSON (a `json` Content-Type, or text
      that starts with `{` or `[`) and at most 1 MiB decoded; Content-Encoding is kept and
      Content-Length follows. *Set JSON field* adds a missing last key to an object but never
      creates a parent or an array item; a missing parent or item, or a body that is not JSON,
      skips that change and says so in the Changes tab ("not found", "body is not JSON").
- [ ] A rewritten JSON body is written back compactly: spacing and number spelling may change
      (`1.50` becomes `1.5`); key order is kept.
- [ ] A rewritten request shows a **REWRITTEN** tag. Its comment gains "rewrite: <rule name>
      (N changes)", so it reaches the HAR and the bug report like other comments; the comment
      never holds a header value or a JSON value. The detail gains a **Changes** tab: each
      change as applied or skipped, the values of `authorization`, `cookie`, `set-cookie`,
      `proxy-authorization` and `x-api-key` shown masked.
- [ ] The Request and Response tabs show what was sent and received after the changes. A
      breakpoint (slice D) on the same request sees the rewritten version; its **Original**
      shows the message before any change.

### Approach

1. New `addons/rewrite.py`, no mitmproxy state: `parse_ops(raw) -> (ops, error)`,
   `parse_path(text)`, `apply_header_ops(headers, ops) -> list[ChangeResult]`,
   `apply_json_ops(text, ops) -> (text | None, list[ChangeResult])`. Pure functions, unit tested
   on their own.
2. `addons/qa_tools.py`: action `rewrite` with action key `ops`; the walk in "Rule order with
   change rules" replaces `pick_rule` with `pick_rules(rules, flow) -> (changes, answer)`. Request
   ops apply in `request` after the answer is known; response ops are kept in
   `flow.metadata["wiretrace_rewrite"]` (rule names and ops, never values from the flow) and
   applied in `response` for responses from a server (no `MOCK_MARK` or `FAULT_MARK`). Applied
   and skipped results go to `flow.metadata["wiretrace_changes"]` for the window.
3. Missing action keys default (`ops` to `[]`), so a 0.9.1 rules file loads unchanged. A file
   saved with a Rewrite rule is refused by 0.9.1 (unknown key), which is acceptable for a minor
   version; the user guide says so.
4. `addons/wiretrace_ui.py`: summaries carry `rewritten`; the detail carries `changes`; the
   breakpoint's original copy is taken before request changes, and before response changes.
5. Window: `logic/rules.ts` (action, ops, validation mirroring `rewrite.py`), `RuleEditor.tsx`
   (the change rows), `RulesView.tsx` (header text, Changes/Answers labels), `TrafficList.tsx`
   (tag), `DetailPanel.tsx` (Changes tab), `types.ts`.

Rejected: find-and-replace on raw body text (user chose header and JSON changes; text replace
breaks JSON quoting silently); regex paths like JSONPath `$..price` (one exact path is easy to
read and test); changing the status by rule (a status rule already answers with one).

#### Invariants

1. A rules file without Rewrite or Map remote rules gives the same answer, the same counters and
   the same comments as 0.9.1 for every request.
2. Change rules apply only to a request that goes to a server; a request answered by Wiretrace
   is never rewritten, and their applied counters do not move for it.
3. No change touches Host, Content-Length, Transfer-Encoding, connection headers or pseudo
   headers.
4. A JSON change never writes a body that does not parse: on any failure the body is left as it
   was and the change is reported skipped.
5. Values from the flow and values typed into a change never reach the comment, the logs, the
   status file or `meta.json`.

#### Tests

rewrite.py: each op on headers (case-insensitive names, several values); paths with dots,
indexes, quoted keys; set on a missing last key adds it; missing parent and out-of-range index
skip; remove missing is skipped; non-JSON and over-1-MiB bodies skip; gzip body stays gzip;
every refused name and value. qa_tools: the order rules 1–5 (stacking, first Map remote only,
answer ends the walk, answered requests skip changes and keep counters), invariant 1 against the
existing rules fixtures, response ops not applied to a mock. Window API: `changes` in the detail,
masked values, the comment text. Window logic: validation texts, Changes tab text.

---

## Slice F — Map local from a request (screen 10n, 10o)

Map local already exists: a **Mock** rule answers with a file from `mocks/<preset>/` or a typed
body, and a file at `mocks/<preset>/<METHOD>/<path>.json` answers on its own. This slice makes one
from a request in Traffic.

### Acceptance criteria

- [ ] A request with a response gets **Map local…** in the detail (next to **Copy as mock**) and
      in a new right-click menu on request rows (**Map local…**, **Copy as mock**, **New rule
      from this request**, **Replay**, **Copy cURL**). It is disabled, with the reason as a
      tooltip, while viewing a previous session, for a response that is binary or over 1 MiB
      decoded, and for a request still in flight.
- [ ] The dialog shows: **File** — `mocks/<preset>/` then an editable name, by default
      `saved/<METHOD>_<path>.json` (path without the query, `/` as `_`, at most 120
      characters); **Status**, the response's; **Body**, editable, pretty-printed when JSON;
      and **Answer with it now**, on by default, which adds the rule "Map local GET
      /api/v1/profile": method, host and path of the request, action Mock with that file and
      status, always, **at the top of the rules**.
- [ ] A warning says: "The file keeps the response as it is, tokens and personal data included.
      Edit them out before you share the mocks folder."
- [ ] **Save and map** writes the file (created 0600, folders 0700), then the rule. When the
      file exists, the dialog asks **Replace** first. The name is refused unless every part is
      1–80 of `A–Z a–z 0–9 . _ -`, no part starts with `.`, and it ends `.json`; the body over
      1 MiB, a status outside 100–599, and a file that would leave `mocks/<preset>/` (symlinks
      included) are refused.
- [ ] With **Answer with it now** off, only the file is written; a name under
      `<METHOD>/…` then answers through the existing mock-file mapping, which the dialog says.
- [ ] The next matching request is answered from the file, tagged **MOCK**, with
      "mock: saved/GET_api_v1_profile.json" in its comment.

### Approach

1. `addons/wiretrace_ui.py`: `POST /api/flows/<id>/map-local` `{"file", "status", "body",
   "rule": bool, "replace": bool, "revision"}`. In one synchronous step on the event loop (no
   `await` in between): check the rules revision when `rule`, check the name, resolve it with
   `resolve_mock`'s rule, refuse 409 `{"exists": true}` without `replace`, write the file through
   a temporary file and `os.replace`, then insert the rule and save through `save_rules`. A
   failure after the file write reports "File saved; the rule was not added: …".
2. `qa_tools.py`: `mock_dir_for_write(name) -> Path | None`, the write-side twin of
   `resolve_mock` (it may create folders, never follows a symlink out).
3. Window: `logic/mapLocal.ts` (default name, validation, texts) and test,
   `MapLocalDialog.tsx` (new) on `Modal`, `TrafficList.tsx` (row menu), `DetailPanel.tsx`
   (button), `api.ts`.

Rejected: files anywhere on the Mac (spec 009 keeps mocks inside the preset's folder); naming
the file `<METHOD>/<path>.json` by default (it would answer on its own, even with the rule
switched off).

#### Invariants

1. Wiretrace writes only inside `mocks/<preset>/`, never through a symlink, never over an
   existing file without **Replace**.
2. The rule is added only against the rules revision the dialog loaded; a stale revision is a
   409 before anything is written.
3. The file and its contents are never in logs, the status file or a bug report.

#### Tests

Window API: default and edited names; each refused name (`..`, leading dot, absolute, other
extension, a symlinked folder that leads out); exists → 409 then replace; stale revision → 409
and no file; rule inserted first and answering the next request; rule off → file only. Window
logic: default name from method and path (query dropped, long paths cut), disabled reasons.

---

## Slice G — Map remote: send matching requests to another server (screens 10l, 10m)

### Acceptance criteria

- [ ] The rule editor's action list gains **Map remote**, with **To**: scheme (*https* or
      *http*), host and port (default 443 or 80). A preview shows the result for the rule's path:
      `https://api.example.com/api/v1/orders` → `https://staging-api.example.com/api/v1/orders`.
      Path and query are kept.
- [ ] Save refuses a host that is not a DNS name or IP literal, `localhost`, a name ending
      `.localhost` or `.local`, an IP literal that is loopback, private (10/8, 172.16/12,
      192.168/16), shared (100.64/10), link-local, unique-local (fc00::/7), unspecified or
      multicast; a port outside 1–65535; a target equal to the matched host and port; a delay
      with Map remote. The editor says: "Not this Mac or addresses on your network."
- [ ] The editor warns: "The app's tokens and cookies go to this server too." With *http* it
      adds: "Plain HTTP: anyone on the network path can read it."
- [ ] A mapped request goes to the target with Host (or `:authority`) set to the target; the
      server's certificate is checked as for any request. When the target resolves to an address
      the save rule refuses, or to one of this Mac's addresses, the request is not sent: the
      app gets 502 "Wiretrace refuses Map remote to an address on your network" and the comment
      gains "map remote: refused, local address". This holds for every device, this Mac included.
- [ ] A mapped request shows a **MAPPED** tag. Traffic, the Hosts list and filters keep the host
      the app asked for; the detail adds "Sent to **https://staging-api.example.com**"; the
      comment gains "map remote: api.example.com → staging-api.example.com", so the HAR and the
      bug report show it.
- [ ] Map remote does not apply to WebSocket handshakes. A replay of a mapped request goes to
      the server it was sent to.

### Approach

1. `addons/qa_tools.py`: action `map_remote` with action key `target` (`{"scheme", "host",
   "port"}`, default empty); `parse_target` validates at load. When applied: resolve the host
   (`proxy_guard.resolve`), refuse as above, otherwise set `flow.request.scheme`, `.host`,
   `.port` (mitmproxy updates Host and authority and opens a new server connection) and record
   `flow.metadata["wiretrace_mapped"] = {"from": host, "to": url}`. `is_api_host` checks in the
   response hook use the original host from that metadata. `map_targets()` returns the hosts of
   enabled Map remote rules.
2. `addons/proxy_guard.py`: `server_connect` runs a strict check before its loopback-client
   early return: for a server host in `qatools.map_targets()`, refuse when any resolved address
   is loopback, private, shared, link-local, unique-local, unspecified, multicast, or this Mac's.
   A new `_blocked_for_map(address)` beside `_blocked()` holds those ranges, and `Resolved`
   gains `map_blocked`; `_blocked()` and the existing check are unchanged.
3. `addons/wiretrace_ui.py`: summaries carry `mapped` and `sent_to`; `host` stays the original.
4. Window: `logic/rules.ts` (target, validation, preview), `RuleEditor.tsx`, `RulesView.tsx`,
   `TrafficList.tsx` (tag), `DetailPanel.tsx` ("Sent to"), `types.ts`.

Rejected: targets on this Mac or the LAN, e.g. a dev server or a VPN-only staging host on 10.x
(it reopens what spec 009 closed: any accepted phone could reach services on this Mac's network
through a rule); path mapping (`/v1/` → `/v2/`; a later spec if QA need it); a "keep Host header"
option (rarely right, and it breaks TLS name checks).

#### Invariants

1. No mapped request reaches loopback, private, shared, link-local, unique-local, unspecified or
   multicast addresses, or this Mac, for any client. The check runs at request time and again
   when the server connection opens; the remaining window is DNS changing between the two, the
   same residual risk spec 009 accepted for loopback.
2. Upstream certificate checking is never turned off for a mapped request.
3. Only the first applied Map remote changes the destination; Rewrite changes then apply to the
   mapped request.
4. The window and the comment always name both the host the app asked for and the target.

#### Tests

qa_tools: target validation (every refused literal and name, port range, same as source);
applied mapping changes scheme, host, port and Host; refused at request time for a name that
resolves to 10.0.0.5, 127.0.0.1, ::1, this Mac's address; WebSocket handshake not mapped; replay
keeps the target; only the first Map remote applies; response rewrites still run on a mapped
response. proxy_guard: strict check for a map target from a remote and from a loopback client;
the existing loopback check unchanged for other hosts. Window API: `mapped`, `sent_to`, `host`
unchanged, comment text. Window logic: preview text, warnings for http.

### Files expected to change (E, F, G)

`addons/rewrite.py` (new), `addons/qa_tools.py`, `addons/proxy_guard.py`,
`addons/wiretrace_ui.py`; `ui/src/logic/rules.ts`, `logic/mapLocal.ts` (new) and tests;
`ui/src/components/RuleEditor.tsx`, `RulesView.tsx`, `TrafficList.tsx`, `DetailPanel.tsx`,
`MapLocalDialog.tsx` (new); `ui/src/api.ts`, `types.ts`, `styles.css`; `ui/dist/`;
`tests/test_rewrite.py` (new), `tests/test_qa_tools.py`, `tests/test_proxy_guard.py`,
`tests/test_wiretrace_ui.py`; `docs/user-guide.md`.

---

## Out of scope

- More than 4 devices, or a limit per preset; remembering or naming devices across sessions.
- Device logs for more than one phone: the collector follows the session's device kind.
- Device addresses in `flows.har` or a bug report.
- Changing the WireGuard port from the window.
- Removing an API host from the Encrypted view (Edit presets does it, with a restart).
- Sizes of encrypted connections.
- Breakpoints on WebSocket messages, or editing binary bodies.
- The two-port split window (`feature/two-phones`).
- Rewrite of body text by find and replace, of the query or the path, or of the status; JSONPath
  wildcards; rewriting WebSocket messages.
- Map local files outside `mocks/<preset>/`; a Content-Type other than JSON for mocks.
- Map remote to this Mac or the LAN (dev servers, VPN-only staging), path mapping, keeping the
  original Host header, mapping WebSocket handshakes.

## Manual test

Two phones (A, B) and a laptop (C) on the same Wi-Fi, certificate trusted on the phones,
Wiretrace started from the app in mode `proxy`.

1. **Port**: Setup and the sidebar show `<Mac IP>:8889`. Set A and B to 8889. Start Charles on
   8888 at the same time: both run.
2. **Devices**: A opens the app: accepted, listed by IP, its rows show its IP in the Device
   column. B connects: the banner names B; **Allow…**, confirm. B's rows appear with B's IP;
   filter by B. C connects and is allowed; reach 4 if you can and check **Allow…** is disabled.
3. **Remove**: remove B. Its next request fails; its old rows stay. B appears in the banner again;
   allow it back. Remove every device: the next one to connect is refused, not accepted.
4. **Change port**: change to 8890: the session restarts on 8890; set the phones to 8890; quit
   and start Wiretrace.app again: still 8890.
5. **Encrypted**: open a page that loads a third-party image host: grey Encrypted rows appear.
   Right-click → Decrypt; reopen the app: that host's requests are listed. The preset file has
   the host.
6. **Breakpoints**: add a pause rule on one endpoint, *Both*. Trigger it: the request pauses;
   change the body, **Continue**; the response pauses; change the status to 503, **Send to app**:
   the app shows its error. Trigger again and **Abort**: network error. Close the window tab with
   a request paused: after 30 s it continues.
7. **Rewrite**: a rule on the profile endpoint, *Response*, *Set JSON field*
   `data.user.isPremium` = `true`, plus *Request*, *Set header* `x-feature-flags`. The app shows
   the premium state; the row is REWRITTEN; the Changes tab lists both; the server log or the
   Request tab shows the header.
8. **Map local**: right-click a response → **Map local…**, change one value, **Save and map**.
   The next request shows MOCK and the changed value; `mocks/<preset>/saved/` has the file.
9. **Map remote**: map the API host to the staging host. Requests show MAPPED and "Sent to";
   the data is staging's. Change the target to `192.168.1.20` or `localhost`: save refuses.
   Point a test DNS name at `10.0.0.5`: the app gets 502 and the comment says refused.
10. Stop the session: no device address or encrypted host in `meta.json`, `.status.json`,
   `flows.har` or a bug report.

## Automated tests

`pytest` (the cases above) and `npm --prefix ui test`; `npm --prefix ui run build` leaves
`git diff -- ui/dist` empty.
