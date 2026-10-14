"""Wiretrace app log receiver: answers POST https://qa-logs.internal/log inside mitmproxy.

QA builds send their own log lines there (R6). Every request to that name is answered in
the `request` hook and never forwarded; the name is made reachable without contacting
anything. Configured only through mitmproxy options (`qa_app_log_file`). It imports
nothing from cli/. Spec: docs/specs/004-log-collectors-and-app-log-receiver.md.

Addon log lines carry counts and states only: no log text, request IDs or paths.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from mitmproxy import ctx, dns, http, tls
from mitmproxy.proxy import server_hooks

logger = logging.getLogger(__name__)

HOST = "qa-logs.internal"
# TEST-NET-1 (RFC 5737): never routed, so nothing outside can ever answer for it.
ADDRESS = "192.0.2.10"
PATH = "/log"
DNS_TTL = 60
MAX_BODY = 1 << 20
MAX_ITEMS = 1000
MAX_SHORT = 64
MAX_REQUEST_ID = 128
JSON_TYPE = {"Content-Type": "application/json"}
# Field -> longest allowed value; `message` has no limit besides the body size.
OPTIONAL = {"level": MAX_SHORT, "tag": MAX_SHORT, "ts": MAX_SHORT, "request_id": MAX_REQUEST_ID}


# NamedTuple, not dataclass: mitmproxy loads this file without registering it in
# sys.modules, which dataclasses cannot handle under `from __future__ import annotations`.
class Verdict(NamedTuple):
    """The answer to one request: status, an error text (400 only), and the records to store."""

    status: int
    error: str = ""
    records: tuple[dict, ...] = ()


def is_receiver_host(host: str) -> bool:
    return host.lower().rstrip(".") == HOST


def parse_batch(body: bytes) -> Verdict:
    """Validate a whole body: 204 with the records to store, or 400 with a fixed reason."""
    try:
        data = json.loads(body)
    except ValueError:
        return Verdict(400, "body is not JSON")
    items = data if isinstance(data, list) else [data]
    if len(items) > MAX_ITEMS:
        return Verdict(400, f"at most {MAX_ITEMS} objects per request")
    records = []
    for item in items:
        if not isinstance(item, dict):
            return Verdict(400, "expected an object or an array of objects")
        if not isinstance(item.get("message"), str):
            return Verdict(400, "message is required and must be a string")
        record = {"message": item["message"]}
        for field, limit in OPTIONAL.items():
            if field not in item:
                continue
            value = item[field]
            if not isinstance(value, str) or len(value) > limit:
                return Verdict(400, f"{field} must be a string of at most {limit} characters")
            record[field] = value
        records.append(record)
    return Verdict(204, records=tuple(records))


def judge(method: str, path: str, body: bytes) -> Verdict:
    if path.split("?", 1)[0] != PATH:
        return Verdict(404)
    if method != "POST":
        return Verdict(405)
    if len(body) > MAX_BODY:
        return Verdict(413)
    return parse_batch(body)


def stored_line(record: dict, received: str) -> str:
    line = {"ts": record.get("ts", received), "received": received, "source": "app"}
    for field in ("level", "tag", "message", "request_id"):
        if field in record:
            line[field] = record[field]
    return json.dumps(line, ensure_ascii=False) + "\n"


def response_for(verdict: Verdict) -> http.Response:
    if verdict.status == 204:
        response = http.Response.make(204)
        # A 204 has no body, and RFC 9110 forbids a Content-Length on it.
        response.headers.pop("Content-Length", None)
        return response
    headers = dict(JSON_TYPE)
    if verdict.status == 405:
        headers["Allow"] = "POST"
    reason = {400: verdict.error, 404: "not found", 405: "use POST /log", 413: "body over 1 MiB"}.get(
        verdict.status, "could not store the log lines")
    return http.Response.make(verdict.status, json.dumps({"error": reason}).encode(), headers)


class _Sink(asyncio.Protocol):
    """Accepts and reads nothing: any byte that arrives here means a request was forwarded."""

    def __init__(self, owner: AppLogs) -> None:
        self.owner = owner
        self.transport: asyncio.Transport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        self.owner.sink_bytes += len(data)
        if self.owner.sink_bytes == len(data):
            logger.warning("Wiretrace app logs: unexpected data reached the local sink")

    def eof_received(self) -> bool:
        return False

    def connection_lost(self, exc) -> None:
        self.transport = None


class _TlsLast:
    """Runs `tls_clienthello` after mitmproxy's own handler, which would set the flag again."""

    def __init__(self, owner: AppLogs) -> None:
        self.owner = owner

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        self.owner.tls_clienthello(data)


