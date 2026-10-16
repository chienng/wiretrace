# Spec: a setup wizard a first-time tester can finish alone

- **Summary**: the five-step Setup wizard (spec 008 slice B) works for someone who already knows
  what a proxy, a VPN app and a CA certificate are. This makes it work for someone who does not:
  plain words, what to expect before starting, a live check in every step, and a concrete hint
  when a step does not turn green.
- **Repo**: wiretrace
- **Status**: approved (2026-10-16; the wizard does not open by itself)
- **Tier**: M (one repo, UI only, no new endpoint, nothing logged)
- **Branch**: `feature/wizard-for-new-users` (from `feature/ui-mockups`)
- **Related**: spec 008 slice B (the wizard), user guide Part 2

## Goal

A tester who has never set up a phone for traffic capture gets from *Setup* to the first
captured API request using the wizard only, without the user guide, and knows at every step
whether it worked and what to try if it did not.

## What is hard today

- Jargon without explanation: "Connect tunnel", "Physical device", "Needs Mac proxy",
  "WireGuard / 10.0.2.2", "CA certificate", `--target`.
- Nothing says what is needed before starting (the phone, a QA build of the app, about five
  minutes) or that it is once per phone.
- *Install certificate* is instructions only: no sign whether the phone opened `mitm.it` or
  downloaded the certificate. The rail marks it done only when the first API request arrives.
- *Verify traffic* waits forever with no hint when the phone is connected but the app sends
  nothing Wiretrace can see (a store build, a wrong environment, the tunnel switched off).
- Android menus follow stock Android; Samsung's differ (fixed for the certificate already on
  this branch; the Wi-Fi proxy steps still have the same gap).

## Acceptance criteria

### A. Plain words

- [ ] Rail labels: **Choose device**, **Connect to this Mac**, **Trust Wiretrace**, **Check the
      app**, **Device logs** (optional). Device cards: *iPhone — a real iPhone*, *Android — a
      real Android phone*, *iOS Simulator — on this Mac*, *Android emulator — on this Mac*.
