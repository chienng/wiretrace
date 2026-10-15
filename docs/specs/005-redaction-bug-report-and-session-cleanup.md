# Spec: redaction, bug report zip, and old-session cleanup

- **Date**: 2026-10-14
- **Risk**: high — decides which secrets leave the Mac in files QA attach to tickets.
  Needs a code, security and privacy review and a runtime check.
- **Repo**: wiretrace
- **Status**: implemented
- **Branch**: `main` (as specs 003 and 004)
- **Related**: [`PLAN.md`](../../PLAN.md) §8 Phase 1 (F5, F11), §9.2 (`redact` preset key),
  §9.4, §11 ("exports are redacted by default, and sessions older than N days are deleted
  automatically"); spec 002 (launcher FINALIZING state, session folder); spec 003 (fault and
  mock comments); spec 004 (log files; "redaction of log content and the bug-report zip"
  deferred here)

## Goal

What QA attach to a bug ticket is safe to share: tokens, passwords and cookies are
replaced by `***` in `flows.har` and in a new one-command bug report zip, which also says
which requests failed. Sessions on the Mac do not pile up: they are deleted 14 days after
they started.

## Acceptance criteria

- [ ] After Ctrl+C, `<session>/flows.har` has `***` as the value of every `Authorization`,
      `Proxy-Authorization`, `Cookie` and `Set-Cookie` header, of every request and
      response cookie, and of the default fields (`password`, `access_token`,
      `refresh_token`, `id_token`, `client_secret`) wherever they appear: JSON request and
      response bodies (any depth), URL-encoded form bodies, query strings, the `Location`
      header and WebSocket text messages. `flows.mitm` still holds the original values.
- [ ] Field names match ignoring case, `_` and `-`: `accessToken`, `AccessToken` and
      `access-token` are all masked by `access_token`.
- [ ] A preset `redact:` block adds header names (`headers:`) and field names
      (`json_fields:`) to the defaults. The defaults cannot be turned off. An unknown key
      or an invalid name under `redact:` stops the start with a message naming it.
- [ ] A body that is not JSON or form data, and a binary (base64) body, is left as it
      was. A JSON body with nothing to mask keeps its exact original text.
- [ ] `./wiretrace report <session>` (folder name or path; no argument = the most recent
      session) writes `<session>/<session-name>-report.zip`, holding one folder
      `<session-name>/` with `summary.md`, `flows.har` (rebuilt from `flows.mitm` and
      masked with the preset's rules as they are now), `device.log.jsonl` and
      `app.log.jsonl` when they have lines (masked, see below), and `meta.json`.
      It never contains `flows.mitm`.
- [ ] In the zip's log files, the text of each line is masked by pattern: `<header>: …`
      to the end of the line, `Bearer <token>`, `"<field>": "…"` and `<field>=…` /
      `<field>: …`. The log files in the session folder are unchanged.
- [ ] `summary.md` gives the session (preset, target, mode, start and end, status,
      Wiretrace version), counts (requests, failed, mocked, faulted, log lines), the masked
      header and field names, and a table of failed requests (status ≥ 400, or no response):
      time, method, host and path without the query, status or "no response" with the
      error, duration, request ID, and the Wiretrace fault or mock note, so an injected 500
      is never mistaken for a backend bug. At most 100 rows, then "and N more".
- [ ] The report works on a session that is still running or was killed (a cut-off
      `flows.mitm`): it uses the flows that could be read and says the file ends early.
- [ ] The report prints the zip path, the counts, and "Log lines are masked by pattern
      only; check them before sharing." A failure (unknown session, nothing to report,
      write error) prints why, exits 1 and leaves no partial zip. A preset that can no
      longer be loaded gives a warning, and the defaults are still applied.
- [ ] `./wiretrace start` deletes session folders that started more than 14 days ago, before
      creating its own, and says how many it deleted. It deletes only folders directly in
      `sessions/` whose name is a Wiretrace session name and that contain `meta.json`; a
      symlink, a renamed folder or any other file is never touched.
- [ ] After a session is saved, the launcher prints the `./wiretrace report <name>` command.

## Approach

### Rules (`cli/redact.py`, new; no mitmproxy import)

