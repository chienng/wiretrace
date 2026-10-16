import asyncio
import gzip
import http.client
import http.server
import io
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import quote

import brotli
import pytest
import tornado.httpclient
import tornado.websocket
import zstandard
from mitmproxy import ctx
from mitmproxy.test import taddons, tflow

from addons import wiretrace_ui, qa_tools
from cli import report, screenshot, session, start
from cli.preset import Preset

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
HOST = "api.example.com"
ASSET = next((ROOT / "ui" / "dist" / "assets").glob("index-*.js"))


def make_flow(path="/api/v1/profile", method="GET", status=200, host=HOST, comment="", body=b"{}",
              content_type="application/json"):
    flow = tflow.tflow(resp=status is not None)
    flow.request.host = host
    flow.request.path = path
    flow.request.method = method
    flow.comment = comment
    if status is not None:
        flow.response.status_code = status
        flow.response.content = body
        flow.response.headers["Content-Type"] = content_type
    return flow


def write_session(folder: Path, **meta) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    session.write_meta(folder, {"preset": "staging", "target": "android", "mode": "wireguard",
                                "started_at": "2026-10-14T09:00:00+07:00", "device_logs": "android", **meta})
    return folder


class Client:
    """A browser that has the link: talks to the addon's real server on 127.0.0.1."""

    def __init__(self, ui: wiretrace_ui.WiretraceUI) -> None:
        self.ui = ui
        self.http = tornado.httpclient.AsyncHTTPClient()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.ui.port}"

    async def fetch(self, path: str, method="GET", *, cookie: str | bool = True, mutate: bool | None = None,
                    headers: dict | None = None, body=None, host: str | None = None):
        sent = dict(headers or {})
        if cookie:
            sent["Cookie"] = f"{wiretrace_ui.COOKIE}={self.ui.token if cookie is True else cookie}"
        if mutate is None:
            mutate = method in ("PUT", "POST")
        if mutate:
            sent["X-Wiretrace"] = "1"
        if host:
            sent["Host"] = host
        if body is not None and not isinstance(body, (str, bytes)):
            body = json.dumps(body)
        if method == "POST" and body is None:
            body = "{}"
        return await self.http.fetch(self.base + path, method=method, headers=sent, body=body,
                                     follow_redirects=False, raise_error=False)

    async def json(self, path: str, **kwargs):
        response = await self.fetch(path, **kwargs)
        assert response.code == 200, response.body
        return json.loads(response.body)

    async def socket(self, *, cookie: str | bool = True, origin: str | None = "default", host: str | None = None):
        headers = {}
        if cookie:
            headers["Cookie"] = f"{wiretrace_ui.COOKIE}={self.ui.token if cookie is True else cookie}"
        if origin == "default":
            origin = f"http://127.0.0.1:{self.ui.port}"
        if origin is not None:
            headers["Origin"] = origin
        if host:
            headers["Host"] = host
        request = tornado.httpclient.HTTPRequest(f"ws://127.0.0.1:{self.ui.port}/api/updates", headers=headers)
        return await tornado.websocket.websocket_connect(request)


def scenario(body, *, folder: Path | None = None, extra: tuple = (), **options):
    """Run `body(ui, client, tctx)` with the QA and UI addons loaded and the server listening."""
    async def main():
        ui = wiretrace_ui.WiretraceUI()
        with taddons.context(qa_tools.QATools(), *extra, ui) as tctx:
            tctx.configure(ui, **{"qa_ui_port": 0, "qa_ui_open_browser": False,
                                  "qa_ui_session_dir": str(folder) if folder else "", **options})
            await ui.running()
            try:
                await body(ui, Client(ui), tctx)
            finally:
                await ui.done()

    asyncio.run(main())


async def settle(ui: wiretrace_ui.WiretraceUI) -> None:
    """Long enough for a 100 ms batch and a 250 ms log poll."""
    await asyncio.sleep(wiretrace_ui.TAIL_S + 2 * wiretrace_ui.BATCH_S + 0.1)


# Token, cookie, Host, Origin, mutations (invariants 1 to 3)

def test_token_exchange_sets_a_strict_http_only_cookie_and_redirects(capsys):
    async def body(ui, client, tctx):
        response = await client.fetch(f"/?token={ui.token}", cookie=False)
        assert (response.code, response.headers["Location"]) == (302, "/")
        cookie = response.headers["Set-Cookie"]
        assert cookie.startswith(f"wiretrace_ui={ui.token};")
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
        assert "Secure" not in cookie

        page = await client.fetch("/")
        assert page.code == 200 and b'<div id="root">' in page.body
        assert (await client.fetch("/?token=wrong", cookie=False)).code == 403

    scenario(body)


def test_the_link_is_the_only_output_and_the_token_is_in_no_option(capsys):
    async def body(ui, client, tctx):
        await client.json("/api/state")
        await client.fetch("/api/nothing")
        assert not any(ui.token in str(value) for _, value in ctx.options.items())

    scenario(body)
    out = capsys.readouterr()
    assert re.fullmatch(r"Wiretrace UI: http://127\.0\.0\.1:\d+/\?token=[\w-]{43}\n", out.out)
    assert out.err == ""


def test_the_browser_opens_the_link_only_when_asked(monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(wiretrace_ui.webbrowser, "open", lambda url: opened.append(url) or True)

    async def body(ui, client, tctx):
        assert opened == [f"http://127.0.0.1:{ui.port}/?token={ui.token}"]

    scenario(body, qa_ui_open_browser=True)
    opened.clear()

    async def quiet(ui, client, tctx):
        assert opened == []

    scenario(quiet, qa_ui_open_browser=False)


PAGES = ["/", "/index.html", f"/assets/{ASSET.name}", "/api/state", "/api/flows", "/api/flows/x",
         "/api/filter?expr=~u%20x", "/api/logs?source=app", "/api/mocks", "/api/nothing", "/api/sessions",
         "/api/search?q=orders", "/api/report/draft", "/api/report/file/har",
         "/api/report/screenshot/20261014-090000.png", "/api/presets"]
MUTATIONS = [("/api/rules/test", "POST"), ("/api/rules/abcdef/rearm", "POST"), ("/api/report", "POST"),
             ("/api/report/reveal", "POST"), ("/api/view", "POST"), ("/api/flows/x/replay", "POST"),
             ("/api/report/screenshot", "POST"), ("/api/report/screenshot/20261014-090000.png", "DELETE"),
             ("/api/preset", "POST")]


@pytest.mark.parametrize("cookie", [False, "wrong", ""])
def test_every_page_api_and_asset_needs_the_cookie(cookie):
    async def body(ui, client, tctx):
        for path in PAGES:
            response = await client.fetch(path, cookie=cookie)
            assert response.code == 403, path
            assert ui.token.encode() not in response.body
        assert (await client.fetch("/api/rules", "PUT", cookie=cookie, body={})).code == 403
        assert (await client.fetch("/api/rules", cookie=cookie)).code == 403
        for path, method in MUTATIONS:
            assert (await client.fetch(path, method, cookie=cookie)).code == 403, path
        with pytest.raises(tornado.httpclient.HTTPClientError) as e:
            await client.socket(cookie=cookie)
        assert e.value.code == 403

    scenario(body)


def test_the_403_page_tells_to_open_the_link():
    async def body(ui, client, tctx):
        response = await client.fetch("/", cookie=False)
        assert response.code == 403 and b"Open the link printed in the Terminal." in response.body

    scenario(body)


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "localhost", "127.0.0.1:1", "localhost:1",
                                  "127.0.0.1.evil.example:{port}", "[::1]:{port}", "0.0.0.0:{port}"])
def test_a_wrong_host_is_refused_even_with_the_cookie(host):
    async def body(ui, client, tctx):
        host_header = host.format(port=ui.port)
        for path in ("/", "/api/state", "/api/flows", f"/assets/{ASSET.name}"):
            assert (await client.fetch(path, host=host_header)).code == 403, path
        exchange = await client.fetch(f"/?token={ui.token}", cookie=False, host=host_header)
        assert exchange.code == 403 and "Set-Cookie" not in exchange.headers
        with pytest.raises(tornado.httpclient.HTTPClientError) as e:
            await client.socket(host=host_header)
        assert e.value.code == 403

    scenario(body)


def test_both_loopback_names_with_the_port_are_accepted():
    async def body(ui, client, tctx):
        for host in (f"127.0.0.1:{ui.port}", f"localhost:{ui.port}", f"LOCALHOST:{ui.port}"):
            assert (await client.fetch("/api/state", host=host)).code == 200
        socket_ = await client.socket(origin=f"http://localhost:{ui.port}")
        socket_.close()

    scenario(body)


@pytest.mark.parametrize("origin", [None, "http://evil.example", "null", "http://127.0.0.1", "https://127.0.0.1:{port}",
                                    "http://127.0.0.1:{port}.evil.example", "http://127.0.0.2:{port}"])
def test_the_websocket_needs_the_right_origin(origin):
    async def body(ui, client, tctx):
        with pytest.raises(tornado.httpclient.HTTPClientError) as e:
            await client.socket(origin=origin.format(port=ui.port) if origin else None)
        assert e.value.code == 403
        assert not ui.hub.clients

    scenario(body)


def test_a_mutation_needs_the_x_wiretrace_header(tmp_path):
    async def body(ui, client, tctx):
        good = {"revision": "", "rules": []}
        assert (await client.fetch("/api/rules", "PUT", mutate=False, body=good)).code == 403
        assert (await client.fetch("/api/rules", "PUT", headers={"X-Wiretrace": "0"}, mutate=False, body=good)).code == 403
        for path, method in MUTATIONS:
            assert (await client.fetch(path, method, mutate=False)).code == 403, path
            assert (await client.fetch(path, method, headers={"X-Wiretrace": "0"}, mutate=False)).code == 403, path
        assert (await client.fetch("/api/rules", "PUT", body=good)).code == 200
        # A method nothing handles still needs the header before it is told 405.
        assert (await client.fetch("/api/state", "DELETE", mutate=False)).code == 403

    rules_scenario(body, tmp_path)


def test_security_headers_are_on_every_response():
    async def body(ui, client, tctx):
        csp = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
               f"connect-src 'self' ws://127.0.0.1:{ui.port} ws://localhost:{ui.port}; frame-ancestors 'none'")
        for response in [await client.fetch("/"), await client.fetch(f"/assets/{ASSET.name}"),
                         await client.fetch("/api/state"), await client.fetch("/api/flows/none"),
                         await client.fetch("/api/state", cookie=False), await client.fetch("/api/state", host="x"),
                         await client.fetch("/nothing-here"), await client.fetch(f"/?token={ui.token}", cookie=False)]:
            assert response.headers["Content-Security-Policy"] == csp
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Referrer-Policy"] == "no-referrer"
        assert (await client.fetch("/api/state")).headers["Cache-Control"] == "no-store"
        assert (await client.fetch("/api/state", cookie=False)).headers["Cache-Control"] == "no-store"

    scenario(body)


def test_only_127_0_0_1_listens():
    async def body(ui, client, tctx):
        names = {s.getsockname()[0] for s in ui._server._sockets.values()}
        assert names == {"127.0.0.1"}

    scenario(body)


def test_the_assets_are_served_and_nothing_outside_dist(tmp_path):
    (tmp_path / "secret.txt").write_text("secret")

    async def body(ui, client, tctx):
        js = await client.fetch(f"/assets/{ASSET.name}")
        assert js.code == 200 and "javascript" in js.headers["Content-Type"] and js.body == ASSET.read_bytes()
        assert (await client.fetch("/assets/missing.js")).code == 404
        assert (await client.fetch("/assets/")).code in (403, 404)
        for path in ("/../README.md", "/%2e%2e/README.md", "/assets/..%2f..%2fREADME.md", "/..%2fREADME.md"):
            assert (await client.fetch(path)).code in (403, 404), path

    scenario(body)


def test_the_page_icon_is_served_as_svg():
    page = (ROOT / "ui" / "dist" / "index.html").read_text()
    href = re.search(r'<link rel="icon" type="image/svg\+xml" href="(/assets/mark-[^"]+\.svg)"', page)
    assert href, "ui/dist/index.html has no SVG icon: run `make ui`"

    async def body(ui, client, tctx):
        icon = await client.fetch(href.group(1))
        assert icon.code == 200 and icon.headers["Content-Type"].startswith("image/svg+xml")
        assert icon.body == (ROOT / "ui" / "dist" / href.group(1).lstrip("/")).read_bytes()

    scenario(body)


def test_without_a_build_the_page_is_not_found(tmp_path):
    async def main():
        ui = wiretrace_ui.WiretraceUI()
        ui.static_dir = tmp_path / "missing"
        with taddons.context(qa_tools.QATools(), ui) as tctx:
            tctx.configure(ui, qa_ui_port=0, qa_ui_open_browser=False)
            await ui.running()
            try:
                assert (await Client(ui).fetch("/")).code == 404
            finally:
                await ui.done()

    asyncio.run(main())


