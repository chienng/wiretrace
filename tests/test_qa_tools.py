import asyncio
import http.client
import http.server
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from mitmproxy import exceptions
from mitmproxy.test import taddons, tflow

from addons import qa_tools

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
HOST = "api.example.com"
PROFILE = b'{"name": "Test User"}'


def make_flow(host: str = HOST, path: str = "/api/v1/profile", method: str = "GET",
              request_headers: dict | None = None, response_headers: dict | None = None):
    flow = tflow.tflow(resp=response_headers is not None)
    flow.request.host = host
    flow.request.path = path
    flow.request.method = method
    for name, value in (request_headers or {}).items():
        flow.request.headers[name] = value
    for name, value in (response_headers or {}).items():
        flow.response.headers[name] = value
    return flow


def scenario(body, **options):
    """Run `body(addon, tctx)` with the addon loaded and the API host configured."""
    async def main():
        addon = qa_tools.QATools()
        with taddons.context(addon) as tctx:
            tctx.configure(addon, **{"qa_api_hosts": [HOST], **options})
            await body(addon, tctx)

    asyncio.run(main())


@pytest.fixture
def mocks(tmp_path):
    root = tmp_path / "mocks"
    (root / "GET" / "api" / "v1").mkdir(parents=True)
    (root / "GET" / "api" / "v1" / "profile.json").write_bytes(PROFILE)
    return root


# Invariant 1: other hosts are never touched

@pytest.mark.parametrize("host", ["other.example.org", "badapi.example.com", "api.example.com.evil.io", "example.com"])
def test_non_api_host_is_untouched(mocks, host):
    async def body(addon, tctx):
        flow = make_flow(host, request_headers={"X-Request-ID": "abc"})
        # A matching mock and fault, and a 5 s delay: nothing may happen, and nothing may wait.
        await asyncio.wait_for(addon.request(flow), timeout=1)
        assert flow.response is None and flow.marked == "" and flow.comment == ""
        assert flow.live and flow.killable and flow.error is None

        answered = make_flow(host, response_headers={"X-Request-ID": "def"})
        addon.response(answered)
        assert answered.comment == ""

    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~all", qa_fault_status=500,
             qa_fault_delay_ms=5000, qa_fault_drop=True)


@pytest.mark.parametrize("host", [HOST, "v2.api.example.com", "API.Example.COM"])
def test_api_host_and_subdomains_match_case_insensitively(mocks, host):
    async def body(addon, tctx):
        flow = make_flow(host)
        await addon.request(flow)
        assert flow.response.status_code == 200

    scenario(body, qa_mocks_dir=str(mocks))


def test_no_api_hosts_means_the_addon_does_nothing(mocks):
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.response is None and flow.marked == ""

    scenario(body, qa_api_hosts=[], qa_mocks_dir=str(mocks), qa_fault_filter="~all", qa_fault_status=500)


# Invariant 2: mocks and injected statuses answer in the request hook

def test_mock_answers_with_the_file(mocks):
    async def body(addon, tctx):
        flow = make_flow(path="/api/v1/profile?page=2&q=%20")
        await addon.request(flow)
        assert flow.response.status_code == 200
        assert flow.response.content == PROFILE
        assert flow.response.headers["Content-Type"] == "application/json"
        assert flow.marked == ":construction:"
        assert flow.comment == "mock: GET/api/v1/profile.json"

    scenario(body, qa_mocks_dir=str(mocks))


def test_no_mock_file_means_the_request_goes_on(mocks):
    async def body(addon, tctx):
        for flow in (make_flow(path="/api/v1/other"), make_flow(method="POST"), make_flow(path="/api/v1")):
            await addon.request(flow)
            assert flow.response is None and flow.marked == "" and flow.comment == ""

    scenario(body, qa_mocks_dir=str(mocks))


@pytest.mark.parametrize("mocks_dir", ["", "/does/not/exist"])
def test_no_mocks_folder_means_no_mocks(mocks_dir):
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.response is None

    scenario(body, qa_mocks_dir=mocks_dir)


