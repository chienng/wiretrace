"""Wiretrace window: a local web page with the traffic, the app's logs, setup, rules and the report.

A Tornado application on mitmproxy's own asyncio loop, so every hook and every request runs
on one thread and flows are read without locks. Listens on 127.0.0.1 only; every page, API
call and WebSocket needs the token that is printed once as a link in the Terminal.
Specs: docs/specs/006-wiretrace-ui-first-slice.md, 008-window-like-the-mockups.md, 013-switch-preset.md,
018-switch-device.md, 021-switch-to-another-phone.md, 022-more-devices-port-encrypted-hosts-breakpoints.md.

Configured through mitmproxy options (`qa_ui_*`); the token is never an option. The addon
prints the link and errors only: no flow content, header or log line goes to the Terminal.
While it is loaded, mitmproxy's own Terminal lines name no client address.
"""

from __future__ import annotations

import asyncio
import codecs
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

import tornado.web
import tornado.websocket
from mitmproxy import ctx, exceptions, flowfilter, http
from mitmproxy.addons.termlog import TermLogHandler
from mitmproxy.net.http import status_codes
from mitmproxy.proxy import mode_specs
from tornado import httpserver, netutil
from tornado.escape import json_encode

# mitmdump does not have the wiretrace folder on sys.path.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons import proxy_guard as guardlib  # noqa: E402
from addons import rewrite as rewritelib  # noqa: E402
from addons.client_stats import ClientStats  # noqa: E402
from addons.tunnels import Tunnels as TunnelList  # noqa: E402
from cli import __version__, report, report_text, screenshot, session  # noqa: E402
from cli import bodies  # noqa: E402
from cli import doctor as doctorlib  # noqa: E402
from cli import preset as presetfile  # noqa: E402
from cli.preset import PRESETS_DIR, Preset, PresetError, list_presets, load_preset  # noqa: E402
from cli.start import (  # noqa: E402
    APP_KEYS,
    DEVICE_LOGS,
    TARGET_LABELS,
    TARGETS,
    TARGETS_SHOWN,
    allow_hosts_args,
    collector_command,
    pinnable_client,
    target_problem,
)

logger = logging.getLogger(__name__)

COOKIE = "wiretrace_ui"
ALREADY_SWITCHING = "Wiretrace is already switching to another session"
# A client switch (spec 021): the kinds that connect over Wi-Fi, and its refusals.
CLIENT_TARGETS = ("ios", "android", "device")
NO_CLIENT_SWITCH = "This session does not pin a device on the Wi-Fi proxy"
CONNECTS_FROM_MAC = "The iOS Simulator and the Android emulator connect from this Mac: they are always accepted."
NOT_AN_ADDRESS = "Not a device address."
NOT_WAITING = "That device is no longer waiting: ask it to connect again."
DEVICES_OFF_WHILE_VIEWING = "Allowing and removing devices is off while a previous session is open"
# Spec 022, slice B.
NO_PROXY_PORT = "This session has no Wi-Fi proxy"
SAME_PORT = "That is the port this session already uses."
PORT_IN_USE = "That port is in use by another program."
MAX_PORT_DIGITS = 5
# Spec 022, slice C.
NOT_OFFERED = "Wiretrace offers a host it passed through, or that host's parent domain, only."
FILE_CHANGED = "The preset file changed since this session started: restart the session to use it."
# Spec 022, slice D: breakpoints.
MAX_PAUSED = 10
BREAKPOINT_WATCHDOG_S = 30.0
MAX_EDIT_BODY = 1 << 20
MAX_EDIT_HEADERS = 200
MAX_EDIT_PATH = 8192
FIXED_HEADERS = ("host", "content-length", "transfer-encoding")
PAUSED_KEY = "wiretrace_paused"
NOT_PAUSED = "This request is no longer paused."
STALE_EDIT = "Another tab changed this request first: reload it."
FIXED_EDITED = "Host, Content-Length and Transfer-Encoding cannot be edited."
BAD_HEADER = "A header needs a name of letters, digits and - _ . ! # $ % & ' * + ^ ` | ~, and no line break."
EDIT_METHOD = re.compile(r"[A-Z]{1,16}")
HEADER_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,256}")
# Spec 022, slice E: what addons/qa_tools.py records of the Rewrite rules it applied.
CHANGES_KEY = "wiretrace_changes"
MASKED_VALUE = "•••• (masked)"
# Spec 022, slice F: a response saved as a mock file, and the Mock rule for it (qa_tools limits).
MAP_LOCAL_KEYS = {"file", "status", "body", "rule", "replace", "revision"}
MAX_MOCK_BODY = 1 << 20
MAX_RULE_NAME = 80
MAX_RULE_PATH = 512
# Spec 022, slice G: where addons/qa_tools.py sent a request a Map remote rule matched.
MAPPED_KEY = "wiretrace_mapped"
# A refusal from an address already listed sends the state at most this often.
WAITING_PUSH_S = 5.0
# mitmproxy's block_global / block_private warning, which names the client in its text.
BLOCKED_CLIENT = re.compile(r"Client connection from \S+ killed by (block_\w+) option\.")
RECEIVER_HOST = "qa-logs.internal"
MAX_FLOWS = 10_000
MAX_LOG_LINES = 50_000
MAX_BODY_BYTES = 2 << 20
MAX_COUNT_BYTES = 64 << 20
MAX_REQUEST_BYTES = 64 << 10
# Rules carry bodies up to 1 MiB each; this larger limit is set only after the request passed the checks.
MAX_RULES_REQUEST_BYTES = 32 << 20
MAX_MOCK_FILES = 5_000
BATCH_S = 0.1
TAIL_S = 0.25
READ_LIMIT = 8 << 20
MAX_PARTIAL = 1 << 20
CHUNK = 500
SNIFF_BYTES = 8192
MAX_META_BYTES = 64 << 10
SEARCH_MIN = 3
SEARCH_MAX = 200
# Flows searched between two yields to the event loop.
SEARCH_CHUNK = 50
SOURCES = {"device": session.DEVICE_LOG, "app": session.APP_LOG}
FAULT_OPTIONS = {"filter": "qa_fault_filter", "status": "qa_fault_status",
                 "delay_ms": "qa_fault_delay_ms", "drop": "qa_fault_drop"}
NO_QA = "The QA addon is not loaded"
NOT_JSON = object()
FORBIDDEN_PAGE = ("<!doctype html><meta charset=utf-8><title>Wiretrace</title>"
                  "<p>Open the link printed in the Terminal.</p>")
TEXT_TYPES = {"application/json", "application/xml", "application/javascript", "application/x-www-form-urlencoded",
              "application/graphql", "image/svg+xml"}
BINARY_PREFIXES = ("image/", "audio/", "video/", "font/")
BINARY_TYPES = {"application/octet-stream", "application/zip", "application/gzip", "application/pdf",
                "application/x-protobuf", "application/protobuf", "application/grpc"}
# secrets.token_urlsafe(32): 32 bytes, base64url without padding, 43 characters.
_UI_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
STATUS_MIN_S = 1.0
STATUS_HEARTBEAT_S = 2.0
STATUS_KEYS = ("v", "updated_at", "started_at", "preset", "target", "mode", "device_state",
               "device_model", "requests", "errors", "rules_on", "last_error")
FLOW_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
REPORT_BOXES = ("others", "device", "app")


# Plain data

def clean(text: str) -> str:
    """JSON-safe text: bytes that were not valid UTF-8 (surrogate escapes) become U+FFFD."""
    try:
        return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8")


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


def comment_parts(comment: str) -> list[str]:
    return [part.strip() for part in (comment or "").split("; ") if part.strip()]


def part_value(parts: list[str], prefix: str) -> list[str]:
    return [part[len(prefix):].strip() for part in parts if part.startswith(prefix)]


def is_receiver(flow: http.HTTPFlow) -> bool:
    return flow.request.host.lower().rstrip(".") == RECEIVER_HOST


def is_api_host(host: str, api_hosts: list[str] | tuple[str, ...]) -> bool:
    """The same match as addons/qa_tools.py: the host or a subdomain of it."""
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in api_hosts)


def map_local_rule(flow: http.HTTPFlow, label: str, status: int, api_hosts: tuple[str, ...],
                   taken: set[str]) -> dict | None:
    """The Mock rule "Map local GET /path" for a request (spec 022, slice F); None when it is not to an API host."""
    mapped = mapped_of(flow)
    host = (mapped["from"] if mapped else flow.request.pretty_host).lower().rstrip(".")
    api_host = next((h for h in api_hosts if host == h or host.endswith("." + h)), None)
    if api_host is None:
        return None
    method = flow.request.method.upper()
    path = (flow.request.path.split("?", 1)[0] or "/")[:MAX_RULE_PATH]
    rule_id = secrets.token_hex(5)
    while rule_id in taken:
        rule_id = secrets.token_hex(5)
    return {"id": rule_id, "name": clean(f"Map local {method} {path}")[:MAX_RULE_NAME], "enabled": True,
            "match": {"method": method if EDIT_METHOD.fullmatch(method) else "ANY", "host": api_host,
                      "path": clean(path), "body_contains": ""},
            "action": {"type": "mock", "status": status, "body": "", "mock_file": label, "delay_ms": 0},
            "apply": {"mode": "always", "n": 0}}


def mime_of(message: http.Message) -> str | None:
    value = message.headers.get("content-type")
    return clean(value.split(";", 1)[0].strip().lower()) if value else None


def take_ui_token() -> str | None:
    """The launcher's token. It is removed from the environment so a child of mitmdump does not inherit it.

    Anything that is not a 32-byte urlsafe token is discarded and the addon makes its own.
    """
    raw = os.environ.pop("WIRETRACE_UI_TOKEN", None)
    if raw and _UI_TOKEN.fullmatch(raw):
        return raw
    return None


def is_error_flow(flow: http.HTTPFlow) -> bool:
    """The window's Errors filter: a status of 400 or higher, or a failure with no response."""
    response = flow.response
    status = response.status_code if response is not None else None
    return (status is not None and status >= 400) or flow.error is not None


def flow_ended(flow: http.HTTPFlow) -> float:
    if flow.response is not None and flow.response.timestamp_end:
        return flow.response.timestamp_end
    if flow.error is not None and getattr(flow.error, "timestamp", None):
        return flow.error.timestamp
    return flow.request.timestamp_start or 0.0


def error_tally(flows: dict[str, http.HTTPFlow]) -> tuple[int, str | None]:
    """How many listed requests failed, and the id of the one that failed last."""
    count = 0
    last_id: str | None = None
    last_at = -1.0
    for flow in flows.values():
        if not isinstance(flow, http.HTTPFlow) or not is_error_flow(flow):
            continue
        count += 1
        ended = flow_ended(flow)
        if last_id is None or ended >= last_at:
            last_at = ended
            last_id = flow.id
    return count, last_id


def write_status_file(path: Path, payload: dict) -> None:
    """Atomically replace the status file. The temporary file is removed if the replace fails."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def terminal_record(record: logging.LogRecord) -> logging.LogRecord:
    """A mitmproxy log record as the Terminal may print it: no client address (spec 021).

    A copy, so the record other handlers see is unchanged."""
    message = record.getMessage()
    blocked = BLOCKED_CLIENT.fullmatch(message)
    if getattr(record, "client", None) is None and blocked is None:
        return record
    copy = logging.makeLogRecord(record.__dict__)
    copy.client = None
    if blocked is not None:
        copy.msg, copy.args = f"Client connection from another device killed by {blocked[1]} option.", None
    return copy


class TerminalFormatter(logging.Formatter):
    """mitmproxy's Terminal formatter, given terminal_record's copy of each record.

    A formatter, not a filter: MitmLogHandler.filter returns a bool, which drops a replaced record."""

    def __init__(self, inner: logging.Formatter | None) -> None:
        super().__init__()
        self.inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return self.inner.format(terminal_record(record))


def redact_terminal() -> None:
    """Wraps the formatter of mitmproxy's Terminal handlers, once; it stays for the process."""
    for handler in logging.getLogger().handlers:
        # By name: a reloaded `-s` script brings a new TerminalFormatter class.
        if isinstance(handler, TermLogHandler) and type(handler.formatter).__name__ != TerminalFormatter.__name__:
            handler.setFormatter(TerminalFormatter(handler.formatter))


def write_switch_file(path: Path, name: str, target: str, client: str | None = None,
                      proxy_port: int | None = None) -> None:
    """`{"name", "target"}`, plus `client` for a client switch or `proxy_port` for a port change, 0600
    from the start, replaced whole (spec 018, invariant 1)."""
    payload: dict = {"name": name, "target": target}
    if client is not None:
        payload["client"] = client
    elif proxy_port is not None:
        payload["proxy_port"] = proxy_port
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def parse_port(raw: str) -> int | None:
    """A query's port as an integer; None (not a whole number) for anything else."""
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= MAX_PORT_DIGITS else None


def port_free(port: int) -> bool:
    """The launcher's busy check for the Wi-Fi proxy: TCP on 0.0.0.0 (and ::), each socket closed at once."""
    return doctorlib.check_port("tcp", "0.0.0.0", port, "proxy").status != doctorlib.FAIL


def preset_entry(name: str, presets_dir: Path, target: str) -> dict:
    """The preset menu's line: its hosts, and the app whose device logs this target would collect.

    A preset that does not load is listed with no hosts; choosing it shows `load_preset`'s message.
    """
    try:
        preset = load_preset(name, presets_dir)
    except (PresetError, OSError):
        return {"name": name, "api_hosts": [], "device_logs": False, "app": None}
    source = DEVICE_LOGS.get(target)
    app = preset.app.get(APP_KEYS[source]) if source else None
    app = app if isinstance(app, str) and app else None
    return {"name": name, "api_hosts": list(preset.api_hosts), "device_logs": app is not None, "app": app}