def test_a_port_in_use_stops_mitmproxy_and_says_so(caplog):
    async def main():
        ui = wiretrace_ui.WiretraceUI()
        with socket.socket() as holder:
            holder.bind(("127.0.0.1", 0))
            holder.listen()
            with taddons.context(qa_tools.QATools(), ui) as tctx:
                tctx.configure(ui, qa_ui_port=holder.getsockname()[1], qa_ui_open_browser=False)
                tctx.master.shutdown = mock.Mock()
                await ui.running()
                tctx.master.shutdown.assert_called_once()
                assert ui._server is None
                await ui.done()

    asyncio.run(main())
    assert "cannot listen on 127.0.0.1" in caplog.text


def test_the_port_option_is_checked():
    ui = wiretrace_ui.WiretraceUI()
    with taddons.context(ui) as tctx:
        with pytest.raises(Exception, match="qa_ui_port"):
            tctx.configure(ui, qa_ui_port=70000)


# Summaries (flows API)

def test_summary_of_a_response():
    flow = make_flow("/api/v1/home?page=2", "POST", 503, comment="request-id: req-7", body=b"x" * 40)
    flow.response.headers["Content-Type"] = "application/json; charset=utf-8"
    assert wiretrace_ui.summary(flow) == {
        "id": flow.id, "ts": 946681200, "method": "POST", "scheme": "http", "host": HOST,
        "port": flow.request.port, "path": "/api/v1/home?page=2", "status": 503, "error": None,
        "duration_ms": 3000, "size": 40, "mime": "application/json", "request_id": "req-7",
        "mock": False, "fault": None, "websocket": False, "replay_of": None}


def test_summary_says_which_request_a_replay_repeats():
    flow = make_flow(comment="replay: abc-1; request-id: r1")
    assert (wiretrace_ui.summary(flow)["replay_of"], wiretrace_ui.summary(flow)["request_id"]) == ("abc-1", "r1")


def test_summary_of_a_failed_request_has_the_error_and_no_status():
    flow = tflow.tflow(err=True)
    summary = wiretrace_ui.summary(flow)
    assert (summary["status"], summary["error"], summary["size"], summary["mime"]) == (None, "error", None, None)
    assert summary["duration_ms"] == 7000


def test_summary_of_a_flow_with_nothing_yet():
    flow = tflow.tflow(resp=False)
    summary = wiretrace_ui.summary(flow)
    assert (summary["status"], summary["duration_ms"], summary["size"]) == (None, None, None)


@pytest.mark.parametrize("comment, mocked, fault, request_id", [
    ("", False, None, None),
    ("request-id: abc", False, None, "abc"),
    ("request-id: abc; fault: status 500", False, "status 500", "abc"),
    ("request-id: abc; fault: dropped", False, "dropped", "abc"),
    ("fault: delay 300 ms; fault: status 500", False, "delay 300 ms, status 500", None),
    ("request-id: abc; mock: GET/api/x.json", True, None, "abc"),
    ("a note about mock: and fault: inside", False, None, None),
])
def test_summary_reads_the_comment_parts(comment, mocked, fault, request_id):
    summary = wiretrace_ui.summary(make_flow(comment=comment))
    assert (summary["mock"], summary["fault"], summary["request_id"]) == (mocked, fault, request_id)


def test_summary_of_a_websocket_flow():
    assert wiretrace_ui.summary(tflow.twebsocketflow())["websocket"] is True


def test_summary_survives_bytes_that_are_not_utf8():
    flow = make_flow()
    flow.request.headers[b"X-Bad"] = b"\xff\xfe"
    flow.request.path = "/caf\udce9"
    json.dumps(wiretrace_ui.summary(flow))
    json.dumps(wiretrace_ui.detail(flow, "mocks/x"))


def test_the_flows_endpoint_lists_http_flows_oldest_first_and_skips_the_receiver():
    async def body(ui, client, tctx):
        first, second = make_flow("/a"), make_flow("/b", status=None)
        receiver = make_flow("/log", "POST", host="qa-logs.internal")
        for flow in (first, receiver, second, tflow.ttcpflow()):
            ui.request(flow)
        ui.response(first)
        listed = await client.json("/api/flows")
        assert [f["id"] for f in listed["flows"]] == [first.id, second.id]
        assert (await client.json("/api/state"))["flow_count"] == 2
        assert (await client.fetch(f"/api/flows/{receiver.id}")).code == 404

    scenario(body)


def test_a_flow_that_changes_stays_one_entry():
    async def body(ui, client, tctx):
        flow = make_flow(status=None)
        ui.request(flow)
        flow.response = make_flow().response
        ui.response(flow)
        flows = (await client.json("/api/flows"))["flows"]
        assert len(flows) == 1 and flows[0]["status"] == 200

    scenario(body)


def test_the_flow_store_drops_the_oldest_over_the_cap():
    hub = wiretrace_ui.Hub(cap=3)
    flows = [make_flow(f"/{i}") for i in range(5)]
    for flow in flows:
        hub.track(flow)
    assert list(hub.flows) == [f.id for f in flows[2:]]
    hub.track(flows[3])
    assert list(hub.flows) == [f.id for f in flows[2:]]
    assert wiretrace_ui.MAX_FLOWS == 10_000 and wiretrace_ui.MAX_LOG_LINES == 50_000


# Detail

def test_detail_of_a_json_flow():
    async def body(ui, client, tctx):
        flow = make_flow("/api/v1/orders?id=1", "POST", 500, body=b'{"error": "boom"}', comment="request-id: r1")
        flow.request.content = b'{"sku": "A"}'
        flow.request.headers["Authorization"] = "Bearer t"
        ui.response(flow)
        detail = await client.json(f"/api/flows/{flow.id}")
        assert detail["summary"] == wiretrace_ui.summary(flow)
        assert detail["request"]["body"] == {"text": '{"sku": "A"}', "size": 12, "truncated": False, "binary": False}
        assert ["Authorization", "Bearer t"] in detail["request"]["headers"]
        assert detail["request"]["http_version"] == "HTTP/1.1"
        assert detail["response"]["status"] == 500 and detail["response"]["reason"] == "OK"
        assert detail["response"]["body"]["text"] == '{"error": "boom"}'
        assert detail["timing"] == {"start": 946681200, "request_end": 946681201,
                                    "response_start": 946681202, "response_end": 946681203}
        assert detail["comment"] == "request-id: r1"
        assert detail["mock_path"] == "mocks/staging/POST/api/v1/orders.json"

    scenario(body, qa_mocks_dir=str(ROOT / "mocks" / "staging"))


def test_detail_without_a_response():
    async def body(ui, client, tctx):
        flow = make_flow(status=None)
        ui.request(flow)
        detail = await client.json(f"/api/flows/{flow.id}")
        assert detail["response"] is None
        assert detail["timing"]["response_start"] is None and detail["timing"]["response_end"] is None

    scenario(body)


def test_detail_decodes_a_compressed_body():
    async def body(ui, client, tctx):
        flow = make_flow(body=b"")
        flow.response.headers["Content-Encoding"] = "gzip"
        flow.response.raw_content = gzip.compress('{"name": "Zoë"}'.encode())
        ui.response(flow)
        detail = await client.json(f"/api/flows/{flow.id}")
        assert detail["response"]["body"]["text"] == '{"name": "Zoë"}'

    scenario(body)


def test_detail_truncates_a_body_at_2_mib():
    async def body(ui, client, tctx):
        flow = make_flow(body=b"a" * (wiretrace_ui.MAX_BODY_BYTES + 10), content_type="text/plain")
        ui.response(flow)
        text = (await client.json(f"/api/flows/{flow.id}"))["response"]["body"]
        assert (text["truncated"], text["binary"], text["size"]) == (True, False, wiretrace_ui.MAX_BODY_BYTES + 10)
        assert len(text["text"]) == wiretrace_ui.MAX_BODY_BYTES

        exact = make_flow(body=b"a" * wiretrace_ui.MAX_BODY_BYTES, content_type="text/plain")
        ui.response(exact)
        body_ = (await client.json(f"/api/flows/{exact.id}"))["response"]["body"]
        assert body_["truncated"] is False and len(body_["text"]) == wiretrace_ui.MAX_BODY_BYTES

    scenario(body)


@pytest.mark.parametrize("data, content_type, binary", [
    (b"\x89PNG\r\n\x1a\n\x00\x00", "image/png", True),
    (bytes(range(256)), "application/x-unknown", True),
    (b"\xff\xfe\xfd\xfc", "application/x-unknown", True),
    (b"has a \x00 nul", "text/plain", True),
    ("héllo".encode(), "application/x-unknown", False),
    (b'{"a": 1}', "application/json", False),
    (b"", "image/png", False),
    (b"plain", "", False),
])
def test_binary_bodies_have_no_text(data, content_type, binary):
    flow = make_flow(body=data, content_type=content_type)
    if not content_type:
        del flow.response.headers["Content-Type"]
    info = wiretrace_ui.body_info(flow.response)
    assert info["binary"] is binary and info["size"] == len(data)
    assert (info["text"] is None) is binary


def test_detail_uses_the_charset_of_a_truncated_body():
    flow = make_flow(body=("é" * (wiretrace_ui.MAX_BODY_BYTES + 5)).encode("latin-1"),
                     content_type="text/plain; charset=latin-1")
    info = wiretrace_ui.body_info(flow.response)
    assert info["truncated"] and info["text"].startswith("éé")


def deflate(data: bytes) -> bytes:
    return zlib.compress(data)


ENCODERS = {
    "gzip": gzip.compress,
    "deflate": deflate,
    "br": lambda data: brotli.compress(data, quality=1),
    "zstd": lambda data: zstandard.ZstdCompressor(level=1).compress(data),
}


def compressed_flow(encoding: str, data: bytes, content_type: str = "text/plain"):
    flow = make_flow(body=b"", content_type=content_type)
    flow.response.headers["Content-Encoding"] = encoding
    flow.response.raw_content = ENCODERS[encoding](data)
    return flow


@pytest.mark.parametrize("encoding", sorted(ENCODERS))
def test_a_small_compressed_body_is_decoded(encoding):
    info = wiretrace_ui.body_info(compressed_flow(encoding, '{"name": "Zoë"}'.encode(), "application/json").response)
    assert info == {"text": '{"name": "Zoë"}', "size": len('{"name": "Zoë"}'.encode()),
                    "truncated": False, "binary": False}


@pytest.mark.parametrize("encoding", sorted(ENCODERS))
def test_a_large_compressed_body_is_never_decoded_whole(encoding):
    flow = compressed_flow(encoding, b"a" * (3 << 20))
    with mock.patch.object(type(flow.response), "get_content", side_effect=AssertionError("full decode")):
        info = wiretrace_ui.body_info(flow.response)
    assert (info["truncated"], info["binary"], info["size"]) == (True, False, 3 << 20)
    assert info["text"] == "a" * wiretrace_ui.MAX_BODY_BYTES


def test_a_large_raw_deflate_body_reports_its_full_size():
    packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    flow = make_flow(body=b"", content_type="text/plain")
    flow.response.headers["Content-Encoding"] = "deflate"
    flow.response.raw_content = packer.compress(b"a" * (3 << 20)) + packer.flush()
    info = wiretrace_ui.body_info(flow.response)
    assert (info["truncated"], info["size"]) == (True, 3 << 20)
    assert info["text"] == "a" * wiretrace_ui.MAX_BODY_BYTES


def test_a_compression_bomb_is_counted_only_up_to_the_cap():
    flow = compressed_flow("gzip", b"a" * (wiretrace_ui.MAX_COUNT_BYTES + (8 << 20)))
    with mock.patch.object(type(flow.response), "get_content", side_effect=AssertionError("full decode")):
        info = wiretrace_ui.body_info(flow.response)
    assert info["truncated"] and len(info["text"]) == wiretrace_ui.MAX_BODY_BYTES
    assert wiretrace_ui.MAX_COUNT_BYTES <= info["size"] < wiretrace_ui.MAX_COUNT_BYTES + (8 << 20)


def test_a_body_that_does_not_decode_is_shown_as_it_travelled():
    flow = make_flow(body=b"", content_type="text/plain")
    flow.response.headers["Content-Encoding"] = "gzip"
    flow.response.raw_content = b"not gzip at all"
    info = wiretrace_ui.body_info(flow.response)
    assert (info["text"], info["size"], info["truncated"]) == ("not gzip at all", 15, False)


def test_an_unknown_flow_is_404_with_an_error():
    async def body(ui, client, tctx):
        response = await client.fetch("/api/flows/does-not-exist")
        assert response.code == 404 and "error" in json.loads(response.body)

    scenario(body)


@pytest.mark.parametrize("path, expected", [
    ("/api/v1/profile?x=1", "GET/api/v1/profile.json"),
    ("/", "GET/index.json"),
    ("/a/b/", "GET/a/b.json"),
])
def test_mock_path_matches_where_the_qa_addon_looks(path, expected):
    assert wiretrace_ui.mock_path("mocks/staging", "GET", path) == f"mocks/staging/{expected}"


