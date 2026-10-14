"""Wiretrace QA addon: mock files, fault injection and request ID comments.

Configured only through mitmproxy options (`qa_*`), so it also works in a plain
mitmproxy command. It imports nothing from cli/ and never writes files.
Spec: docs/specs/003-qa-addon-mocks-faults-request-ids.md.

States of one API flow in `request`: TAGGED -> DELAYING -> FAULTING -> MOCKING -> DONE,
or DELAYING -> GONE when the client left or mitmproxy is stopping.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from mitmproxy import ctx, exceptions, flowfilter, http

logger = logging.getLogger(__name__)

MOCK_MARK = ":construction:"
FAULT_MARK = ":boom:"
FAULT_BODY = b'{"error": "injected by Wiretrace"}'
JSON = {"Content-Type": "application/json"}
MAX_ID_LENGTH = 128


# NamedTuple, not dataclass: mitmproxy loads this file without registering it in
# sys.modules, which dataclasses cannot handle under `from __future__ import annotations`.
class Faults(NamedTuple):
    matcher: flowfilter.TFilter | None
    status: int
    delay_ms: int
    drop: bool

    @property
    def on(self) -> bool:
        return self.matcher is not None and bool(self.status or self.delay_ms or self.drop)


class Snapshot(NamedTuple):
    """Everything one request needs, validated; replaced as a whole, never edited."""

    api_hosts: tuple[str, ...] = ()
    mocks_dir: str = ""
    request_id_header: str = "X-Request-ID"
    faults: Faults = Faults(None, 0, 0, False)


def build_snapshot(hosts: Sequence[str], mocks_dir: str, header: str, fault_filter: str,
                   status: int, delay_ms: int, drop: bool) -> Snapshot:
    """Raise OptionsError if a value is invalid."""
    matcher = None
    if fault_filter.strip():
        try:
            matcher = flowfilter.parse(fault_filter.strip())
        except Exception as e:
            raise exceptions.OptionsError(f"qa_fault_filter: {e}") from None
        if not matcher:
            raise exceptions.OptionsError("qa_fault_filter: not a valid filter expression")
    if status != 0 and not 100 <= status <= 599:
        raise exceptions.OptionsError("qa_fault_status must be 0 (off) or 100 to 599")
    if delay_ms < 0:
        raise exceptions.OptionsError("qa_fault_delay_ms must not be negative")
    return Snapshot(
        api_hosts=tuple(h.strip().lower() for h in hosts if h.strip()),
        mocks_dir=mocks_dir,
        request_id_header=header,
        faults=Faults(matcher, status, delay_ms, drop),
    )


def is_api_host(host: str, api_hosts: Sequence[str]) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in api_hosts)


def mock_file(mocks_dir: str, method: str, raw_path: str) -> tuple[Path, str] | None:
    """The mock file for a request and its label, or None. Never leaves `mocks_dir`."""
    if not mocks_dir or not method.isascii() or not method.isalpha():
        return None
    path = raw_path.split("?", 1)[0]
    if path == "/":
        segments = ["index"]
    elif path.startswith("/"):
        body = path[1:]
        segments = (body[:-1] if body.endswith("/") else body).split("/")
    else:
        return None
    if any(s in ("", ".", "..") for s in segments):
        return None
    label = "/".join([method, *segments]) + ".json"
    try:
        root = Path(mocks_dir).resolve()
        file = (root / label).resolve()
        if file.is_relative_to(root) and file.is_file():
            return file, label
    except (OSError, ValueError):
        pass
    return None


def header_value(headers: http.Headers, name: str) -> str | None:
    value = headers.get(name)
    return value[:MAX_ID_LENGTH] if value else None


def _set_comment(flow: http.HTTPFlow, parts: list[str]) -> None:
    flow.comment = "; ".join(parts)


class QATools:
    def __init__(self) -> None:
        self._snapshot = Snapshot()
        self._summary = ""

    def load(self, loader) -> None:
        loader.add_option("qa_api_hosts", Sequence[str], [],
                          "Hosts (and subdomains) the Wiretrace QA features apply to. Empty: nothing happens.")
        loader.add_option("qa_mocks_dir", str, "",
                          "Folder of mock files: <folder>/<METHOD>/<path>.json.")
        loader.add_option("qa_request_id_header", str, "X-Request-ID",
                          "Header read to show a request ID as the flow comment.")
        loader.add_option("qa_fault_filter", str, "",
                          "Filter expression selecting the requests to fault, e.g. ~u /api/v1/orders. "
                          "Empty: no faults. Response filters (~c, ~bs) never match.")
        loader.add_option("qa_fault_status", int, 0,
                          "Status to return instead of forwarding a matching request. 0: off.")
        loader.add_option("qa_fault_delay_ms", int, 0,
                          "Delay, in milliseconds, before a matching request continues.")
        loader.add_option("qa_fault_drop", bool, False,
                          "Close the connection of a matching request without a response.")

    def configure(self, updated) -> None:
        o = ctx.options
        # Built first: a value that fails validation must leave the snapshot in effect untouched.
        snapshot = build_snapshot(list(o.qa_api_hosts), o.qa_mocks_dir, o.qa_request_id_header,
                                  o.qa_fault_filter, o.qa_fault_status, o.qa_fault_delay_ms, o.qa_fault_drop)
        self._snapshot = snapshot
        summary = (f"Wiretrace QA: {len(snapshot.api_hosts)} API hosts, "
                   f"mocks {'on' if snapshot.mocks_dir else 'off'}, "
                   f"faults {'on' if snapshot.faults.on else 'off'}")
        if summary != self._summary:
            self._summary = summary
            logger.info(summary)

    async def request(self, flow: http.HTTPFlow) -> None:
        snapshot = self._snapshot
        if not is_api_host(flow.request.pretty_host, snapshot.api_hosts):
            return

        parts: list[str] = []
        request_id = header_value(flow.request.headers, snapshot.request_id_header)
        if request_id:
            parts.append(f"request-id: {request_id}")
            _set_comment(flow, parts)

        faults = snapshot.faults
        if faults.on and faults.matcher(flow):
            if faults.delay_ms:
                await asyncio.sleep(faults.delay_ms / 1000)
                # killable is "live and not killed": the client may have left during the delay.
                if not flow.killable:
                    return
                parts.append(f"fault: delay {faults.delay_ms} ms")
                _set_comment(flow, parts)
            if faults.drop:
                parts.append("fault: dropped")
                _set_comment(flow, parts)
                flow.marked = FAULT_MARK
                flow.kill()
                return
            if faults.status:
                parts.append(f"fault: status {faults.status}")
                _set_comment(flow, parts)
                flow.marked = FAULT_MARK
                flow.response = http.Response.make(faults.status, FAULT_BODY, JSON)
                return

        found = mock_file(snapshot.mocks_dir, flow.request.method, flow.request.path)
        if found:
            file, label = found
            try:
                body = file.read_bytes()
            except OSError:
                return
            parts.append(f"mock: {label}")
            _set_comment(flow, parts)
            flow.marked = MOCK_MARK
            flow.response = http.Response.make(200, body, JSON)

    def response(self, flow: http.HTTPFlow) -> None:
        snapshot = self._snapshot
        if not is_api_host(flow.request.pretty_host, snapshot.api_hosts):
            return
        if header_value(flow.request.headers, snapshot.request_id_header):
            return
        request_id = header_value(flow.response.headers, snapshot.request_id_header)
        if request_id:
            # The request-id part comes first, ahead of any fault or mock part.
            _set_comment(flow, [f"request-id: {request_id}", *([flow.comment] if flow.comment else [])])


addons = [QATools()]
