# Spec: switch to another phone on the Wi-Fi proxy

- **Summary**: when the Wi-Fi proxy refuses a device because another one is pinned, the window
  says so and offers **Switch to it**. Switching saves the session and starts a new one that
  accepts only that device's address from its first connection. Works between two phones of
  the same kind (two iPhones), which spec 018's device menu cannot do. Nothing is remembered
  across restarts.
- **Date**: 2026-10-19
- **Repo**: wiretrace
- **Status**: approved (2026-10-19)
- **Tier**: L (changes which device the Wi-Fi proxy accepts; a window action stops the capture
  process; `.switch.json` gains a key the launcher acts on). Gates E, A, B, C, R, P. D n/a (one
  repo).
- **Branch**: `feature/switch-to-another-phone`, from `main` (`258a776`).
- **Related**: spec 009 §2 (proxy accepts this Mac and the first other device, or `--client`);
  spec 013 (`.switch.json`, the loop in `run`, invariants 1–10); spec 018 (device switch, one
  device per session); spec 017 (mode `both`).

## Goal

A QA tester works with several phones and moves between them during the day. On the Wi-Fi
proxy, the first phone that connects is pinned for the whole session (spec 009), so the next
phone is refused with one Terminal line the window never shows. Today the tester has to know
to stop Wiretrace, take the proxy off the first phone so it does not win the pin again, and
start Wiretrace again; or restart from the Terminal with `--client <address>`.

The tester should only have to set the proxy on the next phone (it is already set if it was
used before) and click once in the window. Orchestrator choices (2026-10-19): the window asks
when another device connects; each switch is a new session, as in spec 018; no list of known
phones is kept across restarts.

WireGuard is unchanged: it has no pin. Turning the tunnel off on one phone and on on the other
already moves the traffic.

## Acceptance criteria

- [ ] With `--ui wiretrace`, pinning on (mode `proxy` or `both`, no `--client`), and a device
      pinned: when the proxy refuses a device at another address, a banner under the title bar
      appears within 1 s: "Another device wants to use the Wi-Fi proxy: 192.168.2.72, since
      19:21. Only 192.168.2.71 is accepted in this session." with **Switch to it…** and
      **Ignore**.
- [ ] **Ignore** hides the banner for that address until the session ends, reloads included.
      A refusal from a different address shows the banner again. With several waiting
      addresses, the banner shows the most recent one that is not ignored, and "+N more".