def test_mock_edits_apply_to_the_next_request(mocks):
    async def body(addon, tctx):
        first = make_flow()
        await addon.request(first)
        (mocks / "GET" / "api" / "v1" / "profile.json").write_bytes(b'{"edited": true}')
        (mocks / "GET" / "api" / "v1" / "added.json").write_bytes(b"{}")
        second, added = make_flow(), make_flow(path="/api/v1/added")
        await addon.request(second)
        await addon.request(added)
        assert first.response.content == PROFILE
        assert second.response.content == b'{"edited": true}'
        assert added.response.content == b"{}"

    scenario(body, qa_mocks_dir=str(mocks))


@pytest.mark.parametrize("path, expected_file", [
    ("/", "GET/index.json"),
    ("/?x=1", "GET/index.json"),
    ("/api/v1/profile/", "GET/api/v1/profile.json"),
    ("/a%20b", "GET/a%20b.json"),
])
def test_mock_path_mapping(mocks, path, expected_file):
    async def body(addon, tctx):
        (mocks / "GET" / "a%20b.json").write_bytes(b"percent")
        (mocks / "GET" / "index.json").write_bytes(b"index")
        flow = make_flow(path=path)
        await addon.request(flow)
        assert flow.response is not None
        assert flow.comment == f"mock: {expected_file}"

    scenario(body, qa_mocks_dir=str(mocks))


def test_path_is_not_percent_decoded(mocks):
    async def body(addon, tctx):
        flow = make_flow(path="/api%2Fv1/profile")
        await addon.request(flow)
        assert flow.response is None

    scenario(body, qa_mocks_dir=str(mocks))


def test_fault_status_answers_in_the_request_hook(mocks):
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.response.status_code == 500
        assert flow.response.content == b'{"error": "injected by Wiretrace"}'
        assert flow.response.headers["Content-Type"] == "application/json"
        assert flow.marked == ":boom:"
        assert flow.comment == "fault: status 500"

    # The mock would match too: the fault answers first, and the mark is the fault's.
    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~u /api/v1/profile", qa_fault_status=500)


def test_fault_filter_selects_requests_and_clearing_it_stops_faults():
    async def body(addon, tctx):
        other = make_flow(path="/api/v1/other")
        await addon.request(other)
        assert other.response is None and other.marked == ""

        posted = make_flow(path="/orders", method="POST")
        await addon.request(posted)
        assert posted.response.status_code == 503

        tctx.configure(addon, qa_fault_filter="")
        cleared = make_flow(path="/orders", method="POST")
        await addon.request(cleared)
        assert cleared.response is None

    scenario(body, qa_fault_filter="~m POST & ~u /orders", qa_fault_status=503)


def test_response_filters_never_match():
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.response is None

    scenario(body, qa_fault_filter="~c 200", qa_fault_status=500)


def test_filter_without_any_fault_does_nothing():
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.response is None and flow.marked == "" and flow.comment == ""

    scenario(body, qa_fault_filter="~all")


def test_drop_closes_the_connection_without_a_response():
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.response is None
        assert not flow.live and flow.error is not None and not flow.killable
        assert flow.marked == ":boom:"
        assert flow.comment == "fault: dropped"

    scenario(body, qa_fault_filter="~all", qa_fault_drop=True, qa_fault_status=500)


def test_delay_only_continues_unmarked():
    async def body(addon, tctx):
        flow = make_flow()
        started = time.monotonic()
        await addon.request(flow)
        assert time.monotonic() - started >= 0.05
        assert flow.response is None and flow.marked == "" and flow.live
        assert flow.comment == "fault: delay 60 ms"

    scenario(body, qa_fault_filter="~all", qa_fault_delay_ms=60)


def test_delay_then_mock_comment_order(mocks):
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "r-1"})
        await addon.request(flow)
        assert flow.response.content == PROFILE and flow.marked == ":construction:"
        assert flow.comment == "request-id: r-1; fault: delay 20 ms; mock: GET/api/v1/profile.json"

    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~all", qa_fault_delay_ms=20)


