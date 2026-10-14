import asyncio
import http.client
import http.server
import inspect
import json
import logging
import os
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from ipaddress import IPv4Address
from pathlib import Path
from types import SimpleNamespace

import pytest
from mitmproxy import connection, dns, io, tls
from mitmproxy.proxy import server_hooks
from mitmproxy.test import taddons, tflow, tutils

from addons import app_logs
from cli import start
from cli.preset import Preset

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
HOST = "qa-logs.internal"
MAX_BODY = 1 << 20


def make_flow(body: bytes | str | None = b"", host: str = HOST, path: str = "/log", method: str = "POST"):
    flow = tflow.tflow()
    flow.request.host = host
    flow.request.headers["Host"] = host
    flow.request.path = path
    flow.request.method = method
    flow.request.content = body.encode() if isinstance(body, str) else body
    return flow


def scenario(body, log_file: Path | None = None):
    """Run `body(addon, tctx, file)` with the addon loaded; the log file is empty or `log_file`."""
    async def main():
        addon = app_logs.AppLogs()
        with taddons.context(addon) as tctx:
            tctx.configure(addon, qa_app_log_file=str(log_file) if log_file else "")
            result = body(addon, tctx)
            if inspect.isawaitable(result):
                await result
            addon.done()

    asyncio.run(main())