class AppLogs:
    def __init__(self) -> None:
        self._path = ""
        self._file = None
        self._sink: asyncio.base_events.Server | None = None
        self._summary = ""
        self.stored = 0
        self.rejected = 0
        self.sink_bytes = 0

    def load(self, loader) -> None:
        loader.add_option("qa_app_log_file", str, "",
                          "Absolute path of the app log file (JSON lines). Empty: requests to "
                          f"{HOST} are answered but not stored.")

    def configure(self, updated) -> None:
        self._path = ctx.options.qa_app_log_file
        summary = "Wiretrace app logs: " + ("on" if self._path else "off (qa_app_log_file empty)")
        if summary != self._summary:
            self._summary = summary
            logger.info(summary)

    async def running(self) -> None:
        if self._sink is None:
            self._sink = await asyncio.get_running_loop().create_server(
                lambda: _Sink(self), "127.0.0.1", 0)
            # mitmproxy's TlsConfig sets `establish_server_tls_first` for the same event
            # and runs after any `-s` script, so a copy at the end of the chain has the last word.
            ctx.master.addons.add(_TlsLast(self))

    def done(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        if self._sink is not None:
            self._sink.close()
            self._sink = None
        logger.info(f"Wiretrace app logs: {self.stored} lines stored, {self.rejected} requests rejected")

    @property
    def sink_port(self) -> int | None:
        if self._sink is None or not self._sink.sockets:
            return None
        return self._sink.sockets[0].getsockname()[1]

    # Reachability: the name does not exist, and mitmproxy connects to the server first.

    def dns_request(self, flow: dns.DNSFlow) -> None:
        question = flow.request.question
        if not (flow.request.query and question and is_receiver_host(question.name)):
            return
        answers = []
        if question.class_ == dns.classes.IN and question.type == dns.types.A:
            answers = [dns.ResourceRecord.A(question.name, ipaddress.IPv4Address(ADDRESS), ttl=DNS_TTL)]
        flow.response = flow.request.succeed(answers)

    def server_connect(self, data: server_hooks.ServerConnectionHookData) -> None:
        address = data.server.address
        port = self.sink_port
        if address and port and address[0].lower().rstrip(".") in (HOST, ADDRESS):
            data.server.address = ("127.0.0.1", port)

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        sni = data.client_hello.sni
        if sni and is_receiver_host(sni):
            data.establish_server_tls_first = False

    # The receiver

    def request(self, flow: http.HTTPFlow) -> None:
        if not is_receiver_host(flow.request.pretty_host):
            return
        request = flow.request
        verdict = judge(request.method, request.path, request.raw_content or b"")
        if verdict.status == 204 and not self._store(verdict.records):
            verdict = Verdict(500)
        if verdict.status >= 400:
            self.rejected += 1
        flow.response = response_for(verdict)

    def _store(self, records: tuple[dict, ...]) -> bool:
        if not self._path:
            return True
        received = datetime.now().astimezone().isoformat(timespec="milliseconds")
        text = "".join(stored_line(record, received) for record in records)
        if not text:
            return True
        try:
            if self._file is None:
                self._file = open(Path(self._path), "ab", buffering=0)
            # One write for the whole batch: stored completely or not at all.
            self._file.write(text.encode("utf-8"))
        except OSError:
            return False
        self.stored += len(records)
        return True


addons = [AppLogs()]
