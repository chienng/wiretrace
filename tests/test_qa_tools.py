import asyncio
import gzip
import http.client
import json
import http.server
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
from mitmproxy import exceptions
from mitmproxy import http as mhttp
from mitmproxy.test import taddons, tflow

from addons import qa_tools
from cli import datadir

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


@pytest.fixture(autouse=True)
def _data_folder_is_the_test_folder(monkeypatch, tmp_path):
    """Mock files in these tests live under tmp. Production still requires the data folder."""
    monkeypatch.setattr(qa_tools, "default_data_dir", lambda: tmp_path)


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
        await addon.response(answered)
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


def test_a_replay_keeps_its_replay_part_and_gets_the_new_ones():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "r-2"})
        flow.comment = "replay: orig-1; request-id: r-1; fault: status 502"
        flow.is_replay = "request"
        await addon.request(flow)
        assert flow.comment == "replay: orig-1; request-id: r-2; fault: status 502"

        plain = make_flow(request_headers={"X-Request-ID": "r-3"})
        plain.comment = "replay: forged"
        await addon.request(plain)
        assert plain.comment == "request-id: r-3; fault: status 502"

    scenario(body, qa_fault_filter="~all", qa_fault_status=502)


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
        assert o.qa_fault_drop is False and o.qa_rules_file == ""
        assert addon._snapshot == qa_tools.Snapshot()
        assert addon.rules == qa_tools.Rules()

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
        await addon.response(flow)
        assert flow.comment == "request-id: req-1"

    scenario(body)


def test_request_id_from_the_response_when_the_request_has_none():
    async def body(addon, tctx):
        flow = make_flow(response_headers={"X-Request-ID": "resp-1"})
        await addon.request(flow)
        assert flow.comment == ""
        await addon.response(flow)
        assert flow.comment == "request-id: resp-1"

    scenario(body)


def test_no_request_id_anywhere_leaves_no_comment():
    async def body(addon, tctx):
        flow = make_flow(response_headers={})
        await addon.request(flow)
        await addon.response(flow)
        assert flow.comment == ""

    scenario(body)


def test_request_id_is_cut_to_128_characters():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "x" * 300})
        await addon.request(flow)
        assert flow.comment == "request-id: " + "x" * 128

        answered = make_flow(response_headers={"X-Request-ID": "y" * 300})
        await addon.response(answered)
        assert answered.comment == "request-id: " + "y" * 128

    scenario(body)


def test_response_request_id_goes_first_in_the_comment(mocks):
    async def body(addon, tctx):
        flow = make_flow()
        await addon.request(flow)
        assert flow.comment == "fault: delay 10 ms; mock: GET/api/v1/profile.json"
        flow.response.headers["X-Request-ID"] = "resp-1"
        await addon.response(flow)
        assert flow.comment == "request-id: resp-1; fault: delay 10 ms; mock: GET/api/v1/profile.json"

    scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~all", qa_fault_delay_ms=10)


def test_request_id_header_is_configurable():
    async def body(addon, tctx):
        flow = make_flow(request_headers={"X-Request-ID": "ignored", "X-Trace-Id": "trace-1"})
        await addon.request(flow)
        assert flow.comment == "request-id: trace-1"

    scenario(body, qa_request_id_header="X-Trace-Id")


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


def parse(*rules, hosts=(HOST,), mocks_dir=""):
    return qa_tools.parse_rules({"version": 1, "rules": list(rules)}, hosts, mocks_dir)


def write_rules(path: Path, *rules) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "rules": list(rules)}))
    os.replace(tmp, path)


def post(path="/api/v1/orders", body=b"", headers=None):
    flow = make_flow(path=path, method="POST", request_headers=headers)
    flow.request.raw_content = body
    return flow


def test_a_valid_rules_document_parses_in_order():
    parsed = parse(rule(), rule(id="second1", name="Two", enabled=False))
    assert isinstance(parsed, qa_tools.Rules)
    assert [r.id for r in parsed.rules] == ["orders500", "second1"] and parsed.revision
    assert parsed.rules[0].data == rule()


