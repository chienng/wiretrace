# Wiretrace window (frontend)

The page behind `./wiretrace start --ui wiretrace` (spec
[`006`](../docs/specs/006-wiretrace-ui-first-slice.md)). React + TypeScript, built with Vite into
`dist/`, which is committed because QA Macs have no Node. QA documentation lives in
[`docs/user-guide.md`](../docs/user-guide.md); this file is for working on the page itself.

## Build and test

```bash
npm --prefix ui ci            # once, or after package-lock.json changes
npm --prefix ui test          # unit tests (vitest)
npm --prefix ui run build     # type check, then ui/dist/; commit the result
```

`git diff -- ui/dist` must be empty after a build of the committed sources.

## Try it with sample data

`npm run dev` answers the `/api/*` calls from `dev/fixtures/` and fakes the live connection:
one new request and one device log line every second. Nothing is captured and nothing leaves
the Mac; all hosts are `example.com` and all tokens are fake. This mode never ships in `dist/`.

```bash
cd ui
npx vite --port 5199 --strictPort --host 127.0.0.1
# open http://127.0.0.1:5199/ ; Ctrl+C stops it
```

Use a free port: 8080, 8081 and 51820 belong to mitmproxy.

| Variable | Effect |
|---|---|
| `WIRETRACE_FIXTURE_MODE=proxy` | Setup shows the Wi-Fi proxy address instead of the WireGuard QR code. |
| `WIRETRACE_FIXTURE_BULK=10000` | Adds 10,000 requests, to check scrolling and filtering speed. |
| `WIRETRACE_FIXTURE_403=1` | Every API call is refused, as without the Terminal link's token. |

For example: `WIRETRACE_FIXTURE_BULK=10000 npx vite --port 5199 --strictPort --host 127.0.0.1`.

### What to check

1. **Traffic list**: rows keep arriving; 4xx/5xx rows are red; `MOCK`, `FAULT` and `SLOW`
   badges; the recording time counts up.
2. **Quick filters and hosts** (left): each one narrows the list, and its count matches.
3. **Search**: plain words (`post orders 500`) filter the list. A mitmproxy expression
   (`~m POST`, `~c 500`) is sent to the server; an invalid one (`~zz`) shows an error under the
   box and leaves the list as it was.
4. **Detail panel**: click a row. Response shows JSON you can fold; Headers, Timing and Logs
   (lines with the same request ID) work. **Copy cURL** and **Copy as mock** put text on the
   clipboard; Copy as mock also shows the mock file path.
5. **Log strip** (bottom): Device / App tabs, level menu, text filter, Auto-scroll. Lines
   with the selected request's ID are highlighted.
6. **Logs view** (title bar, **Logs**): Device / App / Crashes tabs with counts, level
   buttons, search, and a detail panel whose linked request opens back in Traffic.
7. **Pause** freezes the list and shows "N new"; **Clear** hides what is listed now.
8. **Setup**: QR code and configuration text with Copy; "Traffic received" is green.
   With `WIRETRACE_FIXTURE_MODE=proxy`: the Mac's address and port instead.
9. **Faults**: save filter `~u /api/v1/orders`, status `500`: the button shows the active
   count. Status `700`, or a filter that does not start with `~` or `!`, shows an error and
   changes nothing. The mock file list is read-only. (The sample server only imitates
   mitmproxy's checks; the real one uses mitmproxy's own filter parser.)
10. **Report bug** → **Create report**: after about a second, a zip name, counts and the
    "check log lines" note. The sample server creates no file, so **Show in Finder** does
    nothing here.
11. **Reconnect**: stop the dev server for a few seconds and start it again; the page
    reconnects without a reload and nothing is listed twice.
12. With `WIRETRACE_FIXTURE_403=1`: only "Open the link printed in the Terminal." is shown.

Not in this version (spec 006, Out of scope): the log timeline, device picker, previous
sessions, saved filters, the full rules editor, YouTrack.