- [ ] The first time a step uses *WireGuard*, *proxy* or *certificate*, one sentence says what
      it is for (for example: "WireGuard is a free VPN app. Here it only sends the phone's
      traffic to this Mac."). No `--target`, IP or port in a sentence unless the user must type it.
- [ ] Step 1 has a *Before you start* box: what you need (the phone, a **QA build** of the app,
      because a store build hides its traffic; about five minutes), and that it is once per
      phone: next time, switch the tunnel on.

### B. A live check in every step

- [ ] **Connect to this Mac**: as today, *Waiting for the device…* → *Connected*; the hint after
      30 s stays.
- [ ] **Trust Wiretrace** shows a checklist that ticks itself from the traffic Wiretrace sees:
      1. *Page opened on the phone*: any request to `mitm.it`.
      2. *Certificate downloaded*: a request to `mitm.it` for a certificate file (`/cert/…`).
      3. *Trusted*: the first request to an API host (the same signal as today).
      If the device is connected and no `mitm.it` request arrives within 60 s on this step, a
      hint: type `http://mitm.it` exactly (not https), in Safari on an iPhone, with the tunnel on.
      If TLS failures to API hosts arrive, the existing "not trusted yet" message shows here too.
- [ ] **Check the app**: if the device is connected but no API request and no TLS failure has
      arrived after 30 s on this step, a hint lists what to check: the app is a **QA build** for
      the environment of this preset; the preset's API hosts (listed, from the state); a screen
      of the app that loads data; the tunnel still on. When TLS failures arrive on Android, the
      message adds that a store build never trusts the certificate.
- [ ] The rail's tick for **Trust Wiretrace** follows checklist item 3; each checklist item and
      each step shows a tick as soon as its check passes. When the current step's check passes,
      the *Next* button says so ("Done — Next: …").

### C. Phone makers

- [ ] Android Wi-Fi proxy steps give the stock path, the Samsung path (Settings → Connections →
      Wi-Fi → the gear next to the network → View more → Proxy → Manual) and "search Settings
      for *Proxy*".
- [ ] (Already on this branch) the Android certificate steps give the stock and Samsung paths,
      a search fallback, *Install anyway*, the screen-lock note and how to check.

### D. The end

- [ ] The last step's button is **Done — open Traffic**; above it a short summary of what is
      set up, and "next time: switch the WireGuard tunnel on (or the Wi-Fi proxy), then start
      Wiretrace".

### All

- [ ] No new endpoint, no change to the server; nothing new logged. The wizard reads only what
      the window already has (flows, state).
- [ ] Colours and spacing from `ui/src/styles.css` variables; no UI library.
- [ ] User guide Part 2 matches the new labels.

## Approach

All in the UI. `ui/src/logic/setup.ts` gains pure functions, unit-tested:

- `onboardingProgress(flows)` → `{ pageOpened, certDownloaded }` from flows whose host is
  `mitm.it` (`/cert/` path prefix for the download).
- `stepDone(step, state, flows)` used by the rail, the checklist and the *Next* label.
- `appHint(state, flows, sinceMs, now)` → which hint the *Check the app* step shows, or none.

`SetupWizard.tsx` keeps its structure: the rail, one component per step, the footer. Text lives
in `logic/setup.ts` and `logic/certificate.ts`, as today, so tests can check it.

## Design that needs care

- **Clear and the 10,000-request cap.** *Clear* only hides requests in the list; the wizard reads
  the store's flows, so the checklist does not untick after Clear. If the `mitm.it` requests were
  dropped by the cap, the checklist relies on item 3 (an API request also proves 1 and 2): once
  item 3 is ticked, 1 and 2 show ticked.
- **Timers** start when the step is opened (as the 30 s hint does today), not when the window
  loaded, so a tester who reads first is not told something failed.
- **Viewing a previous session**: Setup is off while viewing (spec 008); nothing changes.

## Files expected to change

`ui/src/logic/setup.ts`, `ui/src/logic/setup.test.ts`, `ui/src/logic/certificate.ts` (done),
`ui/src/logic/certificate.test.ts` (done), `ui/src/components/SetupWizard.tsx`,
`ui/src/styles.css`, `docs/user-guide.md` (Part 2), `ui/dist/` rebuilt.

## Out of scope

Opening the wizard automatically on the first start (see the question below); detecting whether
the app is a QA build; pictures of each phone's menus; switching WireGuard / proxy at run time;
other languages.

## Decision

The wizard does **not** open by itself (approved 2026-10-16). Opening it when no device has
connected would help a first-time tester but gets in the way of someone who only wants to look
at an earlier session.

## Manual test (about 10 minutes, a Samsung phone)

1. `./wiretrace start --preset <name> --target android --ui wiretrace`; *Setup*.
2. Step 1 reads without jargon; *Next*.
3. Scan the QR, switch the tunnel on: *Connected*, *Done — Next*.
4. Open `http://mitm.it`: *Page opened* ticks; download: *Certificate downloaded* ticks; install
   with the Samsung path from the wizard.
5. Open the QA build: *Trusted* and *Check the app* turn green. With a store build instead: the
   "not trusted / store build" message.
6. Done — open Traffic.

## Automated tests

`npm --prefix ui test` (new cases for `onboardingProgress`, `stepDone`, `appHint`, the Samsung
proxy path), `npm --prefix ui run build` reproduces `ui/dist/` (`tests/test_ui_build.py`).

## Errata

- The state has no API hosts. *Check the app* takes them from the existing `GET /api/rules`
  (`api_hosts`), loaded once if the Rules view has not loaded it yet; when the list is empty the
  hint says "the API hosts in your preset file". Still no new endpoint and no server change
  (approved 2026-10-16).
