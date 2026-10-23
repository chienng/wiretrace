# Spec: resizable panes and a wider request detail

- **Summary**: the request detail panel opens wider, so QA can read Request and Response
  without scrolling sideways. The sidebar, the list and the detail panel can be resized by
  dragging the borders between them, in Traffic and in Logs. The **Traffic | Logs** view tabs
  stay as they are.
- **Date**: 2026-10-23
- **Repo**: wiretrace
- **Status**: implemented (2026-10-24; approved 2026-10-23)
- **Tier**: M (one repo, UI only, ~6 files plus docs). Gates E, A, R, P. B, C n/a (no data,
  network or log change; widths stay in the browser). D n/a (one repo).
- **Branch**: `feature/resizable-panes`, from `main` once `feature/readme-screenshots-0.10` is
  merged. Independent of spec 023.
- **Version**: rides with the next release (0.11.0).

## Goal

At 1440 px the Traffic grid is sidebar 220 px | list (the rest) | detail 470 px. The Path
column takes everything the list has left, so most of the screen shows paths while JSON bodies
wrap or scroll in a 470 px panel. Nothing can be resized.

## Acceptance criteria

### Panes

- [ ] **Traffic** has two drag handles: sidebar | list and list | detail. **Logs** has one:
      list | detail. Each handle is the 1 px border, with a 6 px hit area and a `col-resize`
      cursor, and is highlighted blue while hovered or dragged.
- [ ] **Default widths**:
      - Traffic detail: 40 % of the window width, clamped to 470–720 px (576 px at 1440).
      - Logs detail: the same rule, clamped to 430–720 px.
      - Sidebar: 220 px.
- [ ] **Limits**: sidebar 160–360 px. Detail at least 360 px. The list keeps at least 480 px;
      when the window is too narrow for every minimum, the detail panel gives way first, then
      the sidebar.
- [ ] **Window resize** re-applies the limits. A width the tester chose is kept whenever it
      still fits.
- [ ] **Memory**: each chosen width is remembered by the browser (localStorage, like saved
      filters) for the next window. **Double-click** a handle to go back to the default.
- [ ] **Keyboard**: each handle is focusable, with `role="separator"`,
      `aria-orientation="vertical"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax` and a
      label ("Resize the request details", "Resize the sidebar", "Resize the log line
      details"). ←/→ move it 16 px, Shift+←/→ 64 px, Home/End go to the limits, Enter resets
      to the default.
- [ ] **Dragging** does not select text and does not open a row. A pointer released outside
      the window ends the drag.
- [ ] **Narrow list, path column**: the Path column has a minimum of 120 px and ellipsizes;
      its tooltip already shows the full URL. When the list is narrower than 760 px the Size
      column is hidden; narrower than 640 px, Duration is hidden too (it stays in the detail
      header). With the Device column shown (Wi-Fi proxy or both modes) each step is 100 px
      wider (860 and 740 px), and below 580 px Device is hidden too (it stays in the detail
      header). The badges column never leaves the screen. Columns come back when the list
      widens.

### Docs

- [ ] The user guide describes the handles, double-click to reset, and the keyboard keys.
- [ ] The README's main window and logs screenshots (`docs/images/traffic.png`,
      `docs/images/logs.png`) are retaken with the new default widths.

## Approach

A small `Splitter` component and a `usePaneWidth(key, default, limits)` hook. The hook owns the
width (React state), clamps it against the container width and stores it in localStorage. The
component renders the handle and handles pointer events (`setPointerCapture`) and the keyboard.
The grids keep their shape; only the fixed tracks become CSS variables (`--sidebar-w`,
`--detail-w`) set on `.main-body` and `.lg-body`. The column hiding uses a container query on
the list (`container-type: inline-size`), so no JavaScript measures columns.

Rejected:
- A splitter library (react-resizable-panels): a dependency for about 80 lines, with its own
  layout model that does not fit the existing grids.
- Fractions instead of pixels: a remembered fraction changes the panel's size whenever the
  window changes size, which QA read as the panel jumping.
- Horizontal scrolling in the list instead of hiding columns: the request rows would lose
  their right side (status badges) off screen.

## Design

- Width state per pane: `stored ?? default(window)`, then `clamp(min, max(container))`. The
  clamped value is what renders; the stored value changes only on drag, keyboard or reset, so a
  temporary narrow window does not overwrite the choice.
- Drag: on `pointerdown`, record the start x and width, capture the pointer and add `resizing`
  to `<body>` (`user-select: none; cursor: col-resize`). On `pointermove`, set
  `width = start ± dx`: + for the sidebar, − for the detail panel, which grows leftwards. On
  `pointerup` or `lostpointercapture`, store the width and remove the class.
- localStorage keys: `wiretrace.pane.traffic.sidebar`, `wiretrace.pane.traffic.detail`,
  `wiretrace.pane.logs.detail`. An unreadable or out-of-range value counts as absent.

Tests:
- `usePaneWidth`: the default per window width; clamping; a stored value restored; an invalid
  stored value ignored; reset clears storage; a narrow window does not overwrite the stored
  value.
- `Splitter`: keyboard steps, Home/End, Enter resets, ARIA values; a drag changes the width
  and stores it on release.

## Files expected to change

1. `ui/src/components/Splitter.tsx` (new) and `ui/src/logic/paneWidth.ts` (new: hook and
   clamping), with tests.
2. `ui/src/components/TrafficView.tsx`: two splitters; CSS variables on `.main-body`.
3. `ui/src/components/LogsView.tsx`: one splitter on `.lg-body`.
4. `ui/src/styles.css`: grid tracks from variables, `.splitter`, `body.resizing`, container
   queries for the list columns.
5. `docs/user-guide.md`, `docs/images/traffic.png`, `docs/images/logs.png`; `ui/dist` rebuilt.

## Out of scope

- Resizing the log strip under Traffic vertically, or the Rules view's columns.
- Reordering or choosing columns.
- Collapsing the sidebar completely.
- The **Traffic | Logs** view tabs: names, look and position stay as they are.

## Manual test (~5 min)

1. Open the window at 1440 × 900. The detail panel is about 576 px; the Path column is
   narrower than before.
2. Size is already hidden at the default widths (the list is 644 px). Drag list | detail to
   the right until Size comes back (list 760 px, or 860 px with the Device column), then to
   the left: Request and Response widen, Size then Duration (then Device) disappear from the
   list, and the Path column ellipsizes but never vanishes.
3. Drag the sidebar narrower and wider; it stops at 160 and 360 px.
4. Reload: the widths are kept. Double-click each handle: the defaults come back.
5. Tab to a handle and press ←, →, Home, End, Enter.
6. In Logs, drag list | detail; reload; the width is kept.
7. Shrink the window to 1024 px: nothing overlaps, and the list keeps at least 480 px.

## Decided

The view tabs stay **Traffic | Logs**, unchanged (Orchestrator, 2026-10-23). This replaces
the earlier draft's rename to *Network Traffic | Device Logs* with larger tabs and counts.

## Errata

Gate P, 2026-10-24 (Orchestrator):
- The 760/640 px thresholds did not count the 100 px Device column, so in proxy and both modes
  the badges column ran off the list at the default widths and lost almost all of it at the
  480 px minimum. Device mode now uses 860/740 px and hides Device below 580 px.
- At 1440 px the default list is 644 px, under 760 px, so Size starts hidden. The thresholds
  stay; manual test step 2 now starts by widening the list.
- `ui/src/components/TrafficList.tsx` also changes: the Duration, Size and Device cells get
  classes the container queries can select.
