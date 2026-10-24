# Spec: more room for request details — a wider detail panel and a log strip that hides

- **Summary**: QA can drag the list | detail border further left, so Request, Response and the
  log line detail get more room. The list may shrink to 380 px when the tester drags it there;
  the default layout does not change. The log strip at the bottom of Traffic can be hidden and
  shown again, giving the list and the detail panel its height.
- **Date**: 2026-10-24
- **Repo**: wiretrace
- **Status**: implemented (2026-10-24; approved 2026-10-24)
- **Tier**: M (one repo, UI only, ~7 files plus docs). Gates E, A, R, P. B, C n/a (no data,
  network or log change; the choices stay in the browser). D n/a (one repo).
- **Branch**: `feature/more-room-for-details`, from `main` (spec 024 merged in `8e4e118`).
- **Version**: rides with the next release (0.11.0).
- **Builds on**: spec 024 (resizable panes), implemented. Its defaults, handles, keys and
  storage stay; only the two limits below change.

## Goal

Spec 024 stops the detail panel at 720 px and keeps the list at 480 px. At 1440 px with the
default sidebar, the border cannot go left of 500 px from the window edge (detail 720 px), which
QA finds too narrow for JSON bodies and long headers. Vertically, the log strip always takes
210 px of a 900 px window, even when the tester is reading a response and not the logs.

## Acceptance criteria

### Limits

- [ ] **No 720 px cap** on the Traffic or Logs detail panel: only the list's minimum limits it.
      The Traffic detail minimum stays 360 px, and so does the Logs one.
- [ ] **The list may go down to 380 px**, in Traffic and in Logs, when the tester drags the
      list | detail border (or uses ←/→/End on it). At 1440 px with a 220 px sidebar the detail
      panel reaches 840 px; with a 160 px sidebar, 900 px.
- [ ] **Defaults do not change**: with no chosen width the detail panel is 40 % of the window
      (Traffic 470–720 px, Logs 430–720 px) and gives way so the list keeps 480 px, exactly as
      in spec 024. The README screenshots stay valid.
- [ ] **The sidebar handle does not squeeze the list below 480 px**; only the detail handle can.
- [ ] A chosen width is kept whenever it fits, as before: shrinking the window narrows the
      detail panel down to the 380 px list, then gives way; widening restores it.
- [ ] Widths remembered under spec 024 still load (same keys, any value ≥ 360 px is valid).
- [ ] `aria-valuemax` on the detail handles reports the new reach (e.g. 840 at 1440 px).

### Narrow list columns

