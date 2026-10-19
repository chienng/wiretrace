# Spec: Wi-Fi proxy and WireGuard in the same session, proxy first

- **Summary**: one Wiretrace session listens for the Wi-Fi proxy and for the WireGuard
  tunnel at the same time. The window shows the Wi-Fi proxy steps first, and a switch in
  the Connect step shows the WireGuard steps instead. Nothing restarts: the phone connects
  whichever way it is set up. This becomes the default for `./wiretrace start` and for
  every choice in Wiretrace.app.
- **Date**: 2026-10-19
- **Repo**: wiretrace
- **Status**: approved (2026-10-19)
- **Tier**: L (the default changes from one authenticated UDP listener to an extra TCP
  proxy on the LAN, and `proxy_guard.py`, the access control on that proxy, changes).
  Gates E, A, B, C, R, P, D.
- **Branch**: `feature/proxy-and-wireguard-together` (from `main`)
- **Related**: spec 002 (`--mode`, one session per run); spec 008 (no mode switch at run
  time; *Use Wi-Fi proxy instead* shows a restart command); spec 009 (`proxy_guard.py`:
  loopback clients, pinning, no loopback dials); spec 010 (setup wizard wording); spec 013
  (a preset switch keeps the target and mode); spec 014 (`cli/app.py` device → target, mode)

## Goal

QA testers want the Wi-Fi proxy by default and WireGuard only when an app ignores the
proxy. Today the mode is fixed by `--mode` when Wiretrace starts (default `wireguard`),
and the window can only print the command to start again in the other mode.

## Acceptance criteria

- [ ] `./wiretrace start` without `--mode`, and every device in Wiretrace.app, start one
      mitmdump that accepts the Wi-Fi proxy on the proxy port (TCP, default 8888) and the
      WireGuard tunnel on UDP 51820. `meta.json` and the status file say `"mode": "both"`.
- [ ] `--mode proxy` and `--mode wireguard` start exactly the command they start today,
      except that the default proxy port is now 8888 (see Errata).
- [ ] In `both` mode, the Setup wizard's Connect step shows a two-way switch, **Wi-Fi
      proxy** | **WireGuard**, with Wi-Fi proxy selected the first time. Choosing one shows
      that mode's steps (address and port, or the QR code and configuration file). The
      steps after Connect (certificate, check, "next time" tip, "no page" hint) follow the
      choice. The session keeps running and no request is sent to the server.
- [ ] The choice is remembered in the browser's localStorage and is the starting choice
      next time. A missing or unknown stored value means Wi-Fi proxy.
- [ ] The iOS Simulator has no switch in `both` mode: it shows the Mac proxy steps, and
      the "restart in proxy mode" box does not appear.
- [ ] The Android emulator starts on the Wi-Fi proxy steps (`adb shell settings put global
      http_proxy 10.0.2.2:<port>`). WireGuard stays available behind the switch.
- [ ] With `--mode wireguard` or `--mode proxy`, the window looks and behaves as today:
      no switch, and the restart command where the other mode is needed.
- [ ] A phone connected through WireGuard and a phone (or the same phone) connected
      through the Wi-Fi proxy are both captured in the same session folder and HAR.
- [ ] Wi-Fi proxy protection is unchanged for proxy clients: loopback is always accepted;
      with no `--client`, the first other address is pinned and every further one is
      refused with today's message; a proxy client cannot dial loopback, link-local or
      unspecified addresses. A WireGuard client is never pinned, never refused by the
      guard, and does not use up the pin.
- [ ] If either port is in use, `both` mode is not started, with the message `run`
      already prints for a busy port. There is no automatic fall-back to one mode.
- [ ] The banner tells the tester both ways to connect. The title bar and the menu bar
      show the mode as **Proxy + WireGuard**. The bug report says `Mode: both`.

## Approach

mitmproxy 12.2.3 runs several modes in one process
(`--mode regular --listen-port 8888 --mode wireguard@51820`; checked on 2026-10-19, then
with port 8080: TCP and UDP 51820 both listen). Every client carries the mode it connected
through (`client.proxy_mode`), so `proxy_guard.py` can apply its rules to Wi-Fi proxy
clients only. The window's switch only chooses which instructions to show.