`Rules(headers, fields)`: header names compared case-insensitively; field names
compared after `normalize(name) = name.lower()` without `_` and `-`. `rules_for(preset)`
returns the defaults plus the preset's additions; `rules_for(None)` the defaults.
`MASK = "***"`.

- `redact_har(har: dict, rules) -> (dict, int)`: a masked copy and the number of values
  masked. Tolerates any missing key (an entry with no `request`, no `response`, no
  `content`). Per entry:
  - `request.headers`, `response.headers`: value of a listed name → `***`. The `Location`
    header value and `response.redirectURL` also go through `redact_url`.
  - `request.cookies`, `response.cookies`: every `value` → `***` (cookies are always
    masked, as `Cookie` and `Set-Cookie` are defaults).
  - `request.url` → `redact_url`; `request.queryString` entries whose name matches → `***`.
  - `request.postData`: `params` entries whose name matches → `***`; `text` → `redact_body`
    with the `mimeType`.
  - `response.content.text` → `redact_body`, unless `content.encoding == "base64"`.
  - `_webSocketMessages[].data` → `redact_json_text` when `opcode == 1` (text).
- `redact_json_text(text)`: `json.loads`; on failure return the text unchanged. Walk
  dicts and lists; a matching key's value (any type) becomes `"***"`. Re-serialize with
  `json.dumps(..., ensure_ascii=False)` **only if something was masked**.
- `redact_body(text, mime)`: JSON first; if the MIME type is
  `application/x-www-form-urlencoded`, mask matching fields with `parse_qsl` /
  `urlencode`, again only re-encoding when something changed.
- `redact_url(url)`: mask matching parameters in the query and in a `#a=b&…` fragment;
  unchanged URLs are returned as they were.
