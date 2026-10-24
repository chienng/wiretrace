# Spec: a sidebar that hides, a JSON Text view, and a tree of requests

- **Summary**: three changes QA asked for, used to Charles. (A) The Traffic sidebar hides and
  comes back with a `«` / `»` button. (B) A JSON body can be read as the foldable tree (today)
  or as **JSON Text**: the whole body, indented, as plain text. (C) The request list can be shown
  as today's flat **List** or as a **Tree**: host, then path folders, then the requests.
- **Date**: 2026-10-24
- **Repo**: wiretrace
- **Status**: implemented (2026-10-24), merged to `main` for 0.10.3.
  Approved 2026-10-24. Orchestrator choices: all three slices; JSON Text is the
  body re-indented with literals kept as sent (not the raw bytes); in Tree, hosts start open
  and folders closed. Added the same day by the Orchestrator, from QA: padding for the Map local
  form, and a way back from a new rule (Cancel, back to the request it came from); slices D
  (Breakpoint from the right-click menu, request only) and E (replay rows stand out; Replay
  selects the replay), after C.
- **Tier**: M (one repo, UI only, ~14 files plus docs). Gates E, A, R, P. B, C n/a (no data,
  network or log change; the choices stay in the browser). D n/a (one repo).
- **Branch**: `feature/sidebar-json-text-tree`, from `main` (`4bb020c`). One commit per slice;
  slices A, B, C are independent and may merge in any order.
