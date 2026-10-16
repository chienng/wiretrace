"""`wiretrace report`: a zip of one session that is safe to attach to a bug ticket.

Spec: docs/specs/005-redaction-bug-report-and-session-cleanup.md. The zip holds a summary, a HAR
rebuilt from flows.mitm and masked, the log files masked by pattern, and meta.json. Never flows.mitm.

The bug report form (spec 012) builds its draft and its downloads from the same masked data, limited
to a window around one request and to the boxes the tester ticked. Nothing here is printed.

mitmproxy is imported inside the functions that need it, so `wiretrace doctor` works without it.
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from . import __version__, bodies, redact, report_text, session
from .preset import DEFAULT_REQUEST_ID_HEADER, PRESETS_DIR, PresetError, load_preset

MAX_ROWS = 100
LOG_NOTE = report_text.LOG_NOTE
WINDOW_S = 30
BODY_LIMIT = 4096
MAX_LINKED_LINES = 20
MAX_TITLE = 200
MAX_DEVICE_STATUS_BYTES = 4096
MAX_DEVICE_TEXT = 64
LOG_BOXES = {session.DEVICE_LOG: "device", session.APP_LOG: "app"}
FILE_TYPES = {"har": "application/json", "device-log": "text/plain; charset=utf-8",
              "app-log": "text/plain; charset=utf-8", "zip": "application/zip"}


class Failure(Exception):
    """Why no report was written. The message is shown to the user as is."""


class UnknownRequest(Failure):
    """The request asked for is not in flows.mitm: still in progress, or never saved."""


class Include(NamedTuple):
    """What the bug report form asks for: the reported request, which is always in, and the boxes."""

    flow: str | None = None
    others: bool = True
    device: bool = True
    app: bool = True


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


def _notes(flow) -> list[str]:
    return [part for part in _comment_parts(flow) if part.startswith(("fault:", "mock:"))]


def _status_and_end(flow) -> tuple[str, float | None]:
    if flow.response is not None:
        return str(flow.response.status_code), flow.response.timestamp_end
    error = flow.error.msg if flow.error else "unknown error"
    return f"no response ({error})", flow.error.timestamp if flow.error else None


def _duration(flow, end: float | None) -> str:
    started = flow.request.timestamp_start
    return f"{(end - started) * 1000:.0f} ms" if end and started else "-"


def _raw_request_id(flow, request_id_header: str) -> str | None:
    response = flow.response
    return flow.request.headers.get(request_id_header) or (
        response.headers.get(request_id_header) if response is not None else None) or None


def _request_id(flow, request_id_header: str, rules: redact.Rules) -> str:
    if request_id_header.lower() in rules.header_set:
        return redact.MASK
    return _raw_request_id(flow, request_id_header) or "-"


def _bare_path(path: str) -> str:
    return path.split("?", 1)[0].split("#", 1)[0]


def _row(flow, request_id_header: str, rules: redact.Rules, notes: list[str]) -> Row | None:
    response = flow.response
    if response is not None and response.status_code < 400:
        return None
    status, end = _status_and_end(flow)
    started = flow.request.timestamp_start
    return Row(
        time=datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S") if started else "-",
        method=flow.request.method,
        host=flow.request.pretty_host,
        path=_bare_path(flow.request.path),
        status=status,
        duration=_duration(flow, end),
        request_id=_request_id(flow, request_id_header, rules),
        note="; ".join(f"Wiretrace {part}" for part in notes) or "-",
    )


def load_flows(path: Path) -> tuple[list, bool]:
    """The HTTP flows that can be read from flows.mitm, and whether it ends early."""
    if not path.is_file() or path.stat().st_size == 0:
        return [], False
    from mitmproxy import http, io
    from mitmproxy.exceptions import FlowReadException

    flows, cut_off = [], False
    with open(path, "rb") as f:
        try:
            for flow in io.FlowReader(f).stream():
                if isinstance(flow, http.HTTPFlow):
                    flows.append(flow)
        except FlowReadException:
            cut_off = True
    return flows, cut_off


def read_flows(path: Path, rules: redact.Rules, request_id_header: str) -> Flows:
    """The HTTP flows that can be read from flows.mitm, as a masked HAR and the failed-request rows."""
    flows, cut_off = load_flows(path)
    return summarize_flows(flows, cut_off, rules, request_id_header)


def masked_har(flows: list, rules: redact.Rules) -> dict:
    from mitmproxy.addons.savehar import SaveHar

    copies = []
    for flow in flows:
        copy = flow.copy()
        bodies.trim_oversized(copy)
        copies.append(copy)
    har, _ = redact.redact_har(SaveHar().make_har(copies), rules)
    return har


def summarize_flows(flows: list, cut_off: bool, rules: redact.Rules, request_id_header: str) -> Flows:
    if not flows:
        return Flows({}, [], 0, 0, 0, cut_off)
    rows, mocked, faulted = [], 0, 0
    for flow in flows:
        notes = _notes(flow)
        mocked += any(part.startswith("mock:") for part in notes)
        faulted += any(part.startswith("fault:") for part in notes)
        row = _row(flow, request_id_header, rules, notes)
        if row:
            rows.append(row)
    return Flows(masked_har(flows, rules), rows, len(flows), mocked, faulted, cut_off)


def read_raw_log(path: Path) -> list[str]:
    """The non-empty lines of a log file, as written. Never shown before `redact.mask_log_line`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in text.replace("\r", "").split("\n") if line.strip()]