@pytest.mark.parametrize("bad, field", [
    ({"id": "abc"}, "id"), ({"id": "a" * 33}, "id"), ({"id": "Upper1"}, "id"),
    ({"name": ""}, "name"), ({"name": "x" * 81}, "name"), ({"name": "a\nb"}, "name"),
    ({"enabled": "yes"}, "enabled"),
    ({"match": {"method": "post"}}, "match.method"), ({"match": {"host": "other.example.com"}}, "match.host"),
    ({"match": {"path": ""}}, "match.path"), ({"match": {"path": "/" + "x" * 512}}, "match.path"),
    ({"match": {"path": "api"}}, "match.path"), ({"match": {"body_contains": "x" * 257}}, "match.body_contains"),
    ({"action": {"type": "teapot"}}, "action.type"), ({"action": {"status": 600}}, "action.status"),
    ({"action": {"status": True}}, "action.status"), ({"action": {"body": "x" * ((1 << 20) + 1)}}, "action.body"),
    ({"action": {"delay_ms": -1}}, "action.delay_ms"), ({"action": {"delay_ms": 120_001}}, "action.delay_ms"),
    ({"action": {"type": "delay", "delay_ms": 0}}, "action.delay_ms"),
    ({"apply": {"mode": "sometimes"}}, "apply.mode"), ({"apply": {"mode": "every_nth", "n": 1}}, "apply.n"),
    ({"apply": {"mode": "every_nth", "n": 1001}}, "apply.n"),
    ({"extra": 1}, "extra"), ({"match": {"method": "GET", "query": "x"}}, "match.query"),
])
def test_each_limit_and_field_is_checked(bad, field):
    got = parse(rule(id="okrule1"), rule(**bad))
    assert isinstance(got, qa_tools.RuleError)
    assert (got.index, got.field) == (1, field)


def test_duplicate_ids_too_many_rules_and_bad_documents_are_refused():
    assert parse(rule(), rule()).field == "id"
    assert parse(*[rule(id=f"rule{i:04d}") for i in range(201)]).field == "rules"
    for document in (None, [], {"version": 2, "rules": []}, {"version": 1}, {"version": 1, "rules": [], "x": 1}):
        assert isinstance(qa_tools.parse_rules(document, (HOST,), ""), qa_tools.RuleError)


def test_mock_file_must_be_inside_the_mocks_dir(tmp_path, mocks):
    (tmp_path / "outside.json").write_text("{}")
    ok = parse(rule(action={"type": "mock", "status": 200, "mock_file": "GET/api/v1/profile.json"}), mocks_dir=str(mocks))
    assert isinstance(ok, qa_tools.Rules)
    for label in ("../outside.json", "/etc/passwd", "GET/missing.json", "GET/api/v1"):
        got = parse(rule(action={"type": "mock", "status": 200, "mock_file": label}), mocks_dir=str(mocks))
        assert getattr(got, "field", None) == "action.mock_file", label


@pytest.mark.parametrize("method, path, request_path, matches", [
    ("ANY", "/api/v1/orders", "/api/v1/orders", True),
    ("GET", "/api/v1/orders", "/api/v1/orders", False),
    ("POST", "/api/*", "/api/v1/orders/7", True),
    ("POST", "*/orders", "/api/v1/orders", True),
    ("POST", "/api/v1/orders", "/api/v1/orders?page=2", True),
    ("POST", "/api/v1/orders?page=*", "/api/v1/orders?page=2", True),
    ("POST", "/api/v1/orders?page=*", "/api/v1/orders", False),
    ("POST", "/api/v1/order", "/api/v1/orders", False),
    ("POST", "/API/v1/orders", "/api/v1/orders", False),
])
def test_matching_method_and_wildcard_paths(method, path, request_path, matches):
    parsed = parse(rule(match={"method": method, "path": path}))
    assert (qa_tools.mismatch(parsed.rules[0], post(request_path).request) is None) is matches


def test_host_empty_matches_any_api_host_and_a_set_host_its_subdomains():
    parsed = parse(rule(match={"host": HOST}), hosts=(HOST, "auth.example.com"))
    assert qa_tools.mismatch(parsed.rules[0], make_flow("v2.api.example.com", method="POST", path="/api/v1/orders").request) is None
    assert qa_tools.mismatch(parsed.rules[0], make_flow("auth.example.com", method="POST", path="/api/v1/orders").request)


def test_body_contains_reads_a_gzip_body():
    parsed = parse(rule(match={"body_contains": '"promoCode":"SUMMER25"'}))
    flow = post(body=gzip.compress(b'{"promoCode":"SUMMER25"}'), headers={"Content-Encoding": "gzip"})
    assert qa_tools.mismatch(parsed.rules[0], flow.request) is None
    assert qa_tools.mismatch(parsed.rules[0], post(body=b'{"promoCode":"OTHER"}').request)


@pytest.mark.parametrize("mode, n, expected", [
    ("always", 0, [True, True, True, True]),
    ("once", 0, [True, False, False, False]),
    ("every_nth", 3, [False, False, True, False]),
])
def test_apply_modes_and_counters(tmp_path, mode, n, expected):
    file = tmp_path / "rules.json"
    write_rules(file, rule(apply={"mode": mode, "n": n}))

    async def body(addon, tctx):
        got = []
        for _ in expected:
            flow = post()
            await addon.request(flow)
            got.append(flow.response is not None)
        assert got == expected
        stats = addon.rule_stats()["orders500"]
        assert stats["matches"] == 4 and stats["applied"] == expected.count(True) and stats["last_ts"]
        assert addon.rearm("orders500") and addon.rule_stats()["orders500"]["matches"] == 0

    scenario(body, qa_rules_file=str(file))