- `mask_text(text, rules)` for log lines, in this order, case-insensitive:
  1. `\b<header>\s*:\s*[^\r\n]*` → `<header>: ***` (header values contain spaces).
  2. `\bBearer\s+[A-Za-z0-9._~+/=-]+` → `Bearer ***`.
  3. For every header and field name, `"<name>"\s*:\s*"(?:[^"\\]|\\.)*"` →
     `"<name>": "***"`, and `"<name>"\s*:\s*[^\s,}\]]+` (a number or literal).
  4. For every field name, `\b<name>\s*[=:]\s*[^\s&,;"'}\]]+` → `<name>=***` (keeping the
     separator found). A field's pattern allows an optional `_` or `-` between its
     normalized letters, so it matches the same spellings as the JSON rule.
  `mask_log_line(line, rules)`: a JSON object line gets `mask_text` on its `message`
  value (the only free-text field in spec 004's line format) and is re-serialized only if
  changed; a line that is not a JSON object gets `mask_text` on the whole line.

Rejected: masking in an addon while capturing (PLAN wants live traffic in mitmweb to stay
complete); masking `flows.mitm` (developers lose the originals); masking non-JSON bodies
by regex (false confidence on formats we cannot parse; logs are the exception because
they are free text by nature, and the report says they are pattern-masked only).

### Preset (`cli/preset.py`)

```yaml
redact:                        # optional; adds to the defaults, cannot remove them
  headers: [X-Api-Key]
  json_fields: [otp, login_token]
```

`redact` must be a mapping with only `headers` and `json_fields`, each a list. Header
names must be RFC 9110 tokens (`_HEADER`); field names must match
`[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`. Unknown keys under `redact` are an error (a typo would
otherwise silently turn masking off); unknown top-level keys stay ignored. `Preset` gains
`redact_headers: tuple[str, ...] = ()` and `redact_fields: tuple[str, ...] = ()`.

### Launcher (`cli/start.py`, `cli/session.py`)

- PREPARE, after the port check and before `session.create`:
  `session.remove_old(sessions_dir, now)` → print `Deleted N old session(s) (older than 14
  days).` when N > 0.
- FINALIZING: mitmdump writes the HAR to `<session>/.flows.har.tmp`; the launcher reads
  it, `redact_har` with `rules_for(preset)`, writes `.flows.har.masked` and `os.replace`s
  it to `flows.har`. Both temporary files are removed on every path. A HAR that cannot be
  read or masked is a HAR failure: `flows.har was not written (could not mask it); flows.mitm
  is kept.`, exit 1, as for any HAR failure today. An interrupted conversion behaves as today.
- After `Session saved: …`: `For a bug ticket: ./wiretrace report <folder name>`.
- `session.KEEP_DAYS = 14`; `session.NAME` regex
  `(\d{4}-\d{2}-\d{2}_\d{6})_<preset name>_(android|ios|android-emu|ios-sim|device)`;
  `session.started(name) -> datetime | None` (naive local time, as the name is written);
  `session.list_sessions(sessions_dir)` (session folders by name, oldest first);
  `session.remove_old(sessions_dir, now, keep_days=KEEP_DAYS) -> int`.

### Report (`cli/report.py`, new; `cli/__main__.py`)

`./wiretrace report [SESSION]`. `run(session_arg, sessions_dir, presets_dir, now=None) -> int`.

1. Resolve: no argument → last of `list_sessions`; an argument naming an existing
   directory → that path; else `sessions_dir / arg`. It must contain `meta.json`.
2. Rules: `load_preset(meta["preset"])`; on `PresetError`, warn and use `rules_for(None)`.
3. Flows: `mitmproxy.io.FlowReader` over `flows.mitm` (imported inside the function, so
   `doctor` keeps working without mitmproxy), keeping `HTTPFlow`s; on
   `FlowReadException`, keep what was read and note `cut_off`.
4. HAR: `SaveHar().make_har(flows)` → `redact_har`.
5. Summary from the flows (not the HAR, which has no comments): failed = no response, or
   status ≥ 400; request ID = the preset's `request_id_header` (default if the preset failed)
   on the request, else the response; note = the comment parts starting with `fault:` or
   `mock:`, shown as `Wiretrace fault: status 500`. Mocked / faulted counts from the same
   comment parts. Table cells escape `|` and newlines.
6. Logs: each line through `mask_log_line`.
7. Nothing to report (no HTTP flow and no log line) → `Nothing to report: the session has
   no traffic and no log lines.`, exit 1.
8. Write `<name>-report.zip.tmp` with `ZIP_DEFLATED`, then `os.replace`; on any error,
   remove the temporary file, print `Could not write the report: <reason>`, exit 1.

## Design that needs care

No new process or concurrency; the risk is a secret reaching a shared file, or deleting
the wrong folder.

### Invariants

1. A `flows.har` written by this version is masked. An unmasked HAR exists only as
   `.flows.har.tmp`, which is removed on every exit path, including a failed masking.
2. The defaults are always part of the rules; a preset only adds.
3. Masking is idempotent: `redact_har(redact_har(h)[0])[0] == redact_har(h)[0]`, and the same
   for `mask_text`.
4. Nothing is re-serialized unless a value was masked, so a body with no secret is byte-for-byte
   the original.
5. The report zip contains only the listed members; never `flows.mitm`, never an unmasked
   HAR or log line. It appears only complete (temporary file and `os.replace`).
6. `remove_old` touches only direct children of `sessions_dir` that are real directories
   (not symlinks), whose names fully match `session.NAME`, that contain `meta.json`, and that
   started more than `keep_days` × 24 h before `now`. It runs before the new folder exists.

### Tests derived from the invariants

- Redaction: each location in the first acceptance criterion; case and `_`/`-` variants;
  preset additions; defaults kept when the preset lists none; nested JSON in lists; a
  non-string value; a non-JSON body unchanged; base64 content unchanged; unchanged JSON
  keeps its exact text; idempotence (HAR and text); an entry `{}` and a response without
  `content`; form `text` and `params`; query and fragment in `url` and `Location`;
  WebSocket text vs binary message.
- `mask_text`: each pattern; `Set-Cookie: a=b; c=d`; JSON in a log message; a line that
  is not JSON; a JSON line with no `message`; no change → the same line.
- Preset: valid block; `redact` not a mapping; unknown key; list not a list; bad header;
  bad field; empty lists allowed.
- Session cleanup: old session deleted; 13-day-old kept; non-matching name kept; no
  `meta.json` kept; symlink to an old-looking folder kept and its target untouched; a file
  kept; missing `sessions/` → 0.
- Launcher: the fake mitmdump's HAR with an `Authorization` header comes out masked; no
  temporary file left; a fake HAR that is not JSON → no `flows.har`, message, exit 1;
  cleanup line printed and an old folder gone after `start`; the report hint is printed.
- Report: members and folder name; HAR masked and `flows.mitm` absent; summary rows for a
  500, a fault comment, a no-response flow, a request ID; mocked/faulted counts; the 100-row
  cap; latest session by default; path argument; unknown session → 1; nothing to report → 1;
  cut-off `flows.mitm` → partial report with the note; missing preset → warning, defaults
  applied; logs masked in the zip, session files unchanged; an existing zip replaced;
  write failure leaves no zip or temporary file.

## Files expected to change

- `cli/redact.py` — new. Rules, defaults, HAR, body, URL and log-text masking.
- `cli/report.py` — new. Session lookup, flow reading, summary, zip.
- `cli/preset.py` — `redact` block parsing and validation; two `Preset` fields.
- `cli/session.py` — `NAME`, `KEEP_DAYS`, `HAR_TMP`, `started`, `list_sessions`, `remove_old`.
- `cli/start.py` — cleanup in PREPARE; HAR through a temporary file and masking; report hint;
  rules passed to `supervise` / `_finalize`.
- `cli/__main__.py` — `report` subcommand.
- `cli/__init__.py` — version `0.5.0`.
- `presets/example.yaml` — commented `redact` block.
- `tests/test_redact.py`, `tests/test_report.py`, `tests/test_session.py` — new;
  `tests/test_preset.py`, `tests/test_start.py` — updated.
- `docs/user-guide.md` — Step 5 uses `./wiretrace report`; what is masked and what is not
  (mitmweb's own export, `flows.mitm` and non-JSON bodies are not); Part 4: automatic
  deletion after 14 days, and how to keep a session; troubleshooting rows for the report.
- `README.md` — one line for `./wiretrace report`.

## Out of scope

- Posting to YouTrack (F13), screenshots, and `./wiretrace sessions` (listing).
- Masking live traffic in mitmweb, `flows.mitm`, or mitmweb's own HAR export.
- Masking bodies that are not JSON or URL-encoded forms (GraphQL text, XML, multipart,
  protobuf), path segments, and binary WebSocket messages.
- A setting for the 14 days, and keeping a session other than by moving it out of `sessions/`.
- Rebuilding the release files (done after the merge if asked).

## Manual test

1. `./wiretrace start --preset <name>`, log in to the app, open a few screens, Ctrl+C. Open
   `flows.har` in Chrome DevTools: the login request's `password`, the response's
   `access_token`, and every `Authorization` header show `***`. Open `flows.mitm` in
   mitmweb: the originals are there.
2. Set a fault (`qa_fault_status=500`) on one path, trigger it, stop, and run
   `./wiretrace report`: the zip's `summary.md` lists that request with
   `Wiretrace fault: status 500`.
3. Copy a session folder to a name with a date 20 days back; `./wiretrace start` says it
   deleted one old session and the folder is gone.

## Automated tests

`.venv/bin/python -m pytest` — the lists above, plus the existing 359.

## Errata

Changed after the security review, before the first commit:

- Default fields also include `token`, `api_key` and `secret`.
- `meta.json` records the rules used at capture (`redact: {headers, json_fields}`); the report
  adds them to the preset's current rules, so a deleted or edited preset no longer drops names.
- `./wiretrace report <name>`: a bare name is looked up only in `sessions/`; only an argument with
  a path separator is taken as a path.
- `;` separates query and form pairs as well as `&`.
- A fragment with a client-side route (`#/callback?access_token=…`) has the parameters after
  its `?` masked (found in code review).
- A body that starts like JSON (`{` or `[`) but does not parse is masked with the log-text
  patterns instead of being left as it was.
- JSON log lines: matching keys are masked, and every text value goes through the log-text
  patterns, not only `message`.
- The zip has no `flows.har` when the session has no readable HTTP flow.
- Accepted as is: base64 response content is not masked (mitmproxy uses base64 only for mostly
  binary bodies), and a `.flows.har.tmp` left by a launcher killed while finalizing is not removed
  (`flows.mitm` in the same folder holds the same data, and the report never packs either file).