def device_entry(target: str, preset: Preset | None, mode: str, collector_for: Any, bin_dir: Path) -> dict:
    """The device menu's line: whether this session can switch to it, and its device logs with this preset."""
    why_not = target_problem(target, mode)
    if preset is None:
        logs = "off (the preset in use does not load)"
    else:
        # Only the argument list is built; nothing is started and the path is never opened.
        cmd, problem = collector_for(preset, target, bin_dir, Path(session.DEVICE_LOG))
        logs = preset.app[APP_KEYS[DEVICE_LOGS[target]]] if cmd else f"off ({problem})"
    return {"target": target, "label": TARGET_LABELS[target], "allowed": why_not is None, "why_not": why_not,
            "device_logs": logs}


def regular_client(client: Any) -> bool:
    """A Wi-Fi proxy client; one without `proxy_mode` counts as one, as in addons/proxy_guard.py."""
    mode = getattr(client, "proxy_mode", None)
    return mode is None or isinstance(mode, mode_specs.RegularMode)


def peer_address(client: Any) -> str | None:
    peer = getattr(client, "peername", None)
    if not peer or not isinstance(peer[0], str):
        return None
    return guardlib.normalize(peer[0])


def client_of(flow: http.HTTPFlow) -> str | None:
    """The Device column: the client's address, "mac" for loopback, "wireguard" for a tunnel client."""
    return client_label(getattr(flow, "client_conn", None))


def client_label(client: Any) -> str | None:
    if client is None:
        return None
    if isinstance(getattr(client, "proxy_mode", None), mode_specs.WireGuardMode):
        return "wireguard"
    address = peer_address(client)
    try:
        parsed = ipaddress.ip_address(address or "")
    except ValueError:
        return None
    return "mac" if parsed.is_loopback else str(parsed)


def summary(flow: http.HTTPFlow, paused: tuple[str, float] | None = None) -> dict:
    """`paused` is the live session's (phase, since) for a flow held at a breakpoint."""
    request, response = flow.request, flow.response
    parts = comment_parts(flow.comment)
    request_ids = part_value(parts, "request-id:")
    faults = part_value(parts, "fault:")
    replays = part_value(parts, "replay:")
    start = request.timestamp_start
    end = response.timestamp_end if response else (flow.error.timestamp if flow.error else None)
    size = len(response.raw_content) if response is not None and response.raw_content is not None else None
    mapped = mapped_of(flow)
    return {
        "id": flow.id,
        "ts": start,
        "method": clean(request.method),
        "scheme": mapped["from_scheme"] if mapped else request.scheme,
        "host": clean(mapped["from"] if mapped else request.pretty_host),
        "port": mapped["from_port"] if mapped else request.port,
        "path": clean(request.path),
        "status": response.status_code if response else None,
        "error": clean(flow.error.msg) if flow.error else None,
        "duration_ms": max(0, round((end - start) * 1000)) if start and end else None,
        "size": size,
        "mime": mime_of(response) if response else None,
        "request_id": clean(request_ids[0]) if request_ids else None,
        "mock": any(part.startswith("mock:") for part in parts),
        "fault": clean(", ".join(faults)) if faults else None,
        "websocket": flow.websocket is not None,
        "replay_of": clean(replays[0]) if replays else None,
        "client": client_of(flow),
        "paused": paused[0] if paused else None,
        "paused_since": paused[1] if paused else None,
        "edited": any(part.startswith("breakpoint:") and part.endswith(" edited") for part in parts),
        "rewritten": any(part.startswith("rewrite:") for part in parts),
        "mapped": mapped is not None,
        "sent_to": clean(mapped["to"]) if mapped else None,
    }


def mapped_of(flow: http.HTTPFlow) -> dict | None:
    """Where a Map remote rule sent the request, when the record is whole (spec 022, slice G)."""
    mapped = flow.metadata.get(MAPPED_KEY)
    if not isinstance(mapped, dict) or not all(isinstance(mapped.get(k), str) for k in ("from", "to")) \
            or mapped.get("from_scheme") not in ("http", "https") or not isinstance(mapped.get("from_port"), int):
        return None
    return mapped


def looks_binary(data: bytes, mime: str | None) -> bool:
    if not data:
        return False
    if mime and (mime.startswith("text/") or mime in TEXT_TYPES or mime.endswith(("+json", "+xml"))):
        return b"\0" in data[:SNIFF_BYTES]
    if mime and (mime.startswith(BINARY_PREFIXES) or mime in BINARY_TYPES):
        return True
    if b"\0" in data[:SNIFF_BYTES]:
        return True
    try:
        codecs.getincrementaldecoder("utf-8")().decode(data[:SNIFF_BYTES])
    except UnicodeDecodeError:
        return True
    return False


def decode_prefix(data: bytes, content_type: str) -> str:
    found = re.search(r"charset=\"?([\w.:-]+)", content_type, re.IGNORECASE)
    try:
        return data.decode(found.group(1) if found else "utf-8", "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def body_info(message: http.Message) -> dict:
    """The body as text up to 2 MiB, or only its size when it is binary. Never decodes more than 2 MiB."""
    data, size, truncated = bodies.bounded_content(message, MAX_BODY_BYTES, MAX_COUNT_BYTES)
    if looks_binary(data, mime_of(message)):
        return {"text": None, "size": size, "truncated": False, "binary": True}
    if not truncated and not message.headers.get("content-encoding", "").strip():
        text = message.get_text(strict=False) if data else ""
        return {"text": clean(text or ""), "size": size, "truncated": False, "binary": False}
    text = decode_prefix(data, message.headers.get("content-type", ""))
    return {"text": clean(text), "size": size, "truncated": truncated, "binary": False}


def header_list(headers: http.Headers) -> list[list[str]]:
    return [[clean(name), clean(value)] for name, value in headers.items(multi=True)]


def mock_path(mocks_dir: str, method: str, raw_path: str) -> str:
    """`<mocks_dir>/<METHOD><path without query>.json`, as addons/qa_tools.py looks it up."""
    path = raw_path.split("?", 1)[0]
    if path in ("", "/"):
        path = "/index"
    elif path.endswith("/"):
        path = path[:-1]
    prefix = mocks_dir.rstrip("/") + "/" if mocks_dir else ""
    return f"{prefix}{method}{path}.json"


def detail(flow: http.HTTPFlow, mocks_dir: str, paused: tuple[str, float] | None = None) -> dict:
    request, response = flow.request, flow.response
    return {
        "summary": summary(flow, paused),
        "request": {"http_version": clean(request.http_version), "headers": header_list(request.headers),
                    "body": body_info(request)},
        "response": None if response is None else {
            "status": response.status_code, "reason": clean(response.reason or ""),
            "http_version": clean(response.http_version), "headers": header_list(response.headers),
            "body": body_info(response)},
        "timing": {"start": request.timestamp_start, "request_end": request.timestamp_end,
                   "response_start": response.timestamp_start if response else None,
                   "response_end": response.timestamp_end if response else None},
        "comment": clean(flow.comment or ""),
        "mock_path": clean(mock_path(mocks_dir, request.method, request.path)),
        "changes": change_list(flow.metadata.get(CHANGES_KEY)),
        "map_remote": map_remote_of(flow),
    }


def map_remote_of(flow: http.HTTPFlow) -> dict | None:
    """The Map remote step for the Changes tab (spec 022, slice G)."""
    mapped = mapped_of(flow)
    if mapped is None:
        return None
    rule = mapped.get("rule")
    return {"rule": clean(rule) if isinstance(rule, str) else "", "from": clean(mapped["from"]),
            "to": clean(mapped["to"])}


def change_list(raw: object) -> list[dict]:
    """What the Rewrite rules did to a flow (spec 022, slice E); secret header values masked."""
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw[:200]:
        if not isinstance(entry, dict):
            continue
        texts = {key: entry.get(key) if isinstance(entry.get(key), str) else "" for key in ("rule", "on", "op", "target", "reason")}
        value = entry.get("value")
        if isinstance(value, str) and texts["op"].endswith("_header") and texts["target"].lower() in rewritelib.MASKED_HEADERS:
            value = MASKED_VALUE
        out.append({**{key: clean(text) for key, text in texts.items()},
                    "value": clean(value) if isinstance(value, str) else None,
                    "applied": entry.get("applied") is True})
    return out


class Breakpoint(NamedTuple):
    """A flow held at a breakpoint. `original` is the message as it was when it paused."""
    flow: http.HTTPFlow
    phase: str
    since: float
    revision: int
    original: http.Message


def held_message(flow: http.HTTPFlow, phase: str) -> http.Message:
    return flow.request if phase == "request" else flow.response


def body_not_editable(message: http.Message) -> str | None:
    """Why the body cannot be edited as text, or None."""
    data, size, truncated = bodies.bounded_content(message, MAX_EDIT_BODY, MAX_COUNT_BYTES)
    if truncated or size > MAX_EDIT_BODY:
        return "over 1 MiB"
    if looks_binary(data, mime_of(message)):
        return "binary"
    try:
        message.get_text(strict=True)
    except ValueError:
        return "binary"
    return None


def breakpoint_view(held: Breakpoint) -> dict:
    original = held.original
    shown: dict[str, Any] = {"headers": header_list(original.headers), "body": body_info(original)}
    if isinstance(original, http.Request):
        shown |= {"method": clean(original.method), "path": clean(original.path)}
    else:
        shown |= {"status": original.status_code}
    return {"phase": held.phase, "since": held.since, "revision": held.revision,
            "body_not_editable": body_not_editable(held_message(held.flow, held.phase)), "original": shown}


def fixed_headers(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted((name.lower(), value) for name, value in pairs if name.lower() in FIXED_HEADERS)


def edit_problem(held: Breakpoint, edits: object) -> str | None:
    """Why the edits cannot be applied, or None. They name every part: a missing part is not 'unchanged'."""
    message = held_message(held.flow, held.phase)
    first = ("method", "path") if held.phase == "request" else ("status",)
    if not isinstance(edits, dict) or set(edits) != {*first, "headers", "body"}:
        return "Send the " + ", ".join(first) + ", headers and body."
    if held.phase == "request":
        if not isinstance(edits["method"], str) or not EDIT_METHOD.fullmatch(edits["method"]):
            return "The method must be 1 to 16 capital letters."
        path = edits["path"]
        if not isinstance(path, str) or not path.startswith("/") or len(path) > MAX_EDIT_PATH \
                or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in path):
            return "The path must start with / and have no spaces or line breaks."
    else:
        status = edits["status"]
        if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
            return "The status must be a number from 100 to 599."
    headers = edits["headers"]
    if not isinstance(headers, list) or len(headers) > MAX_EDIT_HEADERS:
        return f"Send at most {MAX_EDIT_HEADERS} headers, each a name and a value."
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(p, str) for p in pair):
            return f"Send at most {MAX_EDIT_HEADERS} headers, each a name and a value."
        name, value = pair
        if not HEADER_NAME.fullmatch(name) or any(c in value for c in "\r\n\0"):
            return BAD_HEADER
    if fixed_headers([tuple(pair) for pair in headers]) != fixed_headers(list(message.headers.items(multi=True))):
        return FIXED_EDITED
    body = edits["body"]
    if body is not None:
        if not isinstance(body, str):
            return "The body must be text."
        reason = body_not_editable(message)
        if reason is not None:
            return f"This body cannot be edited: {reason}."
        if len(body.encode("utf-8", "surrogatepass")) > MAX_EDIT_BODY:
            return "The body must be at most 1 MiB."
    return None


def apply_edits(held: Breakpoint, edits: dict) -> bool:
    """Applies edits that passed `edit_problem`; True when the message changed."""
    message = held_message(held.flow, held.phase)

    def state() -> tuple:
        first = (message.method, message.path) if isinstance(message, http.Request) else (message.status_code,)
        return first, message.headers.fields, message.raw_content

    before = state()
    message.headers = http.Headers([(name.encode("utf-8", "surrogateescape"), value.encode("utf-8", "surrogateescape"))
                                    for name, value in edits["headers"]])
    if isinstance(message, http.Request):
        message.method = edits["method"]
        message.path = edits["path"]
    elif edits["status"] != message.status_code:
        message.status_code = edits["status"]
        message.reason = status_codes.RESPONSES.get(edits["status"], "")
    if edits["body"] is not None and edits["body"] != message.get_text(strict=False):
        message.text = edits["body"]
    return state() != before


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def parse_log_line(raw: bytes, source: str, seq: int) -> dict | None:
    """One log line for the API; None for a blank line. A line that is not a JSON object keeps its text."""
    text = raw.decode("utf-8", "replace").rstrip("\r")
    if not text.strip():
        return None
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if not isinstance(record, dict):
        return {"seq": seq, "source": source, "message": text}
    message = record.get("message")
    if message is None:
        message = ""
    elif not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)
    return {"seq": seq, "source": source, "ts": parse_ts(record.get("ts")),
            "level": optional_str(record.get("level")), "tag": optional_str(record.get("tag")),
            "message": message, "request_id": optional_str(record.get("request_id")), "raw": text}


DEVICE_STATES = ("waiting", "streaming", "several", "stopped", "error")
DEVICE_TEXT_KEYS = ("message", "source", "app", "model", "os")
MAX_STATUS_BYTES = 4096
MAX_STATUS_TEXT = 200


def device_status(raw: bytes) -> dict | None:
    """The collector's state file, field by field; None if it is not one."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("state") not in DEVICE_STATES:
        return None
    status: dict[str, Any] = {"state": data["state"]}
    for key in DEVICE_TEXT_KEYS:
        value = data.get(key)
        status[key] = clean(value)[:MAX_STATUS_TEXT] if isinstance(value, str) else ""
    status["updated_at"] = parse_ts(data.get("updated_at"))
    return status


class StatusFile:
    """Follows device.status.json: the new contents when it changed since the last poll."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.status: dict | None = None
        self._seen: tuple | None = None

    def poll(self) -> bool:
        if self.path is None:
            return False
        try:
            stat = self.path.stat()
            marker = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if marker == self._seen:
                return False
            with open(self.path, "rb") as f:
                raw = f.read(MAX_STATUS_BYTES + 1)
        except OSError:
            return False
        self._seen = marker
        status = device_status(raw) if len(raw) <= MAX_STATUS_BYTES else None
        if status is None or status == self.status:
            return False
        self.status = status
        return True