def read_log(path: Path, rules: redact.Rules) -> list[str]:
    """The non-empty lines of a log file, masked."""
    return [redact.mask_log_line(line, rules) for line in read_raw_log(path)]


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


def _write_members(archive: zipfile.ZipFile, name: str, members: dict[str, bytes], now: datetime) -> None:
    for member, data in members.items():
        info = zipfile.ZipInfo(f"{name}/{member}", date_time=max(now.timetuple()[:6], (1980, 1, 1, 0, 0, 0)))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, data)


def write_zip(target: Path, name: str, members: dict[str, bytes], now: datetime) -> None:
    """Write `target` complete or not at all: a temporary file, then os.replace."""
    tmp = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            _write_members(archive, name, members, now)
        os.replace(tmp, target)
        os.chmod(target, 0o600)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def zip_bytes(name: str, members: dict[str, bytes], now: datetime) -> bytes:
    """The same zip as `write_zip`, in memory: the form's downloads write nothing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        _write_members(archive, name, members, now)
    return buffer.getvalue()


# Window and boxes (spec 012)

def parse_ts(value: object) -> float | None:
    """Unix seconds from an ISO 8601 string or a number; None if missing or unparseable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip()).timestamp()
        except (ValueError, OverflowError, OSError):
            return None
    return None


