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
import io
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
import webbrowser
import zlib
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import brotli
import tornado.web
import zstandard
import tornado.websocket
from mitmproxy import ctx, exceptions, flowfilter, http
from tornado import httpserver, netutil
from tornado.escape import json_encode

# mitmdump does not have the wiretrace folder on sys.path.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli import __version__, report, session  # noqa: E402
from cli.preset import PRESETS_DIR  # noqa: E402

logger = logging.getLogger(__name__)

COOKIE = "wiretrace_ui"
RECEIVER_HOST = "qa-logs.internal"
MAX_FLOWS = 10_000
MAX_LOG_LINES = 50_000
MAX_BODY_BYTES = 2 << 20
MAX_COUNT_BYTES = 64 << 20
CHUNK_BYTES = 1 << 20
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


def mime_of(message: http.Message) -> str | None:
    value = message.headers.get("content-type")
    return clean(value.split(";", 1)[0].strip().lower()) if value else None


def summary(flow: http.HTTPFlow) -> dict:
    request, response = flow.request, flow.response
    parts = comment_parts(flow.comment)
    request_ids = part_value(parts, "request-id:")
    faults = part_value(parts, "fault:")
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


def _decompressor(encoding: str):
    """A function `(raw, limit) -> output` that stops once `limit` bytes are out; None if not supported."""
    if encoding == "gzip":
        return lambda raw, limit: zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, limit)
    if encoding == "deflate":
        def deflate(raw: bytes, limit: int) -> bytes:
            try:
                return zlib.decompressobj().decompress(raw, limit)
            except zlib.error:
                return zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw, limit)
        return deflate
    if encoding == "br":
        return lambda raw, limit: brotli.Decompressor().process(raw, output_buffer_limit=limit)
    if encoding == "zstd":
        return lambda raw, limit: zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read(limit)
    return None


def _zlib_size(raw: bytes, wbits: int) -> int:
    d = zlib.decompressobj(wbits)
    total = len(d.decompress(raw, CHUNK_BYTES))
    while d.unconsumed_tail and total < MAX_COUNT_BYTES:
        total += len(d.decompress(d.unconsumed_tail, CHUNK_BYTES))
    return total