def list_mocks(root: str) -> list[str]:
    """JSON files under `root`, at most MAX_MOCK_FILES of them, sorted. Symlinked folders are not entered."""
    if not root:
        return []
    base = Path(root)
    found: list[str] = []
    seen = 0
    try:
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = [name for name in dirnames if not (Path(dirpath) / name).is_symlink()]
            for name in filenames:
                seen += 1
                path = Path(dirpath) / name
                if name.endswith(".json") and path.is_file():
                    found.append(path.relative_to(base).as_posix())
                if seen >= MAX_MOCK_FILES:
                    return sorted(found)
        return sorted(found)
    except OSError:
        return sorted(found)


def qa_rules_document(rules: list) -> dict:
    """The rules file format of addons/qa_tools.py (`version: 1`)."""
    return {"version": 1, "rules": list(rules)}


def display_dir(path: str) -> str:
    """The folder relative to the wiretrace folder when it is inside it, else as given."""
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return path


# Log files

class LogTail:
    """Follows one JSON-lines log file: new lines since the last poll, the last `cap` kept."""

    def __init__(self, path: Path | None, source: str, cap: int = MAX_LOG_LINES) -> None:
        self.path = path
        self.source = source
        self.lines: deque[dict] = deque(maxlen=cap)
        self.seq = 0
        self.offset = 0
        self.partial = b""

    def poll(self) -> list[dict]:
        if self.path is None:
            return []
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.offset, self.partial = 0, b""
            if size == self.offset:
                return []
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read(READ_LIMIT)
        except OSError:
            return []
        self.offset += len(chunk)
        *complete, self.partial = (self.partial + chunk).split(b"\n")
        if len(self.partial) > MAX_PARTIAL:
            complete.append(self.partial)
            self.partial = b""
        new = []
        for raw in complete:
            line = parse_log_line(raw, self.source, self.seq + 1)
            if line:
                self.seq += 1
                new.append(line)
        self.lines.extend(new)
        return new


# Previous sessions, opened read-only

def open_regular(path: Path):
    """A binary file object for a regular file that is not a symlink, or None. Never writes."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
        return os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)
        return None


def read_session_meta(folder: Path) -> dict:
    f = open_regular(folder / session.META)
    if f is None:
        return {}
    try:
        with f:
            meta = json.loads(f.read(MAX_META_BYTES + 1)[:MAX_META_BYTES] or b"null")
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def count_of(meta: dict, key: str) -> int | None:
    value = meta.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def session_entry(folder: Path) -> dict:
    """What Previous sessions lists: from the folder name and meta.json only."""
    meta = read_session_meta(folder)
    started = parse_ts(meta.get("started_at"))
    if started is None:
        named = session.started(folder.name)
        started = named.timestamp() if named else None

    def text(key: str) -> str:
        value = meta.get(key)
        return clean(value) if isinstance(value, str) else ""

    return {"name": folder.name, "preset": text("preset"), "target": text("target"), "started_at": started,
            "ended_at": parse_ts(meta.get("ended_at")), "status": text("status") or None,
            "requests": count_of(meta, "requests"), "device_lines": count_of(meta, "device_log_lines"),
            "app_lines": count_of(meta, "app_log_lines"), "live": False}


def read_flows_file(path: Path, cap: int = MAX_FLOWS) -> tuple[dict[str, http.HTTPFlow], bool]:
    """The newest `cap` HTTP flows of a flows.mitm, and whether it ended early (a cut-off file)."""
    from mitmproxy import io

    f = open_regular(path)
    if f is None:
        return {}, False
    newest: deque[http.HTTPFlow] = deque(maxlen=cap)
    cut_off = False
    with f:
        try:
            for flow in io.FlowReader(f).stream():
                if isinstance(flow, http.HTTPFlow) and not is_receiver(flow):
                    newest.append(flow)
        except (exceptions.FlowReadException, OSError):
            cut_off = True
    return {flow.id: flow for flow in newest}, cut_off


def read_log_file(path: Path, source: str, cap: int = MAX_LOG_LINES) -> list[dict]:
    """The last `cap` lines of a log file, numbered from the start like the live tail numbers them."""
    f = open_regular(path)
    if f is None:
        return []
    lines: deque[dict] = deque(maxlen=cap)
    seq = 0
    with f:
        try:
            while raw := f.readline(MAX_PARTIAL):
                line = parse_log_line(raw.rstrip(b"\n"), source, seq + 1)
                if line:
                    seq += 1
                    lines.append(line)
        except OSError:
            pass
    return list(lines)


class Store:
    """What the read endpoints answer from: the live session, or one previous session."""

    def __init__(self, name: str, flows: dict[str, http.HTTPFlow], lines: dict[str, Any], cut_off: bool = False) -> None:
        self.name = name
        self.flows = flows
        self.lines = lines
        self.cut_off = cut_off


def read_session(folder: Path) -> Store:
    """Invariant 6: reads the folder and writes nothing to it. Runs in a worker thread."""
    flows, cut_off = read_flows_file(folder / session.FLOWS)
    lines = {name: read_log_file(folder / file, name) for name, file in SOURCES.items()}
    return Store(folder.name, flows, lines, cut_off)


def text_matches(flow: http.HTTPFlow, needle: str) -> bool:
    """Plain search: the URL, header names and values, and both bodies (bounded decode), ignoring case."""
    request, response = flow.request, flow.response
    if needle in clean(request.pretty_url).lower():
        return True
    messages = [m for m in (request, response) if m is not None]
    for message in messages:
        for name, value in message.headers.items(multi=True):
            if needle in clean(name).lower() or needle in clean(value).lower():
                return True
    for message in messages:
        text = body_info(message)["text"]
        if text and needle in text.lower():
            return True
    return False


# Flows and live updates

class Hub:
    """The flows listed in the window, and what the connected pages have not been told yet."""

    def __init__(self, cap: int = MAX_FLOWS) -> None:
        self.cap = cap
        self.flows: dict[str, http.HTTPFlow] = {}
        self.clients: set[tornado.websocket.WebSocketHandler] = set()
        self._dirty: dict[str, None] = {}
        self._lines: list[dict] = []
        self._device: dict | None = None
        self._state_changed = False
        self._tunnels: dict[str, dict] = {}
        # Flows held at a breakpoint: (phase, since). Never in a flow, so never in flows.mitm.
        self.paused: dict[str, tuple[str, float]] = {}

    def track(self, flow: http.HTTPFlow) -> None:
        if not isinstance(flow, http.HTTPFlow) or is_receiver(flow):
            return
        self.flows[flow.id] = flow
        while len(self.flows) > self.cap:
            dropped = next(iter(self.flows))
            del self.flows[dropped]
            self._dirty.pop(dropped, None)
        if self.clients:
            self._dirty[flow.id] = None

    def add_lines(self, lines: list[dict]) -> None:
        # A page that connects later loads the lines with a request, so nothing is kept for no one.
        if self.clients and lines:
            self._lines.extend(lines)

    def state_changed(self) -> None:
        self._state_changed = True

    def device_changed(self, status: dict) -> None:
        self._device = status

    def tunnel_changed(self, row: dict) -> None:
        # A page that connects later loads the rows with GET /api/tunnels.
        if self.clients:
            self._tunnels[row["id"]] = row

    def flush(self, state: Any) -> None:
        """Send the batch to every connected page. `state` builds the state message when it changed."""
        dirty, self._dirty = list(self._dirty), {}
        lines, self._lines = self._lines, []
        device, self._device = self._device, None
        changed, self._state_changed = self._state_changed, False
        tunnels, self._tunnels = list(self._tunnels.values()), {}
        if not self.clients:
            return
        messages = []
        flows = [summary(self.flows[i], self.paused.get(i)) for i in dirty if i in self.flows]
        for i in range(0, len(flows), CHUNK):
            messages.append({"type": "flows", "flows": flows[i:i + CHUNK]})
        for i in range(0, len(tunnels), CHUNK):
            messages.append({"type": "tunnels", "tunnels": tunnels[i:i + CHUNK]})
        for i in range(0, len(lines), CHUNK):
            messages.append({"type": "logs", "lines": lines[i:i + CHUNK]})
        if device is not None:
            messages.append({"type": "device", "status": device})
        if changed:
            messages.append({"type": "state", "state": state()})
        self.broadcast(messages)

    def broadcast(self, messages: list[dict]) -> None:
        for message in messages:
            text = json_encode(message)
            for client in list(self.clients):
                try:
                    future = client.write_message(text)
                except tornado.websocket.WebSocketClosedError:
                    continue
                future.add_done_callback(lambda f: f.cancelled() or f.exception())


# HTTP

class Guarded(tornado.web.RequestHandler):
    """Invariants 1 to 3: a valid Host, the token cookie, and X-Wiretrace on a mutation, before anything else."""

    def initialize(self, addon: WiretraceUI) -> None:
        self.addon = addon

    def set_default_headers(self) -> None:
        # Tornado calls this once before `initialize` (no `addon` yet), and again whenever it clears an error.
        addon = getattr(self, "addon", None)
        if addon is None:
            return
        for name, value in addon.security_headers.items():
            self.set_header(name, value)
        if self.request.path.startswith("/api/"):
            self.set_header("Cache-Control", "no-store")

    def prepare(self) -> None:
        addon = self.addon
        self.set_default_headers()
        if self.request.headers.get("Host", "").lower() not in addon.hosts:
            return self.refuse()
        if self.request.method == "GET" and self.request.path == "/" and self.get_query_argument("token", None):
            if addon.is_token(self.get_query_argument("token", "")):
                self.set_cookie(COOKIE, addon.token, httponly=True, samesite="Strict", path="/")
                return self.redirect("/")
            return self.refuse()
        if not addon.is_token(self.get_cookie(COOKIE, "")):
            return self.refuse()
        if self.request.method not in ("GET", "HEAD") and self.request.headers.get("X-Wiretrace") != "1":
            return self.refuse()

    def refuse(self) -> None:
        self.set_status(403)
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        self.finish(FORBIDDEN_PAGE)

    def fail(self, status: int, message: str) -> None:
        self.set_status(status)
        self.finish({"error": message})

    def store(self) -> Store | None:
        """The store `?session=` names: live without it. Fails the request and returns None otherwise."""
        status, found = self.addon.store_named(self.get_query_argument("session", ""))
        if found is None:
            self.fail(status, "Not a session name" if status == 400 else
                      "That session is not open: open it from Previous sessions first")
        return found

    def small_json(self) -> object:
        try:
            return json.loads(self.request.body or b"null")
        except ValueError:
            return NOT_JSON

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        self.finish({"error": self._reason})

    def log_exception(self, typ: type, value: BaseException, tb: Any) -> None:
        if isinstance(value, tornado.web.HTTPError):
            return
        # Only the type: a message or traceback could carry a URL, a filter or a header value.
        logger.error("Wiretrace UI: a request failed (%s)", typ.__name__)


class Assets(Guarded, tornado.web.StaticFileHandler):
    def initialize(self, addon: WiretraceUI, path: str, default_filename: str | None = None) -> None:
        Guarded.initialize(self, addon)
        tornado.web.StaticFileHandler.initialize(self, path, default_filename)

    def set_extra_headers(self, path: str) -> None:
        self.set_header("Cache-Control", "no-cache")


class State(Guarded):
    def get(self) -> None:
        self.write(self.addon.state())


class Flows(Guarded):
    def get(self) -> None:
        store = self.store()
        if store is not None:
            paused = self.addon.hub.paused if store.flows is self.addon.hub.flows else {}
            self.write({"flows": [summary(f, paused.get(f.id)) for f in store.flows.values()]})


class Tunnels(Guarded):
    """The live session's encrypted connections (spec 022, slice C); a previous session has none."""

    def get(self) -> None:
        self.write({"tunnels": [] if self.addon.viewed is not None else self.addon.tunnels.payload()})


class ApiHosts(Guarded):
    """Decrypt a passed-through host in the running session (spec 022, slice C)."""

    async def post(self) -> None:
        body = self.small_json()
        if not isinstance(body, dict) or set(body) != {"host"} or not isinstance(body["host"], str):
            return self.fail(400, "The body must be {host}")
        status, payload = await self.addon.decrypt_host(body["host"])
        self.set_status(status)
        self.finish(payload)


class FlowDetail(Guarded):
    def get(self, flow_id: str) -> None:
        store = self.store()
        if store is None:
            return
        flow = store.flows.get(flow_id)
        if flow is None:
            return self.fail(404, "Unknown request: it was never listed or has been dropped from memory.")
        live = store.flows is self.addon.hub.flows
        held = self.addon.breakpoints.get(flow_id) if live else None
        shown = detail(flow, display_dir(self.addon.mocks_dir()), self.addon.hub.paused.get(flow_id) if live else None)
        shown["breakpoint"] = breakpoint_view(held) if held is not None else None
        self.write(shown)


class Filter(Guarded):
    def get(self) -> None:
        store = self.store()
        if store is None:
            return
        expr = self.get_query_argument("expr", "").strip()
        if not expr:
            return self.fail(400, "Empty filter expression")
        try:
            matcher = flowfilter.parse(expr)
        except ValueError as e:
            return self.fail(400, str(e))
        if not matcher:
            return self.fail(400, "Invalid filter expression")
        ids = []
        for flow in store.flows.values():
            try:
                if matcher(flow):
                    ids.append(flow.id)
            except Exception:
                continue
        self.write({"ids": ids})