def stored(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def post(addon, body, **kwargs):
    flow = make_flow(body, **kwargs)
    addon.request(flow)
    return flow


# The receiver

def test_valid_object_is_stored_with_known_fields_only(tmp_path):
    path = tmp_path / "app.log.jsonl"
    payload = {"message": "Order list loaded", "level": "I", "tag": "Orders", "ts": "2026-10-14T09:30:12.481+07:00",
               "request_id": "6f1c", "extra": "dropped", "nested": {"a": 1}}

    async def body(addon, tctx):
        flow = post(addon, json.dumps(payload))
        assert flow.response.status_code == 204 and flow.response.content == b""
        assert "Content-Length" not in flow.response.headers

    scenario(body, path)
    [line] = stored(path)
    assert list(line) == ["ts", "received", "source", "level", "tag", "message", "request_id"]
    assert line["source"] == "app" and line["ts"] == payload["ts"]
    assert line["message"] == "Order list loaded" and line["request_id"] == "6f1c"
    assert line["received"] != line["ts"] and "extra" not in line and "nested" not in line


def test_absent_fields_are_omitted_and_ts_defaults_to_received(tmp_path):
    path = tmp_path / "app.log.jsonl"
    scenario(lambda addon, tctx: post(addon, '{"message": "hi"}'), path)
    [line] = stored(path)
    assert set(line) == {"ts", "received", "source", "message"} and line["ts"] == line["received"]


def test_array_of_three_stores_three_lines(tmp_path):
    path = tmp_path / "app.log.jsonl"
    batch = [{"message": f"m{i}", "level": "D"} for i in range(3)]

    async def body(addon, tctx):
        assert post(addon, json.dumps(batch)).response.status_code == 204

    scenario(body, path)
    assert [line["message"] for line in stored(path)] == ["m0", "m1", "m2"]
    assert len({line["received"] for line in stored(path)}) == 1


def test_array_with_one_bad_item_stores_nothing(tmp_path):
    path = tmp_path / "app.log.jsonl"
    batch = [{"message": "good"}, {"message": "good too"}, {"level": "I"}]

    async def body(addon, tctx):
        flow = post(addon, json.dumps(batch))
        assert flow.response.status_code == 400
        assert json.loads(flow.response.content) == {"error": "message is required and must be a string"}
        assert flow.response.headers["Content-Type"] == "application/json"

    scenario(body, path)
    assert not path.exists()


BAD_BODIES = {
    "not JSON": "{broken",
    "empty body": "",
    "string": '"just text"',
    "number": "42",
    "null": "null",
    "message missing": '{"level": "I"}',
    "message not a string": '{"message": 5}',
    "message null": '{"message": null}',
    "level not a string": '{"message": "m", "level": 3}',
    "tag too long": json.dumps({"message": "m", "tag": "t" * 65}),
    "ts too long": json.dumps({"message": "m", "ts": "2" * 65}),
    "request_id too long": json.dumps({"message": "m", "request_id": "r" * 129}),
    "request_id not a string": '{"message": "m", "request_id": 7}',
    "array with a non-object": '[{"message": "m"}, "x"]',
    "nested array": '[[{"message": "m"}]]',
    "1001 items": json.dumps([{"message": "m"}] * 1001),
}


@pytest.mark.parametrize("name", sorted(BAD_BODIES))
def test_bad_bodies_get_400_and_store_nothing(tmp_path, name):
    path = tmp_path / "app.log.jsonl"

    async def body(addon, tctx):
        flow = post(addon, BAD_BODIES[name])
        assert flow.response.status_code == 400
        assert list(json.loads(flow.response.content)) == ["error"]

    scenario(body, path)
    assert not path.exists()


def test_limits_are_inclusive(tmp_path):
    path = tmp_path / "app.log.jsonl"
    edge = {"message": "m", "level": "L" * 64, "tag": "t" * 64, "ts": "2" * 64, "request_id": "r" * 128}

    async def body(addon, tctx):
        assert post(addon, json.dumps(edge)).response.status_code == 204
        assert post(addon, json.dumps([{"message": "m"}] * 1000)).response.status_code == 204
        assert post(addon, "[]").response.status_code == 204

    scenario(body, path)
    assert len(stored(path)) == 1001


def test_body_size_limit(tmp_path):
    path = tmp_path / "app.log.jsonl"
    frame = json.dumps({"message": ""}).encode()
    exact = json.dumps({"message": "a" * (MAX_BODY - len(frame))}).encode()
    assert len(exact) == MAX_BODY

    async def body(addon, tctx):
        assert post(addon, exact).response.status_code == 204
        over = post(addon, exact + b" ")
        assert over.response.status_code == 413
        assert post(addon, b"x" * (MAX_BODY * 3)).response.status_code == 413

    scenario(body, path)
    assert len(stored(path)) == 1


@pytest.mark.parametrize("method, path, status", [
    ("GET", "/log", 405), ("PUT", "/log", 405), ("DELETE", "/log?x=1", 405), ("HEAD", "/log", 405),
    ("POST", "/other", 404), ("GET", "/", 404), ("POST", "/log/", 404), ("POST", "/logs", 404),
    ("DELETE", "/other", 404),
])
def test_other_paths_and_methods(tmp_path, method, path, status):
    log = tmp_path / "app.log.jsonl"

    async def body(addon, tctx):
        flow = post(addon, '{"message": "m"}', method=method, path=path)
        assert flow.response.status_code == status
        if status == 405:
            assert flow.response.headers["Allow"] == "POST"

    scenario(body, log)
    assert not log.exists()


def test_query_string_does_not_change_the_route(tmp_path):
    log = tmp_path / "app.log.jsonl"

    async def body(addon, tctx):
        assert post(addon, '{"message": "m"}', path="/log?v=1").response.status_code == 204

    scenario(body, log)
    assert len(stored(log)) == 1


def test_every_receiver_flow_is_answered_in_the_request_hook(tmp_path):
    async def body(addon, tctx):
        for host in (HOST, "QA-Logs.Internal", "qa-logs.internal."):
            for method, path, content in (("POST", "/log", '{"message": "m"}'), ("POST", "/log", "{"),
                                          ("GET", "/log", ""), ("POST", "/x", "")):
                flow = post(addon, content, host=host, method=method, path=path)
                assert flow.response is not None and flow.live and flow.error is None

    scenario(body, tmp_path / "app.log.jsonl")


@pytest.mark.parametrize("host", ["api.example.com", "qa-logs.internal.evil.io", "evilqa-logs.internal",
                                  "sub.qa-logs.internal", "192.0.2.10", "127.0.0.1"])
def test_other_hosts_are_untouched(tmp_path, host):
    log = tmp_path / "app.log.jsonl"

    async def body(addon, tctx):
        flow = post(addon, '{"message": "m"}', host=host)
        assert flow.response is None and flow.comment == "" and flow.marked == ""

    scenario(body, log)
    assert not log.exists()


def test_empty_option_answers_but_stores_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def body(addon, tctx):
        assert post(addon, '{"message": "m"}').response.status_code == 204
        assert post(addon, "{").response.status_code == 400

    scenario(body)
    assert list(tmp_path.iterdir()) == []


def test_unwritable_file_answers_500_and_counts_the_request(tmp_path):
    async def body(addon, tctx):
        flow = post(addon, '{"message": "m"}')
        assert flow.response.status_code == 500
        assert addon.stored == 0 and addon.rejected == 1

    scenario(body, tmp_path / "missing-folder" / "app.log.jsonl")


def test_batches_append_across_requests_and_file_opens_on_first_line(tmp_path):
    path = tmp_path / "app.log.jsonl"
    path.write_text('{"earlier": true}\n')

    async def body(addon, tctx):
        post(addon, '{"message": "one"}')
        # Flushed after every request: a reader sees the line before `done`.
        assert len(path.read_text().splitlines()) == 2
        post(addon, '{"message": "two"}')

    scenario(body, path)
    assert [line.get("message") for line in stored(path)] == [None, "one", "two"]

    never = tmp_path / "never.jsonl"
    scenario(lambda addon, tctx: post(addon, "{"), never)
    assert not never.exists()


# Addon log lines

def test_addon_log_lines_carry_counts_and_states_only(tmp_path, caplog):
    secret_text, secret_id = "SECRET-LOG-TEXT", "SECRET-REQUEST-ID"
    path = tmp_path / "SECRET-FOLDER" / "app.log.jsonl"
    path.parent.mkdir()
    caplog.set_level(logging.DEBUG)

    async def body(addon, tctx):
        await addon.running()
        post(addon, json.dumps({"message": secret_text, "request_id": secret_id}))
        post(addon, json.dumps({"message": secret_text, "request_id": 5}))
        post(addon, "{", path="/SECRET-PATH")
        stray = socket.create_connection(("127.0.0.1", addon.sink_port))
        stray.sendall(f"POST /log {secret_text}".encode())
        stray.close()
        await asyncio.sleep(0.1)

    scenario(body, path)
    messages = [record.getMessage() for record in caplog.records if record.name.startswith("addons.app_logs")]
    assert messages[0] == "Wiretrace app logs: on"
    assert messages[-1] == "Wiretrace app logs: 1 lines stored, 2 requests rejected"
    assert "Wiretrace app logs: unexpected data reached the local sink" in messages
    text = "\n".join(messages)
    for private in (secret_text, secret_id, "SECRET-FOLDER", "SECRET-PATH", str(tmp_path)):
        assert private not in text


def test_addon_says_when_it_is_off(caplog):
    caplog.set_level(logging.INFO)
    scenario(lambda addon, tctx: None)
    messages = [record.getMessage() for record in caplog.records if record.name.startswith("addons.app_logs")]
    assert messages[0] == "Wiretrace app logs: off (qa_app_log_file empty)"


# Reachability: DNS, connect, TLS

def dns_flow(name: str, type_: int = dns.types.A, query: bool = True):
    request = tutils.tdnsreq(questions=[dns.Question(name, type_, dns.classes.IN)], query=query)
    return tflow.tdnsflow(req=request)


def test_dns_a_for_the_receiver_name():
    addon = app_logs.AppLogs()
    flow = dns_flow(HOST)
    addon.dns_request(flow)
    response = flow.response
    assert response.response_code == dns.response_codes.NOERROR and response.id == flow.request.id
    [answer] = response.answers
    assert (answer.name, answer.type, answer.ttl) == (HOST, dns.types.A, 60)
    assert answer.data == IPv4Address("192.0.2.10").packed


@pytest.mark.parametrize("type_", [dns.types.AAAA, dns.types.HTTPS, dns.types.TXT])
def test_dns_other_types_for_the_receiver_name_have_no_answers(type_):
    addon = app_logs.AppLogs()
    flow = dns_flow(HOST, type_)
    addon.dns_request(flow)
    assert flow.response.response_code == dns.response_codes.NOERROR and flow.response.answers == []


@pytest.mark.parametrize("name", ["api.example.com", "qa-logs.internal.evil.io", "sub.qa-logs.internal", "internal"])
def test_dns_other_names_get_no_response(name):
    addon = app_logs.AppLogs()
    for type_ in (dns.types.A, dns.types.AAAA):
        flow = dns_flow(name, type_)
        addon.dns_request(flow)
        assert flow.response is None and flow.error is None


def test_dns_trailing_dot_and_case_still_match():
    addon = app_logs.AppLogs()
    flow = dns_flow("QA-Logs.Internal.")
    addon.dns_request(flow)
    assert flow.response is not None


def connect_data(address):
    return server_hooks.ServerConnectionHookData(
        server=connection.Server(address=address), client=tflow.tclient_conn())


def test_server_connect_redirects_only_the_two_addresses_to_the_sink():
    async def body(addon, tctx):
        await addon.running()
        sink = ("127.0.0.1", addon.sink_port)
        assert addon.sink_port
        for address in ((HOST, 443), (HOST, 8443), ("192.0.2.10", 443), ("192.0.2.10", 80)):
            data = connect_data(address)
            addon.server_connect(data)
            assert data.server.address == sink
        for address in (("api.example.com", 443), ("192.0.2.11", 443), ("sub.qa-logs.internal", 443),
                        ("127.0.0.1", 443), ("::1", 443)):
            data = connect_data(address)
            addon.server_connect(data)
            assert data.server.address == address

    scenario(body)


def test_server_connect_without_a_sink_changes_nothing():
    addon = app_logs.AppLogs()
    data = connect_data((HOST, 443))
    addon.server_connect(data)
    assert data.server.address == (HOST, 443)


def test_sink_listens_on_loopback_only_reads_nothing_and_closes_with_the_peer():
    async def body(addon, tctx):
        await addon.running()
        [sock] = addon._sink.sockets
        assert sock.getsockname()[0] == "127.0.0.1"
        reader, writer = await asyncio.open_connection("127.0.0.1", addon.sink_port)
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
        assert addon.sink_bytes == 0
        port = addon.sink_port
        addon.done()
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1)

    scenario(body)