def decoded_size(encoding: str, raw: bytes, known: int) -> int:
    """The decoded size, counted in chunks up to MAX_COUNT_BYTES, so a compression bomb is never held in memory."""
    if encoding in ("gzip", "deflate"):
        attempts = [16 + zlib.MAX_WBITS] if encoding == "gzip" else [zlib.MAX_WBITS, -zlib.MAX_WBITS]
        for wbits in attempts:
            try:
                return _zlib_size(raw, wbits)
            except zlib.error:
                continue
        return known
    if encoding == "zstd":
        reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
        total = 0
        while total < MAX_COUNT_BYTES and (chunk := reader.read(CHUNK_BYTES)):
            total += len(chunk)
        return total
    if encoding == "br":
        d = brotli.Decompressor()
        total = len(d.process(raw, output_buffer_limit=CHUNK_BYTES))
        while not d.is_finished() and total < MAX_COUNT_BYTES:
            chunk = d.process(b"", output_buffer_limit=CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
        return total
    return known


def bounded_content(message: http.Message) -> tuple[bytes, int, bool]:
    """Up to MAX_BODY_BYTES of the decoded body, its size, and whether it was cut."""
    raw = message.raw_content or b""
    encoding = message.headers.get("content-encoding", "").strip().lower()
    if encoding in ("", "identity", "none"):
        return raw[:MAX_BODY_BYTES], len(raw), len(raw) > MAX_BODY_BYTES
    decompress = _decompressor(encoding)
    if decompress is None:
        return raw[:MAX_BODY_BYTES], len(raw), len(raw) > MAX_BODY_BYTES
    try:
        data = decompress(raw, MAX_BODY_BYTES + 1)
    except Exception:
        # As mitmproxy's get_content(strict=False): an undecodable body is shown as it travelled.
        return raw[:MAX_BODY_BYTES], len(raw), len(raw) > MAX_BODY_BYTES
    if len(data) <= MAX_BODY_BYTES:
        return data, len(data), False
    # Past MAX_COUNT_BYTES the size is a lower bound.
    return data[:MAX_BODY_BYTES], decoded_size(encoding, raw, len(data)), True


def body_info(message: http.Message) -> dict:
    """The body as text up to 2 MiB, or only its size when it is binary. Never decodes more than 2 MiB."""
    data, size, truncated = bounded_content(message)
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


def list_mocks(root: str) -> list[str]:
    if not root:
        return []
    base = Path(root)
    try:
        found = (p.relative_to(base).as_posix() for p in base.rglob("*.json") if p.is_file())
        return sorted(found)[:MAX_MOCK_FILES]
    except OSError:
        return []


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


# Flows and live updates

class Hub:
    """The flows listed in the window, and what the connected pages have not been told yet."""

    def __init__(self, cap: int = MAX_FLOWS) -> None:
        self.cap = cap
        self.flows: dict[str, http.HTTPFlow] = {}
        self.clients: set[tornado.websocket.WebSocketHandler] = set()
        self._dirty: dict[str, None] = {}
        self._lines: list[dict] = []
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

    def flush(self, state: Any) -> None:
        """Send the batch to every connected page. `state` builds the state message when it changed."""
        dirty, self._dirty = list(self._dirty), {}
        lines, self._lines = self._lines, []
        changed, self._state_changed = self._state_changed, False
        if not self.clients:
            return
        messages = []
        flows = [summary(self.flows[i]) for i in dirty if i in self.flows]
        for i in range(0, len(flows), CHUNK):
            messages.append({"type": "flows", "flows": flows[i:i + CHUNK]})
        for i in range(0, len(lines), CHUNK):
            messages.append({"type": "logs", "lines": lines[i:i + CHUNK]})
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
        self.write({"flows": [summary(f) for f in self.addon.hub.flows.values()]})


class FlowDetail(Guarded):
    def get(self, flow_id: str) -> None:
        flow = self.addon.hub.flows.get(flow_id)
        if flow is None:
            return self.fail(404, "Unknown request: it was never listed or has been dropped from memory.")
        self.write(detail(flow, display_dir(self.addon.mocks_dir())))


class Filter(Guarded):
    def get(self) -> None:
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
        for flow in self.addon.hub.flows.values():
            try:
                if matcher(flow):
                    ids.append(flow.id)
            except Exception:
                continue
        self.write({"ids": ids})


class Logs(Guarded):
    def get(self) -> None:
        source = self.get_query_argument("source", "")
        if source not in SOURCES:
            return self.fail(400, "source must be device or app")
        self.write({"lines": list(self.addon.tails[source].lines)})


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
        if self.addon.report_running:
            return self.fail(409, "A report is already being written")
        self.write(await self.addon.make_report())


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
        self.token = ""
        self.port = 0
        self.hosts: set[str] = set()
        self.origins: set[str] = set()
        self.security_headers: dict[str, str] = {}
        self.report_running = False
        self.last_report: Path | None = None
        self.started_at = time.time()
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
                (r"/api/flows/([^/]+)", FlowDetail, handler_args),
                (r"/api/filter", Filter, handler_args),
                (r"/api/logs", Logs, handler_args),
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

    # Background loops

    def poll_logs(self) -> None:
        for tail in self.tails.values():
            self.hub.add_lines(tail.poll())

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
        return {
            "version": __version__,
            "preset": str(meta.get("preset") or ""),
            "target": str(meta.get("target") or ""),
            "mode": mode,
            "started_at": started if started is not None else self.started_at,
            "session": Path(ctx.options.qa_ui_session_dir).name,
            "device_logs": device_logs if isinstance(device_logs, str) and device_logs else None,
            "default_filter": ctx.options.qa_ui_default_filter,
            "proxy_port": ctx.options.listen_port if "listen_port" in ctx.options else 8080,
            "wireguard_conf": self.wireguard_conf() if mode != "proxy" else None,
            "mac_ip": local_ip.get_local_ip() if mode == "proxy" else None,
            "faults": faults,
            "faults_on": self.faults_on(faults),
            "mocks_dir": display_dir(self.mocks_dir()),
            "flow_count": len(self.hub.flows),
            "rules_on": sum(1 for r in live.rules.rules if r.enabled) if live is not None else 0,
        }

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

    async def make_report(self) -> dict:
        self.report_running = True
        try:
            folder = Path(ctx.options.qa_ui_session_dir).resolve()
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
