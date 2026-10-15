"""Wiretrace window: a local web page with the traffic, the app's logs, setup, rules and the report.

A Tornado application on mitmproxy's own asyncio loop, so every hook and every request runs
on one thread and flows are read without locks. Listens on 127.0.0.1 only; every page, API
call and WebSocket needs the token that is printed once as a link in the Terminal.
Specs: docs/specs/006-wiretrace-ui-first-slice.md, 008-window-like-the-mockups.md.

Configured through mitmproxy options (`qa_ui_*`); the token is never an option. The addon
prints the link and errors only: no flow content, header or log line goes to the Terminal.
"""

from __future__ import annotations

import asyncio
import codecs
import hmac
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
from typing import Any

import tornado.web
import tornado.websocket
from mitmproxy import ctx, exceptions, flowfilter, http
from tornado import httpserver, netutil
from tornado.escape import json_encode

# mitmdump does not have the wiretrace folder on sys.path.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import __version__, report, session  # noqa: E402
from cli import bodies  # noqa: E402
from cli.preset import PRESETS_DIR  # noqa: E402

logger = logging.getLogger(__name__)

COOKIE = "wiretrace_ui"
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


def mime_of(message: http.Message) -> str | None:
    value = message.headers.get("content-type")
    return clean(value.split(";", 1)[0].strip().lower()) if value else None


def summary(flow: http.HTTPFlow) -> dict:
    request, response = flow.request, flow.response
    parts = comment_parts(flow.comment)
    request_ids = part_value(parts, "request-id:")
    faults = part_value(parts, "fault:")
    replays = part_value(parts, "replay:")
    start = request.timestamp_start
    end = response.timestamp_end if response else (flow.error.timestamp if flow.error else None)
    size = len(response.raw_content) if response is not None and response.raw_content is not None else None
    return {
        "id": flow.id,
        "ts": start,
        "method": clean(request.method),
        "scheme": request.scheme,
        "host": clean(request.pretty_host),
        "port": request.port,
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
    }


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


def detail(flow: http.HTTPFlow, mocks_dir: str) -> dict:
    request, response = flow.request, flow.response
    return {
        "summary": summary(flow),
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
    }


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

    def flush(self, state: Any) -> None:
        """Send the batch to every connected page. `state` builds the state message when it changed."""
        dirty, self._dirty = list(self._dirty), {}
        lines, self._lines = self._lines, []
        device, self._device = self._device, None
        changed, self._state_changed = self._state_changed, False
        if not self.clients:
            return
        messages = []
        flows = [summary(self.flows[i]) for i in dirty if i in self.flows]
        for i in range(0, len(flows), CHUNK):
            messages.append({"type": "flows", "flows": flows[i:i + CHUNK]})
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
            self.write({"flows": [summary(f) for f in store.flows.values()]})


class FlowDetail(Guarded):
    def get(self, flow_id: str) -> None:
        store = self.store()
        if store is None:
            return
        flow = store.flows.get(flow_id)
        if flow is None:
            return self.fail(404, "Unknown request: it was never listed or has been dropped from memory.")
        self.write(detail(flow, display_dir(self.addon.mocks_dir())))


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
        self.last_report: Path | None = None
        self.started_at = time.time()
        # Setup: when a device last connected, and failed TLS handshakes with API hosts. Nothing about the peer.
        self.device_seen_at: float | None = None
        self.tls_failures = 0
        # One previous session opened read-only; the live capture goes on meanwhile.
        self.viewed: Store | None = None
        self.view_generation = 0
        self._rules_sent: tuple = ()
        self._server: httpserver.HTTPServer | None = None
        self._tasks: list[asyncio.Task] = []

    # Options

    def load(self, loader) -> None:
        loader.add_option("qa_ui_port", int, 8081, "Port of the Wiretrace window on 127.0.0.1.")
        loader.add_option("qa_ui_session_dir", str, "",
                          "Session folder: meta.json, the log files and the report.")
        loader.add_option("qa_ui_default_filter", str, "", "Initial search of the Wiretrace window.")
        loader.add_option("qa_ui_open_browser", bool, True, "Open the Wiretrace window link at start.")

    def configure(self, updated) -> None:
        if not 0 <= ctx.options.qa_ui_port <= 65535:
            raise exceptions.OptionsError("qa_ui_port must be 0 to 65535")

    # Lifecycle

    async def running(self) -> None:
        if self._server is not None:
            return
        self.token = secrets.token_urlsafe(32)
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
        try:
            print(f"Wiretrace UI: {link}", flush=True)
        except OSError:
            pass
        if ctx.options.qa_ui_open_browser:
            try:
                await asyncio.to_thread(webbrowser.open, link)
            except Exception:
                logger.error("Wiretrace UI: could not open the browser; open the link above")

    async def done(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
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
                (r"/api/flows/([^/]+)/replay", Replay, handler_args),
                (r"/api/flows/([^/]+)", FlowDetail, handler_args),
                (r"/api/filter", Filter, handler_args),
                (r"/api/search", Search, handler_args),
                (r"/api/logs", Logs, handler_args),
                (r"/api/sessions", Sessions, handler_args),
                (r"/api/view", View, handler_args),
                (r"/api/mocks", Mocks, handler_args),
                (r"/api/rules", RulesApi, handler_args),
                (r"/api/rules/test", RuleTest, handler_args),
                (r"/api/rules/([a-z0-9]{6,32})/rearm", RuleRearm, handler_args),
                (r"/api/report", Report, handler_args),
                (r"/api/report/reveal", Reveal, handler_args),
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

    request = response = error = websocket_start = websocket_end = track

    # Hooks: connections, for Setup

    def client_connected(self, client) -> None:
        # proxy_guard runs first and sets `error` on a client it refuses: that is not the device.
        if getattr(client, "error", None):
            return
        first = self.device_seen_at is None
        self.device_seen_at = time.time()
        if first:
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
            self.hub.state_changed()

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
        return {
            "version": __version__,
            "preset": str(meta.get("preset") or ""),
            "target": str(meta.get("target") or ""),
            "mode": mode,
            "started_at": started if started is not None else self.started_at,
            "session": Path(ctx.options.qa_ui_session_dir).name,
            "device_logs": device_logs if isinstance(device_logs, str) and device_logs else None,
            "device_logs_off": device_logs_off if isinstance(device_logs_off, str) and device_logs_off else None,
            "default_filter": ctx.options.qa_ui_default_filter,
            "proxy_port": ctx.options.listen_port if "listen_port" in ctx.options else 8080,
            "wireguard_conf": self.wireguard_conf() if mode != "proxy" else None,
            "mac_ip": local_ip.get_local_ip() if mode == "proxy" else None,
            "faults": faults,
            "faults_on": self.faults_on(faults),
            "mocks_dir": display_dir(self.mocks_dir()),
            "flow_count": len(self.hub.flows),
            "rules_on": sum(1 for r in live.rules.rules if r.enabled) if live is not None else 0,
            "device_seen_at": self.device_seen_at,
            "tls_failures": self.tls_failures,
            "device_status": self.device_file.status,
            "viewing": self.viewed.name if self.viewed else None,
            "viewing_cut_off": bool(self.viewed and self.viewed.cut_off),
        }

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