- [ ] **Traffic**: below a 480 px list the Time column is hidden too (the request's start time
      is in the Timing tab; an encrypted row's is in its header as *Opened*). Method, Status,
      Path (still at least 120 px, ellipsized) and the badges stay. With the Device column,
      Device is already hidden below 580 px, so the same rule applies.
- [ ] **Logs**: the Message column keeps at least 120 px and ellipsizes. Below a 560 px list
      the Time column is hidden (it stays in the line detail). Level, Tag, Message and the
      linked-request mark stay.
- [ ] Columns come back when the list widens. Nothing overlaps at any width the handles allow.

### Log strip (Traffic view)

- [ ] The strip's bar ends with a **Hide logs** button (a down chevron and the label). It
      collapses the strip to its bar: the *Device logs* | *App logs* tabs and the button, now
      **Show logs** with an up chevron. The level menu, the filter box and *Auto-scroll* are not
      shown while it is collapsed. The list and the detail panel take the freed height (about
      170 px).
- [ ] **Show logs**, or a click on either tab while collapsed, opens the strip again, on that
      tab, with its level, filter and Auto-scroll as they were.
- [ ] The button has `aria-expanded` and `aria-controls` pointing at the line list, and a
      tooltip: "Hide the log strip; the Logs view and the detail panel's Logs tab still show
      the lines" / "Show the log strip".
- [ ] The choice is remembered by the browser (localStorage `wiretrace.pane.traffic.logs`,
      value `hidden`; anything else means shown) for the next window. The default is shown.
- [ ] Nothing else changes: logs keep being received and counted, the Logs view and the detail
      panel's *Logs* tab are unaffected, and the strip has no other way to change height.

### Docs

- [ ] The user guide's *Pane widths* paragraph gives the new reach and column rules, and the
      *Logs* item says the strip can be hidden and shown.

## Approach

Two list minimums instead of one in `ui/src/logic/paneWidth.ts`: `LIST_MIN_DEFAULT = 480`
(defaults and the sidebar handle) and `LIST_MIN = 380` (a width the tester chose on a detail
handle). `fitWidth` takes the room for a default and the room for a chosen width separately;
`paneRange` for the detail handles uses the 380 px room. The detail specs drop `max: 720` (no
cap; `initial` still clamps the default to 720). Column hiding stays in container queries:
`.flows-wrap` gets one more step at 480 px, and `.lg-list` becomes a query container with a step
at 560 px.

The log strip keeps its bar and drops its body: `LogStrip` holds a `hidden` state loaded from
and stored to localStorage (helpers next to the pane widths in `paneWidth.ts`), adds a
`collapsed` class to `.logs` (`height: auto`), and does not render the level menu, filter, Auto-scroll
or the line list while hidden. Since `.main-body` is the flex child that grows, it takes the
height without other changes.

Rejected:
- Lowering one shared minimum to 380 px: a 1024 px window would open with a 380 px list and no
  Time column by default, a regression for testers who never drag.
- A list minimum below 380 px: the badges column would have to go (spec 024 rejected losing it).
- A *maximize detail* button that hides the list: a new control and mode for what a drag
  already does.
- Hiding the strip completely, with the toggle in the title bar: the way back would be far from
  where the strip was, and the title bar is already full.
- A draggable strip height: more than asked; hide/show covers reading a long response.

## Design

- Detail width: `stored === null` → `min(initial(window), roomDefault)`; otherwise
  `min(clamp(stored, min, max), roomChosen)`; then `max(0, …)`.
  - Traffic: `roomDefault = box − 480 − sidebar`, `roomChosen = box − 380 − sidebar`.
  - Logs: `roomDefault = box − 480`, `roomChosen = box − 380`.
  - Sidebar: unchanged, `room = box − 480`.
- Detail handle range: `paneRange(spec, roomChosen)`. A drag that starts from the default width
  can therefore move past the default room; on release the width is stored and is from then on a
  chosen width.
- `max: Infinity` for both detail specs; `loadWidth` accepts any finite value ≥ min.

Tests (`paneWidth.test.ts`):
- the default keeps a 480 px list (1024 px: 220/480/324 as before; 1440 px: 576);
- a chosen width may leave a 380 px list (1440 px: 840), never less;
- no 720 px cap on a chosen width in a wide window;
- the detail range's max is `box − 380 − sidebar`;
- a stored value above 720 now loads; a value below 360 still does not;
- the sidebar range is unchanged;
- the strip choice: `hidden` loads as hidden; absent, unreadable or any other value as shown;
  storing shown removes the key; a browser that refuses storage does not throw.

`LogStrip.test.ts` (static render, as `Splitter.test.ts`): expanded shows the controls and
"Hide logs" with `aria-expanded="true"`; with the stored choice hidden it shows the two tabs and
"Show logs" with `aria-expanded="false"` and no line list.

## Files expected to change

1. `ui/src/logic/paneWidth.ts` and `paneWidth.test.ts`: the two minimums, no cap, `fitWidth`
   and `usePaneWidth` taking both rooms.
2. `ui/src/components/TrafficView.tsx`, `ui/src/components/LogsView.tsx`: pass both rooms; the
   Logs header's Time cell gets a class.
3. `ui/src/components/TrafficList.tsx`: the header's Time cell gets a class.
4. `ui/src/components/LogStrip.tsx` (+ `LogStrip.test.ts`): the toggle button, the collapsed
   bar, the remembered choice.
5. `ui/src/styles.css`: the Traffic step at 480 px; `.lg-list` container, Message minimum, the
   Logs step at 560 px; `.logs.collapsed`.
6. `docs/user-guide.md`; `ui/dist` rebuilt.

## Out of scope

- Changing the default widths, the sidebar limits, keys or storage keys.
- A list minimum below 380 px, hiding the badges, or collapsing the list completely.
- Dragging the log strip's height; a keyboard shortcut for the toggle.
- The Rules view.

## Manual test (~5 min)

1. Clear the remembered widths (double-click each handle). At 1440 × 900 the layout is as
   before: 220 | 644 | 576.
2. Drag list | detail as far left as it goes: the detail panel stops at 840 px, the list at
   380 px; Time, Size and Duration are gone; Path and the badges are on screen.
3. Narrow the sidebar to 160 px and drag again: the detail panel reaches 900 px.
4. Tab to the detail handle and press End: it goes to the same limit.
5. Reload: the width is kept. Shrink the window to 1024 px: the list stays at 380 px, the detail
   panel gives way. Widen again: the detail panel is back at its width.
6. In Logs, drag list | detail as far left as it goes: list 380 px, no Time column, Message at
   least 120 px; select a line and read its time in the detail.
7. Double-click the handles: the defaults (and a 480 px list at 1024 px) come back.
8. In Traffic, click **Hide logs**: the strip shrinks to its bar and the list shows more rows.
   Select a request: its *Logs* tab still lists the matching lines. Reload: still hidden.
9. Click **App logs** in the collapsed bar: the strip opens on App logs. Click **Hide logs**,
   then **Show logs**: the level and filter you set are unchanged.