def test_first_applying_rule_wins_and_a_matching_one_that_does_not_apply_passes_on(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rule(id="oncefirst", apply={"mode": "once"}, action={"status": 501}),
                rule(id="always2", action={"status": 502}), rule(id="never33", action={"status": 503}))

    async def body(addon, tctx):
        statuses = []
        for _ in range(2):
            flow = post()
            await addon.request(flow)
            statuses.append(flow.response.status_code)
        assert statuses == [501, 502]
        stats = addon.rule_stats()
        assert (stats["oncefirst"]["matches"], stats["always2"]["matches"], stats["never33"]["matches"]) == (2, 1, 0)

    scenario(body, qa_rules_file=str(file))


def test_order_is_rules_then_faults_then_mocks(tmp_path, mocks):
    file = tmp_path / "rules.json"
    write_rules(file, rule(match={"method": "GET", "path": "/api/v1/profile"}, apply={"mode": "once"}))

    async def body(addon, tctx):
        statuses = []
        for _ in range(2):
            flow = make_flow()
            await addon.request(flow)
            statuses.append(flow.response.status_code)
        tctx.configure(addon, qa_fault_status=0)
        flow = make_flow()
        await addon.request(flow)
        statuses.append(flow.response.status_code)
        assert statuses == [500, 418, 200]

    scenario(body, qa_rules_file=str(file), qa_mocks_dir=str(mocks), qa_fault_filter="~u /profile",
             qa_fault_status=418)


def test_comment_parts_name_the_rule_and_its_effect(tmp_path, mocks):
    file = tmp_path / "rules.json"
    write_rules(file, rule(name="Orders; fail"),
                rule(id="mockrule", match={"method": "GET", "path": "/api/v1/profile"},
                     action={"type": "mock", "status": 200, "mock_file": "GET/api/v1/profile.json"}),
                rule(id="droprule", match={"method": "ANY", "path": "/drop"}, action={"type": "drop"}))

    async def body(addon, tctx):
        status = post(headers={"X-Request-ID": "abc"})
        await addon.request(status)
        assert status.comment == "request-id: abc; rule: Orders, fail; fault: status 500"
        assert status.marked == qa_tools.FAULT_MARK
        mocked = make_flow()
        await addon.request(mocked)
        assert mocked.comment == "rule: Orders fail; mock: GET/api/v1/profile.json"
        assert mocked.response.content == PROFILE and mocked.marked == qa_tools.MOCK_MARK
        dropped = make_flow(path="/drop")
        await addon.request(dropped)
        assert "fault: dropped" in dropped.comment and dropped.error is not None

    scenario(body, qa_rules_file=str(file), qa_mocks_dir=str(mocks))


def test_rules_reload_when_the_file_changes_and_an_invalid_file_keeps_the_old_ones(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rule())

    async def body(addon, tctx):
        assert [r.id for r in addon.rules.rules] == ["orders500"]
        write_rules(file, rule(id="newrule1", action={"status": 503}))
        addon._rules_checked -= qa_tools.RELOAD_CHECK_S
        flow = post()
        await addon.request(flow)
        assert flow.response.status_code == 503
        file.write_text('{"version": 1, "rules": [{"id": "x"}]}')
        addon._rules_checked -= qa_tools.RELOAD_CHECK_S
        flow = post()
        await addon.request(flow)
        assert flow.response.status_code == 503 and addon.rules_error
        file.write_text("{not json")
        assert addon.reload_rules() == "The rules file is not valid JSON"
        assert [r.id for r in addon.rules.rules] == ["newrule1"]

    scenario(body, qa_rules_file=str(file))


def test_a_request_keeps_its_rules_snapshot_across_a_delay(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rule(action={"delay_ms": 200}))

    async def body(addon, tctx):
        flow = post()
        task = asyncio.create_task(addon.request(flow))
        await asyncio.sleep(0.05)
        write_rules(file, rule(action={"status": 503}))
        assert addon.reload_rules() == ""
        await task
        assert flow.response.status_code == 500
        assert "fault: delay 200 ms" in flow.comment

    scenario(body, qa_rules_file=str(file))


def test_saving_new_content_resets_its_counters(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rule())

    async def body(addon, tctx):
        await addon.request(post())
        assert addon.rule_stats()["orders500"]["matches"] == 1
        write_rules(file, rule(enabled=True, name="Renamed"))
        addon.reload_rules()
        assert addon.rule_stats()["orders500"]["matches"] == 0

    scenario(body, qa_rules_file=str(file))


def test_testing_a_rule_changes_no_counter(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rule())

    async def body(addon, tctx):
        flow = post()
        got = addon.test_rule(rule(), flow)
        assert got["matches"] is True and "500" in got["result"]
        assert addon.rule_stats()["orders500"]["matches"] == 0 and flow.response is None
        assert addon.test_rule(rule(match={"method": "GET"}), flow)["matches"] is False
        assert "error" in addon.test_rule(rule(name=""), flow)

    scenario(body, qa_rules_file=str(file))