def test_delay_then_status_comment_order():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "r-1"})
        await addon.request(flow)
        assert flow.response.status_code == 502
        assert flow.comment == "request-id: r-1; fault: delay 20 ms; fault: status 502"

    scenario(body, qa_fault_filter="~all", qa_fault_delay_ms=20, qa_fault_status=502)


# Invariant 3: one snapshot per flow

def test_delaying_flow_keeps_its_snapshot_and_new_flows_get_the_new_one():
    async def body(addon, tctx):
        old = make_flow()
        task = asyncio.create_task(addon.request(old))
        await asyncio.sleep(0.05)
        assert not task.done()

        tctx.configure(addon, qa_fault_status=503, qa_fault_delay_ms=0)
        new = make_flow()
        await addon.request(new)
        assert new.response.status_code == 503

        await task
        assert old.response.status_code == 500
        assert old.comment == "fault: delay 300 ms; fault: status 500"

    scenario(body, qa_fault_filter="~all", qa_fault_status=500, qa_fault_delay_ms=300)


def test_clearing_the_filter_does_not_cancel_a_delaying_flow():
    async def body(addon, tctx):
        old = make_flow()
        task = asyncio.create_task(addon.request(old))
        await asyncio.sleep(0.05)
        tctx.configure(addon, qa_fault_filter="")
        await task
        assert old.response.status_code == 500

    scenario(body, qa_fault_filter="~all", qa_fault_status=500, qa_fault_delay_ms=200)


# Invariant 4: a delay never blocks others and can be cancelled

def test_a_delayed_flow_does_not_block_another():
    async def body(addon, tctx):
        slow, fast = make_flow(path="/slow"), make_flow(path="/fast")
        slow_task = asyncio.create_task(addon.request(slow))
        fast_task = asyncio.create_task(addon.request(fast))
        done, pending = await asyncio.wait({slow_task, fast_task}, return_when=asyncio.FIRST_COMPLETED)
        assert done == {fast_task} and pending == {slow_task}
        assert slow.response is None
        await slow_task
        assert slow.response.status_code == 500

    scenario(body, qa_fault_filter="~u /slow", qa_fault_status=500, qa_fault_delay_ms=400)


def test_cancelling_a_delaying_flow_propagates_and_leaves_no_response():
    async def body(addon, tctx):
        flow = make_flow()
        task = asyncio.create_task(addon.request(flow))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert flow.response is None and flow.marked == "" and flow.comment == ""
        assert flow.live and flow.error is None

    scenario(body, qa_fault_filter="~all", qa_fault_status=500, qa_fault_delay_ms=10_000)


# Invariant 5: after a delay, only a live flow is touched

def test_flow_killed_during_the_delay_gets_no_response():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "r-1"})
        task = asyncio.create_task(addon.request(flow))
        await asyncio.sleep(0.05)
        flow.kill()
        await task
        assert flow.response is None and flow.marked == ""
        assert flow.comment == "request-id: r-1"

    scenario(body, qa_fault_filter="~all", qa_fault_status=500, qa_fault_delay_ms=200)


def test_flow_that_is_no_longer_live_gets_no_response(mocks):
    async def body(addon, tctx):
        flow = make_flow()
        task = asyncio.create_task(addon.request(flow))
        await asyncio.sleep(0.05)
        flow.live = False
        await task
        assert flow.response is None and flow.marked == ""

    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~all", qa_fault_delay_ms=200)


def test_dropped_flow_killed_during_the_delay_is_not_killed_twice():
    async def body(addon, tctx):
        flow = make_flow()
        task = asyncio.create_task(addon.request(flow))
        await asyncio.sleep(0.05)
        flow.kill()
        await task  # kill() on a dead flow would raise ControlException
        assert flow.marked == ""

    scenario(body, qa_fault_filter="~all", qa_fault_drop=True, qa_fault_delay_ms=200)


# Invariant 6: mock lookup stays inside the mocks folder