The WireGuard port is written explicitly (`@51820`) because `--listen-port` is the
default port for every mode without one. Without it WireGuard would try UDP 8888. With
it, `ctx.options.listen_port` stays the proxy port, which the window already reads.

Rejected:

- **A window button that restarts into the other mode** (like spec 013). Each switch
  writes a HAR, opens a new session folder and drops a few seconds of traffic. Also,
  a tester who needs WireGuard has to be told in the window to press the button.
- **Changing mitmproxy's `mode` option in the running session.** `proxy_guard.py` is
  loaded only in proxy mode, ports are checked only before the start, and `meta.mode`
  would change partway through one HAR.

### Security posture

Today's default, WireGuard only, has no unauthenticated listener on the LAN: a client
needs the key in `~/.mitmproxy/wireguard.conf`. The new default adds TCP 8888 on all
interfaces, protected the way `--mode proxy` already is: by loopback plus first-device
pinning, or `--client`. This is what QA asked for, not a side effect of running both
modes. Anyone else on the Wi-Fi network who connects first takes the pin. The tester then
sees today's refusal message and restarts Wiretrace or passes `--client`. The banner and
the user guide say so.

## Design that needs care

### The guard's decision, per connection

| Client came in through | `client_connected` | `server_connect` |
|---|---|---|
| Regular proxy, loopback address | accept | no check (as today) |
| Regular proxy, `--client` address or the pinned one | accept | refuse loopback, link-local, unspecified |
| Regular proxy, nothing pinned yet, pinning on | pin, accept | as above |
| Regular proxy, any other address | refuse (today's message, once) | (connection already closed) |
| WireGuard (or any mode that is not `regular`) | accept, does not pin | no check (as in `--mode wireguard` today) |

### Invariants

1. In `--mode proxy` every client is a regular-mode client, so the guard's behaviour there
   is identical to today's. The existing `tests/test_proxy_guard.py` cases pass unchanged.
2. A WireGuard client's address (`10.0.0.1` for every tunnel) is never stored as the pin.
3. The guard tests the mode type (`isinstance(client.proxy_mode, mode_specs.RegularMode)`),
   not the address. A WireGuard client that happens to be `10.0.0.1` and a LAN device at
   `10.0.0.1` are told apart by how they connected.
4. A client with no `proxy_mode` attribute is treated as a regular-mode client: the
   stricter rule.
5. The window's switch is client-side state only. No new endpoint, no new file, no
   new option.
6. `both` checks both ports before the first spawn and before every spawn after a preset
   switch (spec 013 invariant 8).

## Files expected to change

1. `addons/proxy_guard.py`: `client_connected` and `server_connect` apply only to
   regular-mode clients (decision table above). Module docstring: loaded in proxy and
   both modes.
2. `cli/start.py`: `MODES = ("wireguard", "proxy", "both")`; a `WIREGUARD_PORT = 51820`
   constant. `needed_ports` returns both ports for `both`. `build_command` for `both`:
   `--mode regular --listen-port <proxy_port> --mode wireguard@51820`, loads
   `PROXY_GUARD`, and sets `qa_proxy_clients` / `qa_proxy_pin` as proxy mode does. The
   banner gives both "Phone:" ways. The `proxy` and `wireguard` branches are not changed.
3. `cli/__main__.py`: `--mode` default `both`; help text lists the three.
4. `cli/app.py`: every `DEVICES` entry starts `both`.
5. `addons/wiretrace_ui.py`: `/api/state` returns `mac_ip` when the mode is not
   `wireguard` (today: only when it is `proxy`). `wireguard_conf` already comes back for
   every mode except `proxy`.
6. `menubar/__init__.py`: `MODE_LABELS["both"] = "Proxy + WireGuard"`.
7. `ui/src/logic/setup.ts`: `ConnectionChoice = 'proxy' | 'wireguard'`. A function for
   whether the steps are WireGuard steps, from the mode, the choice and the device kind
   (`needsProxy` kinds are always proxy). Read and write of the stored choice.
8. `ui/src/components/SetupWizard.tsx`: the switch in the Connect step for `both`. Every
   place that now computes `state.mode === 'wireguard'` uses the function from step 7.
9. `ui/src/components/TitleBar.tsx`: `both` shows **Proxy + WireGuard**.
10. `docs/user-guide.md` and `README.md`: the new default, the switch, `--mode proxy|wireguard`
    for one listener only, the pinning note, and removing the Wi-Fi proxy from the phone
    when done.
11. Tests (next section).

## Out of scope

- Falling back to one mode when the other's port is busy.
- Recording per flow which mode it came through.
- Refusing loopback dials from WireGuard clients. That is not checked in `--mode wireguard`
  today. It is a separate hardening spec if wanted.
- Changing the pinning rules, the refusal message, or the listen addresses.
- A mode choice in Wiretrace.app's dialogs.

## Tests

Automated:

- `tests/test_start.py`: the `both` command (the three mode arguments in order, the guard
  loaded, the client options), `needed_ports("both", …)` has both ports, the `both`
  banner, the CLI default is `both`, and the `proxy` / `wireguard` commands are byte-for-byte
  what they were, apart from the default proxy port 8888.
- `tests/test_proxy_guard.py`: a WireGuard-mode client at `10.0.0.1` is accepted and not
  pinned. A regular client after it is still pinned, and a second regular client is
  refused. A WireGuard client's loopback dial is not refused. A client without
  `proxy_mode` is treated as regular. The live mitmdump test runs once more with
  `--mode regular --listen-port <p> --mode wireguard@<free UDP port>` and still refuses a
  second proxy client.
- `tests/test_app.py`: every device starts `--mode both`.
- `tests/test_menubar.py`: the `both` label.
- `tests/test_wiretrace_ui.py`: `/api/state` in `both` returns `mac_ip` and
  `wireguard_conf`. In `wireguard`, `mac_ip` is null. In `proxy`, `wireguard_conf` is null.
- `ui/src/logic/setup.test.ts`: the choice function for each mode, choice and kind. An
  unknown stored value means proxy. The iOS Simulator is always proxy.

Manual (about 5 minutes, Orchestrator, real phone):

1. Start from Wiretrace.app with an Android phone or iPhone. Setup → Connect shows the
   Wi-Fi proxy address first.
2. Set the phone's Wi-Fi proxy and open the app under test: flows appear.
3. Flip the switch to WireGuard: the QR code appears and the session keeps recording.
   Remove the Wi-Fi proxy, turn the tunnel on: flows keep arriving in the same session.
4. Reload the window: WireGuard is still the selected choice.
5. Point a second device's Wi-Fi proxy at the Mac: it is refused, and the first phone keeps
   working.
6. Stop. The report says `Mode: both`, and the HAR has flows from both ways of connecting.

## Gates

- **E**: the switch uses the existing segmented-control style (the rule editor's apply
  choice) and design tokens. Screenshots of Connect for `both` (each choice), `proxy`
  and `wireguard`.
- **A**: Bugbot on the branch.
- **B**: security review of `proxy_guard.py` and the default change. Mandatory.
- **C**: no new log lines; the refusal message still has no address.
- **R**: a live `both` mitmdump on spare ports. `lsof` shows both listeners; a curl through
  the proxy is captured; a second proxy client is refused. The real-phone WireGuard step is
  the Orchestrator's (manual test 3).
- **P**, **D**: as usual.

## Errata

- 2026-10-19, during implementation, at the Orchestrator's request: the default proxy port is
  **8888** instead of 8080, in every mode (`PROXY_PORT`, the `doctor` port check and firewall
  hint, the window's fallback, the docs). The text above says 8888; `--mode proxy` keeps
  today's command except for that port. 8888 is also Charles Proxy's default port: with
  Charles running, Wiretrace does not start and names the busy port. The release is **0.9.1**.
- The first criterion said `--proxy-port`; there is no such option. The port is `run()`'s
  `proxy_port` (default `PROXY_PORT`), which the command line does not expose.