# Breakpoints (spec 022, slice D)

PAUSE = {"type": "pause", "status": 200, "body": "", "mock_file": "", "delay_ms": 0}


class FakeWindow:
    """The window addon's side of a pause: it may refuse, and it registers what paused."""
    name = "wiretraceui"

    def __init__(self, refusal=None):
        self.refusal = refusal
        self.held: list[tuple[str, str]] = []
        self.originals: list = []

    def pause_refusal(self):
        return self.refusal

    def paused(self, flow, phase, original=None):
        self.held.append((flow.id, phase))
        self.originals.append(original)


def pause_scenario(tmp_path, body, pause_at="request", window=None, **options):
    file = tmp_path / "rules.json"
    write_rules(file, rule(action={**PAUSE, "pause_at": pause_at}))

    async def run(addon, tctx):
        if window is not None:
            tctx.master.addons.add(window)
        await body(addon, tctx)

    scenario(run, qa_rules_file=str(file), **{"qa_breakpoints": True, **options})


def with_response(flow):
    flow.response = tflow.tresp()
    return flow


@pytest.mark.parametrize("pause_at, at_request, at_response", [
    ("request", True, False), ("response", False, True), ("both", True, True)])
def test_022_d_a_pause_rule_holds_the_flow_at_its_phase(tmp_path, pause_at, at_request, at_response):
    window = FakeWindow()

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        assert flow.intercepted is at_request and flow.response is None
        flow.resume()
        answering = asyncio.create_task(addon.response(with_response(flow)))
        await asyncio.sleep(0.01)
        assert flow.intercepted is at_response and answering.done() is not at_response
        flow.resume()
        await asyncio.wait_for(answering, 1)
        phases = [phase for _, phase in window.held]
        assert phases == [p for p, on in (("request", at_request), ("response", at_response)) if on]
        expected = ["rule: Orders fail"] + [f"breakpoint: {p}" for p in phases]
        assert flow.comment == "; ".join(expected)
        assert qa_tools.PAUSE_KEY not in flow.metadata

    pause_scenario(tmp_path, body, pause_at, window)


@pytest.mark.parametrize("window, option, reason", [
    (FakeWindow("10 already paused"), True, "10 already paused"),
    (None, True, "no window"),
    (FakeWindow(), False, "no window"),
])
def test_022_d_a_match_that_cannot_pause_passes_with_its_comment(tmp_path, window, option, reason):
    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        assert not flow.intercepted and flow.response is None
        assert flow.comment == f"rule: Orders fail; breakpoint: not paused, {reason}"
        assert not (window and window.held)

    pause_scenario(tmp_path, body, window=window, qa_breakpoints=option)


def test_022_d_replays_and_websocket_handshakes_are_never_paused(tmp_path):
    window = FakeWindow()

    async def body(addon, tctx):
        replayed = post()
        replayed.is_replay = "request"
        socket = post(headers={"Upgrade": "websocket", "Connection": "Upgrade"})
        for flow in (replayed, socket):
            await addon.request(flow)
            assert not flow.intercepted and "breakpoint" not in flow.comment
        assert window.held == []

    pause_scenario(tmp_path, body, pause_at="both", window=window)


def test_022_d_pause_rules_parse_and_old_files_still_load():
    for field, action in (("action.delay_ms", {**PAUSE, "delay_ms": 100}),
                          ("action.pause_at", {**PAUSE, "pause_at": "later"}),
                          ("action.pause_at", {**PAUSE, "pause_at": 1})):
        got = parse(rule(action=action))
        assert isinstance(got, qa_tools.RuleError) and got.field == field
    paused = parse(rule(action=PAUSE)).rules[0]
    assert paused.pause_at == "request" and paused.data["action"]["pause_at"] == "request"
    assert qa_tools.describe(paused).startswith("Paused before it is sent")
    # A 0.9.1 rule keeps exactly its keys, so the file it is saved back to still loads in 0.9.1.
    assert parse(rule()).rules[0].data == rule()
    assert parse(rule(action={"pause_at": "request"})).rules[0].data == rule()


# Rewrite rules and the rule order (spec 022, slice E)

def rewrite_rule(rule_id="rewrite1", name="Premium", ops=None, action=None, **over):
    ops = ops if ops is not None else [
        {"on": "request", "op": "set_header", "name": "X-Feature", "value": "on"},
        {"on": "response", "op": "set_json", "path": "data.isPremium", "value": "true"}]
    return rule(id=rule_id, name=name, action={"type": "rewrite", "status": 200, "body": "", "mock_file": "",
                                               "delay_ms": 0, "ops": ops, **(action or {})}, **over)