@pytest.mark.parametrize("path", ["/../../outside/secret", "/a//b", "/./x", "/a/./b", "/a/../x", "//x", "//",
                                  "/api/v1//profile", "x", "*"])
def test_odd_paths_find_no_mock(tmp_path, mocks, path):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.json").write_bytes(b"secret")
    (mocks / "GET" / "a").mkdir()
    (mocks / "GET" / "a" / "b.json").write_bytes(b"ab")
    (mocks / "GET" / "x.json").write_bytes(b"x")
    (mocks / "GET" / "index.json").write_bytes(b"index")

    async def body(addon, tctx):
        flow = make_flow(path=path)
        await addon.request(flow)
        assert flow.response is None and flow.marked == "" and flow.comment == ""

    scenario(body, qa_mocks_dir=str(mocks))


def test_the_passwd_traversal_finds_no_mock(tmp_path, mocks):
    (tmp_path / "GET" / "etc").mkdir(parents=True)
    (tmp_path / "GET" / "etc" / "passwd.json").write_bytes(b"secret")

    async def body(addon, tctx):
        flow = make_flow(path="/../../etc/passwd")
        await addon.request(flow)
        assert flow.response is None

    scenario(body, qa_mocks_dir=str(mocks))


def test_symlinks_pointing_outside_are_refused(tmp_path, mocks):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_bytes(b"secret")
    (mocks / "GET" / "dir").symlink_to(outside, target_is_directory=True)
    (mocks / "GET" / "leak.json").symlink_to(outside / "secret.json")
    (mocks / "GET" / "inside.json").symlink_to(mocks / "GET" / "api" / "v1" / "profile.json")

    async def body(addon, tctx):
        for path in ("/dir/secret", "/leak"):
            flow = make_flow(path=path)
            await addon.request(flow)
            assert flow.response is None, path
        inside = make_flow(path="/inside")
        await addon.request(inside)
        assert inside.response.content == PROFILE

    scenario(body, qa_mocks_dir=str(mocks))


def test_a_folder_is_not_a_mock(mocks):
    (mocks / "GET" / "folder.json").mkdir()

    async def body(addon, tctx):
        flow = make_flow(path="/folder")
        await addon.request(flow)
        assert flow.response is None

    scenario(body, qa_mocks_dir=str(mocks))


# Invariant 7: an invalid value never replaces the snapshot in effect

@pytest.mark.parametrize("option, value", [
    ("qa_fault_filter", "foo("),
    ("qa_fault_filter", "~c"),
    ("qa_fault_filter", "~u ("),
    ("qa_fault_status", 99),
    ("qa_fault_status", 600),
    ("qa_fault_status", -5),
    ("qa_fault_delay_ms", -1),
])
def test_invalid_option_is_rejected_and_the_old_snapshot_stays(option, value):
    async def body(addon, tctx):
        with pytest.raises(exceptions.OptionsError):
            tctx.configure(addon, **{option: value})
        # mitmproxy rolls the option back and configures again, so the snapshot is rebuilt from the old values.
        assert tctx.options.qa_fault_status == 500 and tctx.options.qa_fault_filter == "~all"
        faults = addon._snapshot.faults
        assert (faults.matcher.pattern, faults.status, faults.delay_ms, faults.drop) == ("~all", 500, 0, False)
        flow = make_flow()
        await addon.request(flow)
        assert flow.response.status_code == 500

    scenario(body, qa_fault_filter="~all", qa_fault_status=500)


@pytest.mark.parametrize("option, value", [
    ("qa_fault_filter", "foo("),
    ("qa_fault_status", 600),
    ("qa_fault_delay_ms", -1),
])
def test_configure_failure_leaves_the_snapshot_object_untouched(option, value):
    async def body(addon, tctx):
        before = addon._snapshot
        tctx.options._options[option].value = value  # bypasses the options' own change notification
        with pytest.raises(exceptions.OptionsError):
            addon.configure({option})
        assert addon._snapshot is before

    scenario(body, qa_fault_filter="~all", qa_fault_status=500)