def hello(sni: str | None) -> tls.ClientHelloData:
    # Only `sni` is read; building a real ClientHello needs a recorded handshake.
    return tls.ClientHelloData(context=None, client_hello=SimpleNamespace(sni=sni), establish_server_tls_first=True)


@pytest.mark.parametrize("sni, changed", [
    (HOST, True), ("QA-LOGS.internal", True), ("api.example.com", False), ("sub.qa-logs.internal", False),
    ("qa-logs.internal.evil.io", False), (None, False),
])
def test_tls_clienthello_changes_only_the_receiver_sni(sni, changed):
    addon = app_logs.AppLogs()
    data = hello(sni)
    addon.tls_clienthello(data)
    assert data.establish_server_tls_first is (not changed)
    assert data.ignore_connection is False


def test_a_copy_of_the_tls_hook_runs_at_the_end_of_the_chain():
    async def body(addon, tctx):
        await addon.running()
        late = tctx.master.addons.chain[-1]
        data = hello(HOST)
        late.tls_clienthello(data)
        assert data.establish_server_tls_first is False
        other = hello("api.example.com")
        late.tls_clienthello(other)
        assert other.establish_server_tls_first is True

    scenario(body)


def test_qa_tools_never_sees_the_receiver_as_an_api_host():
    preset = Preset(name="staging", api_hosts=("api.example.com",))
    cmd = start.build_command(preset, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"))
    assert [a for a in cmd if a.startswith("qa_api_hosts=")] == ["qa_api_hosts=api.example.com"]


# Integration: real mitmdump, proxy mode, temporary confdir

def free_port() -> int:
    # mitmproxy listens on "::", so the port must be free for IPv6 as well as IPv4.
    with socket.socket(socket.AF_INET6) as probe:
        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        probe.bind(("::", 0))
        return probe.getsockname()[1]


def wait_for(condition, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


def accepts(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


class Mitmdump:
    def __init__(self, tmp_path: Path, args: list[str]):
        self.confdir = tmp_path / "confdir"
        self.log = tmp_path / "mitmdump.log"
        with open(self.log, "w") as out:
            # Unbuffered, so the test can read the event log while mitmdump runs.
            self.proc = subprocess.Popen(
                [str(VENV_BIN / "mitmdump"), "--set", f"confdir={self.confdir}", *args],
                stdout=out, stderr=subprocess.STDOUT, cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1"})

    def stop(self) -> str:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        return self.log.read_text()

    @property
    def ca(self) -> Path:
        return self.confdir / "mitmproxy-ca-cert.pem"


class Backend(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):
        self.hits.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_):
        pass


def tunnel(port: int, ca: Path, method: str, path: str, body: bytes | None) -> tuple[int, bytes, http.client.HTTPMessage]:
    """An HTTPS request to the receiver host through the proxy, verified against the mitmproxy CA."""
    context = ssl.create_default_context(cafile=str(ca))
    conn = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=15)
    conn.set_tunnel(HOST, 443)
    try:
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.read(), response.msg
    finally:
        conn.close()


needs_mitmdump = pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")


@needs_mitmdump
def test_real_mitmdump_receiver_in_proxy_mode(tmp_path):
    backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    Backend.hits = []
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    port = free_port()
    preset = Preset(name="staging", api_hosts=("127.0.0.1",))
    # The launcher's own command line, so its receiver arguments are what is tested.
    cmd = start.build_command(preset, "proxy", False, session_dir / "flows.mitm", VENV_BIN,
                              proxy_port=port, wiretrace_dir=tmp_path)
    mitmdump = Mitmdump(tmp_path, cmd[1:])
    try:
        wait_for(lambda: accepts(port))

        status, _, _ = tunnel(port, mitmdump.ca, "POST", "/log", b'[{"message": "hi", "level": "I"}]')
        assert status == 204
        assert tunnel(port, mitmdump.ca, "POST", "/log", b"{")[0] == 400
        assert tunnel(port, mitmdump.ca, "POST", "/log", b"x" * (MAX_BODY + 1))[0] == 413
        assert tunnel(port, mitmdump.ca, "GET", "/log", None)[0] == 405
        assert tunnel(port, mitmdump.ca, "POST", "/other", b"{}")[0] == 404

        # A normal API flow is still saved while the receiver flows are not.
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", f"http://127.0.0.1:{backend.server_port}/hello")
        assert conn.getresponse().read() == b"ok"
        conn.close()
    finally:
        output = mitmdump.stop()
        backend.shutdown()

    assert Backend.hits == ["/hello"]
    assert [line["message"] for line in stored(session_dir / "app.log.jsonl")] == ["hi"]
    with open(session_dir / "flows.mitm", "rb") as f:
        flows = list(io.FlowReader(f).stream())
    assert [flow.request.path for flow in flows] == ["/hello"]
    # Redirected to the local sink, never connected anywhere else, and the sink never got a byte.
    assert "unexpected data reached the local sink" not in output
    assert "error establishing server connection" not in output and "Unable to establish" not in output
    assert "Wiretrace app logs: 1 lines stored, 4 requests rejected" in output
    assert "<< 204" in output
    # Five receiver connections, each redirected to the sink, plus the one to the backend.
    assert f"server connect {HOST}" not in output and output.count("server connect 127.0.0.1:") == 6


@needs_mitmdump
@pytest.mark.skipif(not shutil.which("curl"), reason="curl is not installed")
def test_real_mitmdump_receiver_with_curl(tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    port = free_port()
    preset = Preset(name="staging", api_hosts=("api.example.com",))
    cmd = start.build_command(preset, "proxy", False, session_dir / "flows.mitm", VENV_BIN,
                              proxy_port=port, wiretrace_dir=tmp_path)
    mitmdump = Mitmdump(tmp_path, cmd[1:])
    try:
        wait_for(lambda: accepts(port) and mitmdump.ca.exists())
        result = subprocess.run(
            ["curl", "--silent", "--show-error", "--cacert", str(mitmdump.ca), "-x", f"http://127.0.0.1:{port}",
             "-X", "POST", f"https://{HOST}/log", "-d", '[{"message":"hi"}]', "-o", "/dev/null",
             "-w", "%{http_code}"],
            capture_output=True, text=True, timeout=60)
        assert (result.returncode, result.stdout) == (0, "204"), result.stderr
    finally:
        output = mitmdump.stop()

    assert [line["message"] for line in stored(session_dir / "app.log.jsonl")] == ["hi"]
    flows_file = session_dir / "flows.mitm"
    assert not flows_file.exists() or flows_file.stat().st_size == 0
    assert "unexpected data reached the local sink" not in output


@needs_mitmdump
def test_real_mitmdump_answers_dns_for_the_receiver_name_before_the_resolver(tmp_path):
    port = free_port()
    mitmdump = Mitmdump(tmp_path, ["--mode", f"dns@{port}", "-s", str(ROOT / "addons" / "app_logs.py")])

    def query(name: str, type_: int) -> dns.DNSMessage:
        request = tutils.tdnsreq(questions=[dns.Question(name, type_, dns.classes.IN)], id=7)
        with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
            conn.sendall(struct.pack("!H", len(request.packed)) + request.packed)
            (length,) = struct.unpack("!H", conn.recv(2))
            data = b""
            while len(data) < length:
                data += conn.recv(length - len(data))
        return dns.DNSMessage.unpack(data)

    try:
        wait_for(lambda: accepts(port))
        answer = query(HOST, dns.types.A)
        assert [IPv4Address(a.data) for a in answer.answers] == [IPv4Address("192.0.2.10")]
        assert answer.response_code == dns.response_codes.NOERROR and answer.answers[0].ttl == 60
        empty = query(HOST, dns.types.AAAA)
        assert empty.response_code == dns.response_codes.NOERROR and empty.answers == []
    finally:
        mitmdump.stop()