def server_answer(flow, body=b'{"data": {"isPremium": false}}', **headers):
    flow.response = tflow.tresp()
    flow.response.headers["Content-Type"] = "application/json"
    for name, value in headers.items():
        flow.response.headers[name] = value
    flow.response.content = body
    return flow


def test_022_e_rewrite_changes_the_request_now_and_the_response_later(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rewrite_rule())

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        assert flow.response is None and flow.request.headers["X-Feature"] == "on"
        assert flow.comment == "rewrite: Premium (2 changes)"
        assert qa_tools.REWRITE_KEY in flow.metadata
        await addon.response(server_answer(flow))
        assert json.loads(flow.response.content) == {"data": {"isPremium": True}}
        assert qa_tools.REWRITE_KEY not in flow.metadata
        changes = flow.metadata[qa_tools.CHANGES_KEY]
        assert [(c["on"], c["op"], c["target"], c["applied"]) for c in changes] == [
            ("request", "set_header", "X-Feature", True), ("response", "set_json", "data.isPremium", True)]
        assert addon.rule_stats()["rewrite1"] == {**addon.rule_stats()["rewrite1"], "matches": 1, "applied": 1}

    scenario(body, qa_rules_file=str(file))


def test_022_e_change_rules_stack_and_an_answer_ends_the_walk(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file,
                rewrite_rule("rewrite1", "One", [{"on": "request", "op": "add_header", "name": "X-A", "value": "1"}]),
                rule(id="slowrule", name="Slow", action={"type": "delay", "delay_ms": 20}),
                rewrite_rule("rewrite2", "Two", [{"on": "request", "op": "add_header", "name": "X-A", "value": "2"}]))

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        # The delay answers: the walk ends there, so the second Rewrite is neither counted nor applied.
        assert flow.request.headers.get_all("X-A") == ["1"]
        assert flow.comment == "rule: Slow; fault: delay 20 ms; rewrite: One (1 change)"
        stats = addon.rule_stats()
        assert (stats["rewrite1"]["applied"], stats["slowrule"]["applied"], stats["rewrite2"]["matches"]) == (1, 1, 0)

    scenario(body, qa_rules_file=str(file))


def test_022_e_a_request_answered_by_wiretrace_is_never_rewritten(tmp_path, mocks):
    file = tmp_path / "rules.json"
    write_rules(file, rewrite_rule(apply={"mode": "once"}),
                rule(id="status50", action={"status": 503}, match={"method": "POST", "path": "/api/v1/orders"}))

    async def body(addon, tctx):
        answered = post()
        await addon.request(answered)
        assert answered.response.status_code == 503 and "X-Feature" not in answered.request.headers
        assert "rewrite" not in answered.comment and qa_tools.CHANGES_KEY not in answered.metadata
        await addon.response(answered)
        assert json.loads(answered.response.content) == {"error": "injected by Wiretrace"}
        # A once rule not applied stays armed.
        assert addon.rule_stats()["rewrite1"] == {**addon.rule_stats()["rewrite1"], "matches": 1, "applied": 0}
        mocked = make_flow()
        mocked_rules = [rewrite_rule(match={"method": "GET", "path": "/api/v1/profile"})]
        write_rules(file, *mocked_rules)
        addon.reload_rules()
        await addon.request(mocked)
        assert mocked.marked == qa_tools.MOCK_MARK and "X-Feature" not in mocked.request.headers

    scenario(body, qa_rules_file=str(file), qa_mocks_dir=str(mocks))


def test_022_e_response_changes_skip_a_mock_and_a_non_json_body_and_keep_gzip(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rewrite_rule())

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        compressed = server_answer(flow)
        compressed.response.headers["Content-Encoding"] = "gzip"
        compressed.response.content = b'{"data": {"isPremium": false}, "price": 1.50}'
        await addon.response(compressed)
        assert compressed.response.headers["Content-Encoding"] == "gzip"
        assert gzip.decompress(compressed.response.raw_content) == b'{"data":{"isPremium":true},"price":1.5}'
        assert compressed.response.headers["Content-Length"] == str(len(compressed.response.raw_content))

        html = post()
        await addon.request(html)
        await addon.response(server_answer(html, b"<html></html>", **{"Content-Type": "text/html"}))
        assert html.response.content == b"<html></html>"
        assert html.metadata[qa_tools.CHANGES_KEY][-1]["reason"] == "body is not JSON"

        mocked = post()
        await addon.request(mocked)
        mocked.response = mhttp.Response.make(200, b'{"data": {"isPremium": false}}', qa_tools.JSON)
        mocked.marked = qa_tools.MOCK_MARK
        await addon.response(mocked)
        assert json.loads(mocked.response.content) == {"data": {"isPremium": False}}

    scenario(body, qa_rules_file=str(file))