class Search(Guarded):
    """Plain text over headers and bodies, in chunks that let mitmproxy run; stops when the page goes away."""

    def initialize(self, addon: WiretraceUI) -> None:
        super().initialize(addon)
        self.gone = False

    def on_connection_close(self) -> None:
        self.gone = True

    async def get(self) -> None:
        text = self.get_query_argument("q", "").strip()
        if not SEARCH_MIN <= len(text) <= SEARCH_MAX:
            return self.fail(400, f"Search for {SEARCH_MIN} to {SEARCH_MAX} characters")
        store = self.store()
        if store is None:
            return
        needle = text.lower()
        ids = []
        # A snapshot: flows arrive and leave while this yields.
        for i, flow in enumerate(list(store.flows.values())):
            if i and i % SEARCH_CHUNK == 0:
                await asyncio.sleep(0)
                if self.gone:
                    return
            try:
                if text_matches(flow, needle):
                    ids.append(flow.id)
            except Exception:
                continue
        self.write({"ids": ids})


class Logs(Guarded):
    def get(self) -> None:
        source = self.get_query_argument("source", "")
        if source not in SOURCES:
            return self.fail(400, "source must be device or app")
        store = self.store()
        if store is not None:
            self.write({"lines": list(store.lines[source])})


class Sessions(Guarded):
    async def get(self) -> None:
        self.write({"sessions": await self.addon.list_sessions()})


class View(Guarded):
    async def post(self) -> None:
        body = self.small_json()
        if not isinstance(body, dict) or "session" not in body:
            return self.fail(400, "The body must be {session}")
        status, payload = await self.addon.open_view(body["session"])
        self.set_status(status)
        self.finish(payload)


class Replay(Guarded):
    def post(self, flow_id: str) -> None:
        status, payload = self.addon.replay(flow_id)
        self.set_status(status)
        self.finish(payload)


class Mocks(Guarded):
    def get(self) -> None:
        self.write({"files": list_mocks(self.addon.mocks_dir())})


class PresetForm(Guarded):
    """What the preset form's calls share: a body of at most 64 KiB, and a 400 that names the form field."""

    def preset_body(self) -> dict | None:
        """The JSON object sent, or None after a 400 (A8: the size is checked before the body is parsed)."""
        if len(self.request.body) > MAX_REQUEST_BYTES:
            self.bad("The request is larger than 64 KiB")
            return None
        body = self.small_json()
        if not isinstance(body, dict):
            self.bad("The body is not a JSON object")
            return None
        return body

    def bad(self, message: str, field: str | None = None) -> None:
        self.reply(400, {"error": message, "field": field})

    def reply(self, status: int, payload: dict) -> Any:
        self.set_status(status)
        return self.finish(payload)


class Presets(PresetForm):
    async def get(self) -> None:
        self.write({"presets": await self.addon.list_presets()})

    async def post(self) -> None:
        body = self.preset_body()
        if body is None:
            return
        if not isinstance(body.get("name"), str) or not presetfile.fields_shape_ok(body.get("fields")):
            return self.bad("The body must be {name, fields}")
        status, payload = await self.addon.create_preset(body["name"], body["fields"])
        self.reply(status, payload)


class PresetDetail(PresetForm):
    """One preset as the form shows it (spec 013, extension A)."""

    async def get(self, name: str) -> None:
        status, payload = await self.addon.preset_detail(name)
        self.reply(status, payload)

    async def put(self, name: str) -> None:
        body = self.preset_body()
        if body is None:
            return
        if not isinstance(body.get("revision"), str) or not presetfile.fields_shape_ok(body.get("fields")):
            return self.bad("The body must be {revision, fields}")
        status, payload = await self.addon.save_preset(name, body["revision"], body["fields"],
                                                       body.get("restart") is True)
        await self.reply(status, payload)
        if status == 202:
            # Only once the page has its answer: the launcher saves this session and starts the next.
            ctx.master.shutdown()


class SwitchRequest(Guarded):
    async def answer_switch(self, status: int, payload: dict) -> None:
        self.set_status(status)
        if status == 204:
            return self.finish()
        await self.finish(payload)
        if status == 202:
            # Only once the page has its answer: the launcher saves this session and starts the next.
            ctx.master.shutdown()


class PresetSwitch(SwitchRequest):
    async def post(self) -> None:
        body = self.small_json()
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            return self.fail(400, "The body must be {name}")
        status, payload = await self.addon.switch_preset(body["name"])
        await self.answer_switch(status, payload)


class Devices(Guarded):
    async def get(self) -> None:
        self.write({"devices": await self.addon.list_devices()})


class DeviceSwitch(SwitchRequest):
    async def post(self) -> None:
        body = self.small_json()
        if isinstance(body, dict) and set(body) == {"target", "client"}:
            # The target and the client are checked in invariant 2's order, after the 409s.
            status, payload = await self.addon.switch_client(body["target"], body["client"])
            return await self.answer_switch(status, payload)
        if not isinstance(body, dict) or set(body) != {"target"} or not isinstance(body["target"], str):
            return self.fail(400, "Unknown device.")
        status, payload = await self.addon.switch_device(body["target"])
        await self.answer_switch(status, payload)


class ProxyDevice(Guarded):
    """Allow a refused device, or remove an accepted one, in this session (spec 022, slice A)."""

    def initialize(self, addon: WiretraceUI, action: str) -> None:
        super().initialize(addon)
        self.action = action

    def post(self) -> None:
        body = self.small_json()
        if not isinstance(body, dict) or set(body) != {"client"} or not isinstance(body["client"], str):
            return self.fail(400, "The body must be {client}")
        status, payload = self.addon.change_device(self.action, body["client"])
        self.set_status(status)
        self.finish(payload)


class ProxyPortCheck(Guarded):
    async def get(self) -> None:
        status, payload = await self.addon.port_check(self.get_query_argument("port", ""))
        self.set_status(status)
        self.finish(payload)


class ProxyPort(SwitchRequest):
    """Restart on another Wi-Fi proxy port (spec 022, slice B)."""

    async def post(self) -> None:
        body = self.small_json()
        if not isinstance(body, dict) or set(body) != {"port"}:
            return self.fail(400, "The body must be {port}")
        status, payload = await self.addon.change_port(body["port"])
        await self.answer_switch(status, payload)


@tornado.web.stream_request_body
class LargeBody(Guarded):
    """A JSON body up to MAX_RULES_REQUEST_BYTES; the limit is raised only once `Guarded.prepare` passed."""

    def initialize(self, addon: WiretraceUI) -> None:
        super().initialize(addon)
        self._chunks: list[bytes] = []

    def prepare(self) -> None:
        Guarded.prepare(self)
        if not self._finished and self.request.method in ("PUT", "POST"):
            self.request.connection.set_max_body_size(MAX_RULES_REQUEST_BYTES)

    def data_received(self, chunk: bytes) -> None:
        if not self._finished:
            self._chunks.append(chunk)

    def json_body(self) -> object:
        try:
            return json.loads(b"".join(self._chunks) or b"null")
        except ValueError:
            return NOT_JSON


class BreakpointAction(LargeBody):
    """Continue or abort a paused flow, with its edits (spec 022, slice D)."""

    def post(self, flow_id: str) -> None:
        status, payload = self.addon.breakpoint_action(flow_id, self.json_body())
        self.set_status(status)
        self.finish(payload)


class MapLocal(LargeBody):
    """Save a response as a mock file, and the rule that answers with it (spec 022, slice F)."""

    def post(self, flow_id: str) -> None:
        body = self.json_body()
        if body is NOT_JSON:
            return self.fail(400, "The body is not JSON")
        status, payload = self.addon.map_local(flow_id, body)
        self.set_status(status)
        self.finish(payload)


class ContinueAll(Guarded):
    def post(self) -> None:
        self.write({"continued": self.addon.release_all()})


class RulesApi(LargeBody):
    def get(self) -> None:
        self.write(self.addon.rules_payload())

    def put(self) -> None:
        body = self.json_body()
        if body is NOT_JSON:
            return self.fail(400, "The body is not JSON")
        if not isinstance(body, dict) or not isinstance(body.get("revision"), str) or not isinstance(body.get("rules"), list):
            return self.fail(400, "The body must be {revision, rules}")
        status, payload = self.addon.save_rules(body["revision"], body["rules"])
        self.set_status(status)
        self.finish(payload)


class RuleTest(LargeBody):
    def post(self) -> None:
        body = self.json_body()
        if body is NOT_JSON:
            return self.fail(400, "The body is not JSON")
        if not isinstance(body, dict) or not isinstance(body.get("flow_id"), str):
            return self.fail(400, "The body must be {rule, flow_id}")
        live = self.addon.qatools()
        if live is None:
            return self.fail(503, NO_QA)
        flow = self.addon.hub.flows.get(body["flow_id"])
        if flow is None:
            return self.fail(404, "Unknown request: it was never listed or has been dropped from memory.")
        result = live.test_rule(body.get("rule"), flow)
        if "error" in result:
            self.set_status(400)
        self.finish(result)


class UnknownApi(Guarded):
    """Any other /api/ path: 404 after the usual checks, rather than the static files' 405."""

    def prepare(self) -> None:
        Guarded.prepare(self)
        if not self._finished:
            self.fail(404, "Unknown API endpoint")


class RuleRearm(Guarded):
    def post(self, rule_id: str) -> None:
        live = self.addon.qatools()
        if live is None:
            return self.fail(503, NO_QA)
        if not live.rearm(rule_id):
            return self.fail(404, "Unknown rule")
        self.write(self.addon.rules_payload())


class Report(Guarded):
    async def post(self) -> None:
        body = self.small_json()
        name = body.get("session") if isinstance(body, dict) else None
        if body is NOT_JSON or (name is not None and not isinstance(name, str)):
            return self.fail(400, "The body must be empty or {session}")
        folder = None
        if name and name != self.addon.live_name():
            folder = await self.addon.find_session(name)
            if folder is None:
                return self.fail(404, "Unknown session")
        if self.addon.report_running:
            return self.fail(409, "A report is already being written")
        self.write(await self.addon.make_report(folder))


class Reveal(Guarded):
    async def post(self) -> None:
        error = await self.addon.reveal_report()
        if error:
            return self.fail(404 if error == NO_REPORT else 500, error)
        self.write({"ok": True})


class ReportForm(Guarded):
    """The bug report form (spec 012): the session, the request and the boxes come from the query."""

    async def session_folder(self, name: object) -> tuple[Path, bool] | None:
        """The folder and whether it is a previous session; fails the request and returns None otherwise."""
        status, message, folder, previous = await self.addon.report_folder(name)
        if folder is None:
            self.fail(status, message)
            return None
        return folder, previous

    def include(self) -> report.Include | None:
        flow = self.get_query_argument("flow", "")
        if flow and not FLOW_ID.fullmatch(flow):
            self.fail(400, "Not a request id")
            return None
        raw = self.get_query_argument("include", None)
        boxes = set(REPORT_BOXES) if raw is None else {box for box in raw.split(",") if box}
        if boxes - set(REPORT_BOXES):
            self.fail(400, "include lists others, device and app")
            return None
        return report.Include(flow or None, "others" in boxes, "device" in boxes, "app" in boxes)


class ReportDraft(ReportForm):
    async def get(self) -> None:
        include = self.include()
        if include is None:
            return
        fmt = self.get_query_argument("format", "markdown")
        if fmt not in report_text.FORMATS:
            return self.fail(400, "format is markdown or jira")
        found = await self.session_folder(self.get_query_argument("session", ""))
        if found is None:
            return
        status, payload = await self.addon.report_draft(*found, include, fmt)
        self.set_status(status)
        self.finish(payload)


class ReportFile(ReportForm):
    async def get(self, kind: str) -> None:
        if kind not in report.FILE_TYPES:
            return self.fail(404, "Unknown file")
        include = self.include()
        if include is None:
            return
        found = await self.session_folder(self.get_query_argument("session", ""))
        if found is None:
            return
        status, result = await self.addon.report_file(found[0], kind, include)
        if isinstance(result, str):
            return self.fail(status, result)
        name, data = result
        self.set_header("Content-Type", report.FILE_TYPES[kind])
        self.set_header("Content-Disposition", f'attachment; filename="{name}"')
        self.finish(data)


class ReportScreenshots(ReportForm):
    async def post(self) -> None:
        body = self.small_json()
        name = body.get("session") if isinstance(body, dict) else None
        if body is NOT_JSON or (name is not None and not isinstance(name, str)):
            return self.fail(400, "The body must be empty or {session}")
        found = await self.session_folder(name or "")
        if found is None:
            return
        folder, previous = found
        if previous:
            return self.fail(409, screenshot.PREVIOUS)
        if self.addon.screenshot_running:
            return self.fail(409, "A screenshot is already being taken")
        status, payload = await self.addon.take_screenshot(folder)
        self.set_status(status)
        self.finish(payload)


class ReportScreenshot(ReportForm):
    """One screenshot, by a name that must be in the session's listing (invariant 5)."""

    async def get(self, name: str) -> None:
        found = await self.session_folder(self.get_query_argument("session", ""))
        if found is None:
            return
        folder = found[0]
        data = await asyncio.to_thread(read_screenshot, folder, name)
        if data is None:
            return self.fail(404, "Unknown screenshot")
        self.set_header("Content-Type", "image/png")
        if self.get_query_argument("download", "") == "1":
            self.set_header("Content-Disposition",
                            f'attachment; filename="{screenshot.download_name(folder.name, name)}"')
        self.finish(data)

    async def delete(self, name: str) -> None:
        found = await self.session_folder(self.get_query_argument("session", ""))
        if found is None:
            return
        folder, previous = found
        if previous:
            return self.fail(409, "A previous session is read-only")
        status, payload = await self.addon.remove_screenshot(folder, name)
        self.set_status(status)
        self.finish(payload)


def read_screenshot(folder: Path, name: str) -> bytes | None:
    path = screenshot.find(folder, name)
    f = open_regular(path) if path is not None else None
    if f is None:
        return None
    with f:
        data = f.read(screenshot.MAX_BYTES + 1)
    return data if len(data) <= screenshot.MAX_BYTES else None