@pytest.mark.parametrize("status", [0, 100, 599])
def test_status_bounds_are_accepted(status):
    async def body(addon, tctx):
        tctx.configure(addon, qa_fault_status=status)
        assert addon._snapshot.faults.status == status

    scenario(body, qa_fault_filter="~all")


def test_addon_options_have_the_documented_defaults():
    async def body(addon, tctx):
        o = tctx.options
        assert list(o.qa_api_hosts) == [] and o.qa_mocks_dir == "" and o.qa_request_id_header == "X-Request-ID"
        assert o.qa_fault_filter == "" and o.qa_fault_status == 0 and o.qa_fault_delay_ms == 0
        assert o.qa_fault_drop is False
        assert addon._snapshot == qa_tools.Snapshot()

    async def main():
        addon = qa_tools.QATools()
        with taddons.context(addon) as tctx:
            await body(addon, tctx)

    asyncio.run(main())


def test_repeated_api_hosts_accumulate():
    async def body(addon, tctx):
        tctx.options.set("qa_api_hosts=a.example.com", "qa_api_hosts=b.example.com")
        assert addon._snapshot.api_hosts == ("a.example.com", "b.example.com")

    async def main():
        addon = qa_tools.QATools()
        with taddons.context(addon) as tctx:
            await body(addon, tctx)

    asyncio.run(main())


# Request IDs

def test_request_id_from_the_request_header():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"x-request-id": "req-1"})
        await addon.request(flow)
        assert flow.comment == "request-id: req-1"
        assert flow.response is None and flow.marked == ""

        flow.response = tflow.tresp()
        flow.response.headers["X-Request-ID"] = "from-response"
        addon.response(flow)
        assert flow.comment == "request-id: req-1"

    scenario(body)


def test_request_id_from_the_response_when_the_request_has_none():
    async def body(addon, tctx):
        flow = make_flow(response_headers={"X-Request-ID": "resp-1"})
        await addon.request(flow)
        assert flow.comment == ""
        addon.response(flow)
        assert flow.comment == "request-id: resp-1"

    scenario(body)


def test_no_request_id_anywhere_leaves_no_comment():
    async def body(addon, tctx):
        flow = make_flow(response_headers={})
        await addon.request(flow)
        addon.response(flow)
        assert flow.comment == ""

    scenario(body)


def test_request_id_is_cut_to_128_characters():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "x" * 300})
        await addon.request(flow)
        assert flow.comment == "request-id: " + "x" * 128

        answered = make_flow(response_headers={"X-Request-ID": "y" * 300})
        addon.response(answered)
        assert answered.comment == "request-id: " + "y" * 128

    scenario(body)


def test_response_request_id_goes_first_in_the_comment(mocks):
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.comment == "fault: delay 10 ms; mock: GET/api/v1/profile.json"
        flow.response.headers["X-Request-ID"] = "resp-1"
        addon.response(flow)
        assert flow.comment == "request-id: resp-1; fault: delay 10 ms; mock: GET/api/v1/profile.json"

    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~all", qa_fault_delay_ms=10)


def test_request_id_header_is_configurable():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "ignored", "X-Trace-Id": "trace-1"})
        await addon.request(flow)
        assert flow.comment == "request-id: trace-1"

    scenario(body, qa_request_id_header="X-Trace-Id")


# Logging and files

def test_addon_logs_only_counts_and_states(caplog, mocks):
    async def body(addon, tctx):
        for flow in (make_flow(request_headers={"X-Request-ID": "secret-id"}), make_flow(path="/orders")):
            await addon.request(flow)
        tctx.configure(addon, qa_fault_status=0)

    with caplog.at_level(logging.DEBUG):
        scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~u /orders", qa_fault_status=500)

    messages = [r.getMessage() for r in caplog.records if r.name == qa_tools.__name__]
    assert "Wiretrace QA: 1 API hosts, mocks on, faults on" in messages
    assert "Wiretrace QA: 1 API hosts, mocks on, faults off" in messages
    text = " ".join(messages)
    for secret in (HOST, "secret-id", "orders", "profile", str(mocks)):
        assert secret not in text