def test_022_e_a_pause_sees_the_rewritten_request_and_its_original_the_one_before(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rewrite_rule(), rule(id="pauserul", name="Hold", action={**PAUSE, "pause_at": "both"}))
    window = FakeWindow()

    async def body(addon, tctx):
        tctx.master.addons.add(window)
        flow = post()
        await addon.request(flow)
        assert flow.intercepted and flow.request.headers["X-Feature"] == "on"
        assert "X-Feature" not in window.originals[0].headers
        flow.resume()
        answering = asyncio.create_task(addon.response(server_answer(flow)))
        await asyncio.sleep(0.01)
        assert json.loads(flow.response.content)["data"]["isPremium"] is True
        assert json.loads(window.originals[1].content)["data"]["isPremium"] is False
        flow.resume()
        await asyncio.wait_for(answering, 1)

    scenario(body, qa_rules_file=str(file), qa_breakpoints=True)


def test_022_e_rewrite_rules_parse_and_files_without_them_keep_0_9_1_keys():
    assert parse(rewrite_rule(ops=[])).field == "action.ops"
    assert parse(rewrite_rule(ops=[{"on": "request", "op": "set_header", "name": "Host", "value": "x"}])).field \
        == "action.ops.0.name"
    assert parse(rewrite_rule(action={"delay_ms": 10})).field == "action.delay_ms"
    parsed = parse(rewrite_rule()).rules[0]
    assert parsed.data["action"]["ops"] == rewrite_rule()["action"]["ops"] and len(parsed.ops) == 2
    assert qa_tools.describe(parsed) == "The server's response, with 2 changes to the request and the response"
    for plain in (rule(), rule(action={"type": "delay", "delay_ms": 5}), rule(action={"type": "drop"})):
        assert set(parse(plain).rules[0].data["action"]) == set(RULE["action"])


def test_022_e_an_error_drops_the_pending_response_changes(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, rewrite_rule())

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        addon.error(flow)
        assert qa_tools.REWRITE_KEY not in flow.metadata

    scenario(body, qa_rules_file=str(file))


def test_a_missing_rules_file_means_no_rules(tmp_path):
    async def body(addon, tctx):
        assert addon.rules.rules == () and addon.rules_error == ""
        flow = post()
        await addon.request(flow)
        assert flow.response is None

    scenario(body, qa_rules_file=str(tmp_path / "missing.json"))


# Logging and files

def test_addon_logs_only_counts_and_states(caplog, mocks):
    async def body(addon, tctx):
        for flow in (make_flow(request_headers={"X-Request-ID": "secret-id"}), make_flow(path="/orders")):
            await addon.request(flow)
        tctx.configure(addon, qa_fault_status=0)

    with caplog.at_level(logging.DEBUG):
        scenario(body, qa_mocks_dir=str(mocks), qa_fault_filter="~u /orders", qa_fault_status=500)

    messages = [r.getMessage() for r in caplog.records if r.name == qa_tools.__name__]
    assert "Wiretrace QA: 1 API hosts, mocks on, faults on, 0 rules on" in messages
    assert "Wiretrace QA: 1 API hosts, mocks on, faults off, 0 rules on" in messages
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
        # The real process names no qa_data_dir, so the mocks must live inside the data folder it resolves.
        self.mocks_dir = Path(tempfile.mkdtemp(prefix=".test-mocks-", dir=datadir.DATA_DIR / datadir.MOCKS))
        shutil.copytree(mocks, self.mocks_dir, dirs_exist_ok=True)
        args = [str(VENV_BIN / "mitmdump"), "--mode", "regular", "--listen-port", str(self.port),
                "--set", f"confdir={tmp_path / 'confdir'}", "-s", str(ROOT / "addons" / "qa_tools.py"),
                "--set", "qa_api_hosts=127.0.0.1", "--set", f"qa_mocks_dir={self.mocks_dir}"]
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
        shutil.rmtree(self.mocks_dir, ignore_errors=True)


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
def test_real_mitmdump_applies_a_rule_from_the_rules_file(tmp_path, mocks):
    # Incident 2026-10-14: the rule value types must load in a `-s` script, not only in an import.
    file = tmp_path / "rules" / "staging.json"
    write_rules(file, rule(match={"method": "GET", "path": "/ruled*"}, apply={"mode": "once"},
                           action={"status": 503, "body": '{"error": "ruled"}'}))
    proxy = Proxy(tmp_path, mocks, f"qa_rules_file={file}")
    try:
        assert proxy.get("/ruled?x=1") == (503, b'{"error": "ruled"}', "application/json")
        assert _Backend.hits == []
        assert proxy.get("/ruled")[:2] == (200, b"backend")
        assert _Backend.hits == ["/ruled"]
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


def test_lowercase_and_nonstandard_methods_serve_no_mock(mocks):
    assert qa_tools.mock_file(str(mocks), "GET", "/api/v1/profile") is not None
    for method in ("get", "trace", "TRACE", "CONNECT"):
        assert qa_tools.mock_file(str(mocks), method, "/api/v1/profile") is None

    async def body(addon, tctx):
        for method in ("get", "TRACE"):
            flow = make_flow(method=method)
            await addon.request(flow)
            assert flow.response is None

    scenario(body, qa_mocks_dir=str(mocks))


