# Spec: a branded title bar

- **Summary**: the Wiretrace window's title bar becomes a deep brand-blue bar ("Ocean") with
  white controls, and fits on one row at 1440 px (two rows today). Traffic | Logs, the primary
  navigation, is the most visible control; Report bug steps back to a plain button. Same
  controls, same order, same behaviour, plus icons, a live Recording dot, and Preset, Device and
  the device-logs status joined into one session box.
- **Date**: 2026-10-24
- **Repo**: wiretrace
- **Status**: implemented (2026-10-24)
- **Tier**: M (one repo, UI only, ~5 files plus docs and screenshots). Gates E, A, R, P. B, C n/a
  (no data, network, storage or log change). D n/a (one repo).
- **Branch**: `feature/polished-title-bar`, from `main` (`683cfa3`).
- **Version**: the next release (0.10.1 if it is not tagged by then).
- **Mockup**: `mockups/titlebar-polished-mockup.html`, sections *Background 3 — Ocean*
  (today's bar is at the top for comparison; the other sections are the rejected variants).

## Goal

The title bar is the first thing a tester sees, and today it looks like two loose rows of grey
buttons: at 1440 px the right-hand group (Preset, Device, device-logs status, Rules, Setup,
Report bug) wraps to a second row, the bar takes about 80 px, and nothing but the logo says
"Wiretrace". The Orchestrator wants it more attractive and branded, with the two primary views,
Traffic and Logs, easy to see, and Report bug less loud than it is now.

## Acceptance criteria

### Look

- [ ] **Background**: a deep brand-blue gradient, left to right `#083f8f` → `#0a4aa3` (50 %) →
      `#0a50ad`, with a faint light glow at the top right (`rgba(140, 192, 255, .12)`), a 1 px
      white highlight along the top edge fading at both ends, and a dark bottom border
      (`#073a84`).
- [ ] **Brand**: the mark at 34 px in its white version (white tile, brand-blue zigzag) with a
      soft shadow; "Wiretrace" 17 px bold white; the version under it in white at 72 % opacity,
      always rendered as today so the name does not move.
- [ ] **Traffic | Logs** (primary navigation): a dark translucent track
      (`rgba(0, 20, 60, .28)`); the selected tab is solid white with brand-blue bold text and a
      shadow; the other tab has white text. Tabs are 26 px high, 13 px text, 14 px side padding.
      The crash count is a solid red badge with a white ring.
- [ ] **Recording**: a white pill with red text, "Recording" and the elapsed time; its red dot
      pulses (a ring that grows and fades every 1.8 s). With `prefers-reduced-motion: reduce`
      it does not pulse. *List paused* and *Reconnecting…* are white pills with orange text,
      without a pulse.
- [ ] **Buttons**: translucent white (`rgba(255, 255, 255, .12)` with a 1 px
      `rgba(255, 255, 255, .22)` inner border), white text, and a 14 px white line icon: Rules
      (sliders), Setup (checklist), Report bug (bug). **Report bug is styled like Rules and
      Setup**, no longer the solid blue primary button; it stays last on the right. Hover
      lightens to `.22`. A toggled button (Rules while open, Resume) is solid white with
      brand-blue text.
- [ ] **Pause and Clear** become one joined pair of icon buttons (pause bars, circle-slash).
      Paused, the first one shows a play icon and a blue badge with the count, "12 new", and is
      toggled. Each has a tooltip ("Pause the list", "Resume the list",
      "Clear: hide what is listed now") and an `aria-label` ("Pause", "Resume, 12 new
      requests", "Clear").
- [ ] **Session box**: the preset menu, the device menu and the device-logs status are one
      joined translucent box with dividers. The preset button shows a layers icon and the preset
      name (the word "Preset" moves to the tooltip and the `aria-label`,
      "Preset: staging-example"). The device button shows a phone icon, light green
      (`#7ee2a0`) once requests were seen and white before, then
      "pixel-example · Proxy + WireGuard"; its `aria-label` starts with "Device:". The status
      segment keeps today's text, tooltip and tone, on its light tone background (green,
      orange, grey or red soft) so it reads as status, not as a button.
- [ ] **Rules count**: "Rules 2" with the orange badge; the tooltip says "2 rules on" (today the
      badge says "2 active").
- [ ] **Contrast**: every white label on the bar, including inside the translucent buttons,
      has at least 4.5:1 contrast against the pixels behind it. The mockup measures 5.26:1 at
      worst (Setup).
- [ ] Colours become tokens in `styles.css` (`--tb-bg`, `--tb-track`, `--tb-glass`,
      `--tb-glass-line`, `--tb-glass-hover`, `--tb-seen`), next to the existing `--blue`,
      `--red`, `--orange`, `--green` and their `-soft` pairs. No new fonts; the icons are inline
      SVG with `currentColor`; the white mark is a second SVG next to `mark.svg`.

### Layout

- [ ] At 1440 px with today's fixture data (preset `staging-example`, device
      `pixel-example · Proxy + WireGuard`, status `Android device · starting`), the bar is one
      row, about 53 px tall, recording (24 px to spare in the mockup) and paused.
- [ ] A narrower window, or long preset or device names, wraps the right-hand group to a second
      row, right-aligned, as today; the blue background covers both rows. No control is
      squeezed, truncated or hidden by width.

### Behaviour (unchanged)

- [ ] Every control does what it does today, in the same order, with the same enabled, disabled
      and hidden rules: Pause/Resume only in Traffic and not while viewing a previous session;
      Clear not in Rules or while viewing; the preset and device menus, Rules and Setup disabled
      while viewing, with the same tooltip; *⏸ N paused* with **Continue all** (breakpoints)
      stays in the left group, as a white pill.