def _record(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return record if isinstance(record, dict) else None


def line_time(line: str) -> float | None:
    record = _record(line)
    return parse_ts(record.get("ts")) if record is not None else None


def in_window(ts: float | None, window: tuple[float, float] | None) -> bool:
    """Bounds included. Without a window everything is in; with one, a line without a time is out."""
    return window is None or (ts is not None and window[0] <= ts <= window[1])


class Material(NamedTuple):
    """Everything a report is made from, read once. The log lines are raw: mask before showing."""

    meta: dict
    rules: redact.Rules
    request_id_header: str
    flows: list
    cut_off: bool
    logs: dict[str, list[str]]


def gather(folder: Path, presets_dir: Path) -> Material:
    meta = read_meta(folder)
    rules, request_id_header = load_rules(meta, presets_dir)
    try:
        flows, cut_off = load_flows(folder / session.FLOWS)
    except ImportError:
        raise Failure("mitmproxy is not installed; run ./wiretrace doctor.") from None
    except OSError as e:
        raise Failure(f"Could not read flows.mitm: {e.strerror or e}") from None
    logs = {name: read_raw_log(folder / name) for name in (session.DEVICE_LOG, session.APP_LOG)}
    return Material(meta, rules, request_id_header, flows, cut_off, logs)


def chosen_flows(material: Material, window: tuple[float, float] | None, include: Include | None) -> list:
    if include is None:
        return [f for f in material.flows if in_window(f.request.timestamp_start, window)]
    return [f for f in material.flows
            if f.id == include.flow or (include.others and in_window(f.request.timestamp_start, window))]


def window_lines(material: Material, name: str, window: tuple[float, float] | None) -> list[str]:
    lines = material.logs[name]
    return lines if window is None else [line for line in lines if in_window(line_time(line), window)]


def chosen_lines(material: Material, name: str, window: tuple[float, float] | None,
                 include: Include | None) -> list[str]:
    """The masked lines of one log file in the window, or none when its box is off."""
    if include is not None and not getattr(include, LOG_BOXES[name]):
        return []
    return [redact.mask_log_line(line, material.rules) for line in window_lines(material, name, window)]


class Assembled(NamedTuple):
    members: dict[str, bytes]
    flows: Flows
    logs: dict[str, list[str]]


def assemble(folder: Path, material: Material, window: tuple[float, float] | None = None,
             include: Include | None = None) -> Assembled:
    flows = summarize_flows(chosen_flows(material, window, include), material.cut_off, material.rules,
                            material.request_id_header)
    logs = {name: chosen_lines(material, name, window, include) for name in (session.DEVICE_LOG, session.APP_LOG)}
    log_lines = sum(len(lines) for lines in logs.values())
    if not flows.requests and not log_lines:
        if window is None and include is None:
            raise Failure("Nothing to report: the session has no traffic and no log lines.")
        raise Failure("Nothing to report: no traffic and no log lines in the window and the boxes chosen.")

    members: dict[str, bytes] = {"summary.md": summary(folder.name, material.meta, flows, log_lines,
                                                       material.rules).encode()}
    if flows.requests:
        members[session.HAR] = json.dumps(flows.har, indent=4).encode()
    for name, lines in logs.items():
        if lines:
            members[name] = ("\n".join(lines) + "\n").encode()
    members[session.META] = (folder / session.META).read_bytes()
    return Assembled(members, flows, logs)


def build(folder: Path, presets_dir: Path, window: tuple[float, float] | None = None,
          include: Include | None = None) -> tuple[dict[str, bytes], Flows, int, redact.Rules]:
    """The report's members. `window` and `include` limit it as the bug report form asks; without
    them it is the whole session, as `./wiretrace report` writes it."""
    material = gather(folder, presets_dir)
    built = assemble(folder, material, window, include)
    return built.members, built.flows, sum(len(lines) for lines in built.logs.values()), material.rules


# Text logs and the draft of the bug report form (spec 012)

def _clock(ts: float | None, fmt: str = "%Y-%m-%d %H:%M:%S.%f") -> str:
    if ts is None:
        return "-"
    try:
        text = datetime.fromtimestamp(ts).strftime(fmt)
    except (OverflowError, OSError, ValueError):
        return "-"
    return text[:-3] if fmt.endswith("%f") else text


def text_log_line(masked: str) -> str:
    """`time level tag message` on one line, from a line already masked."""
    record = _record(masked)
    if record is None:
        return report_text.one_line(masked)

    def short(key: str) -> str:
        value = record.get(key)
        return report_text.one_line(value) if isinstance(value, str) and value.strip() else "-"

    message = record.get("message")
    if message is None:
        message = ""
    elif not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)
    return report_text.one_line(f"{_clock(parse_ts(record.get('ts')))} {short('level')} {short('tag')} {message}")


def text_log(lines: list[str]) -> bytes:
    return ("\n".join(text_log_line(line) for line in lines) + "\n").encode()


def find_flow(material: Material, flow_id: str):
    for flow in material.flows:
        if flow.id == flow_id:
            return flow
    raise UnknownRequest("That request is not in flows.mitm yet: it is still in progress, or it was not saved.")


def window_of(flow) -> tuple[float, float] | None:
    started = flow.request.timestamp_start
    return (started - WINDOW_S, started + WINDOW_S) if started else None


def report_files(folder: Path, material: Material, window: tuple[float, float] | None, include: Include,
                 now: datetime) -> dict[str, tuple[str, bytes]]:
    """kind -> (download name, bytes). A file with no content is left out."""
    try:
        built = assemble(folder, material, window, include)
    except Failure:
        return {}
    name = folder.name
    files: dict[str, tuple[str, bytes]] = {}
    if session.HAR in built.members:
        files["har"] = (f"{name}-requests.har", built.members[session.HAR])
    for kind, log in (("device-log", session.DEVICE_LOG), ("app-log", session.APP_LOG)):
        if built.logs[log]:
            files[kind] = (f"{name}-{kind}.txt", text_log(built.logs[log]))
    files["zip"] = (f"{name}-report.zip", zip_bytes(name, built.members, now))
    return files


def _material_window(folder: Path, presets_dir: Path, include: Include):
    material = gather(folder, presets_dir)
    flow = find_flow(material, include.flow) if include.flow else None
    return material, flow, window_of(flow) if flow is not None else None