- **Version**: 0.10.3 (Orchestrator's choice at merge; planned as 0.11.0).
- **Builds on**: spec 024 (pane widths), spec 026 (log strip toggle and its storage pattern).

## Goal

QA testers come from Charles and asked for three things:

1. The sidebar takes 160–360 px they want for the list and the detail panel while reading
   traffic, and there is no way to put it away.
2. A JSON response is only shown as a tree. They cannot select the whole body, read it as one
   piece of text, or find a value with ⌘F inside folded nodes.
3. Requests are only a flat list in time order. With many endpoints they want them grouped by
   host and path, as Charles' *Structure* view does.

## Acceptance criteria

### Slice A — sidebar toggle

- [ ] A button at the left end of the Traffic filter bar, before the search box:
      **`«`** while the sidebar is shown (tooltip and label "Hide the sidebar"), **`»`** while it
      is hidden ("Show the sidebar"). It has `aria-expanded`, and `aria-controls` pointing at the
      sidebar while the sidebar is rendered.
- [ ] Hidden: the sidebar and its resize handle are not rendered; the list and the detail panel
      share the freed width as if the sidebar were 0 px wide (default detail width and its room
      follow the spec 024/026 formulas with `sidebar = 0`).
- [ ] Showing it again restores the sidebar at its remembered width, scrolled to the top.
- [ ] Filters chosen in the sidebar (quick filter, host, device, saved filter) stay applied
      while it is hidden and stay visible as chips in the filter bar, which already show them.
- [ ] The choice is remembered by the browser: localStorage `wiretrace.pane.traffic.sidebar.state`,
      value `hidden`; anything else means shown. Default shown. The width key
      `wiretrace.pane.traffic.sidebar` is untouched.
- [ ] The Logs and Rules views have no sidebar and do not change.

### Slice B — JSON and JSON Text

- [ ] When a body parses as JSON (today's test: `tryParseJson`), a two-button segmented control
      above it: **JSON** | **JSON Text**. Bodies that are not JSON show no control and do not
      change.
- [ ] **JSON** is today's foldable tree, unchanged.
- [ ] **JSON Text** is the whole body re-indented with 2 spaces, one value per line, as plain
      selectable text (`<pre>`). Every literal is kept exactly as sent: numbers such as
      `12345678901234567890` or `1.50`, and string escapes such as `\u00e9`, are not rewritten.
      Empty `{}` and `[]` stay on one line.
- [ ] Re-indented text over 300,000 characters shows the first 300,000 with today's
      "Showing the first … characters" note. The truncated-body note shows in both views.
- [ ] The control is on every `BodyView`: Response, Request, a breakpoint's *Original*, and a
      WebSocket message. One choice for all of them, remembered by the browser: localStorage
      `wiretrace.body.view`, value `text`; anything else means JSON. Default JSON.
- [ ] Switching views keeps the body's scroll at the top; the tree's fold state is not kept
      when switching back (the tree reopens at its default depth, as when a request is selected).

### Slice C — List and Tree

- [ ] A segmented control at the right end of the Traffic filter bar: **List** | **Tree**.
      Remembered by the browser: localStorage `wiretrace.pane.traffic.layout`, value `tree`;
      anything else means List. Default List.
- [ ] **List** is today's list, unchanged.
- [ ] **Tree** shows the same rows as List would (search, quick filter, host, device, *Show
      encrypted* and Pause all apply first), grouped:
  - a **host** node per `scheme://host` (`:port` added when it is not the scheme's default);
  - **folder** nodes for each path segment except the last; the query string is never a level;
  - a **request** leaf named after the last segment plus its query (`42?expand=1`), or `/`
    when the last segment is empty. `/v1/users` is a leaf `users` under folder `v1`, while
    `/v1/users/42` is a leaf `42` under folders `v1` › `users`; both appear under `v1`;
  - an encrypted connection is a leaf **Encrypted connection** directly under its host node.
- [ ] Children appear in the order their first request arrived. A new request never moves an
      existing row; it is appended to its folder, or creates the folder at the end.
- [ ] Host and folder rows show a fold triangle, the name, and the number of requests below
      them. Request leaves show method, status, name, duration, size and the badges, as a List
      row does (same colours, *Paused*, *Mock*, *Fault*, …); encrypted leaves show the lock and
      the tag.
- [ ] New host nodes start open, new folders start closed. Open/closed state lasts while the
      window is open (not across reloads) and survives switching List ↔ Tree.
- [ ] Clicking a request leaf selects it: the detail panel, Report, Compare, the log strip and
      the right-click menu behave exactly as in List. Clicking a host or folder row opens or
      closes it and moves the cursor there; the detail panel keeps the selected request.
- [ ] Right-click a host or folder: **Expand all below**, **Collapse all below**; on a host also
      **Show only this host** (sets the host filter, as the sidebar does).
- [ ] Keyboard, with the tree focused: ↑/↓ move the cursor through visible rows; → opens a
      closed node, or moves to its first child when open; ← closes an open node, or moves to its
      parent; Enter or Space opens/closes a node. Moving the cursor onto a request selects it.
- [ ] When something else selects a request (a replay's *the original request* link, or a
      selection made in List before switching), its host and folders open and it scrolls into
      view.
- [ ] The tree does not follow new requests (List still does); the list's follow choice is kept.
- [ ] 10,000 requests stay responsive: the tree is flattened to visible rows and rendered by the
      existing `VirtualList` at the list's 28 px row height.
- [ ] Narrow widths: duration and size columns hide below the same container widths as List;
      name and badges stay.

### Slice D — Breakpoint from the right-click menu

Added by the Orchestrator after QA asked how to set a breakpoint, with Charles' right-click
**Breakpoints** as the reference; approved 2026-10-24 with the request only (Charles pauses
both). Today it takes four steps: *New rule from this request*, action *Pause at a
breakpoint*, pick the phase, *Save rule*.

- [ ] Right-click a request (List or Tree) → **Breakpoint**: adds, in one click, a rule at the
      top of the rules that pauses that request's method, host and path (query ignored, as
      *New rule from this request* does) at **the request** only (`pause_at: request`). A toast
      says so and names the rule; the rule is then like any other in Rules, where the tester can
      switch it to the response or both.
- [ ] In Tree, right-click a host → **Breakpoint on this host** (any method, path `/*`) and a
      folder → **Breakpoint on this folder** (any method, `/v1/users/*`).
- [ ] When an enabled pause rule with exactly that method, host and path (no body text) already
      exists, the item reads **Remove breakpoint** and deletes that rule.
- [ ] Disabled, with the reason as a tooltip, like the other items: a host that is not one of
      the preset's API hosts, a previous session, an encrypted connection (no item at all).
- [ ] A rules file changed meanwhile is reloaded and the click is refused with the message the
      Rules view gives today; nothing is overwritten.
- Files: `ui/src/logic/rules.ts` (`breakpointRule`, `findBreakpoint`, + tests in
  `rules.test.ts`); `ui/src/components/TrafficList.tsx` (`useTrafficMenus`: the item);
  `ui/src/components/TrafficTree.tsx` (host and folder items); `docs/user-guide.md`.
- Manual test: right-click a request → **Breakpoint**; make the request again from the app: it
  waits, orange and *PAUSED*. Right-click it → **Remove breakpoint**; the next one goes through.
- Out of scope: a ⏸ icon or stripe on held rows, a "changed by rules" filter, marking requests
  a rule matches before it fires (offered and not chosen, 2026-10-24).

### Slice E — Replays stand out, and Replay shows its result

Added and approved by the Orchestrator, 2026-10-24: a replay carries only the *REPLAY* badge at
the right end of its row, which a narrow badges column or other badges can hide.

- [ ] A replay row (`replay_of` set) has a 3 px blue stripe (`--blue`) at its left edge, in List
      and on Tree leaves; the *REPLAY* badge stays. On the selected (blue) row the stripe is white
      at 60 % so it still shows; on a paused (orange) row it shows over the orange.
- [ ] Other rows, encrypted connections and the original request are unchanged.
- [ ] After **Replay** succeeds (detail panel or right-click menu), the window selects the new
      replay as soon as it is listed: the detail panel shows it (*REPLAY*, *Replay of the
      original request*) and the list scrolls to it (in Tree its host and folders open). QA
      reported that nothing showed the replay was sent: the panel stayed on the original, the
      row was added out of view, and the only sign was a 2.2 s toast at the bottom. The server
      already answers with the replay's `id`. If the tester selects another request before the
      replay is listed, the replay is not selected. While Pause is on, the replay is listed
      anyway, as *Open in Traffic* does. The toast stays.
- Files: `ui/src/components/TrafficList.tsx` (`replay` class on the row; the menu's Replay
  selects the replay); `ui/src/components/TrafficTree.tsx` (same class on leaves);
  `ui/src/components/DetailPanel.tsx` (Replay selects the replay); `ui/src/store.tsx`
  (`replaySent`: select now if listed, else when the flow arrives; a selection in between
  cancels it); `ui/src/styles.css`; + `ui/src/store.test.ts` (selected now; selected on arrival;
  cancelled by another selection; added to the paused list), a new
  `ui/src/components/TrafficList.test.tsx` (static render: a replay row has the class, another
  row does not), and the same check in `TrafficTree.test.tsx`.
- Manual test: replay a request (its detail panel, **Replay**): the replay is selected and in
  view, with the stripe, in List and in Tree; scroll the list up and replay from the right-click
  menu: the list scrolls down to it.
- Out of scope: marking the original request, putting *REPLAY* first among the badges, a
  *Replays* quick filter (offered and not chosen).

### Map local dialog padding

- [ ] In *Map local*, the lead line, the fields, the *Answer with it now* box, the warning and the
      footer start 26 px from the sheet's left edge and end 26 px from its right, like the title
      and like *Report bug*. Today `.sheet.wide` has no padding and only its title is padded, so
      everything below the title touches the sheet's edge.

### A way back from a new rule

- [ ] A new rule's editor has **Cancel** beside *Save rule* (a saved rule keeps *Delete* and
      gets no Cancel). Cancel drops the unsaved rule. When the rule came from a request
      (*New rule* in the detail panel or *New rule from this request* in the right-click menu),
      Cancel also goes back to Traffic with that request selected; after *+ New rule* it stays
      in Rules. Its tooltip says which. Today the only way out is the title bar's *Traffic* tab,
      which leaves the draft behind without a word.

### Docs

- [ ] The user guide's *Wiretrace window* section describes the sidebar toggle, JSON Text, and
      List | Tree. `ui/dist` rebuilt.

## Approach

**A.** `TrafficView` holds `sidebarHidden` (loaded/stored like the log strip in spec 026, via two
small helpers). Hidden → do not render `Sidebar` or its `Splitter`, set `--sidebar-w: 0px`, and
pass `0` instead of `sidebar.width` to the detail room. The `usePaneWidth` state for the
sidebar is kept, so its width comes back.

**B.** A new `formatJsonText(text)` in `ui/src/logic/jsonText.ts`: a single-pass tokenizer
over the original text (strings with escapes, `{}[]:,`, other literals copied verbatim)
emitting newlines and indentation. It only runs after `tryParseJson` succeeded, so input is
valid JSON. `BodyView` shows the segmented control when parsed, and renders the tree or the
text.

**C.** `ui/src/logic/tree.ts`: `buildTree(rows)` → host/folder/leaf nodes in first-arrival order
(a `Map` per node keeps insertion order); `visibleRows(tree, open)` flattens to
`{ kind, depth, key, row?, count }`; `ancestorsOf(tree, id)`; `treeKey(...)` for keyboard moves.
`TrafficTree.tsx` renders the flat rows with `VirtualList`. The request/encrypted menus and
their actions move out of `TrafficList` into a shared `useTrafficMenus()` hook so both views
use one copy. `VirtualList` gains an optional `onKey(e)` for keys other than ↑/↓.

Rejected:
- A: an icon at the sidebar's own top edge to hide it, and another to show it: two places for
  one toggle, and the "show" one would have to float over the list.
- A: collapsing the sidebar to a narrow icon rail: icons for hosts and saved filters do not
  exist and would be guesses.
- B: `JSON.stringify(JSON.parse(text), null, 2)`: changes large numbers, `1.50` and escapes,
  so JSON Text would not be what the server sent.
- B: a third *Raw* view: not asked for; the Request and Response tabs of a non-JSON body
  already show raw text.
- C: sorting tree children alphabetically: rows would jump while recording, and Charles orders
  by first arrival too.
- C: rendering the tree with nested DOM elements: slow at thousands of requests, and the list's
  virtualisation and keyboard handling would be duplicated.

## Design (slice C: cursor and selection)

State: `open: Set<nodeKey>` (in the store's `ui`, so it survives List ↔ Tree), `cursor:
nodeKey | null` (local to `TrafficTree`), and the existing `ui.selectedFlowId`.

- Node keys: host `h:<scheme>://<host>[:port]`; folder `<parent>/<segment>`; leaf `f:<flow id>`
  or `t:<tunnel id>`. Keys are stable across rebuilds.
- Invariant 1: if `cursor` is a leaf, its id equals `selectedFlowId`.
- Invariant 2: a folder cursor never changes `selectedFlowId`.
- Invariant 3: `cursor` is always a visible row, or null. When the cursor's node disappears
  (filter, close of an ancestor), the cursor moves to the nearest visible ancestor, or null.
- `selectedFlowId` changes from outside the tree → open its ancestors, set `cursor` to its leaf,
  reveal it. When the selected request is filtered out, `cursor` is null and nothing is opened.
- Close a node that contains the selected request → the request stays selected (detail panel
  unchanged); the cursor moves to the closed node.
- New host nodes are added to `open` when first built; folders are not.
- Keyboard transitions (`treeKey(visible, cursor, key, open)` → `{ cursor, open }`):
  - ↓/↑: next/previous visible row; at the ends, unchanged.
  - →: closed node → open it; open node → first child; leaf → unchanged.
  - ←: open node → close it; leaf or closed node → parent; host → unchanged.
  - Enter/Space: node → toggle; leaf → unchanged.

Tests (`tree.test.ts`):
- grouping: host with and without a default port; folders per segment; query not a level; `/`
  and trailing-slash leaves; `/v1/users` and `/v1/users/42` both under `v1`; encrypted rows
  under their host;
- order is first arrival and a new request never moves an existing row;
- counts per node; `visibleRows` hides children of closed nodes and gives depths;
- `ancestorsOf` for a leaf, and null for a missing id;
- every keyboard transition above, including the ends and the host on ←;
- a vanished cursor moves to the nearest visible ancestor.

## Tests

- `ui/src/logic/viewPrefs.test.ts`: each of the three choices loads `hidden`/`text`/`tree` as
  set and anything else (absent, unreadable, other value) as the default; storing the default
  removes the key; a browser that refuses storage does not throw.
- `ui/src/logic/jsonText.test.ts`: nested objects and arrays; empty `{}` `[]`; strings with
  `\"`, `\\`, `\u00e9`, and `{`/`,` inside them; `12345678901234567890`, `1.50`, `-0`, `1e10`
  kept verbatim; already-indented and minified input give the same output; whitespace around
  the body ignored.
- `ui/src/components/BodyView.test.tsx` (static render, as `WsMessages.test.tsx`): a JSON body
  shows the control with JSON on by default; with the stored choice `text` it renders the
  indented text; a non-JSON body shows no control.
- `ui/src/logic/tree.test.ts`: as in *Design*.
- `ui/src/components/TrafficTree.test.tsx` (static render): host, folder and leaf rows with the
  counts; a selected leaf has `aria-selected="true"`.
- `ui/src/components/MapLocalDialog.test.tsx` (static render): the content and the footer are
  inside the padded `.ml-form` of the wide sheet.
- `ui/src/components/RuleEditor.test.tsx` (static render): a new rule shows Cancel with its
  tooltip and no Delete; a saved rule shows Delete and no Cancel.
- Existing `paneWidth.test.ts` and `LogStrip.test.ts` keep passing unchanged.

## Files expected to change

1. `ui/src/logic/viewPrefs.ts` (new, + test): load/store for the sidebar, body view and layout
   choices.
2. Slice A: `ui/src/components/TrafficView.tsx` (toggle button, hidden sidebar, room with
   sidebar 0); `ui/src/styles.css` (toggle button).
3. Slice B: `ui/src/logic/jsonText.ts` (new, + test); `ui/src/components/BodyView.tsx` (+ new
   `BodyView.test.tsx`); `ui/src/styles.css` (control above `.code`).
4. Slice C: `ui/src/logic/tree.ts` (new, + test); `ui/src/components/TrafficTree.tsx` (new, +
   test); `ui/src/components/TrafficList.tsx` (menus moved to an exported `useTrafficMenus`);
   `ui/src/components/VirtualList.tsx` (optional `onKey`); `ui/src/components/TrafficView.tsx`
   (List | Tree control, renders one or the other); `ui/src/store.tsx` and `ui/src/types.ts`
   if needed (`ui.treeOpen`); `ui/src/styles.css` (tree rows, indentation, container steps).
5. Map local padding: `ui/src/components/MapLocalDialog.tsx` (content in a `.ml-form` wrapper,
   + new `MapLocalDialog.test.tsx`); `ui/src/styles.css` (`.ml-form` padding, and a wide sheet's
   `.lead` padded like its title).
6. Way back from a new rule: `ui/src/components/RuleEditor.tsx` (Cancel for a new rule, + new
   `RuleEditor.test.tsx`); `ui/src/components/RulesView.tsx` (a new rule remembers the request
   it came from; Cancel goes back to it).
7. `docs/user-guide.md`; `ui/dist` rebuilt.

## Out of scope

- A keyboard shortcut for the sidebar, or a sidebar in Logs or Rules.
- A JSON Text view with syntax colours, line numbers, or a copy button; changing the tree's
  handling of large numbers.
- A Raw, Hex or Headers-and-body view.
- Tree for the Logs view; a Device column in the tree; sorting or searching inside the tree
  beyond the existing filters; remembering open folders across reloads.
- Server, session format, report or HAR changes.

## Manual test (~5 min)

1. Start a session with traffic to at least two hosts. Click **«**: the sidebar goes, the list
   widens, the button reads **»**. Choose a host in the sidebar first and repeat: its chip
   stays and the list stays filtered. Reload: still hidden. Click **»**: the sidebar is back
   at its width.
2. Select a JSON response. Click **JSON Text**: the body is indented text; select all of it
   with the mouse; ⌘F finds a value that was folded in the tree. Select another request: still
   JSON Text. Open the *Request* tab of a JSON POST: also JSON Text. Reload: still JSON Text.
3. Find a response with a long ID number and compare JSON Text with the raw body
   (`./wiretrace report` or Copy as mock): digits identical.
4. Click **Tree**: hosts open, folders closed, counts shown. Open folders down to a request and
   click it: the detail panel shows it. Use ↑/↓/←/→ through the tree. Right-click a host →
   **Expand all below**, then **Collapse all below**.
5. While recording, watch a folder: new requests are appended, nothing above moves.
6. Select a request in **List**, switch to **Tree**: it is open and in view. Switch back:
   List as before.
7. Right-click a request → **Map local…**: the text under the title, the fields, the blue box,
   the warning and the footer are inset from the sheet's edges like the title.
8. Select a request, click **New rule**, then **Cancel**: back in Traffic with that request
   selected, and no new rule in Rules. In Rules, **+ New rule** then **Cancel**: still in Rules,
   the editor empty.