- [ ] The menus open as today, light, under their button (`role="menu"`, `aria-haspopup`,
      `aria-expanded`); the tabs keep `role="tab"` and `aria-selected`; Pause and Rules keep
      `aria-pressed`. Icons are `aria-hidden`; every icon-only button has an accessible name.
- [ ] The focus outline is visible on the blue bar (white, 2 px) for every control.
- [ ] The banners under the bar (amber proxy banner, blue viewing banner) are unchanged.

### Docs

- [ ] User guide: *Preset: …* becomes "the preset menu (layers icon)"; Pause, Resume and Clear
      are described as the icon buttons next to *Recording*; the Rules count wording follows.
      README, line 104 and the screen 1 caption, likewise.
- [ ] The README screenshots that show the title bar (screens 1 to 4 and 5a) are retaken at
      1440 × 900 from the dev fixtures, and their captions say 0.10.1.

## Approach

CSS first, in the title bar section of `ui/src/styles.css`, scoped to `.titlebar`, so other
`.btn`, `.seg` and `.pill` uses (dialogs, the setup wizard, the WebSocket Sent/Received switch)
keep today's look. `TitleBar.tsx` changes markup only: an `Icon` component with the eight
paths (`ui/src/components/Icon.tsx`), the white mark (`ui/src/assets/mark-on-blue.svg`), the
joined Pause/Clear pair, the joined session box wrapping the existing `PresetMenu`,
`DeviceMenu` and status pill, and the new labels and `aria-label`s. `Report bug` drops the
`primary` class. No logic module changes except the Rules tooltip text.

Rejected (all in the mockup):
- *Subtle* (near-white bar, thin blue line) and *tinted* (light blue bar): judged too plain.
- *Brand tile* (a blue block behind the logo only): the tightest fit at 1440 px, and the block
  covers only the first row when the bar wraps.
- *Aurora* and *wire traces* backgrounds: the Orchestrator chose Ocean.
- A brighter blue on the right (`#1a74e8`, first draft): white text in the translucent buttons
  fell to about 3.7:1.
- Restyling `.seg`, `.btn` and `.pill` everywhere: outside the request (decision 2).
- Hiding labels by window width: the bar would change shape while the tester resizes.
- Dropping or shortening the mode ("Proxy + WireGuard") or the device-logs status to win
  width: they are information testers read.
- An icon font or icon package: eight inline paths are smaller than any dependency.

## Design

- `.titlebar`: `position: relative`; background as above; `::before` is the 1 px highlight;
  padding `10px 14px 8px`; `min-height: 52px`; the two groups and wrapping as today, gaps
  10 px (left group 9 px, right group 6 px).
- Joined boxes (Pause/Clear, session box): one `inline-flex` with the glass background and inner
  border, 7 px radius, children separated by a 1 px `rgba(255, 255, 255, .22)` line, outer
  corners rounded; children 8–9 px side padding.
- Pulse: `.rec .dot::after` scales 1 → 2.6 and fades .55 → 0, `1.8s ease-out infinite`.
- Focus: `.titlebar :focus-visible { outline-color: #fff; outline-offset: 1px; }`.
- Disabled (viewing a previous session): today's `opacity: .5`.

Tests, `ui/src/components/TitleBar.test.ts` (static render with `StoreProvider` and fixture
state, as `LogStrip.test.ts`):
- recording: Pause and Clear have `aria-label`s and tooltips; icons are `aria-hidden`;
- paused: the Resume button's `aria-label` carries the new count and `aria-pressed="true"`;
- the preset button's `aria-label` is "Preset: <name>", the device button's starts "Device:";
- Report bug has no `primary` class;
- viewing a previous session: no Pause or Clear, the menus, Rules and Setup disabled.

Runtime (Gate R, Playwright against the dev fixtures in both mode, WebKit): one row and the
height at 1440 px, recording and paused; wrapping at 1024 px with the background behind both
rows and no overlap; each control still works (tabs, Pause/Resume count, Clear, both menus
open and are readable, Rules, Setup, Report bug); Tab order as today with a visible outline;
reduced motion stops the pulse; contrast of every white label ≥ 4.5:1 measured from a
screenshot, as for the mockup.

## Files expected to change

1. `ui/src/components/TitleBar.tsx` (+ new `TitleBar.test.ts`).
2. `ui/src/components/Icon.tsx` (new): the inline icons.
3. `ui/src/assets/mark-on-blue.svg` (new): the white mark.
4. `ui/src/styles.css`: the tokens and the title bar section.
5. `docs/user-guide.md`, `README.md`, `docs/images/*.png` (screens 1 to 4 and 5a); `ui/dist`
   rebuilt.

## Out of scope

- Dark mode for the rest of the window; a new logo (the white mark is the same drawing in
  reversed colours); the favicon and the Wiretrace.app icon.
- The window's other bars and banners; the sidebar, list, detail panel, menus and dialogs.
- New controls, new shortcuts, or moving controls between groups.
- Restyling `.seg`, `.btn` or `.pill` outside the title bar.

## Decisions (Orchestrator, 2026-10-24)

1. Pause and Clear are icon-only buttons with tooltips, so one row fits at 1440 px.
2. The new switch style stays in the title bar; other segmented controls may follow in a
   later spec.
3. Background: *Ocean* (deep brand-blue gradient, white controls), over the subtle, tinted,
   brand tile, aurora and wire-traces variants.
4. Traffic | Logs is the primary navigation and the most visible control; Report bug is a plain
   button like Rules and Setup.