def test_a_mocks_dir_that_resolves_outside_the_wiretrace_folder_is_ignored(tmp_path):
    link = tmp_path / "escape"
    link.symlink_to("/")
    assert qa_tools.mock_file(str(link), "GET", "/etc/passwd") is None
    assert qa_tools.resolve_mock(str(link), "GET/etc/passwd.json") is None


# Map remote (spec 022, slice G)

STAGING = "staging-api.example.net"


def map_rule(rule_id="maprule1", name="Staging", target=None, **over):
    target = {"scheme": "https", "host": STAGING, "port": 443, **(target or {})}
    action = {"type": "map_remote", "status": 200, "body": "", "mock_file": "", "delay_ms": 0, "target": target,
              **over.pop("action", {})}
    return rule(id=rule_id, name=name, action=action, **over)


@pytest.fixture
def staging_resolves(monkeypatch):
    """STAGING and any other name resolve to the addresses in `.answer`; this Mac is 198.51.100.7."""
    found = {"answer": ["203.0.113.10"], "asked": []}

    async def lookup(host: str):
        found["asked"].append(host)
        return [(0, 0, 0, "", (address, 0)) for address in found["answer"]]

    monkeypatch.setattr(qa_tools.guard, "_lookup", lookup)
    monkeypatch.setattr(qa_tools.guard, "own_addresses", lambda: frozenset({"198.51.100.7"}))
    return found


@pytest.mark.parametrize("host", ["localhost", "api.localhost", "printer.local", "10.0.0.5", "127.0.0.1", "::1", "[::1]",
                                  "100.64.0.1", "172.16.0.1", "192.168.1.20", "169.254.1.1", "fe80::1", "fc00::1",
                                  "fd12::1", "0.0.0.0", "::", "224.0.0.1", "ff02::1", "::ffff:10.0.0.1", "LOCALHOST."])
def test_022_g_a_target_on_this_macs_network_is_refused_on_save(host):
    got = parse(map_rule(target={"host": host}))
    assert (got.field, got.message) == ("action.target.host", "must not be this Mac or an address on your network")


@pytest.mark.parametrize("target, field", [
    ({"host": ""}, "action.target.host"), ({"host": "staging"}, "action.target.host"),
    ({"host": "-a.example.com"}, "action.target.host"), ({"host": "a_b.example.com"}, "action.target.host"),
    ({"host": "a..example.com"}, "action.target.host"), ({"host": "1.2.3"}, "action.target.host"),
    ({"host": "https://x.example.com"}, "action.target.host"), ({"host": "x.example.com/v1"}, "action.target.host"),
    ({"host": "x.example.com:8443"}, "action.target.host"), ({"host": "ü.example.com"}, "action.target.host"),
    ({"host": 7}, "action.target.host"), ({"port": 0}, "action.target.port"), ({"port": 65536}, "action.target.port"),
    ({"port": "443"}, "action.target.port"), ({"port": True}, "action.target.port"),
    ({"scheme": "ftp"}, "action.target.scheme"), ({"extra": 1}, "action.target.extra"),
    ({"host": HOST}, "action.target.host"),
])
def test_022_g_target_checks_name_the_field(target, field):
    got = parse(map_rule(target=target, match={"method": "POST", "host": HOST, "path": "/api/v1/orders"}))
    assert isinstance(got, qa_tools.RuleError) and got.field == field, got


def test_022_g_target_is_normalized_and_its_shape_checked():
    data = parse(map_rule(target={"host": "Staging-API.Example.net."})).rules[0].data
    assert data["action"]["target"] == {"scheme": "https", "host": STAGING, "port": 443}
    assert parse(map_rule(target={"host": "[2606:4700::1]"})).rules[0].target.url == "https://[2606:4700::1]"
    # The matched host on another port is another server.
    assert not isinstance(parse(map_rule(target={"host": HOST, "port": 8443},
                                         match={"method": "ANY", "host": HOST, "path": "/*"})), qa_tools.RuleError)
    assert parse(map_rule(action={"delay_ms": 10})).field == "action.delay_ms"
    missing = map_rule()
    del missing["action"]["target"]
    assert parse(missing).field == "action.target.host"
    assert parse(rule(action={"target": {"host": STAGING}})).rules[0].data == rule()
    described = parse(map_rule(target={"scheme": "http", "port": 8080})).rules[0]
    assert qa_tools.describe(described) == f"The response of http://{STAGING}:8080, with the same path and query"


