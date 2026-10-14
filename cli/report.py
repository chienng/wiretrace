"""`wiretrace report`: a zip of one session that is safe to attach to a bug ticket.

Spec: docs/specs/005-redaction-bug-report-and-session-cleanup.md. The zip holds a summary, a HAR
rebuilt from flows.mitm and masked, the log files masked by pattern, and meta.json. Never flows.mitm.

mitmproxy is imported inside the functions that need it, so `wiretrace doctor` works without it.
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from . import __version__, redact, session
from .preset import DEFAULT_REQUEST_ID_HEADER, PRESETS_DIR, PresetError, load_preset

MAX_ROWS = 100
LOG_NOTE = "Log lines are masked by pattern only; check them before sharing."


class Failure(Exception):
    """Why no report was written. The message is shown to the user as is."""


class Row(NamedTuple):
    time: str
    method: str
    host: str
    path: str
    status: str
    duration: str
    request_id: str
    note: str


class Flows(NamedTuple):
    har: dict
    rows: list[Row]
    requests: int
    mocked: int
    faulted: int
    cut_off: bool


def say(message: str, err: bool = False) -> None:
    try:
        print(message, file=sys.stderr if err else sys.stdout, flush=True)
    except OSError:
        pass


def resolve(session_arg: str | None, sessions_dir: Path) -> Path:
    if session_arg is None:
        found = session.list_sessions(sessions_dir)
        if not found:
            raise Failure("No sessions to report: sessions/ has no Wiretrace session yet.")
        folder = found[-1]
    else:
        # A bare name is only ever looked up in sessions/, never in the current folder.
        is_path = os.sep in session_arg or (os.altsep or os.sep) in session_arg
        folder = Path(session_arg) if is_path else sessions_dir / session_arg
        if not folder.is_dir():
            raise Failure(f"Unknown session {session_arg!r}: it is neither a folder nor a name in sessions/.")
    if not (folder / session.META).is_file():
        raise Failure(f"{folder.name} is not a Wiretrace session: it has no meta.json.")
    return folder.resolve()


def read_meta(folder: Path) -> dict:
    try:
        meta = session.read_meta(folder)
    except (OSError, ValueError) as e:
        raise Failure(f"Could not read meta.json of {folder.name}: {e}") from None
    if not isinstance(meta, dict):
        raise Failure(f"Could not read meta.json of {folder.name}: not a JSON object")
    return meta


def load_rules(meta: dict, presets_dir: Path) -> tuple[redact.Rules, str]:
    """The preset's rules plus those recorded at capture, and the request ID header.

    A preset that cannot be loaded gives a warning; the defaults and the recorded rules still apply.
    """
    recorded = meta.get("redact") if isinstance(meta.get("redact"), dict) else {}
    name = meta.get("preset")
    try:
        if not isinstance(name, str):
            raise PresetError("the session does not name its preset")
        preset = load_preset(name, presets_dir)
    except (PresetError, OSError, ValueError) as e:
        say(f"Warning: the preset of this session cannot be loaded ({e}); only the default masking "
            "rules and those recorded when the session was captured are applied.", err=True)
        preset, header = None, DEFAULT_REQUEST_ID_HEADER
    else:
        header = preset.request_id_header
    rules = redact.with_names(redact.rules_for(preset), recorded.get("headers"), recorded.get("json_fields"))
    return rules, header


def cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _comment_parts(flow) -> list[str]:
    return [part.strip() for part in (flow.comment or "").split("; ") if part.strip()]


def _row(flow, request_id_header: str, rules: redact.Rules, notes: list[str]) -> Row | None:
    response = flow.response
    if response is not None and response.status_code < 400:
        return None
    if response is not None:
        status, end = str(response.status_code), response.timestamp_end
    else:
        error = flow.error.msg if flow.error else "unknown error"
        status, end = f"no response ({error})", flow.error.timestamp if flow.error else None
    started = flow.request.timestamp_start
    duration = f"{(end - started) * 1000:.0f} ms" if end and started else "-"
    request_id = flow.request.headers.get(request_id_header) or (
        response.headers.get(request_id_header) if response is not None else None) or "-"
    if request_id_header.lower() in rules.header_set:
        request_id = redact.MASK
    return Row(
        time=datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S") if started else "-",
        method=flow.request.method,
        host=flow.request.pretty_host,
        path=flow.request.path.split("?", 1)[0].split("#", 1)[0],
        status=status,
        duration=duration,
        request_id=request_id,
        note="; ".join(f"Wiretrace {part}" for part in notes) or "-",
    )


def read_flows(path: Path, rules: redact.Rules, request_id_header: str) -> Flows:
    """The HTTP flows that can be read from flows.mitm, as a masked HAR and the failed-request rows."""
    if not path.is_file() or path.stat().st_size == 0:
        return Flows({}, [], 0, 0, 0, False)
    from mitmproxy import http, io
    from mitmproxy.addons.savehar import SaveHar
    from mitmproxy.exceptions import FlowReadException

    flows, cut_off = [], False
    with open(path, "rb") as f:
        try:
            for flow in io.FlowReader(f).stream():
                if isinstance(flow, http.HTTPFlow):
                    flows.append(flow)
        except FlowReadException:
            cut_off = True
    if not flows:
        return Flows({}, [], 0, 0, 0, cut_off)

    rows, mocked, faulted = [], 0, 0
    for flow in flows:
        notes = [part for part in _comment_parts(flow) if part.startswith(("fault:", "mock:"))]
        mocked += any(part.startswith("mock:") for part in notes)
        faulted += any(part.startswith("fault:") for part in notes)
        row = _row(flow, request_id_header, rules, notes)
        if row:
            rows.append(row)
    har, _ = redact.redact_har(SaveHar().make_har(flows), rules)
    return Flows(har, rows, len(flows), mocked, faulted, cut_off)


def read_log(path: Path, rules: redact.Rules) -> list[str]:
    """The non-empty lines of a log file, masked."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [redact.mask_log_line(line, rules) for line in text.replace("\r", "").split("\n") if line.strip()]