class Updates(Guarded, tornado.websocket.WebSocketHandler):
    def prepare(self) -> None:
        Guarded.prepare(self)
        if not self._finished and self.request.headers.get("Origin", "") not in self.addon.origins:
            self.refuse()

    def check_origin(self, origin: str) -> bool:
        return origin in self.addon.origins

    def open(self, *args: str, **kwargs: str) -> None:
        self.addon.hub.clients.add(self)

    def on_close(self) -> None:
        self.addon.hub.clients.discard(self)

    def on_message(self, message: str | bytes) -> None:
        """The page sends nothing."""


NO_REPORT = "No report has been written yet."


# The addon

class WiretraceUI:
    def __init__(self) -> None:
        self.hub = Hub()
        self.static_dir = ROOT / "ui" / "dist"
        self.tails: dict[str, LogTail] = {}
        self.device_file = StatusFile(None)
        self.token = ""
        self.port = 0
        self.hosts: set[str] = set()
        self.origins: set[str] = set()
        self.security_headers: dict[str, str] = {}
        self.report_running = False
        self.screenshot_running = False
        self.last_report: Path | None = None
        self.presets_dir = PRESETS_DIR
        # For the device menu's device-log line; tests replace both.
        self.collector_for = collector_command
        self.bin_dir = Path(sys.prefix) / "bin"
        # The preset `.switch.json` names once it is written; mitmdump is then shutting down.
        self.switching: str | None = None
        # One preset write at a time, so a refused restart never writes a file another request is racing for.
        self.preset_lock = asyncio.Lock()
        self.started_at = time.time()
        # Setup: when a device last connected, and failed TLS handshakes with API hosts. Nothing about the peer.
        self.device_seen_at: float | None = None
        self.tls_failures = 0
        # The sidebar's device list: per accepted address, in memory only (spec 022, slice A).
        self.client_stats = ClientStats()
        self.tunnels = TunnelList()
        # Flows held at a breakpoint, a revision per pause, and when a window was last connected (monotonic).
        self.breakpoints: dict[str, Breakpoint] = {}
        self._breakpoint_revision = 0
        self._window_seen_at = time.monotonic()
        # The Wi-Fi proxy's refused addresses the page was last sent, and when (monotonic seconds).
        self._waiting_sent: frozenset[str] = frozenset()
        self._waiting_sent_at = 0.0
        # One previous session opened read-only; the live capture goes on meanwhile.
        self.viewed: Store | None = None
        self.view_generation = 0
        self._rules_sent: tuple = ()
        self._server: httpserver.HTTPServer | None = None
        self._tasks: list[asyncio.Task] = []
        # Status file: last write, and the fields apart from updated_at, so a quiet session still heartbeats.
        self._status_at = 0.0
        self._status_body: tuple | None = None
        self._closed = False

    # Options

    def load(self, loader) -> None:
        # Before the listener accepts, and kept after done(): connections still close then.
        redact_terminal()
        loader.add_option("qa_ui_port", int, 8081, "Port of the Wiretrace window on 127.0.0.1.")
        loader.add_option("qa_ui_session_dir", str, "",
                          "Session folder: meta.json, the log files and the report.")
        loader.add_option("qa_ui_default_filter", str, "", "Initial search of the Wiretrace window.")
        loader.add_option("qa_ui_open_browser", bool, True, "Open the Wiretrace window link at start.")
        loader.add_option("qa_ui_print_link", bool, True,
                          "Print the window link. Off when the output goes to a file (Wiretrace.app).")
        loader.add_option("qa_ui_from_app", bool, False,
                          "Started from Wiretrace.app: the window shows where to switch and how to stop.")

    def configure(self, updated) -> None:
        if not 0 <= ctx.options.qa_ui_port <= 65535:
            raise exceptions.OptionsError("qa_ui_port must be 0 to 65535")

    # Lifecycle

    async def running(self) -> None:
        if self._server is not None:
            return
        self.token = take_ui_token() or secrets.token_urlsafe(32)
        folder = Path(ctx.options.qa_ui_session_dir) if ctx.options.qa_ui_session_dir else None
        self.tails = {name: LogTail(folder / file if folder else None, name) for name, file in SOURCES.items()}
        self.device_file = StatusFile(folder / session.DEVICE_STATUS if folder else None)
        try:
            sockets = netutil.bind_sockets(ctx.options.qa_ui_port, address="127.0.0.1")
        except OSError as e:
            logger.error("Wiretrace UI: cannot listen on 127.0.0.1:%s (%s)", ctx.options.qa_ui_port,
                         e.strerror or e)
            ctx.master.shutdown()
            return
        self.port = sockets[0].getsockname()[1]
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{host}" for host in self.hosts}
        self.security_headers = {
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                f"connect-src 'self' ws://127.0.0.1:{self.port} ws://localhost:{self.port}; "
                "frame-ancestors 'none'"),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        self._server = httpserver.HTTPServer(self.make_app(), max_body_size=MAX_REQUEST_BYTES)
        self._server.add_sockets(sockets)
        self.poll_logs()
        self._tasks = [asyncio.create_task(self._tail_logs()), asyncio.create_task(self._flush_updates())]

        link = f"http://127.0.0.1:{self.port}/?token={self.token}"
        print_link = ctx.options.qa_ui_print_link
        try:
            print(f"Wiretrace UI: {link}" if print_link else "Wiretrace UI: opened in the browser", flush=True)
        except OSError:
            pass
        if ctx.options.qa_ui_open_browser:
            try:
                await asyncio.to_thread(webbrowser.open, link)
            except Exception:
                where = "open the link above" if print_link else "use Open Wiretrace in the Wiretrace menu (the W icon at the top right)"
                logger.error("Wiretrace UI: could not open the browser; %s", where)

    async def done(self) -> None:
        self._closed = True
        self.release_all(abort=True)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self.remove_status()
        for client in list(self.hub.clients):
            client.close()
        if self._server is not None:
            self._server.stop()
            await self._server.close_all_connections()
            self._server = None

    def make_app(self) -> tornado.web.Application:
        handler_args = {"addon": self}
        return tornado.web.Application(
            [
                (r"/api/state", State, handler_args),
                (r"/api/flows", Flows, handler_args),
                (r"/api/tunnels", Tunnels, handler_args),
                (r"/api/api-hosts", ApiHosts, handler_args),
                (r"/api/flows/([^/]+)/replay", Replay, handler_args),
                (r"/api/flows/([^/]+)/breakpoint", BreakpointAction, handler_args),
                (r"/api/flows/([^/]+)/map-local", MapLocal, handler_args),
                (r"/api/breakpoints/continue-all", ContinueAll, handler_args),
                (r"/api/flows/([^/]+)", FlowDetail, handler_args),
                (r"/api/filter", Filter, handler_args),
                (r"/api/search", Search, handler_args),
                (r"/api/logs", Logs, handler_args),
                (r"/api/sessions", Sessions, handler_args),
                (r"/api/view", View, handler_args),
                (r"/api/mocks", Mocks, handler_args),
                (r"/api/presets", Presets, handler_args),
                (r"/api/presets/([A-Za-z0-9][A-Za-z0-9_-]{0,63})", PresetDetail, handler_args),
                (r"/api/preset", PresetSwitch, handler_args),
                (r"/api/devices", Devices, handler_args),
                (r"/api/device", DeviceSwitch, handler_args),
                (r"/api/proxy/allow", ProxyDevice, {**handler_args, "action": "allow"}),
                (r"/api/proxy/remove", ProxyDevice, {**handler_args, "action": "remove"}),
                (r"/api/proxy/port-check", ProxyPortCheck, handler_args),
                (r"/api/proxy/port", ProxyPort, handler_args),
                (r"/api/rules", RulesApi, handler_args),
                (r"/api/rules/test", RuleTest, handler_args),
                (r"/api/rules/([a-z0-9]{6,32})/rearm", RuleRearm, handler_args),
                (r"/api/report", Report, handler_args),
                (r"/api/report/reveal", Reveal, handler_args),
                (r"/api/report/draft", ReportDraft, handler_args),
                (r"/api/report/file/([^/]+)", ReportFile, handler_args),
                (r"/api/report/screenshot", ReportScreenshots, handler_args),
                (r"/api/report/screenshot/([^/]+)", ReportScreenshot, handler_args),
                (r"/api/updates", Updates, handler_args),
                (r"/api/.*", UnknownApi, handler_args),
                (r"/(.*)", Assets, {**handler_args, "path": str(self.static_dir), "default_filename": "index.html"}),
            ],
            log_function=lambda handler: None,
            websocket_ping_interval=20,
        )

    def is_token(self, value: str) -> bool:
        return bool(self.token) and hmac.compare_digest(value.encode(), self.token.encode())

    # Hooks: HTTP flows only

    def track(self, flow: http.Flow) -> None:
        try:
            self.hub.track(flow)
        except Exception as e:
            # The capture must go on whatever the window does.
            logger.error("Wiretrace UI: could not list a request (%s)", type(e).__name__)

    response = websocket_start = websocket_end = track

    def request(self, flow: http.HTTPFlow) -> None:
        self.track(flow)
        if getattr(flow, "is_replay", None) == "request":
            return
        try:
            address = self.device_address(flow.client_conn)
            if address:
                self.client_stats.request(address)
        except Exception as e:
            logger.error("Wiretrace UI: could not count a request (%s)", type(e).__name__)

    # Hooks: connections, for Setup and the device list

    def device_address(self, client: Any) -> str | None:
        """The Wi-Fi proxy device a connection comes from, when the device list shows it: accepted with
        pinning, listed with `--client`. None for this Mac, a WireGuard client or a refused one."""
        if client is None or not regular_client(client):
            return None
        guard = self.proxyguard()
        address = guardlib.pinnable(peer_address(client) or "")
        if guard is None or address is None:
            return None
        if self.pin_option():
            return address if address in guard.accepted() else None
        return address if guard.listed(address) else None

    def client_connected(self, client) -> None:
        # proxy_guard runs first and sets `error` on a client it refuses: that is not the device.
        if getattr(client, "error", None):
            try:
                self.refusal_seen()
            except Exception as e:
                logger.error("Wiretrace UI: could not read the refused devices (%s)", type(e).__name__)
            return
        now = time.time()
        first = self.device_seen_at is None
        self.device_seen_at = now
        try:
            address = self.device_address(client)
            if address and self.client_stats.seen(address, now):
                first = True
        except Exception as e:
            logger.error("Wiretrace UI: could not note a device (%s)", type(e).__name__)
        if first:
            self.hub.state_changed()

    def refusal_seen(self) -> None:
        """A new refused address reaches the page at once; a repeat at most every WAITING_PUSH_S."""
        if not self.pin_option():
            return
        listed = frozenset(entry["address"] for entry in self.waiting_list())
        now = time.monotonic()
        if listed - self._waiting_sent or now - self._waiting_sent_at >= WAITING_PUSH_S:
            self._waiting_sent, self._waiting_sent_at = listed, now
            self.hub.state_changed()

    def tls_failed_client(self, data) -> None:
        try:
            sni = data.context.client.sni or ""
        except AttributeError:
            return
        live = self.qatools()
        hosts = list(live.api_hosts) if live is not None else []
        if sni and is_api_host(sni, hosts):
            self.tls_failures += 1
            address = self.device_address(data.context.client)
            if address:
                self.client_stats.tls_failure(address)
            self.hub.state_changed()

    # Hooks: connections passed through without decrypting (spec 022, slice C)

    def http_connect(self, flow: http.HTTPFlow) -> None:
        try:
            self.tunnels.connect(flow)
        except Exception as e:
            logger.error("Wiretrace UI: could not note a CONNECT (%s)", type(e).__name__)

    def next_layer(self, nextlayer) -> None:
        try:
            row = self.tunnels.layer(nextlayer, client_label(nextlayer.context.client), time.time())
        except Exception as e:
            logger.error("Wiretrace UI: could not list an encrypted connection (%s)", type(e).__name__)
            return
        if row is not None:
            self.hub.tunnel_changed(row.payload())

    def client_disconnected(self, client) -> None:
        self._tunnel_closed(getattr(client, "id", None))
        # A flow paused on this connection would otherwise wait for a page action that cannot help.
        for flow_id, held in list(self.breakpoints.items()):
            if held.flow.client_conn.id == getattr(client, "id", None):
                self.release(flow_id)

    def server_disconnected(self, data) -> None:
        self._tunnel_closed(getattr(getattr(data, "client", None), "id", None))

    def _tunnel_closed(self, client_id: str | None) -> None:
        if client_id is None:
            return
        row = self.tunnels.closed(client_id, time.time())
        if row is not None:
            self.hub.tunnel_changed(row.payload())

    # Breakpoints (spec 022, slice D). qa_tools intercepts a flow a pause rule matched and
    # registers it here; only this window releases it.

    def pause_refusal(self) -> str | None:
        """Why a pause rule must let a flow through instead, or None."""
        if self._closed or self.switching is not None or not self.hub.clients:
            return "no window"
        if len(self.breakpoints) >= MAX_PAUSED:
            return f"{MAX_PAUSED} already paused"
        return None

    def paused(self, flow: http.HTTPFlow, phase: str, original: http.Message | None = None) -> None:
        self._breakpoint_revision += 1
        held = Breakpoint(flow, phase, time.time(), self._breakpoint_revision,
                          original if original is not None else held_message(flow, phase).copy())
        self.breakpoints[flow.id] = held
        self.hub.paused[flow.id] = (phase, held.since)
        self.track(flow)
        self.hub.state_changed()

    def release(self, flow_id: str, abort: bool = False) -> bool:
        """Lets a paused flow go on, or ends it. Resume and kill happen in one step: kill alone
        would leave mitmproxy waiting on the flow."""
        held = self.breakpoints.pop(flow_id, None)
        self.hub.paused.pop(flow_id, None)
        if held is None:
            return False
        held.flow.resume()
        if abort and held.flow.killable:
            held.flow.kill()
        self.track(held.flow)
        self.hub.state_changed()
        return True

    def release_all(self, abort: bool = False) -> int:
        return sum(self.release(flow_id, abort) for flow_id in list(self.breakpoints))

    def error(self, flow: http.HTTPFlow) -> None:
        # The app or the server went away while the flow was paused.
        self.release(flow.id)
        self.track(flow)

    def breakpoint_action(self, flow_id: str, body: object) -> tuple[int, dict]:
        if not isinstance(body, dict) or set(body) - {"action", "edits", "revision"} \
                or body.get("action") not in ("continue", "abort"):
            return 400, {"error": "Send action continue or abort, the revision, and the edits or null."}
        revision = body.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool):
            return 400, {"error": "Send action continue or abort, the revision, and the edits or null."}
        held = self.breakpoints.get(flow_id)
        if held is None or not held.flow.live:
            return 409, {"error": NOT_PAUSED}
        if revision != held.revision:
            return 409, {"error": STALE_EDIT}
        if body["action"] == "abort":
            self.release(flow_id, abort=True)
            return 200, {"id": flow_id, "action": "abort", "edited": False}
        edits = body.get("edits")
        edited = False
        if edits is not None:
            problem = edit_problem(held, edits)
            if problem is not None:
                return 400, {"error": problem}
            edited = apply_edits(held, edits)
            if edited:
                tag = f"breakpoint: {held.phase}"
                held.flow.comment = "; ".join(f"{part} edited" if part == tag else part
                                              for part in comment_parts(held.flow.comment))
        self.release(flow_id)
        return 200, {"id": flow_id, "action": "continue", "edited": edited}

    def breakpoint_watchdog(self, now: float) -> None:
        """With no window for BREAKPOINT_WATCHDOG_S, paused flows go on unchanged."""
        if self.hub.clients or not self.breakpoints:
            self._window_seen_at = now
            return
        if now - self._window_seen_at >= BREAKPOINT_WATCHDOG_S:
            count = self.release_all()
            logger.info("Wiretrace UI: no window for %d s: %d paused requests continue unchanged",
                        BREAKPOINT_WATCHDOG_S, count)

    # Background loops

    def poll_logs(self) -> None:
        for tail in self.tails.values():
            self.hub.add_lines(tail.poll())
        if self.device_file.poll():
            self.hub.device_changed(self.device_file.status)

    async def _tail_logs(self) -> None:
        while True:
            await asyncio.sleep(TAIL_S)
            try:
                self.poll_logs()
            except Exception as e:
                logger.error("Wiretrace UI: could not read the log files (%s)", type(e).__name__)

    async def _flush_updates(self) -> None:
        while True:
            await asyncio.sleep(BATCH_S)
            try:
                self.maybe_write_status()
            except Exception as e:
                logger.error("Wiretrace UI: could not write status (%s)", type(e).__name__)
            try:
                self.breakpoint_watchdog(time.monotonic())
            except Exception as e:
                logger.error("Wiretrace UI: could not continue paused requests (%s)", type(e).__name__)
            try:
                self.flush_rules()
                self.hub.flush(self.state)
            except Exception as e:
                logger.error("Wiretrace UI: could not send updates (%s)", type(e).__name__)

    # API

    def meta(self) -> dict:
        folder = ctx.options.qa_ui_session_dir
        try:
            meta = session.read_meta(Path(folder)) if folder else {}
        except (OSError, ValueError):
            return {}
        return meta if isinstance(meta, dict) else {}

    def mocks_dir(self) -> str:
        return ctx.options.qa_mocks_dir if "qa_mocks_dir" in ctx.options else ""

    def faults(self) -> dict:
        o = ctx.options
        if FAULT_OPTIONS["filter"] not in o:
            return {"filter": "", "status": 0, "delay_ms": 0, "drop": False}
        return {key: getattr(o, option) for key, option in FAULT_OPTIONS.items()}

    def wireguard_conf(self) -> str | None:
        proxyserver = ctx.master.addons.get("proxyserver")
        for server in getattr(proxyserver, "servers", ()):
            client_conf = getattr(server, "client_conf", None)
            if client_conf is None:
                continue
            try:
                text = client_conf()
            except Exception:
                text = None
            if text:
                return text.strip() + "\n"
        return None

    def state(self) -> dict:
        from mitmproxy.net import local_ip

        meta = self.meta()
        mode = meta.get("mode") if isinstance(meta.get("mode"), str) else ""
        faults = self.faults()
        live = self.qatools()
        started = parse_ts(meta.get("started_at"))
        device_logs = meta.get("device_logs")
        device_logs_off = meta.get("device_logs_off")
        pinning = self.pin_option() and mode != "wireguard"
        guard = self.proxyguard() if pinning else None
        pinned = getattr(guard, "pinned", None)
        mac_ip = local_ip.get_local_ip() if mode != "wireguard" else None
        proxy_port = self.current_proxy_port()
        return {
            "version": __version__,
            "preset": str(meta.get("preset") or ""),
            # The hosts decrypted now: the preset's, plus any the window added (spec 022, slice C).
            "api_hosts": self.live_api_hosts(),
            "target": str(meta.get("target") or ""),
            "mode": mode,
            "started_at": started if started is not None else self.started_at,
            "session": Path(ctx.options.qa_ui_session_dir).name,
            "device_logs": device_logs if isinstance(device_logs, str) and device_logs else None,
            "device_logs_off": device_logs_off if isinstance(device_logs_off, str) and device_logs_off else None,
            "default_filter": ctx.options.qa_ui_default_filter,
            "proxy_port": proxy_port,
            # proxy_guard adds the option, and only in a mode with the Wi-Fi proxy.
            "proxy_pin": bool(ctx.options.qa_proxy_pin) if "qa_proxy_pin" in ctx.options else False,
            # Spec 021: addresses only here and on the socket, both behind the token (invariant 5).
            "proxy_device": pinned if isinstance(pinned, str) else None,
            "proxy_waiting": self.waiting_list() if pinning and self.viewed is None else [],
            "proxy_clients": self.proxy_clients(mode),
            "proxy_max": guardlib.MAX_ACCEPTED,
            "proxy_address": f"{mac_ip}:{proxy_port}" if mac_ip else None,
            "from_app": bool(ctx.options.qa_ui_from_app),
            "wireguard_conf": self.wireguard_conf() if mode != "proxy" else None,
            "mac_ip": mac_ip,
            "faults": faults,
            "faults_on": self.faults_on(faults),
            "mocks_dir": display_dir(self.mocks_dir()),
            "flow_count": len(self.hub.flows),
            "paused_count": len(self.breakpoints),
            "paused_max": MAX_PAUSED,
            "rules_on": sum(1 for r in live.rules.rules if r.enabled) if live is not None else 0,
            "device_seen_at": self.device_seen_at,
            "tls_failures": self.tls_failures,
            "device_status": self.device_file.status,
            "viewing": self.viewed.name if self.viewed else None,
            "viewing_cut_off": bool(self.viewed and self.viewed.cut_off),
        }

    def status_payload(self, now: float) -> dict:
        """Version 1 of the menu bar file: counts only, nothing a report would have to hide."""
        meta = self.meta()
        started = parse_ts(meta.get("started_at"))
        device = self.device_file.status or {}
        model = device.get("model") if isinstance(device.get("model"), str) else ""
        device_state = device.get("state") if isinstance(device.get("state"), str) else ""
        mode = meta.get("mode") if isinstance(meta.get("mode"), str) else ""
        errors, last_error = error_tally(self.hub.flows)
        live = self.qatools()
        rules_on = sum(1 for rule in live.rules.rules if rule.enabled) if live is not None else 0
        return {
            "v": 1,
            "updated_at": now,
            "started_at": started if started is not None else self.started_at,
            "preset": str(meta.get("preset") or ""),
            "target": str(meta.get("target") or ""),
            "mode": mode,
            "device_state": device_state or None,
            "device_model": model.strip() or None,
            "requests": len(self.hub.flows),
            "errors": errors,
            "rules_on": rules_on,
            "last_error": last_error,
        }

    def maybe_write_status(self, now: float | None = None) -> None:
        """Write when a value changed, at most once a second, and at least every two seconds."""
        if self._closed:
            return
        folder = ctx.options.qa_ui_session_dir
        if not folder:
            return
        now = time.time() if now is None else now
        payload = self.status_payload(now)
        body = tuple(payload[key] for key in STATUS_KEYS if key != "updated_at")
        elapsed = now - self._status_at
        if self._status_at:
            if elapsed < STATUS_MIN_S:
                return
            if body == self._status_body and elapsed < STATUS_HEARTBEAT_S:
                return
        try:
            write_status_file(Path(folder) / session.STATUS, payload)
        except OSError as e:
            logger.error("Wiretrace UI: could not write status (%s)", type(e).__name__)
            return
        self._status_at = now
        self._status_body = body

    def remove_status(self) -> None:
        folder = ctx.options.qa_ui_session_dir
        if not folder:
            return
        path = Path(folder) / session.STATUS
        for leftover in (path, path.with_name(path.name + ".tmp")):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                logger.error("Wiretrace UI: could not remove status (%s)", "OSError")

    # Previous sessions. Invariant 5: a session is found in the listing by its name, never by a path from the page.

    def live_name(self) -> str:
        folder = ctx.options.qa_ui_session_dir
        return Path(folder).name if folder else ""

    def live_store(self) -> Store:
        return Store(self.live_name(), self.hub.flows, {name: tail.lines for name, tail in self.tails.items()})

    def store_named(self, name: str) -> tuple[int, Store | None]:
        if not name or name == self.live_name():
            return 200, self.live_store()
        if not session.NAME.fullmatch(name):
            return 400, None
        if self.viewed is None or self.viewed.name != name:
            return 409, None
        return 200, self.viewed

    async def find_session(self, name: object) -> Path | None:
        folder = ctx.options.qa_ui_session_dir
        if not folder or not isinstance(name, str) or not session.NAME.fullmatch(name):
            return None
        listed = await asyncio.to_thread(session.list_sessions, Path(folder).parent)
        return next((p for p in listed if p.name == name), None)

    async def list_sessions(self) -> list[dict]:
        folder = ctx.options.qa_ui_session_dir
        if not folder:
            return []
        live = self.live_name()

        def entries() -> list[dict]:
            return [session_entry(p) for p in reversed(session.list_sessions(Path(folder).parent))]

        found = await asyncio.to_thread(entries)
        for entry in found:
            if entry["name"] == live:
                entry.update(live=True, requests=len(self.hub.flows),
                             device_lines=self.tails["device"].seq if "device" in self.tails else 0,
                             app_lines=self.tails["app"].seq if "app" in self.tails else 0)
        return found

    async def open_view(self, name: object) -> tuple[int, dict]:
        """Open a previous session read-only, or go back to live with None. The last request wins."""
        self.view_generation += 1
        generation = self.view_generation
        if name is None or name == self.live_name():
            self.viewed = None
            self.hub.state_changed()
            return 200, {"viewing": None}
        if not isinstance(name, str) or not session.NAME.fullmatch(name):
            return 400, {"error": "Not a session name"}
        folder = await self.find_session(name)
        if folder is None:
            return 404, {"error": "Unknown session"}
        try:
            opened = await asyncio.to_thread(read_session, folder)
        except Exception as e:
            logger.error("Wiretrace UI: could not read a previous session (%s)", type(e).__name__)
            return 500, {"error": "Could not read that session"}
        if generation != self.view_generation:
            return 409, {"error": "Another session was opened meanwhile"}
        self.viewed = opened
        self.hub.state_changed()
        return 200, {"viewing": opened.name, "cut_off": opened.cut_off, "requests": len(opened.flows)}

    # Replay. Invariant 8: only a flow held in memory for the live session.

    def replay(self, flow_id: str) -> tuple[int, dict]:
        if self.viewed is not None:
            return 409, {"error": "Replay is off while a previous session is open"}
        flow = self.hub.flows.get(flow_id)
        if flow is None:
            return 404, {"error": "Unknown request: it was never listed or has been dropped from memory."}
        if flow.websocket is not None:
            return 400, {"error": "WebSocket connections cannot be replayed"}
        if flow.live or flow.intercepted:
            return 409, {"error": "This request is still in progress"}
        if flow.request.raw_content is None:
            return 400, {"error": "The request body was not kept, so it cannot be replayed"}
        # replay.client changes the flow it gets (backup, no response): the original stays as it was.
        copy = flow.copy()
        copy.comment = f"replay: {flow.id}"
        copy.marked = ""
        copy.request.timestamp_start = copy.request.timestamp_end = time.time()
        try:
            ctx.master.commands.call("replay.client", [copy])
        except Exception as e:
            logger.error("Wiretrace UI: replay failed (%s)", type(e).__name__)
            return 500, {"error": "mitmproxy could not replay this request"}
        if copy.is_replay != "request":
            return 409, {"error": "mitmproxy did not accept this request for replay"}
        self.track(copy)
        return 200, {"id": copy.id}

    # Switching the preset (spec 013): one preset per session, so the launcher starts the next one.

    async def list_presets(self) -> list[dict]:
        target = str(self.meta().get("target") or "")
        presets_dir = self.presets_dir

        def entries() -> list[dict]:
            return [preset_entry(name, presets_dir, target) for name in list_presets(presets_dir)]

        return await asyncio.to_thread(entries)

    def current_target(self) -> str:
        return str(self.meta().get("target") or "")

    def switch_refusal(self) -> tuple[int, dict] | None:
        """The 409s of a switch that come before anything else: a previous session is open, or no session folder."""
        if self.viewed is not None:
            return 409, {"error": "Switching is off while a previous session is open"}
        if not ctx.options.qa_ui_session_dir:
            return 409, {"error": "No session folder: start Wiretrace with ./wiretrace start"}
        return None

    def switch_in_flight(self) -> bool:
        """The file's presence is the lock (invariant 5)."""
        return self.switching is not None or os.path.lexists(Path(ctx.options.qa_ui_session_dir) / session.SWITCH)

    async def switch_preset(self, name: str) -> tuple[int, dict]:
        """Invariants 2, 4 and 5: check the preset, then write `.switch.json`. A 202 means shut down now."""
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        try:
            await asyncio.to_thread(load_preset, name, self.presets_dir)
        except PresetError as e:
            return 400, {"error": str(e)}
        except OSError:
            return 400, {"error": "Could not read that preset file"}
        # Other requests ran while the preset was read.
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        if name == str(self.meta().get("preset") or ""):
            return 204, {}
        return self.start_switch(name, self.current_target())

    def start_switch(self, name: str, target: str, client: str | None = None,
                     proxy_port: int | None = None) -> tuple[int, dict]:
        """Write `.switch.json`; no await between the in-flight check and the write (spec 018, invariant 6)."""
        if self.switch_in_flight():
            return 409, {"error": ALREADY_SWITCHING}
        try:
            write_switch_file(Path(ctx.options.qa_ui_session_dir) / session.SWITCH, name, target, client, proxy_port)
        except OSError as e:
            logger.error("Wiretrace UI: could not write the switch request (%s)", type(e).__name__)
            return 500, {"error": "Could not switch: the session folder cannot be written"}
        self.switching = name
        self.release_all(abort=True)
        return 202, {"switching": name, "target": target}

    # Switching the device (spec 018): one device per session, the same preset and mode.

    def current_mode(self) -> str:
        mode = self.meta().get("mode")
        return mode if isinstance(mode, str) else ""

    async def current_preset(self) -> Preset | None:
        try:
            return await asyncio.to_thread(load_preset, str(self.meta().get("preset") or ""), self.presets_dir)
        except (PresetError, OSError):
            return None

    async def list_devices(self) -> list[dict]:
        preset, mode = await self.current_preset(), self.current_mode()
        collector_for, bin_dir = self.collector_for, self.bin_dir

        def entries() -> list[dict]:
            return [device_entry(target, preset, mode, collector_for, bin_dir) for target in TARGETS_SHOWN]

        # The adb lookup reads the disk.
        return await asyncio.to_thread(entries)

    async def switch_device(self, target: str) -> tuple[int, dict]:
        """Invariants 2, 3, 5 and 6: check the target and the preset in use, then write `.switch.json`."""
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        if target not in TARGETS:
            return 400, {"error": "Unknown device."}
        problem = target_problem(target, self.current_mode())
        if problem:
            return 400, {"error": problem}
        name = str(self.meta().get("preset") or "")
        try:
            await asyncio.to_thread(load_preset, name, self.presets_dir)
        except PresetError as e:
            return 400, {"error": str(e)}
        except OSError:
            return 400, {"error": "Could not read the preset file in use"}
        # Other requests ran while the preset was read.
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        if target == self.current_target():
            return 204, {}
        return self.start_switch(name, target)

    # Switching to a device the Wi-Fi proxy refused (spec 021): a new session pinned to its address.

    def proxyguard(self) -> Any:
        try:
            return ctx.master.addons.get("proxyguard")
        except Exception:
            return None

    @staticmethod
    def pin_option() -> bool:
        """proxy_guard adds the option, and only in a mode with the Wi-Fi proxy."""
        return "qa_proxy_pin" in ctx.options and bool(ctx.options.qa_proxy_pin)

    def waiting_list(self) -> list[dict]:
        """proxy_guard's refused addresses, the most recent first; empty without the guard."""
        waiting = getattr(self.proxyguard(), "waiting", None)
        if not callable(waiting):
            return []
        return [{"address": w.address, "first_at": w.first_at, "last_at": w.last_at, "count": w.count}
                for w in waiting()]

    def client_refusal(self, target: object, client: object) -> tuple[int, dict] | None:
        """Invariant 2, in its order. Nothing here awaits, so a write right after acts on what was checked."""
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        if self.switch_in_flight():
            return 409, {"error": ALREADY_SWITCHING}
        if not self.pin_option() or self.current_mode() == "wireguard":
            return 409, {"error": NO_CLIENT_SWITCH}
        if target in ("ios-sim", "android-emu"):
            return 400, {"error": CONNECTS_FROM_MAC}
        if target not in CLIENT_TARGETS:
            return 400, {"error": "Unknown device."}
        address = pinnable_client(client) if isinstance(client, str) else None
        if address is None:
            return 400, {"error": NOT_AN_ADDRESS}
        if address not in {entry["address"] for entry in self.waiting_list()}:
            return 409, {"error": NOT_WAITING}
        return None

    # More devices on one port (spec 022, slice A): allowed and removed in this session, no new one.

    def proxy_clients(self, mode: str) -> list[dict]:
        """The sidebar's devices: accepted ones in order with pinning, the `--client` ones that connected
        without. Empty in mode wireguard and while a previous session is shown."""
        guard = self.proxyguard()
        if self.viewed is not None or mode == "wireguard" or "qa_proxy_pin" not in ctx.options or guard is None:
            return []
        if self.pin_option():
            return self.client_stats.payload(guard.accepted())
        return self.client_stats.payload([a for a in self.client_stats.addresses() if guard.listed(a)])

    def device_refusal(self, action: str, client: str) -> tuple[int, dict] | None:
        """Invariant 3, in its order. Nothing here awaits, so the guard acts on what was checked."""
        if self.viewed is not None:
            return 409, {"error": DEVICES_OFF_WHILE_VIEWING}
        folder = ctx.options.qa_ui_session_dir
        if self.switching is not None or (folder and os.path.lexists(Path(folder) / session.SWITCH)):
            return 409, {"error": ALREADY_SWITCHING}
        guard = self.proxyguard()
        if not self.pin_option() or self.current_mode() == "wireguard" or guard is None:
            return 409, {"error": NO_CLIENT_SWITCH}
        try:
            ipaddress.ip_address(guardlib.normalize(client))
        except ValueError:
            return 400, {"error": NOT_AN_ADDRESS}
        address = guardlib.pinnable(client)
        if address is None:
            return 400, {"error": guardlib.NOT_PINNABLE}
        accepted = guard.accepted()
        if action == "allow":
            if address not in {entry["address"] for entry in self.waiting_list()}:
                return 409, {"error": NOT_WAITING}
            if len(accepted) >= guardlib.MAX_ACCEPTED:
                return 409, {"error": guardlib.AT_MOST}
        elif address not in accepted:
            return 409, {"error": guardlib.NOT_ACCEPTED}
        return None

    def change_device(self, action: str, client: str) -> tuple[int, dict]:
        refusal = self.device_refusal(action, client)
        if refusal:
            return refusal
        guard = self.proxyguard()
        change = guard.allow if action == "allow" else guard.remove
        reason = change(guardlib.pinnable(client))
        if reason:
            return 409, {"error": reason}
        self.hub.state_changed()
        self.hub.flush(self.state)
        return 200, {"accepted": guard.accepted()}

    # Changing the Wi-Fi proxy port (spec 022, slice B): a new session on the new port.

    @staticmethod
    def current_proxy_port() -> int:
        port = ctx.options.listen_port if "listen_port" in ctx.options else None
        return port if isinstance(port, int) and not isinstance(port, bool) and port else doctorlib.PROXY_PORT

    def port_state_refusal(self) -> tuple[int, dict] | None:
        """The 409s that come before the port is looked at."""
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        if self.switch_in_flight():
            return 409, {"error": ALREADY_SWITCHING}
        if self.current_mode() == "wireguard":
            return 409, {"error": NO_PROXY_PORT}
        return None

    def port_value_refusal(self, port: object) -> tuple[int, dict] | None:
        problem = doctorlib.port_problem(port, ctx.options.qa_ui_port)
        if problem:
            return 400, {"error": problem}
        if port == self.current_proxy_port():
            return 400, {"error": SAME_PORT}
        return None

    async def port_check(self, raw: str) -> tuple[int, dict]:
        """Whether the dialog's port could be the next one: its value, then a bind test."""
        port = parse_port(raw)
        refusal = self.port_value_refusal(port)
        if refusal:
            return refusal
        return 200, {"port": port, "free": await asyncio.to_thread(port_free, port)}

    async def change_port(self, port: object) -> tuple[int, dict]:
        """Check, read the preset and test the port, check again, then write `.switch.json` with the port."""
        refusal = self.port_state_refusal() or self.port_value_refusal(port)
        if refusal:
            return refusal
        name = str(self.meta().get("preset") or "")
        try:
            await asyncio.to_thread(load_preset, name, self.presets_dir)
        except PresetError as e:
            return 400, {"error": str(e)}
        except OSError:
            return 400, {"error": "Could not read the preset file in use"}
        free = await asyncio.to_thread(port_free, port)
        # Other requests ran while the preset was read and the port tested.
        refusal = self.port_state_refusal() or self.port_value_refusal(port)
        if refusal:
            return refusal
        if not free:
            return 409, {"error": PORT_IN_USE}
        return self.start_switch(name, self.current_target(), proxy_port=port)

    # Decrypting a passed-through host in the running session (spec 022, slice C).

    @staticmethod
    def live_api_hosts() -> list[str]:
        return list(ctx.options.qa_api_hosts) if "qa_api_hosts" in ctx.options else []

    def decrypt_state_refusal(self) -> tuple[int, dict] | None:
        if self.viewed is not None:
            return 409, {"error": "Decrypting is off while a previous session is open"}
        refusal = self.switch_refusal()
        if refusal:
            return refusal
        if self.switch_in_flight():
            return 409, {"error": ALREADY_SWITCHING}
        if self.in_use(presetfile.TEMPLATE):
            return 409, {"error": "example is a template and cannot be saved: use New preset"}
        return None

    def decrypt_refusal(self, host: str) -> tuple[int, dict] | None:
        """In this order: the session's state, the host, then the API hosts in effect. Nothing awaits."""
        refusal = self.decrypt_state_refusal()
        if refusal:
            return refusal
        if presetfile.host_problem(host):
            return 400, {"error": "Not a valid host name."}
        offered = {choice for seen in self.tunnels.hosts() for choice in presetfile.decrypt_choices(seen)}
        if host not in offered:
            return 400, {"error": NOT_OFFERED}
        live = self.live_api_hosts()
        if presetfile.covers(live, host):
            return 409, {"error": f"{host} is already decrypted in this session."}
        if len(live) >= presetfile.MAX_ENTRIES:
            return 409, {"error": f"The preset already has {presetfile.MAX_ENTRIES} API hosts."}
        return None

    async def decrypt_host(self, raw: str) -> tuple[int, dict]:
        """Append the host to the preset in use, then give mitmproxy the lists built from the file
        (invariants 3 and 4): never a host removed, never another preset."""
        host = raw.strip().lower().rstrip(".")
        refusal = self.decrypt_refusal(host)
        if refusal:
            return refusal
        name = str(self.meta().get("preset") or "")

        def append(live: list[str]) -> tuple[int, dict]:
            path = self.presets_dir / f"{name}.yaml"
            if not presetfile.is_listed(self.presets_dir, name):
                return 409, {"error": FILE_CHANGED}
            current = presetfile.read_preset_file(path)
            # Another edit since this session loaded the file would go live with this one.
            if current.error or current.fields["api_hosts"] != live:
                return 409, {"error": FILE_CHANGED}
            text = self.checked_text(path, {**current.fields, "api_hosts": [*live, host]}, current.data)
            if presetfile.file_revision(path.read_bytes()) != current.revision:
                return 409, {"error": FILE_CHANGED}
            presetfile.replace_file(path, text)
            return 200, {}

        async with self.preset_lock:
            # Other requests ran while this one waited for the lock.
            refusal = self.decrypt_refusal(host)
            if refusal:
                return refusal
            live = self.live_api_hosts()
            status, payload = await self.write_preset(lambda: append(live))
            if status != 200:
                return status, payload
            try:
                preset = await asyncio.to_thread(load_preset, name, self.presets_dir)
                ctx.options.update(allow_hosts=allow_hosts_args(preset), qa_api_hosts=list(preset.api_hosts))
            except Exception as e:
                logger.error("Wiretrace UI: could not apply the new API host (%s)", type(e).__name__)
                return 200, {"host": host, "applied": False, "message": f"Saved. Restart the session to decrypt {host}."}
            self.hub.state_changed()
            return 200, {"host": host, "applied": True}

    async def switch_client(self, target: object, client: object) -> tuple[int, dict]:
        """Check, read the preset in use, check again, then write `.switch.json` with the client."""
        refusal = self.client_refusal(target, client)
        if refusal:
            return refusal
        name = str(self.meta().get("preset") or "")
        try:
            await asyncio.to_thread(load_preset, name, self.presets_dir)
        except PresetError as e:
            return 400, {"error": str(e)}
        except OSError:
            return 400, {"error": "Could not read the preset file in use"}
        # Other requests ran while the preset was read.
        refusal = self.client_refusal(target, client)
        if refusal:
            return refusal
        return self.start_switch(name, str(target), pinnable_client(str(client)))

    # Editing and creating presets (spec 013, extension A).

    def in_use(self, name: str) -> bool:
        return name == str(self.meta().get("preset") or "")

    async def preset_detail(self, name: str) -> tuple[int, dict]:
        path = self.presets_dir / f"{name}.yaml"

        def read() -> presetfile.PresetFile | None:
            return presetfile.read_preset_file(path) if presetfile.is_listed(self.presets_dir, name) else None

        try:
            found = await asyncio.to_thread(read)
        except OSError as e:
            logger.error("Wiretrace UI: could not read a preset (%s)", type(e).__name__)
            return 500, {"error": "Could not read that preset file"}
        if found is None:
            return 404, {"error": f"Unknown preset {name!r}"}
        return 200, {"name": name, "revision": found.revision, "fields": found.fields, "in_use": self.in_use(name),
                     "read_only": name == presetfile.TEMPLATE, "error": found.error}

    def checked_text(self, path: Path, fields: dict, old: object) -> str:
        """The text to write. A FieldError for any value that a check refuses (A1)."""
        presetfile.check_fields(path, fields)
        expr = fields["default_filter"]
        if expr:
            try:
                valid = bool(flowfilter.parse(expr))
                reason = "is not a valid filter"
            except ValueError as e:
                valid, reason = False, f"is not a valid filter: {e}"
            if not valid:
                raise presetfile.FieldError(f"{path.parent.name}/{path.name}: 'default_filter' {reason}",
                                            "default_filter")
        return presetfile.render_file(path, fields, old)

    async def create_preset(self, name: str, fields: dict) -> tuple[int, dict]:
        if self.viewed is not None:
            return 409, {"error": "Editing presets is off while a previous session is open"}

        def create() -> tuple[int, dict]:
            path = presetfile.preset_path(self.presets_dir, name)
            text = self.checked_text(path, fields, None)
            try:
                presetfile.create_file(path, text)
            except FileExistsError:
                return 409, {"error": f"A preset named {name!r} already exists"}
            return 201, {"name": name, "revision": presetfile.file_revision(text.encode("utf-8"))}

        async with self.preset_lock:
            return await self.write_preset(create)

    async def save_preset(self, name: str, revision: str, fields: dict, restart: bool) -> tuple[int, dict]:
        """Steps 1 to 7 of the save. Only the preset in use may restart the session, and only with `restart`."""
        if self.viewed is not None:
            return 409, {"error": "Editing presets is off while a previous session is open"}
        if name == presetfile.TEMPLATE:
            return 409, {"error": "example is a template and cannot be saved: use New preset"}
        in_use = self.in_use(name)

        def replace() -> tuple[int, dict]:
            path = self.presets_dir / f"{name}.yaml"
            if not presetfile.is_listed(self.presets_dir, name):
                return 409, {"error": "The file changed"}
            current = presetfile.read_preset_file(path)
            if current.revision != revision:
                return 409, {"error": "The file changed"}
            text = self.checked_text(path, fields, current.data)
            presetfile.replace_file(path, text)
            return 200, {"revision": presetfile.file_revision(text.encode("utf-8"))}

        async with self.preset_lock:
            if in_use:
                refusal = self.switch_refusal()
                if refusal is None and self.switch_in_flight():
                    refusal = 409, {"error": ALREADY_SWITCHING}
                if refusal:
                    return refusal
                if not restart:
                    return 409, {"error": "This preset is in use: saving it restarts the session"}
            status, payload = await self.write_preset(replace)
            if status != 200 or not in_use:
                return status, payload
            # Other requests ran while the file was written; the preset is saved either way.
            refusal = self.switch_refusal()
            if refusal is None:
                status, payload = self.start_switch(name, self.current_target())
                if status == 202:
                    return status, payload
            return 500, {"error": "Saved, but the session could not restart: stop and start again"}

    async def write_preset(self, work: Any) -> tuple[int, dict]:
        """Run a file step off the event loop; a refused value is a 400, a failed write a 500 (type only logged)."""
        try:
            return await asyncio.to_thread(work)
        except presetfile.FieldError as e:
            return 400, {"error": str(e), "field": e.field}
        except OSError as e:
            logger.error("Wiretrace UI: could not write a preset (%s)", type(e).__name__)
            return 500, {"error": "Could not save the preset: the file on disk is unchanged"}

    # Rules: the live QA addon validates and applies them; the window writes the file.

    def qatools(self) -> Any:
        try:
            return ctx.master.addons.get("qatools")
        except Exception:
            return None

    @staticmethod
    def faults_on(faults: dict) -> bool:
        return bool(faults["filter"].strip()) and bool(faults["status"] or faults["delay_ms"] or faults["drop"])

    def rules_payload(self) -> dict:
        live = self.qatools()
        legacy = self.faults_on(self.faults())
        if live is None:
            return {"revision": "", "rules": [], "stats": {}, "legacy_faults_on": legacy, "file": "",
                    "error": NO_QA, "api_hosts": []}
        return {"revision": live.rules.revision, "rules": [r.data for r in live.rules.rules],
                "stats": live.rule_stats(), "legacy_faults_on": legacy, "file": display_dir(live.rules_file),
                "error": live.rules_error or None, "api_hosts": list(live.api_hosts)}

    def save_rules(self, revision: str, rules: list) -> tuple[int, dict]:
        """Invariants 2 and 3: validate first, then replace the file whole, then reload. Return status and body."""
        live = self.qatools()
        if live is None:
            return 503, {"error": NO_QA}
        if not live.rules_file:
            return 409, {"error": "No rules file: start Wiretrace with ./wiretrace start"}
        if revision != live.rules.revision:
            return 409, {"error": "The rules changed since they were loaded. They have been reloaded; save again."}
        checked = live.validate_rules(qa_rules_document(rules))
        if "error" in checked:
            return 400, checked
        path = Path(live.rules_file)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(qa_rules_document(checked["rules"]), indent=2, ensure_ascii=True) + "\n"
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            return 500, {"error": "Could not write the rules file"}
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        error = live.reload_rules()
        if error:
            return 500, {"error": error}
        self.hub.state_changed()
        return 200, self.rules_payload()

    def map_local(self, flow_id: str, body: object) -> tuple[int, dict]:
        """Save a response as a mock file, then optionally add a Mock rule for it at the top (spec 022, slice F).

        One synchronous step, so neither the rules nor the file can change between the checks and the writes.
        """
        if not isinstance(body, dict) or set(body) != MAP_LOCAL_KEYS or not isinstance(body["file"], str) \
                or not isinstance(body["body"], str) or not isinstance(body["rule"], bool) \
                or not isinstance(body["replace"], bool) or not isinstance(body["revision"], str):
            return 400, {"error": "Send file, status, body, rule, replace and revision."}
        flow = self.hub.flows.get(flow_id)
        if not isinstance(flow, http.HTTPFlow):
            return 404, {"error": "Unknown request: it was never listed or has been dropped from memory."}
        if flow.response is None:
            return 409, {"error": "This request has no response yet."}
        live = self.qatools()
        if live is None:
            return 503, {"error": NO_QA}
        status = body["status"]
        if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
            return 400, {"error": "The status must be a number from 100 to 599.", "field": "status"}
        try:
            content = body["body"].encode("utf-8")
        except UnicodeEncodeError:
            return 400, {"error": "The body must be text.", "field": "body"}
        if len(content) > MAX_MOCK_BODY:
            return 400, {"error": "The body must be at most 1 MiB.", "field": "body"}
        rule = None
        if body["rule"]:
            if not live.rules_file:
                return 409, {"error": "No rules file: start Wiretrace with ./wiretrace start"}
            if body["revision"] != live.rules.revision:
                return 409, {"error": "The rules changed since this dialog opened. Close it and try again.",
                             "stale": True}
            rule = map_local_rule(flow, body["file"], status, live.api_hosts,
                                  {r.id for r in live.rules.rules})
            if rule is None:
                return 400, {"error": "Rules apply only to the preset's API hosts: turn off Answer with it now "
                                      "to save the file only.", "field": "rule"}
        problem = live.mock_name_problem(body["file"])
        if problem:
            return 400, {"error": problem, "field": "file"}
        folder = live.mock_dir_for_write(body["file"])
        if folder is None:
            return 400, {"error": "The file would leave the preset's mocks folder.", "field": "file"}
        path = folder / body["file"].rsplit("/", 1)[-1]
        if os.path.lexists(path) and not body["replace"]:
            return 409, {"error": "A file with this name exists.", "exists": True}
        if path.is_symlink() or (path.exists() and not path.is_file()):
            return 400, {"error": "The file would leave the preset's mocks folder.", "field": "file"}
        tmp = folder / f".{path.name}.{secrets.token_hex(4)}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            os.replace(tmp, path)
        except OSError:
            return 500, {"error": "Could not write the mock file."}
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        if rule is None:
            return 200, {"file": body["file"], "rule_id": None}
        code, saved = self.save_rules(body["revision"], [rule, *(r.data for r in live.rules.rules)])
        if code != 200:
            return code, {"error": f"File saved; the rule was not added: {saved.get('error', 'unknown error')}",
                          "file": body["file"], "saved": True}
        return 200, {"file": body["file"], "rule_id": rule["id"]}

    def flush_rules(self) -> None:
        """Tell the pages when counters, the rules or the file error changed; also picks up hand edits."""
        live = self.qatools()
        if live is None:
            return
        live.maybe_reload_rules()
        marker = (live.stats_version, live.rules.revision, live.rules_error)
        if marker == self._rules_sent:
            return
        if self._rules_sent and self._rules_sent[1] != marker[1]:
            self.hub.state_changed()
        self._rules_sent = marker
        if self.hub.clients:
            self.hub.broadcast([{"type": "rules", "revision": live.rules.revision, "stats": live.rule_stats(),
                                 "error": live.rules_error or None}])

    async def make_report(self, viewed: Path | None = None) -> dict:
        """The report of the live session, or of a previous one found in the listing."""
        self.report_running = True
        try:
            folder = (viewed or Path(ctx.options.qa_ui_session_dir)).resolve()
            created = await asyncio.to_thread(report.create, folder, PRESETS_DIR)
        except report.Failure as e:
            return {"ok": False, "zip": None, "requests": 0, "failed": 0, "device_lines": 0,
                    "app_lines": 0, "message": str(e)}
        except Exception as e:
            return {"ok": False, "zip": None, "requests": 0, "failed": 0, "device_lines": 0,
                    "app_lines": 0, "message": f"Could not build the report: {type(e).__name__}"}
        finally:
            self.report_running = False
        self.last_report = created.zip
        self.hub.state_changed()
        message = "Report written."
        if created.cut_off:
            message += " flows.mitm ends early; the report uses the requests that could be read."
        return {"ok": True, "zip": created.zip.name, "requests": created.requests, "failed": created.failed,
                "device_lines": created.device_lines, "app_lines": created.app_lines, "message": message}

    # The bug report form (spec 012). Reads only, except screenshots in the live session's screenshots/.

    async def report_folder(self, name: object) -> tuple[int, str, Path | None, bool]:
        """(status, error, folder, previous): the live session, or a previous one found in the listing."""
        live = ctx.options.qa_ui_session_dir
        if not live:
            return 409, "No session folder: start Wiretrace with ./wiretrace start", None, False
        if not name or name == self.live_name():
            return 200, "", Path(live).resolve(), False
        if not isinstance(name, str) or not session.NAME.fullmatch(name):
            return 400, "Not a session name", None, False
        folder = await self.find_session(name)
        if folder is None:
            return 404, "Unknown session", None, False
        return 200, "", folder.resolve(), True

    async def report_draft(self, folder: Path, previous: bool, include: report.Include, fmt: str) -> tuple[int, dict]:
        target = "" if previous else str(self.meta().get("target") or "")

        def job() -> dict:
            data = report.draft(folder, PRESETS_DIR, include, fmt)
            state, reason = screenshot.availability(target, previous)
            data["screenshots"] = {"state": state, "reason": reason, "items": screenshot.listing(folder)}
            return data

        try:
            return 200, await asyncio.to_thread(job)
        except report.UnknownRequest as e:
            return 404, {"error": str(e)}
        except report.Failure as e:
            return 500, {"error": str(e)}
        except Exception as e:
            logger.error("Wiretrace UI: could not build the report draft (%s)", type(e).__name__)
            return 500, {"error": f"Could not build the draft ({type(e).__name__})"}

    async def report_file(self, folder: Path, kind: str, include: report.Include) -> tuple[int, tuple[str, bytes] | str]:
        try:
            found = await asyncio.to_thread(report.export, folder, PRESETS_DIR, kind, include)
        except report.UnknownRequest as e:
            return 404, str(e)
        except report.Failure as e:
            return 500, str(e)
        except Exception as e:
            logger.error("Wiretrace UI: could not build a report file (%s)", type(e).__name__)
            return 500, f"Could not build the file ({type(e).__name__})"
        if found is None:
            return 404, "Nothing to download: that file has no content"
        return 200, found

    async def take_screenshot(self, folder: Path) -> tuple[int, dict]:
        """Invariant 4: one capture at a time, live session only, with the target the session runs."""
        self.screenshot_running = True
        try:
            target = str(self.meta().get("target") or "")
            name = await asyncio.to_thread(screenshot.capture, target, folder)
            items = await asyncio.to_thread(screenshot.listing, folder)
        except screenshot.Unavailable as e:
            return 422, {"error": str(e)}
        except Exception as e:
            logger.error("Wiretrace UI: screenshot failed (%s)", type(e).__name__)
            return 500, {"error": f"The screenshot failed ({type(e).__name__})"}
        finally:
            self.screenshot_running = False
        return 200, {"name": name, "screenshots": items}

    async def remove_screenshot(self, folder: Path, name: str) -> tuple[int, dict]:
        def job() -> list[dict] | None:
            path = screenshot.find(folder, name)
            if path is None:
                return None
            path.unlink()
            return screenshot.listing(folder)

        try:
            items = await asyncio.to_thread(job)
        except OSError as e:
            logger.error("Wiretrace UI: could not remove a screenshot (%s)", type(e).__name__)
            return 500, {"error": "Could not remove the screenshot"}
        if items is None:
            return 404, {"error": "Unknown screenshot"}
        return 200, {"screenshots": items}

    async def reveal_report(self) -> str | None:
        """Open Finder on the zip the last report wrote, never on a path from the page. Return an error text."""
        path = self.last_report
        if path is None or not path.is_file():
            return NO_REPORT
        try:
            result = await asyncio.to_thread(
                subprocess.run, ["open", "-R", str(path)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return "Could not open Finder."
        return None if result.returncode == 0 else "Could not open Finder."


addons = [WiretraceUI()]