def test_addon_never_writes_files(tmp_path, mocks):
    def listing():
        return sorted((str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))

    async def body(addon, tctx):
        before = listing()
        for flow in (make_flow(), make_flow(path="/orders"), make_flow(path="/drop")):
            await addon.request(flow)
        assert listing() == before

    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~u /orders", qa_fault_status=500)


# Integration: real mitmdump

def free_port() -> int:
    # mitmproxy listens on "::", so the port must be free for IPv6 as well as IPv4.
    with socket.socket(socket.AF_INET6) as probe:
        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        probe.bind(("::", 0))
        return probe.getsockname()[1]


class _Backend(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):
        self.hits.append(self.path)
        body = b"backend"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def _accepts(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


def _wait_for(condition, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


class Proxy:
    """A real mitmdump with the addon, in regular mode on a free port, in front of a counting backend."""

    def __init__(self, tmp_path: Path, mocks: Path, *options: str):
        _Backend.hits = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Backend)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = free_port()
        self.log = tmp_path / "mitmdump.log"
        args = [str(VENV_BIN / "mitmdump"), "--mode", "regular", "--listen-port", str(self.port),
                "--set", f"confdir={tmp_path / 'confdir'}", "-s", str(ROOT / "addons" / "qa_tools.py"),
                "--set", "qa_api_hosts=127.0.0.1", "--set", f"qa_mocks_dir={mocks}"]
        for option in options:
            args += ["--set", option]
        with open(self.log, "w") as out:
            # Unbuffered, so the test can see "client connect" as it happens.
            self.proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, cwd=ROOT,
                                         env={**os.environ, "PYTHONUNBUFFERED": "1"})
        _wait_for(lambda: _accepts(self.port))

    def get(self, path: str, timeout: float = 10) -> tuple[int, bytes, str | None]:
        # Absolute-form URL straight to the proxy: urllib would bypass it through the macOS proxy settings.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request("GET", f"http://127.0.0.1:{self.server.server_port}{path}")
            response = conn.getresponse()
            return response.status, response.read(), response.getheader("Content-Type")
        finally:
            conn.close()

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.server.shutdown()
        self.server.server_close()


needs_mitmdump = pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")


@needs_mitmdump
def test_real_mitmdump_mocks_and_faults(tmp_path, mocks):
    proxy = Proxy(tmp_path, mocks, "qa_fault_filter=~u /faulted", "qa_fault_status=500")
    try:
        assert proxy.get("/api/v1/profile?x=1") == (200, PROFILE, "application/json")
        assert _Backend.hits == []

        status, body, content_type = proxy.get("/faulted")
        assert (status, body, content_type) == (500, b'{"error": "injected by Wiretrace"}', "application/json")
        assert _Backend.hits == []

        assert proxy.get("/plain")[:2] == (200, b"backend")
        assert _Backend.hits == ["/plain"]
    finally:
        proxy.close()


@needs_mitmdump
def test_real_mitmdump_stops_quickly_while_a_request_is_delayed(tmp_path, mocks):
    proxy = Proxy(tmp_path, mocks, "qa_fault_filter=~all", "qa_fault_delay_ms=10000")
    outcome: list = []

    def delayed_request():
        try:
            outcome.append(proxy.get("/api/v1/profile", timeout=30))
        except OSError as e:
            outcome.append(e)

    requester = threading.Thread(target=delayed_request, daemon=True)
    try:
        requester.start()
        _wait_for(lambda: "client connect" in proxy.log.read_text(), timeout=30)
        time.sleep(0.5)
        assert not outcome

        stopped_at = time.monotonic()
        proxy.proc.send_signal(signal.SIGINT)
        proxy.proc.wait(timeout=5)
        assert time.monotonic() - stopped_at < 5
        requester.join(timeout=10)
        assert not requester.is_alive()
        assert _Backend.hits == []
        # The client got no response: the delayed request was never answered.
        assert len(outcome) == 1 and isinstance(outcome[0], OSError)
    finally:
        proxy.close()