def test_mock_path_is_a_file_the_qa_addon_would_serve(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_tools, "WIRETRACE", tmp_path)
    root = tmp_path / "mocks"
    for path in ("/api/v1/profile?x=1", "/", "/a/b/"):
        relative = wiretrace_ui.mock_path("", "GET", path)
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("{}")
        assert qa_tools.mock_file(str(root), "GET", path) is not None, path


# Filter

def test_filter_matches_the_flows_in_memory():
    async def body(ui, client, tctx):
        a, b, c = make_flow("/api/v1/orders"), make_flow("/api/v1/profile", status=404), make_flow(status=None)
        for flow in (a, b, c):
            ui.request(flow)
        ids = (await client.json("/api/filter?expr=~u%20orders"))["ids"]
        assert ids == [a.id]
        assert (await client.json("/api/filter?expr=~c%20404"))["ids"] == [b.id]
        assert (await client.json("/api/filter?expr=!~c%20404"))["ids"] == [a.id, c.id]
        assert (await client.json("/api/filter?expr=~u%20nothing"))["ids"] == []

    scenario(body)


@pytest.mark.parametrize("expr", ["~~bad(", "~u", "~zz foo", "", "   "])
def test_an_invalid_filter_is_a_400_with_the_message(expr):
    async def body(ui, client, tctx):
        response = await client.fetch(f"/api/filter?expr={quote(expr)}")
        assert response.code == 400
        assert json.loads(response.body)["error"]

    scenario(body)


def test_the_filter_message_is_the_parsers():
    async def body(ui, client, tctx):
        response = await client.fetch("/api/filter?expr=~~bad(")
        assert "Invalid filter expression" in json.loads(response.body)["error"]

    scenario(body)


# Rules (spec 008 slice A)

RULE = {"id": "orders500", "name": "Orders fail", "enabled": True,
        "match": {"method": "POST", "host": "", "path": "/api/v1/orders", "body_contains": ""},
        "action": {"type": "status", "status": 500, "body": "", "mock_file": "", "delay_ms": 0},
        "apply": {"mode": "always", "n": 0}}