def test_022_g_a_mapped_request_goes_to_the_target_and_keeps_the_asked_host(tmp_path, staging_resolves):
    file = tmp_path / "rules.json"
    write_rules(file, map_rule(target={"port": 8443}), rewrite_rule())

    async def body(addon, tctx):
        assert addon.map_targets() == {STAGING}
        flow = post("/api/v1/orders?page=2")
        flow.request.scheme, flow.request.port = "https", 443
        flow.request.headers["Host"] = HOST
        await addon.request(flow)
        req = flow.request
        assert (req.scheme, req.host, req.port, req.path) == ("https", STAGING, 8443, "/api/v1/orders?page=2")
        assert req.host_header == f"{STAGING}:8443" and req.headers["X-Feature"] == "on"
        assert flow.metadata[qa_tools.MAPPED_KEY] == {"from": HOST, "to": f"https://{STAGING}:8443",
                                                      "rule": "Staging", "from_scheme": "https",
                                                      "from_port": 443}
        assert flow.comment == f"map remote: {HOST} → {STAGING}:8443; rewrite: Premium (2 changes)"
        assert staging_resolves["asked"] == [STAGING]
        # The response hook still knows the request was to an API host: response rewrites run.
        await addon.response(server_answer(flow))
        assert json.loads(flow.response.content) == {"data": {"isPremium": True}}
        stats = addon.rule_stats()
        assert (stats["maprule1"]["applied"], stats["rewrite1"]["applied"]) == (1, 1)

    scenario(body, qa_rules_file=str(file))


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "::1", "198.51.100.7"])
def test_022_g_a_target_resolving_to_this_macs_network_is_answered_502(tmp_path, staging_resolves, address):
    file = tmp_path / "rules.json"
    write_rules(file, map_rule(), rewrite_rule())
    staging_resolves["answer"] = ["203.0.113.10", address]

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        assert flow.request.host == HOST and "X-Feature" not in flow.request.headers
        assert flow.response.status_code == 502
        assert json.loads(flow.response.content) == {"error": "Wiretrace refuses Map remote to an address on your network"}
        assert flow.comment == "map remote: refused, local address"
        assert qa_tools.MAPPED_KEY not in flow.metadata and qa_tools.CHANGES_KEY not in flow.metadata
        await addon.response(flow)
        assert flow.response.status_code == 502
        stats = addon.rule_stats()
        assert (stats["maprule1"]["applied"], stats["rewrite1"]["applied"]) == (0, 0)

    scenario(body, qa_rules_file=str(file))


def test_022_g_only_the_first_map_remote_applies(tmp_path, staging_resolves):
    file = tmp_path / "rules.json"
    write_rules(file, map_rule(), map_rule("maprule2", "Other", target={"host": "other.example.org"}))

    async def body(addon, tctx):
        flow = post()
        await addon.request(flow)
        assert flow.request.host == STAGING and flow.comment == f"map remote: {HOST} → {STAGING}"
        stats = addon.rule_stats()
        assert (stats["maprule2"]["matches"], stats["maprule2"]["applied"]) == (1, 0)

    scenario(body, qa_rules_file=str(file))


def test_022_g_no_map_for_a_websocket_handshake_an_answered_request_or_a_replay(tmp_path, staging_resolves, mocks):
    file = tmp_path / "rules.json"
    write_rules(file, map_rule(match={"method": "ANY", "path": "/*"}))

    async def body(addon, tctx):
        socket_flow = make_flow(path="/socket")
        socket_flow.request.headers["Upgrade"] = "websocket"
        await addon.request(socket_flow)
        assert socket_flow.request.host == HOST and not socket_flow.comment
        mocked = make_flow()
        await addon.request(mocked)
        assert mocked.request.host == HOST and mocked.response is not None and "map remote" not in mocked.comment
        replayed = post()
        replayed.is_replay = "request"
        await addon.request(replayed)
        assert replayed.request.host == HOST
        assert staging_resolves["asked"] == []
        assert addon.rule_stats()["maprule1"]["applied"] == 0

    scenario(body, qa_rules_file=str(file), qa_mocks_dir=str(mocks))


def test_022_g_a_pause_sees_the_mapped_request_and_its_original(tmp_path, staging_resolves):
    file = tmp_path / "rules.json"
    write_rules(file, map_rule(), rule(id="pause001", name="Hold", action={"type": "pause", "pause_at": "request"}))
    window = FakeWindow()

    async def body(addon, tctx):
        tctx.master.addons.add(window)
        flow = post()
        await addon.request(flow)
        assert window.held == [(flow.id, "request")]
        assert flow.request.host == STAGING and window.originals[0].host == HOST

    scenario(body, **{"qa_rules_file": str(file), "qa_breakpoints": True})


def test_022_g_disabled_map_rules_are_not_targets(tmp_path):
    file = tmp_path / "rules.json"
    write_rules(file, map_rule(enabled=False), map_rule("maprule2", target={"host": "other.example.org"}))

    async def body(addon, tctx):
        assert addon.map_targets() == {"other.example.org"}

    scenario(body, qa_rules_file=str(file))