def table(rows: list[Row]) -> list[str]:
    if not rows:
        return ["No failed requests."]
    lines = ["| Time | Method | Host | Path | Status | Duration | Request ID | Wiretrace note |",
             "|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        lines += ["", f"and {len(rows) - MAX_ROWS} more"]
    return lines


def summary(name: str, meta: dict, flows: Flows, log_lines: int, rules: redact.Rules) -> str:
    def shown(key: str) -> str:
        value = meta.get(key)
        return str(value) if value not in (None, "") else "not recorded"

    lines = [
        f"# Wiretrace bug report: {name}", "",
        "## Session", "",
        f"- Preset: {shown('preset')}",
        f"- Target: {shown('target')}",
        f"- Mode: {shown('mode')}",
        f"- Started: {shown('started_at')}",
        f"- Ended: {shown('ended_at')}",
        f"- Status: {shown('status')}",
        f"- Wiretrace version: {shown('wiretrace_version')} (this report: {__version__})",
        "", "## Counts", "",
        f"- Requests: {flows.requests}",
        f"- Failed (status 400 or higher, or no response): {len(flows.rows)}",
        f"- Mocked by Wiretrace: {flows.mocked}",
        f"- Faulted by Wiretrace: {flows.faulted}",
        f"- Log lines: {log_lines}",
    ]
    if flows.cut_off:
        lines += ["", "Note: flows.mitm ends early (the session was still running or was killed), "
                      "so this report uses only the requests that could be read."]
    lines += [
        "", "## Masked", "",
        f"- Header names: {', '.join(rules.headers)}",
        f"- Field names: {', '.join(rules.fields)}",
        f"- {LOG_NOTE}",
        "", "## Failed requests", "",
        "A request marked as a Wiretrace fault or mock was changed on purpose by Wiretrace; "
        "it is not a backend answer.", "",
        *table(flows.rows), "",
    ]
    return "\n".join(lines)


def write_zip(target: Path, name: str, members: dict[str, bytes], now: datetime) -> None:
    """Write `target` complete or not at all: a temporary file, then os.replace."""
    tmp = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            for member, data in members.items():
                info = zipfile.ZipInfo(f"{name}/{member}", date_time=max(now.timetuple()[:6], (1980, 1, 1, 0, 0, 0)))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def build(folder: Path, presets_dir: Path) -> tuple[dict[str, bytes], Flows, int, redact.Rules]:
    meta = read_meta(folder)
    rules, request_id_header = load_rules(meta, presets_dir)
    try:
        flows = read_flows(folder / session.FLOWS, rules, request_id_header)
    except ImportError:
        raise Failure("mitmproxy is not installed; run ./wiretrace doctor.") from None
    except OSError as e:
        raise Failure(f"Could not read flows.mitm: {e.strerror or e}") from None

    logs = {name: read_log(folder / name, rules) for name in (session.DEVICE_LOG, session.APP_LOG)}
    log_lines = sum(len(lines) for lines in logs.values())
    if not flows.requests and not log_lines:
        raise Failure("Nothing to report: the session has no traffic and no log lines.")

    members: dict[str, bytes] = {"summary.md": summary(folder.name, meta, flows, log_lines, rules).encode()}
    if flows.requests:
        members[session.HAR] = json.dumps(flows.har, indent=4).encode()
    for name, lines in logs.items():
        if lines:
            members[name] = ("\n".join(lines) + "\n").encode()
    members[session.META] = (folder / session.META).read_bytes()
    return members, flows, log_lines, rules


def run(session_arg: str | None, sessions_dir: Path = session.SESSIONS_DIR,
        presets_dir: Path = PRESETS_DIR, now: datetime | None = None) -> int:
    now = now or datetime.now()
    try:
        folder = resolve(session_arg, sessions_dir)
        members, flows, log_lines, _ = build(folder, presets_dir)
    except Failure as e:
        say(str(e), err=True)
        return 1
    except Exception as e:
        say(f"Could not build the report: {e}", err=True)
        return 1

    target = folder / f"{folder.name}-report.zip"
    try:
        write_zip(target, folder.name, members, now)
    except Exception as e:
        say(f"Could not write the report: {getattr(e, 'strerror', None) or e}", err=True)
        return 1

    say(f"Report written: {target}")
    if flows.cut_off:
        say("flows.mitm ends early; the report uses the requests that could be read.")
    say(f"Requests: {flows.requests}, failed: {len(flows.rows)}, mocked: {flows.mocked}, "
        f"faulted: {flows.faulted}, log lines: {log_lines}")
    say(LOG_NOTE)
    return 0