- [ ] **Switch to it…** opens a dialog: "Switch to the device at 192.168.2.72?", a choice of
      device kind (iPhone, Android phone, Another device; the current one preselected when it
      is one of these), the device-log line for that kind (spec 018's text), and: "This
      session is saved and a new one starts. Only this device is accepted on the Wi-Fi proxy;
      the device at 192.168.2.71 is refused until you switch back." Cancel changes nothing.
- [ ] Confirm saves the session the way spec 018 does and starts a new one with the chosen
      kind and the same preset, mode, ports and `--from-app`. The new session accepts
      192.168.2.72 from its first connection and refuses 192.168.2.71, which then shows in the
      new session's banner, so switching back is the same click.
- [ ] Choosing the kind already in use is allowed here (two iPhones), unlike the device menu.
- [ ] Setup's *Connect to this Mac* step and the device pill's tooltip name the accepted
      address when a device is pinned: "Wi-Fi proxy: accepting 192.168.2.71".
- [ ] No banner, no waiting list and no client switch: in `wireguard` mode, with `--client`
      (pinning off), with `--ui mitmweb` or `--no-ui`, and while a previous session is open
      (the reason Setup, Rules and the menus use). A client switch request in these cases is
      refused with 409 and changes nothing.
- [ ] A client switch is refused with 409 for an address the running session has not refused
      or no longer lists, and with 400 for a value that is not an IP address, for the iOS
      Simulator or the Android emulator (they connect from this Mac), or for an unknown kind.
- [ ] A second switch (any kind) while one is in flight is refused with 409. Ctrl+C or
      **Stop session** still ends Wiretrace without starting the next session.
- [ ] Device, preset and the Terminal output behave as before: a device or preset switch
      without a client starts a session that pins the first device to connect; the refusal
      line in the Terminal is unchanged and has no address.
- [ ] No address of a waiting or accepted device is written to `meta.json`, `.status.json`, the
      Terminal, the menu bar, `flows.har` or a bug report.
- [ ] User guide: switching phones on the Wi-Fi proxy (the banner, Ignore, switching back);
      the restart route stays for `--ui mitmweb`. All Python and frontend tests pass;
      `ui/dist` reproduces.

## Approach

1. `addons/proxy_guard.py`
   - New option `qa_proxy_pinned` (str, default `""`): the address pinned when the process
     starts. Used only with `qa_proxy_pin`; must parse as an IP address that is not loopback,
     link-local, unspecified or multicast (`OptionsError` otherwise). Normalized the same way
     as client addresses (IPv4-mapped IPv6 to IPv4).
   - Refusals of regular-listener clients are recorded per address: first seen, last seen,
     count. At most 8 addresses; the one seen least recently is dropped. Kept in memory only.
2. `addons/wiretrace_ui.py`
   - Its `client_connected` already skips a client proxy_guard refused. On such a client it
     reads proxy_guard's list (`ctx.master.addons.get("proxyguard")`) and pushes the state when
     the address is new to the list; otherwise at most once every 5 s.
   - State gains `proxy_device` (the pinned address or null) and `proxy_waiting` (the list,
     most recent first: `address`, `first_at`, `last_at`, `count`). Both are null/empty unless
     pinning is on.
   - `POST /api/device` accepts `{"target"}` as today, or `{"target", "client"}`. With a
     client: the checks of the acceptance criteria, in the order of invariant 2, then
     `start_switch` writes `.switch.json` with the three keys.
3. `cli/start.py`
   - `take_switch` accepts exactly `{name, target}` or `{name, target, client}`; any other
     shape is ignored as today.
   - The loop checks the client again before spawning (invariant 3) and passes
     `--set qa_proxy_pinned=<address>` to the next child. A switch without a client passes
     nothing, so the next session pins the first device, as today.
4. Window: `ui/src/logic/proxyDevices.ts` (which address to show, ignored addresses per
   session in `sessionStorage`, banner text), a banner component, the dialog (reusing
   `SwitchDeviceDialog`'s confirm and saving states), `api.switchDevice(target, client?)`,
   types, the Setup line and the pill tooltip.

## Design that needs care

The pin is the proxy's access control on a shared Wi-Fi. This spec must never let two
non-loopback devices through in one pinned session, and the address a session starts pinned to
must come only from a refusal the tester saw and confirmed.

### Invariants

1. With pinning on, a session accepts this Mac and at most one other address, for its whole
   life. Nothing in this spec adds a second accepted address to a running session.
2. The window writes a client switch only after, in this order: no previous session open; no
   switch in flight; pinning on and mode not `wireguard`; the kind is iPhone, Android phone or
   Another device; the client parses as an IP address; the normalized address is in
   proxy_guard's waiting list at that moment. No `await` between the in-flight check and the
   write (spec 018, invariant 6).
3. The launcher re-checks the client from `.switch.json` (parses, not loopback, link-local,
   unspecified or multicast) and that the run has no `--client` list before it spawns. A
   failed check ends Wiretrace with a message, like an invalid preset after a switch
   (spec 013, invariant 3).
4. The next session's proxy_guard is pinned before its first connection is accepted
   (`configure` runs before the listener accepts clients).
5. The waiting list is bounded (8), lives in memory, and is dropped with the process. Its
   addresses go only to the window's token-protected API and WebSocket.
6. Spec 013 and 018 invariants hold unchanged: one switch in flight, any stop signal wins over
   a switch, `.switch.json` is read once and deleted whatever it holds.

### Tests derived from the invariants

- proxy_guard: `qa_proxy_pinned` accepts that address first and refuses the next one; it is
  ignored without `qa_proxy_pin`; loopback, link-local, unspecified, multicast and garbage
  values raise `OptionsError`; refusals are recorded with counts and capped at 8 by last seen;
  WireGuard clients are never recorded.
- window API: each 409/400 case of the acceptance criteria, in invariant 2's order (a previous
  session open wins over a bad address); a client not in the list; a client in the list as an
  IPv4-mapped IPv6 address; the file holds the three keys, 0600; a second request while in
  flight gets 409.
- state push: a new address pushes at once; repeats push at most every 5 s; no `proxy_*`
  content without pinning.
- launcher: `take_switch` with two keys, three keys, an extra key, a non-string client; the
  re-check refuses a loopback client and a run started with `--client`; the next child's
  command has `qa_proxy_pinned` only after a client switch; a stop signal after the write
  starts nothing.
- privacy: after a client switch, `meta.json`, `.status.json`, the banner line printed in the
  Terminal and a bug report contain neither address.
- window logic: banner choice with ignored and several addresses; ignored addresses survive a
  reload and reset with a new session name; texts.

## Files expected to change

`addons/proxy_guard.py`, `addons/wiretrace_ui.py`, `cli/start.py`, `ui/src/api.ts`,
`ui/src/types.ts`, `ui/src/logic/proxyDevices.ts` (new) and its test,
`ui/src/components/` (banner, `SwitchDeviceDialog.tsx`, `SetupWizard.tsx`, `TitleBar.tsx`),
`ui/src/styles.css`, `ui/dist/`, `tests/test_proxy_guard.py`, `tests/test_wiretrace_ui.py`,
`tests/test_start.py`, `docs/user-guide.md`, this spec.

## Out of scope

- Remembering phones across restarts, or naming them (Orchestrator choice).
- Accepting two phones at once without `--client`.
- Telling an iPhone from an Android phone before it connects: a refused device sends nothing
  Wiretrace can read, so the tester picks the kind.
- Device logs when two phones of the same kind are on USB: the collector takes the one
  `pymobiledevice3` or `adb` picks, as today.
- A pinned phone whose address changes (new DHCP lease) shows as another device; switching to
  it fixes it. No automatic follow.
- Keeping the pin across a preset switch.

## Manual test

Two iPhones on the same Wi-Fi, both with the proxy set to this Mac, certificates installed,
Wiretrace started from the app (mode `both`).

1. iPhone A opens the app: its requests are listed; Setup says "accepting <A>".
2. iPhone B opens Safari: within a second the banner names B. **Ignore**: it goes away and stays
   away after a reload.
3. Restart Wiretrace with A connected first, open Safari on B, and click **Switch to it…** in
   the banner, kind iPhone, Confirm: the session is saved, a new window opens, B's requests
   are listed, and A (still with the proxy set) shows in the new session's banner.
4. Switch back to A from that banner.
5. Ctrl+C during step 3 after Confirm: Wiretrace ends and no new session starts.
6. Check that neither address is in the session's `meta.json`, `.status.json` or a bug report.

## Automated tests

`pytest` (the cases above) and `npm --prefix ui test`; `npm --prefix ui run build` leaves
`git diff -- ui/dist` empty.
