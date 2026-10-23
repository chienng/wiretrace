# Spec: see WebSocket messages in the window

- **Summary**: a WebSocket row in Traffic gets a **Messages** tab. It lists every message
  the app sent (↑) and received (↓), live, with time, type and size. A selected message opens in
  the body viewer, so JSON is readable. A text filter and a Sent/Received switch narrow the
  list. Previous sessions show their messages too. Messages are read from mitmproxy's flow;
  nothing new is stored on disk.
- **Date**: 2026-10-23
- **Repo**: wiretrace
- **Status**: approved (2026-10-23). Implementation is in the working tree; Gate P is open (2026-10-24).
- **Tier**: M (one repo; a new read endpoint that serves message content to the window, live
  updates, and a new tab). Gates E, A, B (the endpoint: same guard as the request detail, size
  limits), C (no message content or address in logs), R, P. D n/a (one repo).
- **Branch**: `feature/websocket-messages`, from `main` once `feature/readme-screenshots-0.10`
  is merged. Independent of specs 023 and 024. If spec 024 lands first, the tab uses its wider
  detail panel; nothing here depends on it.
- **Version**: rides with the next release (0.11.0).

## Goal

QA test chat, notifications and live updates that run over WebSocket. Today Wiretrace lists the
connection (`GET 101 /ws/notifications`) and its handshake headers, and saves the messages in
`flows.mitm` and the bug report's HAR. In the window they can't be seen: QA cannot check
what the app sent, what the server pushed, or in which order, without exporting a HAR.

## Acceptance criteria

### List row

- [ ] A WebSocket row shows its message count in the Size column ("↕ 128"), updated live while
      the connection is open. When it closes, the Duration column shows how long it was open.

### Messages tab

- [ ] Selecting a WebSocket row opens the **Messages** tab, the first tab for those rows
      (Request, Response, Headers and Timing stay, for the handshake). Other rows have no
      Messages tab.
- [ ] Each message is one row:
      - direction: **↑** sent by the app, **↓** received from the server;
      - time (clock time with milliseconds, like Traffic);
      - type: *text* or *binary*;
      - size;
      - a one-line preview: text with its first line, binary as "binary, 312 B".
- [ ] Tags show where Wiretrace or mitmproxy changed the flow: **dropped** (the message was not
      passed on) and **injected** (sent by mitmproxy, not by the app or the server).
- [ ] New messages appear while the tab is open. The list follows the newest one unless the
      tester scrolled up or selected a message, like the log strip's *Auto-scroll*.
- [ ] Selecting a message shows it below the list in the existing body viewer:
      - JSON pretty-printed and folding, other text as text;
      - binary as a hex and ASCII dump of its first 4 KiB.
      - *Copy* copies the message: text as is, binary as hex.
- [ ] A search box filters messages by text: case-insensitive, over text messages only. An
      **All | Sent | Received** switch filters by direction. The count reads "12 of 128".
- [ ] The tab's header line says the state of the connection:
      - "Open · 128 messages";
      - "Closed by the server · code 1000 (normal) · 128 messages";
      - "Closed by the app · code 1001 · reason: going away".
- [ ] **Previous sessions**: the same tab works on a session opened from *Previous sessions*,
      read-only, from `flows.mitm`.

### Limits

- [ ] The list endpoint returns at most 500 messages per call, and at most 64 KiB of each
      message's content. The page asks for more as the tester scrolls.
- [ ] One message is served in full only on selection, up to the same 2 MiB as request bodies
      (`MAX_BODY_BYTES`). Beyond that the viewer says "Larger than 2 MiB: shown up to 2 MiB; the
      HAR in a bug report has it".
- [ ] The page keeps at most the newest 5,000 messages of the open connection in memory. Older
      ones are fetched again when scrolled to, and the list says "Showing the newest 5,000;
      scroll up to load older".
- [ ] A connection pushing hundreds of messages a second does not slow the window. The list's
      live update is batched with the existing 100 ms update, one count per connection per
      batch, and the Messages tab fetches only what is new.

### Unchanged

- [ ] WebSocket rows still cannot be replayed. Rules still apply to the handshake only.
- [ ] `flows.mitm`, the HAR and the bug report's masking of text messages are unchanged.

## Approach

mitmproxy already keeps each connection's messages in `flow.websocket.messages`. Each message
has `from_client`, `type` (text or binary), `content`, `timestamp`, `dropped` and `injected`.
Wiretrace does not copy them. The window's server:

1. adds a `websocket_message` hook that calls the existing `track(flow)`, so the row's summary
   (now with `ws_messages`, the count) goes out with the next 100 ms batch;
2. serves `GET /api/flows/<id>/messages?from=<index>&limit=<n>&dir=<all|sent|received>&q=<text>`:
   a page of message summaries with previews, and the total and matched counts;