def export(folder: Path, presets_dir: Path, kind: str, include: Include,
           now: datetime | None = None) -> tuple[str, bytes] | None:
    """One download of the form, built in memory: (name, bytes), or None when it has no content."""
    material, _, window = _material_window(folder, presets_dir, include)
    return report_files(folder, material, window, include, now or datetime.now()).get(kind)


def device_description(folder: Path) -> tuple[str, str]:
    """Model and OS from the collector's status file; never a serial, a UDID or the device's name."""
    try:
        with open(folder / session.DEVICE_STATUS, "rb") as f:
            raw = f.read(MAX_DEVICE_STATUS_BYTES + 1)
        data = json.loads(raw) if len(raw) <= MAX_DEVICE_STATUS_BYTES else None
    except (OSError, ValueError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""

    def text(key: str) -> str:
        value = data.get(key)
        return report_text.one_line(value).strip()[:MAX_DEVICE_TEXT] if isinstance(value, str) else ""

    return text("model"), text("os")


def _clip(text: str, limit: int = MAX_TITLE) -> str:
    return report_text.one_line(text).strip()[:limit]


def _masked_path(flow, rules: redact.Rules) -> str:
    return redact.mask_text(_bare_path(flow.request.path), rules)


def _title(flow, rules: redact.Rules) -> str:
    path = _masked_path(flow, rules)
    if flow.response is not None:
        return _clip(f"{flow.request.method} {path} returns {flow.response.status_code}")
    return _clip(f"{flow.request.method} {path} gets no response")


def _session_title(name: str, failed: int) -> str:
    if not failed:
        return _clip(f"Bug in session {name}")
    return _clip(f"{failed} failed request{'s' if failed != 1 else ''} in session {name}")


def _request_facts(flow, material: Material) -> report_text.Request:
    rules = material.rules
    status, end = _status_and_end(flow)
    response = flow.response
    path, _ = redact.redact_url(flow.request.path, rules)
    return report_text.Request(
        method=flow.request.method, host=flow.request.pretty_host, path=redact.mask_text(path, rules),
        status=redact.mask_text(status, rules), duration=_duration(flow, end),
        request_id=_request_id(flow, material.request_id_header, rules),
        failed=response is None or response.status_code >= 400)


def _body_facts(flow, rules: redact.Rules) -> report_text.Body | None:
    """The response body as the HAR masks it, then masked by pattern too, cut at BODY_LIMIT bytes."""
    if flow.response is None:
        return None
    entries = masked_har([flow], rules).get("log", {}).get("entries") or []
    content = entries[0].get("response", {}).get("content", {}) if entries else {}
    size = content.get("size") if isinstance(content.get("size"), int) else 0
    mime = str(content.get("mimeType") or "").lower()
    if content.get("encoding") == "base64":
        return report_text.Body(None, False, False, size)
    text = redact.mask_text(str(content.get("text") or ""), rules)
    data = text.encode("utf-8")
    cut = len(data) > BODY_LIMIT
    if cut:
        text = data[:BODY_LIMIT].decode("utf-8", "ignore")
    return report_text.Body(text, "json" in mime, cut, size)


def _linked_lines(flow, material: Material, window: tuple[float, float] | None,
                  include: Include) -> tuple[tuple[str, ...], str]:
    """Up to MAX_LINKED_LINES masked lines that carry the request's ID, and what to say when there are none."""
    if material.request_id_header.lower() in material.rules.header_set:
        return (), "The request ID header is masked, so no log lines are linked to it."
    request_id = _raw_request_id(flow, material.request_id_header)
    if not request_id:
        return (), "The request has no request ID, so no log lines are linked to it."
    if not include.device and not include.app:
        return (), "Device and app logs are not included."
    found: list[tuple[float, str]] = []
    for name in (session.DEVICE_LOG, session.APP_LOG):
        if not getattr(include, LOG_BOXES[name]):
            continue
        for line in window_lines(material, name, window):
            record = _record(line)
            if (record is not None and record.get("request_id") == request_id) or request_id in line:
                found.append((line_time(line) or 0.0, line))
    found.sort(key=lambda item: item[0])
    lines = tuple(text_log_line(redact.mask_log_line(line, material.rules)) for _, line in found[:MAX_LINKED_LINES])
    return lines, "" if lines else "No log lines in the window carry this request ID."


def draft(folder: Path, presets_dir: Path, include: Include, fmt: str = "markdown",
          now: datetime | None = None) -> dict:
    """The form's pre-filled title and description, its counts, masked names and files with their sizes.

    Raises UnknownRequest when `include.flow` is not in flows.mitm, Failure when the session cannot be read.
    """
    material, flow, window = _material_window(folder, presets_dir, include)
    rules, meta = material.rules, material.meta
    files = report_files(folder, material, window, include, now or datetime.now())
    model, os_name = device_description(folder)

    def meta_text(key: str) -> str:
        value = meta.get(key)
        return report_text.one_line(str(value)) if value not in (None, "") else ""

    environment = report_text.Environment(
        preset=meta_text("preset"), target=meta_text("target"), mode=meta_text("mode"), model=model, os=os_name,
        version=meta_text("wiretrace_version") or __version__)
    counts = {
        "others": sum(1 for f in material.flows if f is not flow and in_window(f.request.timestamp_start, window)),
        "device": len(window_lines(material, session.DEVICE_LOG, window)),
        "app": len(window_lines(material, session.APP_LOG, window)),
    }
    lead = {"request": None, "at": None, "device": " · ".join(v for v in (model, os_name) if v) or None,
            "session": folder.name}
    if flow is None:
        rows = [row._replace(path=redact.mask_text(row.path, rules), status=redact.mask_text(row.status, rules))
                for f in material.flows if (row := _row(f, material.request_id_header, rules, _notes(f)))]
        facts = report_text.Facts(folder.name, environment, failed=tuple(rows))
        title = _session_title(folder.name, len(rows))
    else:
        linked, no_lines = _linked_lines(flow, material, window, include)
        facts = report_text.Facts(folder.name, environment, request=_request_facts(flow, material),
                                  body=_body_facts(flow, rules), log_lines=linked, no_log_lines=no_lines)
        title = _title(flow, rules)
        status = str(flow.response.status_code) if flow.response is not None else "no response"
        lead.update(request=_clip(f"{flow.request.method} {_masked_path(flow, rules)} → {status}", 300),
                    at=_clock(flow.request.timestamp_start, "%H:%M:%S") if flow.request.timestamp_start else None)
    return {
        "title": title,
        "description": report_text.render(facts, fmt),
        "format": fmt,
        "lead": lead,
        "counts": counts,
        "masked": {"headers": list(rules.headers), "fields": list(rules.fields)},
        "files": [{"kind": kind, "name": name, "size": len(data)} for kind, (name, data) in files.items()],
    }


class Created(NamedTuple):
    """A written report: the zip and the counts that `run` and the Wiretrace window show."""

    zip: Path
    requests: int
    failed: int
    mocked: int
    faulted: int
    device_lines: int
    app_lines: int
    cut_off: bool

    @property
    def log_lines(self) -> int:
        return self.device_lines + self.app_lines


def create(folder: Path, presets_dir: Path = PRESETS_DIR, now: datetime | None = None) -> Created:
    """Write the report zip of a session folder. Raise Failure, with the message for the user, if it cannot."""
    now = now or datetime.now()
    try:
        members, flows, _, _ = build(folder, presets_dir)
    except Failure:
        raise
    except Exception as e:
        raise Failure(f"Could not build the report: {e}") from None

    target = folder / f"{folder.name}-report.zip"
    try:
        write_zip(target, folder.name, members, now)
    except Exception as e:
        raise Failure(f"Could not write the report: {getattr(e, 'strerror', None) or e}") from None
    return Created(
        zip=target, requests=flows.requests, failed=len(flows.rows), mocked=flows.mocked,
        faulted=flows.faulted, device_lines=members.get(session.DEVICE_LOG, b"").count(b"\n"),
        app_lines=members.get(session.APP_LOG, b"").count(b"\n"), cut_off=flows.cut_off)


def run(session_arg: str | None, sessions_dir: Path = session.SESSIONS_DIR,
        presets_dir: Path = PRESETS_DIR, now: datetime | None = None) -> int:
    try:
        created = create(resolve(session_arg, sessions_dir), presets_dir, now)
    except Failure as e:
        say(str(e), err=True)
        return 1

    say(f"Report written: {created.zip}")
    if created.cut_off:
        say("flows.mitm ends early; the report uses the requests that could be read.")
    say(f"Requests: {created.requests}, failed: {created.failed}, mocked: {created.mocked}, "
        f"faulted: {created.faulted}, log lines: {created.log_lines}")
    say(LOG_NOTE)
    return 0