def rule(**over) -> dict:
    out = json.loads(json.dumps(RULE))
    for key, value in over.items():
        if isinstance(value, dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def rules_scenario(body, tmp_path, **options):
    scenario(body, qa_api_hosts=[HOST], qa_rules_file=str(tmp_path / "rules" / "staging.json"), **options)


async def put_rules(client, rules, revision=None):
    if revision is None:
        revision = (await client.json("/api/rules"))["revision"]
    return await client.fetch("/api/rules", "PUT", body={"revision": revision, "rules": rules})


def test_rules_start_empty_and_say_where_the_file_is(tmp_path):
    async def body(ui, client, tctx):
        got = await client.json("/api/rules")
        assert got == {"revision": "", "rules": [], "stats": {}, "legacy_faults_on": False,
                       "file": str(tmp_path / "rules" / "staging.json"), "error": None, "api_hosts": [HOST]}
        assert (await client.json("/api/state"))["rules_on"] == 0

    rules_scenario(body, tmp_path)


def test_a_valid_save_writes_the_file_whole_and_applies_at_once(tmp_path):
    async def body(ui, client, tctx):
        qa = tctx.master.addons.get("qatools")
        response = await put_rules(client, [rule(), rule(id="second1", enabled=False)])
        assert response.code == 200, response.body
        saved = json.loads(response.body)
        assert [r["id"] for r in saved["rules"]] == ["orders500", "second1"] and saved["revision"]
        file = tmp_path / "rules" / "staging.json"
        assert json.loads(file.read_text())["rules"] == saved["rules"]
        assert sorted(p.name for p in file.parent.iterdir()) == ["staging.json"]
        assert [r.id for r in qa.rules.rules] == ["orders500", "second1"]
        assert (await client.json("/api/state"))["rules_on"] == 1

    rules_scenario(body, tmp_path)


@pytest.mark.parametrize("bad, field", [
    ({"match": {"path": ""}}, "match.path"),
    ({"match": {"host": "other.example.com"}}, "match.host"),
    ({"action": {"status": 99}}, "action.status"),
    ({"apply": {"mode": "every_nth", "n": 1}}, "apply.n"),
    ({"id": "UPPER"}, "id"),
])
def test_an_invalid_save_is_a_400_and_changes_neither_file_nor_engine(tmp_path, bad, field):
    async def body(ui, client, tctx):
        qa = tctx.master.addons.get("qatools")
        assert (await put_rules(client, [rule()])).code == 200
        before = (tmp_path / "rules" / "staging.json").read_bytes()
        response = await put_rules(client, [rule(id="keep01"), rule(**bad)])
        assert response.code == 400
        assert json.loads(response.body)["index"] == 1 and json.loads(response.body)["field"] == field
        assert (tmp_path / "rules" / "staging.json").read_bytes() == before
        assert [r.id for r in qa.rules.rules] == ["orders500"]

    rules_scenario(body, tmp_path)


def test_a_save_with_a_stale_revision_is_a_409(tmp_path):
    async def body(ui, client, tctx):
        assert (await put_rules(client, [rule()])).code == 200
        assert (await put_rules(client, [], revision="stale")).code == 409
        assert len((await client.json("/api/rules"))["rules"]) == 1

    rules_scenario(body, tmp_path)


@pytest.mark.parametrize("body_", ["{not json", "null", "[]", '{"rules": []}', '{"revision": "", "rules": {}}'])
def test_a_malformed_rules_body_is_a_400(tmp_path, body_):
    async def body(ui, client, tctx):
        assert (await client.fetch("/api/rules", "PUT", body=body_)).code == 400
        assert not (tmp_path / "rules").exists()

    rules_scenario(body, tmp_path)


def test_without_a_rules_file_a_save_is_refused():
    async def body(ui, client, tctx):
        assert (await client.fetch("/api/rules", "PUT", body={"revision": "", "rules": []})).code == 409

    scenario(body, qa_api_hosts=[HOST])


def test_testing_a_rule_says_what_the_app_gets_and_leaves_the_counters(tmp_path):
    async def body(ui, client, tctx):
        qa = tctx.master.addons.get("qatools")
        assert (await put_rules(client, [rule()])).code == 200
        flow = make_flow("/api/v1/orders", method="POST")
        await qa.request(flow)
        ui.request(flow)
        stats = (await client.json("/api/rules"))["stats"]
        assert stats["orders500"]["matches"] == 1
        got = await client.json("/api/rules/test", method="POST", body={"rule": rule(), "flow_id": flow.id})
        assert got["matches"] is True and "500" in got["result"]
        miss = await client.json("/api/rules/test", method="POST",
                                 body={"rule": rule(match={"method": "GET"}), "flow_id": flow.id})
        assert miss["matches"] is False and miss["result"] is None
        assert (await client.json("/api/rules"))["stats"] == stats
        assert (await client.fetch("/api/rules/test", "POST", body={"rule": rule(), "flow_id": "nope"})).code == 404
        assert (await client.fetch("/api/rules/test", "POST", body={"rule": rule(name=""), "flow_id": flow.id})).code == 400

    rules_scenario(body, tmp_path)


def test_rearm_resets_the_counters(tmp_path):
    async def body(ui, client, tctx):
        qa = tctx.master.addons.get("qatools")
        assert (await put_rules(client, [rule(apply={"mode": "once"})])).code == 200
        for _ in range(2):
            await qa.request(make_flow("/api/v1/orders", method="POST"))
        assert (await client.json("/api/rules"))["stats"]["orders500"]["applied"] == 1
        got = await client.json("/api/rules/orders500/rearm", method="POST")
        assert got["stats"]["orders500"] == {"matches": 0, "applied": 0, "last_ts": None}
        assert (await client.fetch("/api/rules/unknown1/rearm", "POST")).code == 404

    rules_scenario(body, tmp_path)


def test_the_faults_endpoint_is_gone():
    async def body(ui, client, tctx):
        assert (await client.fetch("/api/faults", "PUT", body={})).code == 404

    scenario(body)


def test_a_rule_body_near_1_mib_is_accepted_but_only_after_the_checks(tmp_path):
    async def body(ui, client, tctx):
        big = {"revision": "", "rules": [rule(action={"body": "x" * 900_000})]}
        assert (await client.fetch("/api/rules", "PUT", cookie=False, body=big)).code in (403, 599)
        assert (await client.fetch("/api/rules", "PUT", mutate=False, body=big)).code in (403, 599)
        assert not (tmp_path / "rules").exists()
        assert (await client.fetch("/api/rules", "PUT", body=big)).code == 200

    rules_scenario(body, tmp_path)


def test_a_body_over_the_limit_is_refused():
    async def body(ui, client, tctx):
        response = await client.fetch("/api/report", "POST", body="x" * (wiretrace_ui.MAX_REQUEST_BYTES + 1))
        assert response.code in (400, 413, 599)
        assert (await client.fetch("/api/state")).code == 200

    scenario(body)


def test_a_hand_edited_invalid_file_keeps_the_rules_and_shows_the_error(tmp_path):
    async def body(ui, client, tctx):
        assert (await put_rules(client, [rule()])).code == 200
        file = tmp_path / "rules" / "staging.json"
        tmp = file.with_suffix(".tmp")
        tmp.write_text('{"version": 1, "rules": [{"id": "x"}]}')
        os.replace(tmp, file)
        await asyncio.sleep(qa_tools.RELOAD_CHECK_S + 0.3)
        got = await client.json("/api/rules")
        assert got["error"] and [r["id"] for r in got["rules"]] == ["orders500"]

    rules_scenario(body, tmp_path)


# Mocks, state

def test_the_mocks_endpoint_lists_json_files_relative_to_the_mocks_dir(tmp_path):
    root = tmp_path / "mocks"
    (root / "GET" / "api" / "v1").mkdir(parents=True)
    (root / "GET" / "api" / "v1" / "profile.json").write_text("{}")
    (root / "POST").mkdir()
    (root / "POST" / "x.json").write_text("{}")
    (root / "POST" / "notes.txt").write_text("x")

    async def body(ui, client, tctx):
        assert await client.json("/api/mocks") == {"files": ["GET/api/v1/profile.json", "POST/x.json"]}

    scenario(body, qa_mocks_dir=str(root))


def test_no_mocks_dir_no_files(tmp_path):
    async def body(ui, client, tctx):
        assert await client.json("/api/mocks") == {"files": []}
        assert wiretrace_ui.list_mocks(str(tmp_path / "missing")) == []

    scenario(body)


def test_state_comes_from_the_session_and_options(tmp_path):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")

    async def body(ui, client, tctx):
        state = await client.json("/api/state")
        assert state["version"] == "0.8.0"
        assert (state["preset"], state["target"], state["mode"]) == ("staging", "android", "wireguard")
        assert state["started_at"] == 1791943200.0
        assert state["session"] == "2026-10-14_090000_staging_android"
        assert state["device_logs"] == "android"
        assert state["default_filter"] == "!~t image"
        assert state["mac_ip"] is None and state["wireguard_conf"] is None
        assert state["mocks_dir"] == "mocks/staging"
        assert state["flow_count"] == 0 and state["faults_on"] is False
        assert str(tmp_path) not in json.dumps(state)
        session.update_meta(folder, device_logs=None)
        assert (await client.json("/api/state"))["device_logs"] is None

    scenario(body, folder=folder, qa_ui_default_filter="!~t image", qa_mocks_dir=str(ROOT / "mocks" / "staging"))


def test_state_without_a_readable_meta_has_defaults(tmp_path):
    async def body(ui, client, tctx):
        state = await client.json("/api/state")
        assert (state["preset"], state["mode"], state["device_logs"]) == ("", "", None)
        assert isinstance(state["started_at"], float)

    scenario(body, folder=tmp_path)


def tls_data(sni):
    data = mock.Mock()
    data.context.client.sni = sni
    return data


def test_setup_state_has_the_first_device_connection_and_nothing_about_the_peer(tmp_path):
    async def body(ui, client, tctx):
        state = await client.json("/api/state")
        assert (state["device_seen_at"], state["tls_failures"]) == (None, 0)
        socket_ = await client.socket()
        refused = tflow.tclient_conn()
        refused.error = "refused by proxy_guard"
        ui.client_connected(refused)
        assert (await client.json("/api/state"))["device_seen_at"] is None

        device = tflow.tclient_conn()
        device.peername = ("192.0.2.88", 50123)
        ui.client_connected(device)
        seen = await read_until(socket_, lambda m: m["type"] == "state" and m["state"]["device_seen_at"])
        state = seen[-1]["state"]
        assert isinstance(state["device_seen_at"], float)
        assert "192.0.2.88" not in json.dumps(state) and "50123" not in json.dumps(state)
        socket_.close()

    rules_scenario(body, tmp_path)


def test_setup_counts_failed_tls_handshakes_with_api_hosts_only(tmp_path):
    async def body(ui, client, tctx):
        for sni in (HOST, f"cdn.{HOST}", HOST.upper(), "other.example.org", None, ""):
            ui.tls_failed_client(tls_data(sni))
        ui.tls_failed_client(object())
        assert (await client.json("/api/state"))["tls_failures"] == 3

    rules_scenario(body, tmp_path)


def test_why_device_logs_are_off_comes_from_the_session(tmp_path):
    folder = write_session(tmp_path, device_logs=None, device_logs_off="adb not found")

    async def body(ui, client, tctx):
        state = await client.json("/api/state")
        assert (state["device_logs"], state["device_logs_off"]) == (None, "adb not found")

    scenario(body, folder=folder)


def status_doc(**over) -> bytes:
    doc = {"state": "streaming", "message": "streaming", "source": "android", "app": "com.example.app",
           "model": "Pixel 8", "os": "Android 15", "updated_at": "2026-10-14T09:00:01.000+07:00", **over}
    return json.dumps(doc).encode()


def write_status(folder: Path, raw: bytes) -> None:
    tmp = folder / ".status.tmp"
    tmp.write_bytes(raw)
    os.replace(tmp, folder / session.DEVICE_STATUS)


def test_device_status_is_in_the_state_and_follows_the_file_over_the_socket(tmp_path):
    folder = write_session(tmp_path)

    async def body(ui, client, tctx):
        assert (await client.json("/api/state"))["device_status"] is None
        socket_ = await client.socket()
        write_status(folder, status_doc(state="waiting", message="waiting for a device", model="", os=""))
        seen = await read_until(socket_, lambda m: m["type"] == "device")
        assert seen[-1]["status"]["state"] == "waiting"
        write_status(folder, status_doc())
        seen = await read_until(socket_, lambda m: m["type"] == "device")
        assert seen[-1]["status"] == {"state": "streaming", "message": "streaming", "source": "android",
                                      "app": "com.example.app", "model": "Pixel 8", "os": "Android 15",
                                      "updated_at": 1791943201.0}
        assert (await client.json("/api/state"))["device_status"]["model"] == "Pixel 8"
        socket_.close()

    scenario(body, folder=folder)


@pytest.mark.parametrize("raw", [b"{broken", b"[]", status_doc(state="hacked"), status_doc(state=None),
                                 b" " * (wiretrace_ui.MAX_STATUS_BYTES + 1)])
def test_a_device_status_that_is_not_one_keeps_the_last_good_one(tmp_path, raw):
    folder = write_session(tmp_path)
    write_status(folder, status_doc())

    async def body(ui, client, tctx):
        assert (await client.json("/api/state"))["device_status"]["state"] == "streaming"
        write_status(folder, raw)
        await settle(ui)
        assert (await client.json("/api/state"))["device_status"]["state"] == "streaming"

    scenario(body, folder=folder)


def test_device_status_fields_are_cleaned_and_cut():
    status = wiretrace_ui.device_status(status_doc(model="m" * 500, os=7, extra="SECRET", app=None))
    assert len(status["model"]) == wiretrace_ui.MAX_STATUS_TEXT and status["os"] == "" and status["app"] == ""
    assert "extra" not in status and "SECRET" not in json.dumps(status)


def test_wireguard_configuration_comes_from_the_server_instance(monkeypatch, tmp_path):
    class Instance:
        def client_conf(self):
            return "\n[Interface]\nPrivateKey = not-a-real-key\n"

    class Proxyserver:
        servers = [object(), Instance()]

    async def main():
        ui = wiretrace_ui.WiretraceUI()
        with taddons.context(Proxyserver(), qa_tools.QATools(), ui) as tctx:
            tctx.configure(ui, qa_ui_port=0, qa_ui_open_browser=False,
                           qa_ui_session_dir=str(write_session(tmp_path)))
            await ui.running()
            try:
                client = Client(ui)
                assert (await client.json("/api/state"))["wireguard_conf"] == "[Interface]\nPrivateKey = not-a-real-key\n"
                # Never without the cookie.
                assert b"PrivateKey" not in (await client.fetch("/api/state", cookie=False)).body
                session.update_meta(tmp_path, mode="proxy")
                monkeypatch.setattr("mitmproxy.net.local_ip.get_local_ip", lambda: "192.0.2.7")
                proxy = await client.json("/api/state")
                assert (proxy["wireguard_conf"], proxy["mac_ip"]) == (None, "192.0.2.7")
            finally:
                await ui.done()

    asyncio.run(main())


# Logs

def line(**record) -> bytes:
    return (json.dumps(record) + "\n").encode()


def test_log_tail_reads_lines_and_converts_the_timestamp(tmp_path):
    path = tmp_path / "device.log.jsonl"
    path.write_bytes(line(ts="2026-10-14T09:00:00.500+07:00", source="android", level="E", tag="App",
                          message="boom", request_id="r1") + line(message="bare"))
    tail = wiretrace_ui.LogTail(path, "device")
    new = tail.poll()
    assert [n["seq"] for n in new] == [1, 2]
    assert new[0] == {"seq": 1, "source": "device", "ts": 1791943200.5, "level": "E", "tag": "App",
                      "message": "boom", "request_id": "r1", "raw": path.read_text().splitlines()[0]}
    assert (new[1]["ts"], new[1]["level"], new[1]["tag"], new[1]["request_id"]) == (None, None, None, None)
    assert tail.poll() == []
    with open(path, "ab") as f:
        f.write(line(message="third"))
    assert [n["message"] for n in tail.poll()] == ["third"] and tail.lines[-1]["seq"] == 3


def test_log_tail_keeps_a_partial_last_line_until_its_newline(tmp_path):
    path = tmp_path / "app.log.jsonl"
    tail = wiretrace_ui.LogTail(path, "app")
    whole = line(message="whole").rstrip(b"\n")
    path.write_bytes(whole + b"\n" + b'{"message": "par')
    assert [n["message"] for n in tail.poll()] == ["whole"]
    with open(path, "ab") as f:
        f.write(b'tial"}')
    assert tail.poll() == []
    with open(path, "ab") as f:
        f.write(b"\n")
    assert [n["message"] for n in tail.poll()] == ["partial"]


def test_log_tail_retries_a_file_that_does_not_exist_yet(tmp_path):
    path = tmp_path / "device.log.jsonl"
    tail = wiretrace_ui.LogTail(path, "device")
    assert tail.poll() == [] and tail.poll() == []
    path.write_bytes(line(message="late"))
    assert [n["message"] for n in tail.poll()] == ["late"]
    assert wiretrace_ui.LogTail(None, "device").poll() == []


def test_a_line_that_is_not_json_keeps_only_its_text(tmp_path):
    path = tmp_path / "device.log.jsonl"
    path.write_bytes(b"plain text line\r\n\n   \n42\n[1, 2]\n" + line(message=["a", 1]) + b"\xff\xfe broken\n")
    new = wiretrace_ui.LogTail(path, "device").poll()
    assert new[0] == {"seq": 1, "source": "device", "message": "plain text line"}
    assert [n["message"] for n in new[1:3]] == ["42", "[1, 2]"]
    assert new[3]["message"] == '["a", 1]'
    assert "broken" in new[4]["message"] and "ts" not in new[4]
    assert [n["seq"] for n in new] == [1, 2, 3, 4, 5]


def test_log_tail_keeps_the_last_lines_and_the_sequence_goes_on(tmp_path):
    path = tmp_path / "app.log.jsonl"
    path.write_bytes(b"".join(line(message=str(i)) for i in range(10)))
    tail = wiretrace_ui.LogTail(path, "app", cap=4)
    assert len(tail.poll()) == 10
    assert [n["message"] for n in tail.lines] == ["6", "7", "8", "9"]
    assert [n["seq"] for n in tail.lines] == [7, 8, 9, 10]


def test_log_tail_starts_over_when_the_file_shrinks(tmp_path):
    path = tmp_path / "app.log.jsonl"
    path.write_bytes(line(message="a") + line(message="b"))
    tail = wiretrace_ui.LogTail(path, "app")
    tail.poll()
    path.write_bytes(line(message="c"))
    assert [n["message"] for n in tail.poll()] == ["c"]


def test_log_tail_does_not_hold_a_line_without_end_forever(tmp_path):
    path = tmp_path / "app.log.jsonl"
    path.write_bytes(b"x" * (wiretrace_ui.MAX_PARTIAL + 5))
    tail = wiretrace_ui.LogTail(path, "app")
    assert len(tail.poll()) == 1 and tail.partial == b""


def test_log_tail_reads_in_bounded_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(wiretrace_ui, "READ_LIMIT", 64)
    path = tmp_path / "app.log.jsonl"
    path.write_bytes(b"".join(line(message=f"line {i}") for i in range(20)))
    tail = wiretrace_ui.LogTail(path, "app")
    seen = []
    for _ in range(40):
        seen += [n["message"] for n in tail.poll()]
    assert seen == [f"line {i}" for i in range(20)]


def test_logs_endpoint_serves_both_sources_and_follows_the_files(tmp_path):
    folder = write_session(tmp_path)
    (folder / session.DEVICE_LOG).write_bytes(line(source="android", level="I", message="one"))

    async def body(ui, client, tctx):
        device = await client.json("/api/logs?source=device")
        assert [l["message"] for l in device["lines"]] == ["one"]
        assert (await client.json("/api/logs?source=app")) == {"lines": []}
        (folder / session.APP_LOG).write_bytes(line(level="W", message="later"))
        with open(folder / session.DEVICE_LOG, "ab") as f:
            f.write(line(message="two"))
        await settle(ui)
        assert [l["message"] for l in (await client.json("/api/logs?source=app"))["lines"]] == ["later"]
        assert [l["seq"] for l in (await client.json("/api/logs?source=device"))["lines"]] == [1, 2]
        assert (await client.fetch("/api/logs?source=other")).code == 400
        assert (await client.fetch("/api/logs")).code == 400

    scenario(body, folder=folder)


# Report

def test_report_runs_in_a_worker_thread_and_returns_only_the_file_name(tmp_path, monkeypatch):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")
    calls = []

    def create(session_folder, presets_dir, now=None):
        calls.append((session_folder, threading.current_thread() is threading.main_thread()))
        return report.Created(zip=session_folder / "x-report.zip", requests=5, failed=2, mocked=1, faulted=1,
                              device_lines=7, app_lines=3, cut_off=False)

    monkeypatch.setattr(report, "create", create)

    async def body(ui, client, tctx):
        result = await client.json("/api/report", method="POST")
        assert result == {"ok": True, "zip": "x-report.zip", "requests": 5, "failed": 2, "device_lines": 7,
                          "app_lines": 3, "message": "Report written."}
        assert calls == [(folder.resolve(), False)]
        assert ui.last_report == folder.resolve() / "x-report.zip"

    scenario(body, folder=folder)


def test_a_second_report_while_one_runs_is_409(tmp_path, monkeypatch):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")
    release, started = threading.Event(), threading.Event()

    def create(session_folder, presets_dir, now=None):
        started.set()
        assert release.wait(10)
        return report.Created(zip=session_folder / "r.zip", requests=1, failed=0, mocked=0, faulted=0,
                              device_lines=0, app_lines=0, cut_off=True)

    monkeypatch.setattr(report, "create", create)

    async def body(ui, client, tctx):
        first = asyncio.ensure_future(client.fetch("/api/report", "POST"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        second = await client.fetch("/api/report", "POST")
        assert second.code == 409 and json.loads(second.body)["error"]
        release.set()
        done = await first
        assert done.code == 200 and "flows.mitm ends early" in json.loads(done.body)["message"]
        assert (await client.fetch("/api/report", "POST")).code == 200

    scenario(body, folder=folder)


def test_a_report_that_fails_says_why_and_forgets_nothing(tmp_path, monkeypatch):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")
    outcomes = iter([report.Created(folder / "ok.zip", 1, 0, 0, 0, 0, 0, False), report.Failure("Nothing to report.")])

    def create(*args, **kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(report, "create", create)

    async def body(ui, client, tctx):
        await client.json("/api/report", method="POST")
        failed = await client.json("/api/report", method="POST")
        assert failed == {"ok": False, "zip": None, "requests": 0, "failed": 0, "device_lines": 0,
                          "app_lines": 0, "message": "Nothing to report."}
        assert ui.last_report == folder / "ok.zip" and not ui.report_running

    scenario(body, folder=folder)


def test_an_unexpected_report_error_is_reported_by_type_only(tmp_path, monkeypatch):
    def create(*args, **kwargs):
        raise RuntimeError("/Users/secret/path")

    monkeypatch.setattr(report, "create", create)

    async def body(ui, client, tctx):
        result = await client.json("/api/report", method="POST")
        assert result["ok"] is False and "secret" not in result["message"] and not ui.report_running

    scenario(body, folder=write_session(tmp_path))


def test_the_real_report_is_written_for_the_session_so_far(tmp_path):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android", preset="no-such-preset")
    (folder / session.DEVICE_LOG).write_bytes(line(message="d1") + line(message="d2"))
    (folder / session.APP_LOG).write_bytes(line(message="a1"))

    async def body(ui, client, tctx):
        result = await client.json("/api/report", method="POST")
        assert result["ok"] and result["zip"] == "2026-10-14_090000_staging_android-report.zip"
        assert (result["requests"], result["device_lines"], result["app_lines"]) == (0, 2, 1)
        assert (folder / result["zip"]).is_file()

    scenario(body, folder=folder)


def test_report_create_and_run_agree(tmp_path, capsys):
    folder = write_session(tmp_path / "sessions" / "2026-10-14_090000_staging_android", preset="x")
    (folder / session.DEVICE_LOG).write_bytes(line(message="d1"))
    created = report.create(folder, tmp_path / "presets")
    assert (created.requests, created.failed, created.device_lines, created.app_lines) == (0, 0, 1, 0)
    assert created.log_lines == 1 and created.zip == folder / f"{folder.name}-report.zip"
    capsys.readouterr()
    assert report.run(folder.name, tmp_path / "sessions", tmp_path / "presets") == 0
    assert f"Report written: {created.zip}" in capsys.readouterr().out
    with pytest.raises(report.Failure, match="no meta.json|meta.json"):
        report.create(tmp_path, tmp_path / "presets")


def test_reveal_opens_only_the_file_the_last_report_wrote(tmp_path, monkeypatch):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")
    zip_file = folder / "r.zip"
    zip_file.write_bytes(b"zip")
    monkeypatch.setattr(report, "create",
                        lambda *a, **k: report.Created(zip_file, 1, 0, 0, 0, 0, 0, False))
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(wiretrace_ui.subprocess, "run", run)

    async def body(ui, client, tctx):
        nothing = await client.fetch("/api/report/reveal", "POST")
        assert nothing.code == 404 and calls == []
        await client.json("/api/report", method="POST")
        evil = json.dumps({"path": "/etc/passwd", "zip": "../../x", "cmd": "rm -rf /"})
        assert await client.json("/api/report/reveal", method="POST", body=evil) == {"ok": True}
        assert calls == [["open", "-R", str(zip_file)]]
        zip_file.unlink()
        assert (await client.fetch("/api/report/reveal", "POST")).code == 404
        assert len(calls) == 1

    scenario(body, folder=folder)


@pytest.mark.parametrize("failure", [OSError("no open"), subprocess.CalledProcessError(1, "open"),
                                     subprocess.TimeoutExpired("open", 10), 1])
def test_reveal_that_fails_is_an_error(tmp_path, monkeypatch, failure):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")
    zip_file = folder / "r.zip"
    zip_file.write_bytes(b"zip")
    monkeypatch.setattr(report, "create", lambda *a, **k: report.Created(zip_file, 1, 0, 0, 0, 0, 0, False))

    def run(cmd, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return subprocess.CompletedProcess(cmd, failure)

    monkeypatch.setattr(wiretrace_ui.subprocess, "run", run)

    async def body(ui, client, tctx):
        await client.json("/api/report", method="POST")
        response = await client.fetch("/api/report/reveal", "POST")
        assert response.code == 500 and json.loads(response.body)["error"] == "Could not open Finder."

    scenario(body, folder=folder)


# WebSocket

async def read_until(socket_, predicate, timeout=5.0):
    """Messages until one satisfies `predicate`; returns all read."""
    seen = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(socket_.read_message(), timeout)
        if raw is None:
            break
        seen.append(json.loads(raw))
        if predicate(seen[-1]):
            return seen
    raise AssertionError(f"not delivered: {seen}")


def test_a_new_flow_arrives_on_the_socket_in_a_batch(tmp_path):
    async def body(ui, client, tctx):
        socket_ = await client.socket()
        first, second = make_flow("/a"), make_flow("/b", status=None)
        started = time.monotonic()
        ui.request(first)
        ui.request(second)
        ui.response(first)
        message = (await read_until(socket_, lambda m: m["type"] == "flows"))[-1]
        assert time.monotonic() - started >= 0.05
        # One batch: both flows once each, the first with its response.
        assert [(f["id"], f["status"]) for f in message["flows"]] == [(first.id, 200), (second.id, None)]
        second.response = make_flow().response
        ui.response(second)
        again = (await read_until(socket_, lambda m: m["type"] == "flows"))[-1]
        assert [(f["id"], f["status"]) for f in again["flows"]] == [(second.id, 200)]
        socket_.close()

    scenario(body)


def test_the_receiver_and_untracked_flows_are_never_sent(tmp_path):
    async def body(ui, client, tctx):
        socket_ = await client.socket()
        ui.request(make_flow("/log", "POST", host="qa-logs.internal"))
        visible = make_flow("/seen")
        ui.request(visible)
        message = (await read_until(socket_, lambda m: m["type"] == "flows"))[-1]
        assert [f["id"] for f in message["flows"]] == [visible.id]
        socket_.close()

    scenario(body)


def test_new_log_lines_arrive_on_the_socket(tmp_path):
    folder = write_session(tmp_path)

    async def body(ui, client, tctx):
        socket_ = await client.socket()
        with open(folder / session.DEVICE_LOG, "ab") as f:
            f.write(line(level="E", message="crash"))
        with open(folder / session.APP_LOG, "ab") as f:
            f.write(line(message="hello") + b"not json\n")
        got = []
        while len(got) < 3:
            got += (await read_until(socket_, lambda m: m["type"] == "logs"))[-1]["lines"]
        assert sorted((l["source"], l["message"]) for l in got) == [
            ("app", "hello"), ("app", "not json"), ("device", "crash")]
        socket_.close()

    scenario(body, folder=folder)


def test_a_rules_save_and_a_report_send_the_state(tmp_path, monkeypatch):
    folder = write_session(tmp_path / "2026-10-14_090000_staging_android")
    monkeypatch.setattr(report, "create", lambda *a, **k: report.Created(folder / "r.zip", 1, 0, 0, 0, 0, 0, False))

    async def body(ui, client, tctx):
        socket_ = await client.socket()
        assert (await put_rules(client, [rule()])).code == 200
        state = (await read_until(socket_, lambda m: m["type"] == "state"))[-1]["state"]
        assert state["rules_on"] == 1
        await client.json("/api/report", method="POST")
        assert (await read_until(socket_, lambda m: m["type"] == "state"))[-1]["state"]["preset"] == "staging"
        socket_.close()

    rules_scenario(body, tmp_path, qa_ui_session_dir=str(folder))


def test_rule_counters_reach_the_page_over_the_socket(tmp_path):
    async def body(ui, client, tctx):
        qa = tctx.master.addons.get("qatools")
        assert (await put_rules(client, [rule()])).code == 200
        socket_ = await client.socket()
        while not ui.hub.clients:
            await asyncio.sleep(0.01)
        await qa.request(make_flow("/api/v1/orders", method="POST"))
        message = (await read_until(
            socket_, lambda m: m["type"] == "rules" and m["stats"]["orders500"]["matches"]))[-1]
        assert message["stats"]["orders500"]["applied"] == 1 and message["error"] is None
        socket_.close()

    rules_scenario(body, tmp_path)


def test_a_closed_socket_is_forgotten_and_nothing_is_kept_for_nobody():
    async def body(ui, client, tctx):
        ui.request(make_flow("/early"))
        assert not ui.hub._dirty and not ui.hub._lines
        socket_ = await client.socket()
        while not ui.hub.clients:
            await asyncio.sleep(0.01)
        socket_.close()
        while ui.hub.clients:
            await asyncio.sleep(0.01)
        ui.request(make_flow("/late"))
        await settle(ui)
        assert not ui.hub._dirty

    scenario(body)


def test_the_page_can_connect_again_after_a_drop_and_reload_everything(tmp_path):
    async def body(ui, client, tctx):
        flow = make_flow("/kept")
        ui.request(flow)
        first = await client.socket()
        first.close()
        second = await client.socket()
        assert [f["id"] for f in (await client.json("/api/flows"))["flows"]] == [flow.id]
        second.close()

    scenario(body)


def test_done_closes_the_sockets_and_the_port():
    async def main():
        ui = wiretrace_ui.WiretraceUI()
        with taddons.context(qa_tools.QATools(), ui) as tctx:
            tctx.configure(ui, qa_ui_port=0, qa_ui_open_browser=False)
            await ui.running()
            port = ui.port
            socket_ = await Client(ui).socket()
            await ui.done()
            assert await socket_.read_message() is None
            with pytest.raises(OSError):
                socket.create_connection(("127.0.0.1", port), timeout=1).close()

    asyncio.run(main())


# Previous sessions, search, replay (spec 008 slice D)

LIVE = "2026-10-15_100000_staging_android"
OLD = "2026-10-14_090000_staging_ios"
UNLISTED = "2026-10-13_090000_staging_ios"


def write_flows(path: Path, flows) -> None:
    from mitmproxy import io
    with open(path, "wb") as f:
        writer = io.FlowWriter(f)
        for flow in flows:
            writer.add(flow)


def tree(folder: Path) -> dict:
    return {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in folder.iterdir()}


@pytest.fixture
def sessions(tmp_path):
    """A live session folder and a previous one with two flows and one device log line."""
    root = tmp_path / "sessions"
    live = write_session(root / LIVE)
    old = write_session(root / OLD, target="ios", started_at="2026-10-14T09:00:00+07:00",
                        ended_at="2026-10-14T09:30:00+07:00", status="stopped", requests=2,
                        device_log_lines=1, app_log_lines=0)
    flows = [make_flow("/api/v1/old-a"), make_flow("/api/v1/old-b", status=500)]
    write_flows(old / session.FLOWS, flows)
    (old / session.DEVICE_LOG).write_bytes(line(message="old line"))
    return live, old, flows


def test_sessions_lists_the_folders_newest_first_with_counts_from_meta(sessions):
    live, old, _ = sessions
    root = live.parent
    (root / "2026-10-12_090000_staging_ios").symlink_to(old)
    (root / "notes").mkdir()
    (root / "2026-10-11_090000_staging_android").write_text("a file")

    async def body(ui, client, tctx):
        ui.request(make_flow("/live"))
        listed = (await client.json("/api/sessions"))["sessions"]
        assert [s["name"] for s in listed] == [LIVE, OLD]
        assert listed[0]["live"] is True and listed[0]["requests"] == 1
        assert listed[1] == {"name": OLD, "preset": "staging", "target": "ios", "started_at": 1791943200.0,
                             "ended_at": 1791945000.0, "status": "stopped", "requests": 2, "device_lines": 1,
                             "app_lines": 0, "live": False}

    scenario(body, folder=live)


def test_a_session_without_meta_is_listed_by_its_name(sessions):
    live, _, _ = sessions
    (live.parent / UNLISTED).mkdir()

    async def body(ui, client, tctx):
        entry = (await client.json("/api/sessions"))["sessions"][-1]
        assert entry["name"] == UNLISTED and entry["requests"] is None and entry["started_at"]

    scenario(body, folder=live)


def test_a_previous_session_opens_read_only_and_the_live_capture_goes_on(sessions):
    live, old, old_flows = sessions
    before = tree(old)

    async def body(ui, client, tctx):
        assert await client.json("/api/view", method="POST", body={"session": OLD}) == {
            "viewing": OLD, "cut_off": False, "requests": 2}
        state = await client.json("/api/state")
        assert (state["viewing"], state["viewing_cut_off"]) == (OLD, False)
        listed = await client.json(f"/api/flows?session={OLD}")
        assert [f["path"] for f in listed["flows"]] == ["/api/v1/old-a", "/api/v1/old-b"]
        assert (await client.json(f"/api/logs?source=device&session={OLD}"))["lines"][0]["message"] == "old line"
        assert (await client.json(f"/api/flows/{old_flows[1].id}?session={OLD}"))["summary"]["status"] == 500
        assert (await client.json(f"/api/filter?expr=~c%20500&session={OLD}"))["ids"] == [old_flows[1].id]
        # The live session goes on, and answers without ?session= or with its own name.
        new = make_flow("/live-during-view")
        ui.request(new)
        assert [f["id"] for f in (await client.json("/api/flows"))["flows"]] == [new.id]
        assert [f["id"] for f in (await client.json(f"/api/flows?session={LIVE}"))["flows"]] == [new.id]
        assert (await client.fetch(f"/api/flows/{old_flows[0].id}")).code == 404

        assert await client.json("/api/view", method="POST", body={"session": None}) == {"viewing": None}
        assert (await client.json("/api/state"))["viewing"] is None
        closed = await client.fetch(f"/api/flows?session={OLD}")
        assert closed.code == 409 and "Previous sessions" in json.loads(closed.body)["error"]

    scenario(body, folder=live)
    assert tree(old) == before


@pytest.mark.parametrize("name, code", [
    ("nope", 400), (5, 400), ("../" + OLD, 400), (OLD + "/..", 400), (UNLISTED, 404),
    ("2026-10-12_090000_staging_ios", 404),
])
def test_only_a_listed_session_name_opens(sessions, name, code):
    live, old, _ = sessions
    (live.parent / "2026-10-12_090000_staging_ios").symlink_to(old)

    async def body(ui, client, tctx):
        response = await client.fetch("/api/view", "POST", body={"session": name})
        assert response.code == code and json.loads(response.body)["error"]
        assert ui.viewed is None

    scenario(body, folder=live)


def test_view_needs_a_session_key_and_read_endpoints_check_the_name(sessions):
    live, _, _ = sessions

    async def body(ui, client, tctx):
        assert (await client.fetch("/api/view", "POST", body={})).code == 400
        assert (await client.fetch("/api/view", "POST", body="not json")).code == 400
        for path in ("/api/flows", "/api/flows/x", "/api/logs?source=app", "/api/filter?expr=~a", "/api/search?q=abc"):
            sep = "&" if "?" in path else "?"
            assert (await client.fetch(f"{path}{sep}session=..%2F{OLD}")).code == 400, path
            assert (await client.fetch(f"{path}{sep}session={OLD}")).code == 409, path

    scenario(body, folder=live)


def test_symlinked_files_in_a_session_are_not_read(sessions):
    live, old, _ = sessions
    linked = write_session(live.parent / UNLISTED)
    (linked / session.FLOWS).symlink_to(old / session.FLOWS)
    (linked / session.DEVICE_LOG).symlink_to(old / session.DEVICE_LOG)

    async def body(ui, client, tctx):
        assert (await client.json("/api/view", method="POST", body={"session": UNLISTED}))["requests"] == 0
        assert (await client.json(f"/api/logs?source=device&session={UNLISTED}"))["lines"] == []

    scenario(body, folder=live)


def test_a_cut_off_flows_file_is_read_as_far_as_it_goes(sessions):
    live, old, _ = sessions
    flows = [make_flow(f"/api/v1/n{i}") for i in range(3)]
    write_flows(old / session.FLOWS, flows)
    data = (old / session.FLOWS).read_bytes()
    (old / session.FLOWS).write_bytes(data[:-40])

    async def body(ui, client, tctx):
        opened = await client.json("/api/view", method="POST", body={"session": OLD})
        assert opened["cut_off"] is True and opened["requests"] == 2
        assert (await client.json("/api/state"))["viewing_cut_off"] is True

    scenario(body, folder=live)


def test_a_previous_session_keeps_only_the_newest_flows(sessions):
    _, old, _ = sessions
    write_flows(old / session.FLOWS, [make_flow(f"/api/v1/n{i}") for i in range(5)])
    kept, cut_off = wiretrace_ui.read_flows_file(old / session.FLOWS, cap=3)
    assert [f.request.path for f in kept.values()] == ["/api/v1/n2", "/api/v1/n3", "/api/v1/n4"] and not cut_off


def test_the_last_view_request_wins(sessions, monkeypatch):
    live, _, _ = sessions
    release = threading.Event()
    real = wiretrace_ui.read_session

    def slow(folder):
        assert release.wait(10)
        return real(folder)

    monkeypatch.setattr(wiretrace_ui, "read_session", slow)

    async def body(ui, client, tctx):
        opening = asyncio.ensure_future(client.fetch("/api/view", "POST", body={"session": OLD}))
        await asyncio.sleep(0.2)
        assert await client.json("/api/view", method="POST", body={"session": None}) == {"viewing": None}
        release.set()
        assert (await opening).code == 409
        assert ui.viewed is None

    scenario(body, folder=live)


def searchable():
    header = make_flow("/api/v1/a")
    header.request.headers["X-Trace"] = "Needle-Header"
    body = make_flow("/api/v1/b", body=gzip.compress(b'{"note": "the needle-body is here"}'))
    body.response.headers["Content-Encoding"] = "gzip"
    sent = make_flow("/api/v1/c", method="POST")
    sent.request.content = b'{"q": "needle-request"}'
    other = make_flow("/api/v1/d")
    return [header, body, sent, other]


def test_search_matches_headers_and_bodies_ignoring_case(monkeypatch):
    monkeypatch.setattr(wiretrace_ui, "SEARCH_CHUNK", 1)

    async def body(ui, client, tctx):
        flows = searchable()
        for flow in flows:
            ui.request(flow)
        search = lambda q: client.json(f"/api/search?q={quote(q)}")  # noqa: E731
        assert (await search("needle-HEADER"))["ids"] == [flows[0].id]
        assert (await search("NEEDLE-BODY"))["ids"] == [flows[1].id]
        assert (await search("needle-request"))["ids"] == [flows[2].id]
        assert (await search("needle"))["ids"] == [f.id for f in flows[:3]]
        assert (await search("/api/v1/d"))["ids"] == [flows[3].id]
        for short in ("ab", "  ab  ", "x" * 201):
            assert (await client.fetch(f"/api/search?q={quote(short)}")).code == 400

    scenario(body)


def test_search_in_an_opened_session(sessions):
    live, old, _ = sessions
    write_flows(old / session.FLOWS, searchable())

    async def body(ui, client, tctx):
        await client.json("/api/view", method="POST", body={"session": OLD})
        found = await client.json(f"/api/search?q=needle-body&session={OLD}")
        assert len(found["ids"]) == 1
        assert (await client.json("/api/search?q=needle-body"))["ids"] == []

    scenario(body, folder=live)


def replay_scenario(body, **kwargs):
    from mitmproxy.addons import clientplayback
    scenario(body, extra=(clientplayback.ClientPlayback(),), **kwargs)


def finished(flow):
    """tflow's flows are live, like a request still in progress."""
    flow.live = False
    return flow


def test_replay_sends_a_copy_marked_as_a_replay():
    async def body(ui, client, tctx):
        original = finished(make_flow("/api/v1/orders", "POST", comment="request-id: r1; fault: status 500"))
        original.marked = ":warning:"
        ui.request(original)
        result = await client.json(f"/api/flows/{original.id}/replay", method="POST")
        copy = ui.hub.flows[result["id"]]
        assert copy is not original and copy.id != original.id
        assert (copy.comment, copy.marked, copy.is_replay, copy.response) == (f"replay: {original.id}", "", "request", None)
        assert (original.is_replay, original.response.status_code, original.comment) == (
            None, 200, "request-id: r1; fault: status 500")
        listed = {f["id"]: f for f in (await client.json("/api/flows"))["flows"]}
        assert listed[copy.id]["replay_of"] == original.id and listed[original.id]["replay_of"] is None

    replay_scenario(body)


def test_replay_refuses_what_mitmproxy_cannot_replay(sessions):
    live, _, _ = sessions

    async def body(ui, client, tctx):
        assert (await client.fetch("/api/flows/unknown/replay", "POST")).code == 404
        running = make_flow()
        ui.request(running)
        assert (await client.fetch(f"/api/flows/{running.id}/replay", "POST")).code == 409
        socket_flow = finished(tflow.twebsocketflow())
        ui.websocket_start(socket_flow)
        assert (await client.fetch(f"/api/flows/{socket_flow.id}/replay", "POST")).code == 400
        empty = finished(make_flow())
        empty.request.content = None
        ui.request(empty)
        assert (await client.fetch(f"/api/flows/{empty.id}/replay", "POST")).code == 400

        done = finished(make_flow())
        ui.request(done)
        await client.json("/api/view", method="POST", body={"session": OLD})
        viewing = await client.fetch(f"/api/flows/{done.id}/replay", "POST")
        assert viewing.code == 409 and "previous session" in json.loads(viewing.body)["error"]
        assert len(ui.hub.flows) == 4

    replay_scenario(body, folder=live)


def test_a_report_for_a_viewed_session_is_written_in_its_folder(sessions, monkeypatch):
    live, old, _ = sessions
    calls = []

    def create(folder, presets_dir, now=None):
        calls.append(folder)
        return report.Created(zip=folder / "r.zip", requests=2, failed=1, mocked=0, faulted=0,
                              device_lines=1, app_lines=0, cut_off=False)

    monkeypatch.setattr(report, "create", create)

    async def body(ui, client, tctx):
        assert (await client.json("/api/report", method="POST", body={"session": OLD}))["requests"] == 2
        await client.json("/api/report", method="POST", body={"session": LIVE})
        await client.json("/api/report", method="POST", body={})
        assert (await client.fetch("/api/report", "POST", body={"session": UNLISTED})).code == 404
        assert (await client.fetch("/api/report", "POST", body={"session": "../x"})).code == 404
        assert (await client.fetch("/api/report", "POST", body={"session": 5})).code == 400
        assert ui.last_report == live.resolve() / "r.zip"

    scenario(body, folder=live)
    assert calls == [old.resolve(), live.resolve(), live.resolve()]


# Privacy (Gate C)

def test_nothing_about_traffic_or_logs_reaches_the_terminal(tmp_path, capsys, caplog):
    folder = write_session(tmp_path)
    (folder / session.DEVICE_LOG).write_bytes(line(message="SECRET-LOG-LINE"))

    async def body(ui, client, tctx):
        flow = make_flow("/api/v1/secret-path?token=SECRET-QUERY", comment="request-id: SECRET-ID")
        flow.request.headers["Authorization"] = "Bearer SECRET-HEADER"
        ui.request(flow)
        ui.response(flow)
        socket_ = await client.socket()
        await settle(ui)
        await client.json(f"/api/flows/{flow.id}")
        await client.fetch("/api/filter?expr=~u%20SECRET-FILTER")
        await client.fetch(f"/api/nothing?token={ui.token}")
        await client.fetch("/api/flows/SECRET-MISSING")
        await client.fetch("/api/search?q=SECRET-SEARCH")
        await client.fetch("/api/search?q=SECRET-SEARCH&session=SECRET-SESSION")
        await client.fetch("/api/view", "POST", body={"session": "SECRET-SESSION"})
        await client.fetch("/api/report", "POST", body={"session": "SECRET-SESSION"})
        await client.fetch("/api/flows/SECRET-REPLAY/replay", "POST")
        socket_.close()

    with caplog.at_level(logging.DEBUG):
        scenario(body, folder=folder)
    out = capsys.readouterr()
    everything = out.out + out.err + caplog.text
    for word in ("SECRET",):
        assert word not in everything
    assert out.out.count("\n") == 1


def test_a_failing_request_is_logged_by_type_only_and_a_404_not_at_all(caplog):
    async def body(ui, client, tctx):
        assert (await client.fetch("/favicon.ico")).code == 404
        assert caplog.text == ""
        ui.state = mock.Mock(side_effect=RuntimeError("SECRET detail /api/state?token=SECRET"))
        assert (await client.fetch("/api/state")).code == 500

    scenario(body)
    assert "RuntimeError" in caplog.text and "SECRET" not in caplog.text


def test_a_hook_that_fails_never_breaks_the_capture(caplog):
    ui = wiretrace_ui.WiretraceUI()
    ui.hub.track = mock.Mock(side_effect=RuntimeError("SECRET detail"))
    ui.request(make_flow())
    assert "SECRET" not in caplog.text and "RuntimeError" in caplog.text


# Real mitmdump, built from the launcher's command

def wait_for(condition, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


def free_ports(count: int) -> list[int]:
    """Distinct ports free on IPv4 and IPv6 (mitmproxy listens on "::"), chosen while all probes are open."""
    probes = [socket.socket(socket.AF_INET6) for _ in range(count)]
    try:
        for probe in probes:
            probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            probe.bind(("::", 0))
        return [probe.getsockname()[1] for probe in probes]
    finally:
        for probe in probes:
            probe.close()


class _Hello(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"hello": "world"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")
@pytest.mark.parametrize("default_filter", ["~u hello", None])
def test_real_mitmdump_with_the_launchers_command(tmp_path, default_filter):
    origin = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hello)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    folder = write_session(tmp_path / "sessions" / "2026-10-14_090000_staging_android", mode="proxy")
    (folder / session.DEVICE_LOG).write_bytes(line(source="android", level="I", message="from the device"))
    proxy_port, ui_port = free_ports(2)
    preset = Preset(name="staging", api_hosts=("127.0.0.1",), default_filter=default_filter)
    cmd = start.build_command(preset, "proxy", "wiretrace", folder / session.FLOWS, VENV_BIN, proxy_port,
                              tmp_path / "wiretrace", ui_port)
    cmd[cmd.index("qa_ui_open_browser=true")] = "qa_ui_open_browser=false"
    process = subprocess.Popen(cmd, cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        output: list[str] = []
        threading.Thread(target=lambda: output.extend(process.stdout), daemon=True).start()
        wait_for(lambda: any(l.startswith("Wiretrace UI:") for l in output) or process.poll() is not None, timeout=60)
        time.sleep(0.2)
        assert any(l.startswith("Wiretrace UI:") for l in output), "".join(output)
        [link] = [l.strip() for l in output if l.startswith("Wiretrace UI:")]
        match = re.fullmatch(rf"Wiretrace UI: http://127\.0\.0\.1:{ui_port}/\?token=([\w-]{{43}})", link)
        assert match, link
        token = match.group(1)
        assert token not in " ".join(cmd)

        def get(path, cookie=True, host=None):
            conn = http.client.HTTPConnection("127.0.0.1", ui_port, timeout=10)
            headers = {"Cookie": f"wiretrace_ui={token}"} if cookie else {}
            if host:
                headers["Host"] = host
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()

        assert get("/", cookie=False)[0] == 403
        assert get("/api/state", host="evil.example")[0] == 403
        status, body = get("/api/state")
        state = json.loads(body)
        assert status == 200 and state["preset"] == "staging" and state["default_filter"] == (default_filter or "")
        assert state["wireguard_conf"] is None and state["mode"] == "proxy"
        assert state["proxy_port"] == proxy_port

        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=10)
        conn.request("GET", f"http://127.0.0.1:{origin.server_port}/hello", headers={"X-Request-ID": "req-9"})
        assert conn.getresponse().read() == b'{"hello": "world"}'
        conn.close()
        deadline = time.monotonic() + 15
        flows, lines = [], []
        while time.monotonic() < deadline and not (flows and lines):
            flows = json.loads(get("/api/flows")[1])["flows"]
            lines = json.loads(get("/api/logs?source=device")[1])["lines"]
            time.sleep(0.1)
        assert [(f["path"], f["status"], f["request_id"]) for f in flows] == [("/hello", 200, "req-9")]
        assert [l["message"] for l in lines] == ["from the device"]
        assert isinstance(json.loads(get("/api/state")[1])["device_seen_at"], float)
        assert get(f"/api/flows/{flows[0]['id']}")[0] == 200
        assert get("/")[0] == 200

        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=60)
        time.sleep(0.2)
        printed = "".join(l for l in output if not l.startswith("Wiretrace UI:"))
        assert token not in printed and "hello" not in printed and "req-9" not in printed
        assert "from the device" not in printed
    finally:
        origin.shutdown()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def test_list_mocks_stops_at_the_cap_and_skips_a_symlinked_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(wiretrace_ui, "MAX_MOCK_FILES", 3)
    root = tmp_path / "mocks"
    (root / "keep").mkdir(parents=True)
    for name in ("c.json", "a.json", "b.json", "d.json"):
        (root / "keep" / name).write_text("{}")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text("{}")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    found = wiretrace_ui.list_mocks(str(root))
    assert found == sorted(found) and len(found) == 3
    assert all(not name.startswith("linked/") and "secret" not in name for name in found)


def test_take_ui_token_accepts_only_a_32_byte_urlsafe_token(monkeypatch):
    import secrets
    good = secrets.token_urlsafe(32)
    monkeypatch.setenv("WIRETRACE_UI_TOKEN", good)
    assert wiretrace_ui.take_ui_token() == good
    assert "WIRETRACE_UI_TOKEN" not in os.environ
    monkeypatch.setenv("WIRETRACE_UI_TOKEN", "a" * 43)
    assert wiretrace_ui.take_ui_token() == "a" * 43
    for bad in ("short", "a" * 42, "a" * 44, "a" * 42 + "+", "a" * 42 + "/", "a" * 42 + "="):
        monkeypatch.setenv("WIRETRACE_UI_TOKEN", bad)
        assert wiretrace_ui.take_ui_token() is None
        assert "WIRETRACE_UI_TOKEN" not in os.environ
    assert wiretrace_ui.take_ui_token() is None


def test_running_uses_the_launcher_token_and_drops_it_from_the_environment(monkeypatch):
    import secrets
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("WIRETRACE_UI_TOKEN", token)

    async def body(ui, client, tctx):
        assert ui.token == token
        assert "WIRETRACE_UI_TOKEN" not in os.environ

    scenario(body)


def test_status_file_matches_the_window_counts_and_is_removed(tmp_path):
    from types import SimpleNamespace
    folder = write_session(tmp_path / "sess")
    (folder / session.DEVICE_STATUS).write_text(json.dumps({
        "state": "streaming", "message": "streaming", "source": "adb logcat",
        "app": "com.example.app", "model": "Pixel 8", "os": "Android 15",
        "updated_at": "2026-10-14T09:00:01+07:00",
    }))
    failed = make_flow("/boom", status=500)
    refused = tflow.tflow(err=True)
    ok = make_flow("/ok", status=200)
    failed.response.timestamp_end = 10
    refused.error.timestamp = 20
    seen = {}

    async def body(ui, client, tctx):
        live = ui.qatools()
        live._rules = qa_tools.Rules(rules=(SimpleNamespace(enabled=True), SimpleNamespace(enabled=False)))
        ui.device_file.poll()
        ui.hub.track(ok)
        ui.hub.track(failed)
        ui.hub.track(refused)
        ui.maybe_write_status(1_000.0)
        path = folder / session.STATUS
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        seen["data"] = data
        seen["mode"] = path.stat().st_mode & 0o777
        seen["raw"] = raw
        seen["token"] = ui.token
        assert data["errors"] == 2 and data["last_error"] == refused.id
        assert data["requests"] == ui.state()["flow_count"] == 3
        assert data["rules_on"] == ui.state()["rules_on"] == 1
        assert data["device_state"] == "streaming" and data["device_model"] == "Pixel 8"
        ui.hub.track(make_flow("/later", status=404))
        ui.maybe_write_status(1_000.5)
        assert json.loads(path.read_text())["errors"] == 2
        ui.maybe_write_status(1_001.0)
        later = json.loads(path.read_text())
        assert later["errors"] == 3 and later["updated_at"] == 1_001.0
        ui.maybe_write_status(1_002.0)
        assert json.loads(path.read_text())["updated_at"] == 1_001.0
        ui.maybe_write_status(1_003.0)
        assert json.loads(path.read_text())["updated_at"] == 1_003.0

    scenario(body, folder=folder)
    assert not (folder / session.STATUS).exists()
    assert not (folder / (session.STATUS + ".tmp")).exists()
    assert set(seen["data"]) == set(wiretrace_ui.STATUS_KEYS)
    assert seen["mode"] == 0o600
    raw = seen["raw"]
    assert seen["token"] not in raw and "api.example.com" not in raw and "/boom" not in raw
    assert "authorization" not in raw.lower() and "Bearer" not in raw


def test_a_flow_in_progress_is_not_an_error_and_a_400_is():
    assert wiretrace_ui.is_error_flow(make_flow(status=400))
    assert wiretrace_ui.is_error_flow(make_flow(status=500))
    assert wiretrace_ui.is_error_flow(tflow.tflow(err=True))
    assert not wiretrace_ui.is_error_flow(make_flow(status=200))
    assert not wiretrace_ui.is_error_flow(make_flow(status=399))
    assert not wiretrace_ui.is_error_flow(tflow.tflow(resp=False))


# The bug report form (spec 012)

FORM_SECRETS = ("fake-auth-value", "fake-query-token", "fake-body-token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln")
PNG_BYTES = screenshot.PNG + b"fake image"


def form_session(folder: Path, **meta) -> tuple[Path, Any]:
    """A session folder with a failed request carrying secrets, another request, and a device log line."""
    write_session(folder, preset="example", **meta)
    chosen = make_flow("/api/v1/orders?token=fake-query-token", method="POST", status=500,
                       body=b'{"error": "ORDER_FAILED", "token": "fake-body-token"}')
    chosen.request.headers["Authorization"] = "Bearer fake-auth-value"
    other = make_flow("/api/v1/profile")
    for f, offset in ((chosen, 0), (other, 2)):
        f.request.timestamp_start = 1_791_900_000.0 + offset
        f.response.timestamp_end = f.request.timestamp_start + 0.5
    write_flows(folder / session.FLOWS, [chosen, other])
    (folder / session.DEVICE_LOG).write_bytes(line(ts=1_791_900_001.0, level="E", tag="Net",
                                                   message=f"auth {FORM_SECRETS[3]}.sig"))
    return folder, chosen


def no_device_commands(monkeypatch) -> list:
    """Screenshot availability and capture never run a real tool in these tests."""
    calls = []
    monkeypatch.setattr(screenshot, "availability", lambda target, previous=False: (
        calls.append(("availability", target, previous)) or (("off", screenshot.PREVIOUS) if previous else ("available", None))))
    return calls


def fake_capture(calls: list, name: str = "20261014-090000.png"):
    def capture(target, folder, now=None):
        calls.append((target, threading.current_thread() is threading.main_thread()))
        shots = folder / session.SCREENSHOTS
        shots.mkdir(mode=0o700, exist_ok=True)
        (shots / name).write_bytes(PNG_BYTES)
        return name
    return capture


def test_the_draft_of_a_live_request_is_masked_and_says_whether_screenshots_can_be_taken(tmp_path, monkeypatch):
    folder, chosen = form_session(tmp_path / LIVE)
    calls = no_device_commands(monkeypatch)

    async def body(ui, client, tctx):
        draft = await client.json(f"/api/report/draft?flow={chosen.id}&format=markdown&include=others,device,app")
        assert draft["title"] == "POST /api/v1/orders returns 500"
        assert draft["lead"]["request"] == "POST /api/v1/orders → 500" and draft["lead"]["session"] == LIVE
        assert draft["counts"] == {"others": 1, "device": 1, "app": 0}
        assert [f["kind"] for f in draft["files"]] == ["har", "device-log", "zip"]
        assert draft["screenshots"] == {"state": "available", "reason": None, "items": []}
        assert "Authorization" in draft["masked"]["headers"]
        jira = await client.json(f"/api/report/draft?flow={chosen.id}&format=jira")
        for text in (json.dumps(draft), json.dumps(jira)):
            assert not any(secret in text for secret in FORM_SECRETS)
        assert "h2. Failed request" in jira["description"]
        whole = await client.json("/api/report/draft")
        assert whole["lead"]["request"] is None and "1 failed request in session" in whole["title"]

    scenario(body, folder=folder)
    assert calls[0] == ("availability", "android", False)


@pytest.mark.parametrize("query, status", [
    ("flow=bad%20id", 400), ("format=html", 400), ("include=others,x", 400),
    ("flow=00000000-0000-0000-0000-000000000000", 404), ("session=not-a-name", 400), (f"session={UNLISTED}", 404)])
def test_a_draft_request_that_is_wrong_says_why(tmp_path, monkeypatch, query, status):
    folder, _ = form_session(tmp_path / LIVE)
    no_device_commands(monkeypatch)

    async def body(ui, client, tctx):
        response = await client.fetch(f"/api/report/draft?{query}")
        assert response.code == status and json.loads(response.body)["error"]

    scenario(body, folder=folder)


def test_without_a_session_folder_the_form_has_nothing_to_read():
    async def body(ui, client, tctx):
        assert (await client.fetch("/api/report/draft")).code == 409
        assert (await client.fetch("/api/report/file/har")).code == 409
        assert (await client.fetch("/api/report/screenshot", "POST")).code == 409

    scenario(body)


def test_downloads_are_attachments_built_in_memory_with_the_draft_sizes(tmp_path, monkeypatch):
    folder, chosen = form_session(tmp_path / LIVE)
    (folder / session.STATUS).write_text('{"v": 1}\n')
    no_device_commands(monkeypatch)
    before = tree(folder)

    async def body(ui, client, tctx):
        query = f"flow={chosen.id}&include=others,device,app"
        draft = await client.json(f"/api/report/draft?{query}")
        for item in draft["files"]:
            response = await client.fetch(f"/api/report/file/{item['kind']}?{query}")
            assert response.code == 200 and len(response.body) == item["size"]
            assert response.headers["Content-Disposition"] == f'attachment; filename="{item["name"]}"'
            assert response.headers["Cache-Control"] == "no-store"
            assert not any(secret.encode() in response.body for secret in FORM_SECRETS[:3])
            if item["kind"] == "zip":
                with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
                    names = archive.namelist()
                assert not any(n.endswith((session.FLOWS, session.STATUS)) for n in names)
        assert (await client.fetch(f"/api/report/file/app-log?{query}")).code == 404
        for kind in ("flows.mitm", "meta", "..%2Fmeta.json"):
            assert (await client.fetch(f"/api/report/file/{kind}?{query}")).code == 404

    scenario(body, folder=folder)
    # The window removes its own status file when it stops; the form wrote nothing.
    before.pop(session.STATUS)
    assert tree(folder) == before


def test_a_previous_session_is_reported_read_only_without_screenshots(sessions, monkeypatch):
    live, old, old_flows = sessions
    calls = no_device_commands(monkeypatch)
    captures = []
    monkeypatch.setattr(screenshot, "capture", fake_capture(captures))
    before = tree(old)

    async def body(ui, client, tctx):
        draft = await client.json(f"/api/report/draft?session={OLD}&flow={old_flows[1].id}")
        assert draft["title"] == "GET /api/v1/old-b returns 500" and draft["lead"]["session"] == OLD
        assert draft["screenshots"]["state"] == "off" and draft["screenshots"]["reason"] == screenshot.PREVIOUS
        assert (await client.fetch(f"/api/report/file/har?session={OLD}")).code == 200
        assert (await client.fetch("/api/report/screenshot", "POST", body={"session": OLD})).code == 409
        response = await client.fetch(f"/api/report/screenshot/20261014-090000.png?session={OLD}", "DELETE", mutate=True)
        assert response.code == 409

    scenario(body, folder=live)
    assert calls == [("availability", "", True)] and captures == []
    assert tree(old) == before


def test_a_screenshot_is_taken_in_a_worker_thread_shown_downloaded_and_removed(tmp_path, monkeypatch):
    folder, _ = form_session(tmp_path / LIVE)
    calls = []
    monkeypatch.setattr(screenshot, "capture", fake_capture(calls))

    async def body(ui, client, tctx):
        taken = await client.json("/api/report/screenshot", method="POST")
        assert taken["name"] == "20261014-090000.png"
        assert taken["screenshots"] == [{"name": "20261014-090000.png", "size": len(PNG_BYTES), "time": "09:00:00"}]
        shown = await client.fetch("/api/report/screenshot/20261014-090000.png")
        assert shown.code == 200 and shown.body == PNG_BYTES and shown.headers["Content-Type"] == "image/png"
        assert "Content-Disposition" not in shown.headers
        saved = await client.fetch("/api/report/screenshot/20261014-090000.png?download=1")
        assert saved.headers["Content-Disposition"] == f'attachment; filename="{LIVE}-screenshot-090000.png"'
        removed = await client.fetch("/api/report/screenshot/20261014-090000.png", "DELETE", mutate=True)
        assert removed.code == 200 and json.loads(removed.body) == {"screenshots": []}
        again = await client.fetch("/api/report/screenshot/20261014-090000.png", "DELETE", mutate=True)
        assert again.code == 404

    scenario(body, folder=folder)
    assert calls == [("android", False)]
    assert not ui_state_running(folder)


def ui_state_running(folder: Path) -> bool:
    return (folder / session.SCREENSHOTS / screenshot.TMP).exists()


@pytest.mark.parametrize("name", ["..%2Fmeta.json", "%2e%2e%2fmeta.json", "x.png", "20261014-000000.png",
                                  "20261014-090000.png%2F..%2F..%2Fmeta.json"])
def test_a_screenshot_name_that_is_not_listed_is_404(tmp_path, monkeypatch, name):
    folder, _ = form_session(tmp_path / LIVE)
    monkeypatch.setattr(screenshot, "capture", fake_capture([]))

    async def body(ui, client, tctx):
        await client.json("/api/report/screenshot", method="POST")
        assert (await client.fetch(f"/api/report/screenshot/{name}")).code == 404
        assert (await client.fetch(f"/api/report/screenshot/{name}", "DELETE", mutate=True)).code == 404
        assert (folder / session.META).is_file()

    scenario(body, folder=folder)


def test_two_captures_at_once_give_one_409(tmp_path, monkeypatch):
    folder, _ = form_session(tmp_path / LIVE)
    release, started = threading.Event(), threading.Event()
    inner = fake_capture([])

    def capture(target, session_folder, now=None):
        started.set()
        assert release.wait(10)
        return inner(target, session_folder, now)

    monkeypatch.setattr(screenshot, "capture", capture)

    async def body(ui, client, tctx):
        first = asyncio.ensure_future(client.fetch("/api/report/screenshot", "POST"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        second = await client.fetch("/api/report/screenshot", "POST")
        assert second.code == 409 and json.loads(second.body)["error"]
        release.set()
        assert (await first).code == 200 and not ui.screenshot_running

    scenario(body, folder=folder)


def test_a_failed_screenshot_says_why_and_the_form_keeps_working(tmp_path, monkeypatch):
    folder, chosen = form_session(tmp_path / LIVE)
    no_device_commands(monkeypatch)

    def capture(target, session_folder, now=None):
        raise screenshot.Unavailable("adb: device unauthorized")

    monkeypatch.setattr(screenshot, "capture", capture)

    async def body(ui, client, tctx):
        failed = await client.fetch("/api/report/screenshot", "POST")
        assert failed.code == 422 and json.loads(failed.body) == {"error": "adb: device unauthorized"}
        assert not ui.screenshot_running
        assert (await client.fetch(f"/api/report/draft?flow={chosen.id}")).code == 200

    scenario(body, folder=folder)


def test_nothing_captured_is_printed_or_logged(tmp_path, monkeypatch, caplog, capsys):
    folder, chosen = form_session(tmp_path / LIVE)
    no_device_commands(monkeypatch)
    monkeypatch.setattr(screenshot, "capture", fake_capture([]))
    caplog.set_level(logging.DEBUG)
    shown = []

    async def body(ui, client, tctx):
        draft = await client.json(f"/api/report/draft?flow={chosen.id}")
        shown.extend([draft["title"], draft["description"]])
        for kind in ("har", "device-log", "zip"):
            await client.fetch(f"/api/report/file/{kind}?flow={chosen.id}")
        await client.json("/api/report/screenshot", method="POST")
        await client.fetch("/api/report/screenshot/20261014-090000.png")

    scenario(body, folder=folder)
    printed = capsys.readouterr()
    output = caplog.text + printed.out + printed.err
    for text in ("ORDER_FAILED", "/api/v1/orders", "auth ***", "Steps to reproduce", *FORM_SECRETS):
        assert text not in output
    assert shown and "ORDER_FAILED" in shown[1]


# Switching the preset (spec 013)

SWITCH_PRESETS = {
    "staging": "name: staging\napi_hosts:\n  - api.example.com\napp:\n  android_package: com.example.app\n",
    "other": ("name: other\napi_hosts:\n  - other.example.com\n  - cdn.example.com\napp:\n  ios_process: Example\n"
              "default_filter: '~d other'\nredact:\n  headers: [X-Secret]\n"),
    "broken": "name: broken\napi_hosts: https://not-a-list\n",
}


def switch_session(tmp_path: Path, target: str = "android") -> tuple[Path, Path]:
    presets = tmp_path / "presets"
    presets.mkdir()
    for name, text in SWITCH_PRESETS.items():
        (presets / f"{name}.yaml").write_text(text)
    folder = write_session(tmp_path / "sessions" / f"2026-10-14_090000_staging_{target}", target=target)
    return presets, folder


def switch_scenario(body, tmp_path, target="android"):
    presets, folder = switch_session(tmp_path, target)

    async def wrapped(ui, client, tctx):
        ui.presets_dir = presets
        tctx.master.shutdown = mock.Mock()
        await body(ui, client, tctx, folder)

    scenario(wrapped, folder=folder)


def test_presets_lists_names_hosts_and_device_logs_for_this_target_and_nothing_else(tmp_path):
    async def body(ui, client, tctx, folder):
        listed = (await client.json("/api/presets"))["presets"]
        assert [p["name"] for p in listed] == ["broken", "other", "staging"]
        assert all(set(p) == {"name", "api_hosts", "device_logs", "app"} for p in listed)
        by_name = {p["name"]: p for p in listed}
        assert by_name["staging"] == {"name": "staging", "api_hosts": ["api.example.com"], "device_logs": True,
                                      "app": "com.example.app"}
        assert by_name["other"] == {"name": "other", "api_hosts": ["other.example.com", "cdn.example.com"],
                                    "device_logs": False, "app": None}
        assert by_name["broken"] == {"name": "broken", "api_hosts": [], "device_logs": False, "app": None}

    switch_scenario(body, tmp_path)


@pytest.mark.parametrize("target, logs", [("ios-sim", {"other": "Example"}), ("device", {})])
def test_presets_device_logs_follow_the_target(tmp_path, target, logs):
    async def body(ui, client, tctx, folder):
        listed = (await client.json("/api/presets"))["presets"]
        assert {p["name"]: p["app"] for p in listed if p["device_logs"]} == logs

    switch_scenario(body, tmp_path, target)


@pytest.mark.parametrize("name, message", [("nope", "Unknown preset 'nope'"), ("../etc", "Unknown preset '../etc'"),
                                           ("broken", "presets/broken.yaml: 'api_hosts' must be a non-empty list")])
def test_switching_to_a_preset_that_does_not_load_is_a_400_and_nothing_stops(tmp_path, name, message):
    async def body(ui, client, tctx, folder):
        response = await client.fetch("/api/preset", "POST", body={"name": name})
        assert response.code == 400 and json.loads(response.body)["error"].startswith(message)
        tctx.master.shutdown.assert_not_called()
        assert not (folder / session.SWITCH).exists() and ui.switching is None

    switch_scenario(body, tmp_path)


def test_switching_to_the_current_preset_does_nothing(tmp_path):
    async def body(ui, client, tctx, folder):
        response = await client.fetch("/api/preset", "POST", body={"name": "staging"})
        assert response.code == 204 and response.body == b""
        tctx.master.shutdown.assert_not_called()
        assert not (folder / session.SWITCH).exists()

    switch_scenario(body, tmp_path)


def test_switching_is_refused_while_a_previous_session_is_open(tmp_path):
    async def body(ui, client, tctx, folder):
        ui.viewed = wiretrace_ui.Store("2026-10-13_090000_staging_android", {}, {"device": [], "app": []})
        response = await client.fetch("/api/preset", "POST", body={"name": "other"})
        assert response.code == 409 and "previous session" in json.loads(response.body)["error"]
        tctx.master.shutdown.assert_not_called()
        assert not (folder / session.SWITCH).exists()

    switch_scenario(body, tmp_path)


def test_a_switch_writes_only_the_name_owner_only_then_shuts_mitmdump_down(tmp_path):
    async def body(ui, client, tctx, folder):
        response = await client.fetch("/api/preset", "POST", body={"name": "other"})
        assert response.code == 202 and json.loads(response.body) == {"switching": "other"}
        path = folder / session.SWITCH
        assert json.loads(path.read_text()) == {"name": "other"}
        assert (path.stat().st_mode & 0o777) == 0o600
        assert ui.token not in path.read_text()
        assert sorted(p.name for p in folder.iterdir()) == [session.SWITCH, session.META]
        tctx.master.shutdown.assert_called_once()

    switch_scenario(body, tmp_path)


def test_a_second_switch_is_a_409_and_there_is_one_file(tmp_path):
    async def body(ui, client, tctx, folder):
        first, second = await asyncio.gather(
            client.fetch("/api/preset", "POST", body={"name": "other"}),
            client.fetch("/api/preset", "POST", body={"name": "other"}))
        assert sorted([first.code, second.code]) == [202, 409]
        assert (await client.fetch("/api/preset", "POST", body={"name": "other"})).code == 409
        assert [p.name for p in folder.iterdir() if p.name.startswith(session.SWITCH)] == [session.SWITCH]
        tctx.master.shutdown.assert_called_once()

    switch_scenario(body, tmp_path)


def test_a_switch_file_left_on_disk_is_the_lock(tmp_path):
    async def body(ui, client, tctx, folder):
        (folder / session.SWITCH).write_text('{"name": "other"}')
        assert (await client.fetch("/api/preset", "POST", body={"name": "other"})).code == 409
        tctx.master.shutdown.assert_not_called()

    switch_scenario(body, tmp_path)


def test_a_switch_without_the_x_wiretrace_header_is_refused_and_writes_nothing(tmp_path):
    async def body(ui, client, tctx, folder):
        for headers in ({}, {"X-Wiretrace": "0"}):
            response = await client.fetch("/api/preset", "POST", mutate=False, headers=headers, body={"name": "other"})
            assert response.code == 403
        assert (await client.fetch("/api/preset", "POST", cookie="wrong", body={"name": "other"})).code == 403
        tctx.master.shutdown.assert_not_called()
        assert not (folder / session.SWITCH).exists()

    switch_scenario(body, tmp_path)


@pytest.mark.parametrize("sent", [{}, {"name": 3}, "not json", []])
def test_a_malformed_switch_body_is_a_400(tmp_path, sent):
    async def body(ui, client, tctx, folder):
        assert (await client.fetch("/api/preset", "POST", body=sent)).code == 400
        tctx.master.shutdown.assert_not_called()

    switch_scenario(body, tmp_path)


def test_the_switch_file_is_not_a_report_member(tmp_path):
    presets, folder = switch_session(tmp_path)
    (folder / session.FLOWS).write_bytes(b"")
    (folder / session.SWITCH).write_text('{"name": "other"}')
    (folder / session.APP_LOG).write_text('{"message": "app"}\n')
    created = report.create(folder, presets)
    with zipfile.ZipFile(created.zip) as archive:
        assert not [n for n in archive.namelist() if session.SWITCH in n]