3. serves `GET /api/flows/<id>/messages/<index>`: one message's content, bounded as above.

The page fetches when the open connection's count grows, from the last index it has.

Rejected:
- Pushing every message's content over the updates socket: every open window would receive
  every message of every connection, opened or not. That is a lot of traffic for a chatty
  socket, and it would bypass the per-request read limits.
- Storing messages in a second file next to `flows.mitm`: a duplicate copy of possibly
  sensitive content, for no gain; mitmproxy's flow already holds them.
- Showing messages inside the Response tab: the handshake response and the message stream are
  different things, and QA look for a list of messages.

## Design

- **Index**: a message's index is its position in `flow.websocket.messages`. mitmproxy only
  appends, so an index stays valid for the life of the flow. `from` is the first index wanted.
  The response carries `total`, so the page knows when it is up to date.
- **Filtering on the server**: `dir` and `q` are applied before paging. `matched` counts all
  matching messages, and each item carries its `index`, so a filtered page still opens the
  right message. `q` is at most 200 characters (as `SEARCH_MAX`). It searches text messages
  only, over their first 64 KiB, in a worker thread like *Search*.
- **Guard**: both endpoints are `Guarded`, like `FlowDetail`: token cookie, `Host`, and nothing
  listening beyond `127.0.0.1`. An unknown id gives 404. A flow that is not a WebSocket, or an
  index out of range, gives 400.
- **Previous sessions**: the endpoints read from the store the request detail uses: live, or
  the opened session with `?session=`.
- **Page state**: `messages: Map<index, Summary>` for the open flow, trimmed to the newest
  5,000. Switching rows clears it. A fetch already in flight for an old row is discarded when
  it returns (a generation counter, as `viewing.ts` does).
- **Privacy**: no log line contains message content, a preview, the flow's host or the
  client's address. Errors log the exception type only, as the rest of the add-on does.

Tests:
- Hook: a message updates the summary's `ws_messages`, and many messages in one batch send
  one summary.
- List endpoint: paging (`from`, `limit` clamped to 500), `total` and `matched`; direction and
  text filters; previews truncated at 64 KiB; binary previews; `dropped` and `injected` tags;
  404 and 400 cases; the guard (no cookie gives 403); a previous session.
- Message endpoint: text, JSON, binary (hex); larger than 2 MiB is truncated and flagged.
- No content in logs: a failure while serving logs the exception type only.
- UI: the Messages tab only for WebSocket rows and first for them; live append and
  auto-scroll stop when the tester scrolls up; the filter count; the 5,000 trim; a stale fetch
  is discarded on a row switch; the closed-state header texts.

## Files expected to change

1. `addons/wiretrace_ui.py`: `websocket_message` hook; `ws_messages` and close fields in the
   summary and detail; `WsMessages` and `WsMessage` handlers and routes.
2. `ui/src/types.ts`: `ws_messages` on `FlowSummary`; message summary and content types.
3. `ui/src/api.ts`: the two calls.
4. `ui/src/components/WsMessages.tsx` (new): list, filter, viewer, live follow.
5. `ui/src/components/DetailPanel.tsx`: the Messages tab for WebSocket rows.
6. `ui/src/components/TrafficList.tsx`: the "↕ n" size cell.
7. `ui/src/styles.css`: the message list rows and direction marks.
8. `ui/dev/fixtures/` and `ui/dev/fake-socket.js`: a fixture WebSocket with text, JSON and
   binary messages and a live one that keeps sending, for the dev server and screenshots.
9. Tests: `tests/test_wiretrace_ui.py`, `ui/src/components/WsMessages.test.tsx` (new).
10. `docs/user-guide.md` (Traffic section), `README.md` (features list); `ui/dist` rebuilt.

## Out of scope

- Rules on messages: mock, block or rewrite a message, or breakpoints on messages.
- Sending a message from the window.
- Socket.IO, STOMP or other framing on top of WebSocket: shown as the raw text.
- Server-Sent Events (`text/event-stream`). That is a normal response, already shown as one
  body.
- Binary decoders such as protobuf or MessagePack.

## Manual test (~5 min)

1. Run the dev server with the fixtures, select `GET 101 /ws/notifications`: the Messages tab
   is open, with ↑ and ↓ rows, and the count grows while the live fixture sends.
2. Scroll up: following stops. Scroll to the bottom: it follows again.
3. Select a JSON message: it is pretty-printed. Select a binary one: a hex dump. Copy both.
4. Type in the filter and switch to *Received*: "n of 128" changes, and opening a filtered row
   shows the right message.
5. With a real phone: open the app's chat or notifications screen and check the messages
   against what the app shows.
6. Open the session from *Previous sessions*: the same messages, read-only, and the header
   says how the connection closed.
