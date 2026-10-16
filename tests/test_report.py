import io as std_io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from mitmproxy import io
from mitmproxy.test import tflow

from cli import report, report_text, session

NOW = datetime(2026, 10, 14, 12, 0, 0)
NAME = "2026-10-14_091500_staging_android"
PRESET = "name: staging\napi_hosts:\n  - api.example.com\nredact:\n  headers: [X-Trace-Id]\n  json_fields: [otp]\n"


def flow(path="/orders", status=200, comment="", request_headers=None, response_headers=None,
         body=b"", request_body=b"", method="GET", error=False):
    f = tflow.tflow(resp=not error, err=error)
    f.request.method = method
    f.request.host = "api.example.com"
    f.request.path = path
    f.request.content = request_body
    for name, value in (request_headers or {}).items():
        f.request.headers[name] = value
    if f.response:
        f.response.status_code = status
        f.response.content = body
        for name, value in (response_headers or {}).items():
            f.response.headers[name] = value
    f.comment = comment
    return f


def write_flows(path: Path, flows: list) -> None:
    with open(path, "wb") as out:
        writer = io.FlowWriter(out)
        for f in flows:
            writer.add(f)


@pytest.fixture
def env(tmp_path):
    sessions, presets = tmp_path / "sessions", tmp_path / "presets"
    sessions.mkdir()
    presets.mkdir()
    (presets / "staging.yaml").write_text(PRESET)
    return sessions, presets


def make_session(sessions: Path, flows=None, name=NAME, meta=None, logs=None) -> Path:
    folder = sessions / name
    folder.mkdir()
    base = {"wiretrace_version": "0.5.0", "preset": "staging", "target": "android", "mode": "proxy",
            "started_at": "2026-10-14T09:15:00+07:00", "ended_at": "2026-10-14T09:20:00+07:00", "status": "stopped"}
    (folder / session.META).write_text(json.dumps({**base, **(meta or {})}))
    if flows is not None:
        write_flows(folder / session.FLOWS, flows)
    for log, lines in (logs or {}).items():
        (folder / log).write_text("".join(line + "\n" for line in lines))
    return folder


def run(env, arg=None, **kwargs) -> int:
    sessions, presets = env
    return report.run(arg, sessions, presets, now=NOW, **kwargs)


def open_zip(folder: Path, name: str = NAME) -> zipfile.ZipFile:
    return zipfile.ZipFile(folder / f"{name}-report.zip")


def member(archive: zipfile.ZipFile, name: str, folder: str = NAME) -> str:
    return archive.read(f"{folder}/{name}").decode()


def table_rows(summary: str) -> list[list[str]]:
    lines = [line for line in summary.splitlines() if line.startswith("| ")][1:]
    return [[c.strip() for c in line.strip("|").split(" | ")] for line in lines]


def test_members_and_folder_name(env):
    folder = make_session(env[0], [flow()], logs={session.DEVICE_LOG: ['{"message": "a"}'],
                                                  session.APP_LOG: ['{"message": "b"}']})
    assert run(env) == 0
    with open_zip(folder) as archive:
        assert sorted(archive.namelist()) == sorted(f"{NAME}/{m}" for m in (
            "summary.md", "flows.har", "device.log.jsonl", "app.log.jsonl", "meta.json"))
        assert member(archive, "meta.json") == (folder / session.META).read_text()
    assert not (folder / f"{NAME}-report.zip.tmp").exists()


def test_the_status_file_is_never_packed(env):
    folder = make_session(env[0], [flow()])
    (folder / session.STATUS).write_text('{"v": 1, "last_error": "flow-1"}\n')
    assert run(env) == 0
    with open_zip(folder) as archive:
        assert all(not name.endswith(session.STATUS) for name in archive.namelist())


def test_flows_mitm_is_never_in_the_zip_and_log_files_only_when_they_have_lines(env):
    folder = make_session(env[0], [flow()], logs={session.DEVICE_LOG: ["", "  "]})
    assert run(env) == 0
    with open_zip(folder) as archive:
        names = archive.namelist()
    assert not any("flows.mitm" in n for n in names)
    assert f"{NAME}/device.log.jsonl" not in names and f"{NAME}/app.log.jsonl" not in names


def test_har_is_rebuilt_and_masked_and_flows_mitm_keeps_the_originals(env):
    folder = make_session(env[0], [flow(
        method="POST", request_headers={"Authorization": "Bearer fake-token", "X-Api-Key": "fake-key"},
        request_body=json.dumps({"password": "fake-pw", "otp": "123456", "user": "ann"}).encode(),
        response_headers={"Set-Cookie": "sid=fake-sid"},
        body=json.dumps({"access_token": "fake-access"}).encode())])
    assert run(env) == 0
    with open_zip(folder) as archive:
        har_text = member(archive, "flows.har")
        assert not any(n.endswith("flows.mitm") for n in archive.namelist())
    for secret in ("fake-token", "fake-key", "fake-pw", "123456", "fake-sid", "fake-access"):
        assert secret not in har_text
    assert "ann" in har_text
    assert len(json.loads(har_text)["log"]["entries"]) == 1
    assert b"fake-token" in (folder / session.FLOWS).read_bytes()


def test_summary_session_counts_and_masked_names(env):
    make_session(env[0], [flow(), flow(status=500)], logs={session.APP_LOG: ['{"message": "a"}'] * 3})
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        summary = member(archive, "summary.md")
    for expected in ("Preset: staging", "Target: android", "Mode: proxy", "Started: 2026-10-14T09:15:00+07:00",
                     "Ended: 2026-10-14T09:20:00+07:00", "Status: stopped", "Wiretrace version: 0.5.0",
                     "Requests: 2", "(status 400 or higher, or no response): 1", "Mocked by Wiretrace: 0",
                     "Faulted by Wiretrace: 0", "Log lines: 3", "X-Trace-Id", "Set-Cookie", "otp", "access_token"):
        assert expected in summary


def test_failed_rows_for_a_500_a_fault_a_no_response_and_a_request_id(env):
    make_session(env[0], [
        flow("/ok", 200),
        flow("/boom?token=abc", 500, request_headers={"X-Request-ID": "req-7"}),
        flow("/faulted", 500, comment="request-id: req-8; fault: status 500"),
        flow("/answer-header", 404, response_headers={"X-Request-ID": "resp-9"}),
        flow("/dead", error=True),
        flow("/mocked", 200, comment="mock: GET/mocked.json"),
    ])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        summary = member(archive, "summary.md")
    rows = {row[3]: row for row in table_rows(summary)}
    assert list(rows) == ["/boom", "/faulted", "/answer-header", "/dead"]
    assert rows["/boom"][1:3] == ["GET", "api.example.com"]
    assert rows["/boom"][4] == "500" and rows["/boom"][6] == "req-7" and rows["/boom"][7] == "-"
    assert rows["/faulted"][7] == "Wiretrace fault: status 500"
    assert rows["/answer-header"][4] == "404" and rows["/answer-header"][6] == "resp-9"
    assert rows["/dead"][4] == "no response (error)" and rows["/dead"][7] == "-"
    assert "token=abc" not in summary and "/ok" not in summary and "/mocked" not in summary
    assert rows["/boom"][0].startswith("20") and rows["/boom"][5].endswith(" ms")


def test_mocked_and_faulted_counts_come_from_the_comment_parts(env):
    make_session(env[0], [
        flow("/a", 200, comment="request-id: 1; mock: GET/a.json"),
        flow("/b", 500, comment="fault: status 500"),
        flow("/c", 200, comment="request-id: 3; fault: delay 300 ms"),
        flow("/d", 200, comment="fault: dropped; mock: GET/d.json"),
        flow("/e", 200, comment="a mock: note, not a part"),
        flow("/f", 200),
    ])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        summary = member(archive, "summary.md")
    assert "Mocked by Wiretrace: 2" in summary and "Faulted by Wiretrace: 3" in summary


def test_table_cells_escape_pipes_and_newlines(env):
    make_session(env[0], [flow("/a|b", 500, comment="fault: x|y\nz")])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        summary = member(archive, "summary.md")
    assert "/a\\|b" in summary and "Wiretrace fault: x\\|y z" in summary
    assert all(len(row) == 8 for row in table_rows(summary))


def test_the_table_is_capped_at_100_rows(env):
    make_session(env[0], [flow(f"/p{i}", 500) for i in range(130)])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        summary = member(archive, "summary.md")
    assert len(table_rows(summary)) == 100 and "/p99" in summary and "/p100" not in summary
    assert "and 30 more" in summary and "Failed (status 400 or higher, or no response): 130" in summary


def test_no_failed_request(env):
    make_session(env[0], [flow()])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        assert "No failed requests." in member(archive, "summary.md")


def test_latest_session_by_default(env):
    make_session(env[0], [flow()], name="2026-10-13_090000_staging_android")
    newest = make_session(env[0], [flow()], name="2026-10-14_090000_staging_ios")
    assert run(env) == 0
    assert (newest / "2026-10-14_090000_staging_ios-report.zip").is_file()
    assert not (env[0] / "2026-10-13_090000_staging_android" / "2026-10-13_090000_staging_android-report.zip").exists()


def test_session_by_name_and_by_path(env, tmp_path):
    first = make_session(env[0], [flow()], name="2026-10-13_090000_staging_android")
    make_session(env[0], [flow()])
    assert run(env, "2026-10-13_090000_staging_android") == 0
    assert (first / "2026-10-13_090000_staging_android-report.zip").is_file()

    elsewhere = make_session(tmp_path, [flow()], name="2026-10-12_090000_staging_device")
    assert run(env, str(elsewhere)) == 0
    assert (elsewhere / "2026-10-12_090000_staging_device-report.zip").is_file()


def test_a_bare_name_is_never_taken_from_the_current_folder(env, tmp_path, monkeypatch, capsys):
    planted = make_session(tmp_path, [flow()], name="2026-10-11_090000_staging_android")
    monkeypatch.chdir(tmp_path)
    assert run(env, planted.name) == 1
    assert "Unknown session" in capsys.readouterr().err
    assert not list(planted.glob("*.zip"))


def test_unknown_session_exits_1(env, capsys):
    assert run(env, "2020-01-01_000000_none_android") == 1
    assert "Unknown session" in capsys.readouterr().err


def test_no_sessions_exits_1(env, capsys):
    assert run(env) == 1
    assert "No sessions to report" in capsys.readouterr().err


def test_folder_without_meta_json_exits_1(env, capsys):
    (env[0] / NAME).mkdir()
    assert run(env, NAME) == 1
    assert "meta.json" in capsys.readouterr().err
    assert list((env[0] / NAME).iterdir()) == []


def test_unreadable_meta_json_exits_1(env, capsys):
    folder = make_session(env[0], [flow()])
    (folder / session.META).write_text("{not json")
    assert run(env) == 1
    assert "meta.json" in capsys.readouterr().err


def test_nothing_to_report_exits_1_without_a_zip(env, capsys):
    folder = make_session(env[0], None, logs={session.DEVICE_LOG: [""]})
    assert run(env) == 1
    assert "Nothing to report: the session has no traffic and no log lines." in capsys.readouterr().err
    assert not list(folder.glob("*.zip*"))


def test_empty_flows_file_and_no_logs_is_nothing_to_report(env):
    folder = make_session(env[0], [])
    assert run(env) == 1
    assert not list(folder.glob("*.zip*"))


def test_logs_only_session_has_no_har(env):
    folder = make_session(env[0], None, logs={session.APP_LOG: ['{"message": "hello"}']})
    assert run(env) == 0
    with open_zip(folder) as archive:
        names = archive.namelist()
        assert f"{NAME}/flows.har" not in names and f"{NAME}/app.log.jsonl" in names
        assert "Requests: 0" in member(archive, "summary.md")


def test_cut_off_flows_file_gives_a_partial_report(env, capsys):
    folder = make_session(env[0], [flow("/one", 500), flow("/two", 500), flow("/three", 500)])
    data = (folder / session.FLOWS).read_bytes()
    (folder / session.FLOWS).write_bytes(data[:-40])
    assert run(env) == 0
    out = capsys.readouterr().out
    assert "ends early" in out
    with open_zip(folder) as archive:
        summary = member(archive, "summary.md")
        entries = json.loads(member(archive, "flows.har"))["log"]["entries"]
    assert "ends early" in summary and "/one" in summary and "/three" not in summary
    assert 1 <= len(entries) < 3


def test_cut_off_with_no_complete_flow_and_logs_still_reports(env):
    folder = make_session(env[0], [flow()], logs={session.APP_LOG: ['{"message": "a"}']})
    (folder / session.FLOWS).write_bytes((folder / session.FLOWS).read_bytes()[:20])
    assert run(env) == 0
    with open_zip(folder) as archive:
        assert f"{NAME}/flows.har" not in archive.namelist()
        assert "ends early" in member(archive, "summary.md")


def test_missing_preset_warns_and_applies_the_defaults(env, capsys):
    folder = make_session(env[0], [flow(
        request_headers={"Authorization": "Bearer fake-token", "X-Trace-Id": "fake-key"})],
        meta={"preset": "gone"})
    assert run(env) == 0
    err = capsys.readouterr().err
    assert "Warning" in err and "gone" in err and "default masking rules" in err
    with open_zip(folder) as archive:
        har_text = member(archive, "flows.har")
    assert "fake-token" not in har_text
    # The preset's own additions are not known any more, and this session recorded none.
    assert "fake-key" in har_text


def test_missing_preset_still_applies_the_rules_recorded_at_capture(env, capsys):
    folder = make_session(env[0], [flow(request_headers={"X-Trace-Id": "fake-key"})],
                          meta={"preset": "gone", "redact": {"headers": ["X-Trace-Id"], "json_fields": ["otp"]}})
    assert run(env) == 0
    assert "recorded" in capsys.readouterr().err
    with open_zip(folder) as archive:
        assert "fake-key" not in member(archive, "flows.har")
        assert "X-Trace-Id" in member(archive, "summary.md")


def test_preset_that_no_longer_loads_warns(env, capsys):
    (env[1] / "staging.yaml").write_text("name: staging\n")
    make_session(env[0], [flow()])
    assert run(env) == 0
    assert "Warning" in capsys.readouterr().err


def test_preset_rules_are_used_as_they_are_now(env):
    folder = make_session(env[0], [flow(request_headers={"X-Trace-Id": "fake-key"})])
    (env[1] / "staging.yaml").write_text(PRESET.replace("X-Trace-Id", "X-Other"))
    assert run(env) == 0
    with open_zip(folder) as archive:
        assert "fake-key" in member(archive, "flows.har")


def test_logs_are_masked_in_the_zip_and_the_session_files_are_unchanged(env):
    lines = [
        json.dumps({"ts": "t", "source": "app", "message": "sent Authorization: Bearer fake-token"}),
        json.dumps({"ts": "t", "source": "android", "message": 'body {"otp": "123456", "ok": 1}'}),
        "D/Net: password=fake-pw&x=1",
        json.dumps({"ts": "t", "message": "all fine"}),
    ]
    folder = make_session(env[0], None, logs={session.APP_LOG: lines})
    before = (folder / session.APP_LOG).read_bytes()
    assert run(env) == 0
    with open_zip(folder) as archive:
        text = member(archive, "app.log.jsonl")
    for secret in ("fake-token", "123456", "fake-pw"):
        assert secret not in text
    assert text.splitlines()[3] == lines[3]
    assert json.loads(text.splitlines()[0])["message"] == "sent Authorization: ***"
    assert (folder / session.APP_LOG).read_bytes() == before


def test_report_prints_the_path_counts_and_the_log_warning(env, capsys):
    folder = make_session(env[0], [flow(), flow(status=500, comment="fault: status 500")],
                          logs={session.APP_LOG: ['{"message": "a"}']})
    assert run(env) == 0
    out = capsys.readouterr().out
    assert str(folder / f"{NAME}-report.zip") in out
    assert "Requests: 2, failed: 1, mocked: 0, faulted: 1, log lines: 1" in out
    assert "Log lines are masked by pattern only; check them before sharing." in out


def test_an_existing_zip_is_replaced(env):
    folder = make_session(env[0], [flow()])
    (folder / f"{NAME}-report.zip").write_bytes(b"old")
    assert run(env) == 0
    with open_zip(folder) as archive:
        assert f"{NAME}/summary.md" in archive.namelist()


def test_write_failure_leaves_no_zip_or_temporary_file(env, monkeypatch, capsys):
    folder = make_session(env[0], [flow()])

    def broken(self, info, data, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", broken)
    assert run(env) == 1
    assert "Could not write the report: No space left on device" in capsys.readouterr().err
    assert not [p for p in folder.iterdir() if p.name.startswith(f"{NAME}-report")]


def test_failed_replace_leaves_no_temporary_file_and_keeps_the_old_zip(env, monkeypatch, capsys):
    folder = make_session(env[0], [flow()])
    (folder / f"{NAME}-report.zip").write_bytes(b"old")

    def broken(src, dst):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(report.os, "replace", broken)
    assert run(env) == 1
    assert "Could not write the report" in capsys.readouterr().err
    assert (folder / f"{NAME}-report.zip").read_bytes() == b"old"
    assert not (folder / f"{NAME}-report.zip.tmp").exists()


def test_report_hides_a_masked_request_id_header(env):
    (env[1] / "staging.yaml").write_text(PRESET.replace("X-Trace-Id", "X-Request-ID"))
    make_session(env[0], [flow("/boom", 500, request_headers={"X-Request-ID": "fake-id"})])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        assert "fake-id" not in member(archive, "summary.md")


def test_report_command_is_registered():
    from cli import __main__ as cli_main

    with pytest.raises(SystemExit) as info:
        cli_main.main(["report", "--help"])
    assert info.value.code == 0


def test_a_report_of_a_gzip_bomb_keeps_the_placeholder(env):
    import gzip
    import os
    from cli.bodies import HAR_LIMIT, PLACEHOLDER

    bomb = flow(body=b"")
    bomb.response.headers["Content-Encoding"] = "gzip"
    bomb.response.headers["Content-Type"] = "text/plain"
    bomb.response.raw_content = gzip.compress(b"X" * (HAR_LIMIT + 1))
    folder = make_session(env[0], [bomb])
    previous = os.umask(0o022)
    try:
        created = report.create(folder, env[1], now=NOW)
    finally:
        os.umask(previous)
    assert created.requests == 1
    assert created.zip.stat().st_mode & 0o777 == 0o600
    with open_zip(folder) as archive:
        har = json.loads(member(archive, "flows.har"))
    content = har["log"]["entries"][0]["response"]["content"]
    assert content["text"] == PLACEHOLDER
    assert "X" * 100 not in content["text"]


# The bug report form (spec 012): window, boxes, renderers, masking

T0 = 1_791_900_000.0
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"
SECRETS = ("fake-auth-value", "fake-pw-value", "fake-query-token", "fake-body-token", JWT, "fake-log-pw")


def at(f, offset: float, duration: float = 0.25):
    f.request.timestamp_start = T0 + offset
    f.request.timestamp_end = T0 + offset + 0.01
    if f.response is not None:
        f.response.timestamp_start = T0 + offset + duration - 0.01
        f.response.timestamp_end = T0 + offset + duration
    if f.error is not None:
        f.error.timestamp = T0 + offset + duration
    return f


def iso(offset: float) -> str:
    return datetime.fromtimestamp(T0 + offset).astimezone().isoformat(timespec="milliseconds")


def log(offset: float | None, message: str, **extra) -> str:
    record = {"message": message, "level": "I", "tag": "Net", **extra}
    if offset is not None:
        record["ts"] = iso(offset)
    return json.dumps(record)


def har_paths(data: bytes) -> list[str]:
    return [urlsplit(entry["request"]["url"]).path for entry in json.loads(data)["log"]["entries"]]


def draft(env, include, fmt="markdown"):
    return report.draft(env[0] / NAME, env[1], include, fmt, now=NOW)


def export(env, kind, include):
    return report.export(env[0] / NAME, env[1], kind, include, now=NOW)


# Window and boxes

def test_without_window_or_include_build_is_the_0_8_0_report_and_all_boxes_without_a_request_match_it(env):
    folder = make_session(env[0], [at(flow("/a"), 0), at(flow("/b", 500), 90)],
                          logs={session.DEVICE_LOG: [log(0, "d")], session.APP_LOG: [log(None, "no time")]})
    members, flows, lines, _ = report.build(folder, env[1])
    assert sorted(members) == sorted(["summary.md", session.HAR, session.DEVICE_LOG, session.APP_LOG, session.META])
    assert (flows.requests, lines) == (2, 2)
    assert report.build(folder, env[1], None, report.Include())[0] == members
    with zipfile.ZipFile(std_io.BytesIO(export(env, "zip", report.Include())[1])) as archive:
        assert sorted(archive.namelist()) == sorted(f"{NAME}/{m}" for m in members)
        assert {n.split("/", 1)[1]: archive.read(n) for n in archive.namelist()} == members


def test_the_window_includes_its_bounds_and_nothing_past_them(env):
    chosen = at(flow("/chosen", 500), 0)
    flows = [chosen, at(flow("/minus30"), -30), at(flow("/plus30"), 30),
             at(flow("/past-minus"), -30.001), at(flow("/past-plus"), 30.001)]
    logs = [log(-30, "in-a"), log(30, "in-b"), log(-30.01, "out-a"), log(30.01, "out-b"), log(None, "no time")]
    make_session(env[0], flows, logs={session.DEVICE_LOG: logs})
    include = report.Include(chosen.id)
    assert sorted(har_paths(export(env, "har", include)[1])) == ["/chosen", "/minus30", "/plus30"]
    device = export(env, "device-log", include)[1].decode()
    assert "in-a" in device and "in-b" in device
    assert not any(word in device for word in ("out-a", "out-b", "no time"))
    assert draft(env, include)["counts"] == {"others": 2, "device": 2, "app": 0}


def test_the_boxes_limit_the_files_and_the_reported_request_is_always_in(env):
    chosen = at(flow("/chosen", 500), 0)
    make_session(env[0], [chosen, at(flow("/other"), 5)],
                 logs={session.DEVICE_LOG: [log(1, "d")], session.APP_LOG: [log(2, "a")]})
    alone = report.Include(chosen.id, others=False, device=False, app=True)
    assert har_paths(export(env, "har", alone)[1]) == ["/chosen"]
    assert export(env, "device-log", alone) is None
    kinds = [f["kind"] for f in draft(env, alone)["files"]]
    assert kinds == ["har", "app-log", "zip"]
    with zipfile.ZipFile(std_io.BytesIO(export(env, "zip", alone)[1])) as archive:
        names = archive.namelist()
    assert f"{NAME}/{session.DEVICE_LOG}" not in names and f"{NAME}/{session.APP_LOG}" in names
    # The counts say what a box would add, whether it is on or not.
    assert draft(env, alone)["counts"] == {"others": 1, "device": 1, "app": 1}


def test_a_session_with_no_request_and_every_box_off_offers_no_file(env):
    make_session(env[0], [at(flow("/a"), 0)])
    assert draft(env, report.Include(None, False, False, False))["files"] == []
    assert export(env, "zip", report.Include(None, False, False, False)) is None


def test_an_unknown_request_is_said_so(env):
    make_session(env[0], [at(flow("/a"), 0)])
    with pytest.raises(report.UnknownRequest):
        draft(env, report.Include("not-a-saved-id"))


def test_file_sizes_in_the_draft_are_the_downloaded_bytes(env):
    chosen = at(flow("/chosen", 500, body=b'{"error": "x"}'), 0)
    make_session(env[0], [chosen, at(flow("/other"), 3)],
                 logs={session.DEVICE_LOG: [log(1, "d")], session.APP_LOG: [log(2, "a")]})
    include = report.Include(chosen.id)
    files = draft(env, include)["files"]
    assert [f["name"] for f in files] == [f"{NAME}-requests.har", f"{NAME}-device-log.txt",
                                          f"{NAME}-app-log.txt", f"{NAME}-report.zip"]
    for item in files:
        name, data = export(env, item["kind"], include)
        assert (name, len(data)) == (item["name"], item["size"])


# Text logs

def test_text_logs_are_time_level_tag_message_one_per_line():
    line = report.text_log_line(json.dumps({"ts": iso(0), "level": "E", "tag": "Checkout",
                                            "message": "order failed\nsecond line"}))
    clock = datetime.fromtimestamp(T0).strftime("%Y-%m-%d %H:%M:%S.000")
    assert line == f"{clock} E Checkout order failed second line"
    assert report.text_log_line('{"message": {"code": 1}}') == '- - - {"code": 1}'
    assert report.text_log_line("not json") == "not json"


# Invariant 1: masked everywhere

def secret_session(env):
    chosen = at(flow(
        "/api/v1/orders?token=fake-query-token&page=2", 500, method="POST",
        request_headers={"Authorization": "Bearer fake-auth-value", "X-Request-ID": "req-0010"},
        request_body=json.dumps({"password": "fake-pw-value"}).encode(),
        response_headers={"Content-Type": "application/json"},
        body=json.dumps({"error": "ORDER_FAILED", "token": "fake-body-token"}).encode()), 0)
    logs = {session.DEVICE_LOG: [log(1, f"auth {JWT}", request_id="req-0010")],
            session.APP_LOG: [log(2, "login password=fake-log-pw req-0010")]}
    make_session(env[0], [chosen, at(flow("/other", request_headers={"Authorization": "fake-auth-value"}), 4)],
                 logs=logs)
    return report.Include(chosen.id)


def test_no_secret_reaches_the_title_description_or_any_download(env):
    include = secret_session(env)
    texts = []
    for fmt in report_text.FORMATS:
        data = draft(env, include, fmt)
        texts += [data["title"], data["description"], json.dumps(data["lead"])]
        assert "returns 500" in data["title"] and "?" not in data["title"]
    for kind in ("har", "device-log", "app-log"):
        texts.append(export(env, kind, include)[1].decode())
    with zipfile.ZipFile(std_io.BytesIO(export(env, "zip", include)[1])) as archive:
        texts += [archive.read(n).decode() for n in archive.namelist() if not n.endswith(session.META)]
    for text in texts:
        for secret in SECRETS:
            assert secret not in text
    description = draft(env, include)["description"]
    assert "token=***" in description and "page=2" in description
    assert "req-0010" in description


def test_the_description_has_the_sections_and_linked_log_lines(env):
    include = secret_session(env)
    (env[0] / NAME / session.DEVICE_STATUS).write_text(json.dumps({"state": "streaming", "model": "Pixel 8",
                                                                    "os": "Android 15"}))
    data = draft(env, include)
    text = data["description"]
    for heading in ("## Steps to reproduce", "## Expected", "## Actual", "## Environment", "## Failed request",
                    "## Response body", "## Log lines"):
        assert heading in text
    assert "\n1. \n" in text
    assert "- Preset: staging · Target: android · Mode: proxy" in text
    assert "- Device: Pixel 8 · Android 15 · Wiretrace 0.5.0" in text
    assert "`POST api.example.com/api/v1/orders?token=***&page=2` → 500 · 250 ms · request ID `req-0010`" in text
    assert text.rstrip().endswith(report_text.LOG_NOTE)
    logged = text.split("## Log lines", 1)[1]
    assert "auth ***" in logged and "password=***" in logged
    assert data["lead"] == {"request": "POST /api/v1/orders → 500", "at": datetime.fromtimestamp(T0).strftime("%H:%M:%S"),
                            "device": "Pixel 8 · Android 15", "session": NAME}
    assert "Authorization" in data["masked"]["headers"] and "otp" in data["masked"]["fields"]


def test_no_more_than_20_linked_lines_and_none_without_a_request_id(env):
    chosen = at(flow("/a", 500, request_headers={"X-Request-ID": "rid-1"}), 0)
    plain = at(flow("/b", 500), 1)
    make_session(env[0], [chosen, plain], logs={session.APP_LOG: [log(1, f"n{i}", request_id="rid-1")
                                                                  for i in range(25)]})
    text = draft(env, report.Include(chosen.id))["description"]
    assert "n19" in text and "n20" not in text
    assert "no request ID" in draft(env, report.Include(plain.id))["description"]
    off = draft(env, report.Include(chosen.id, device=False, app=False))["description"]
    assert "n0" not in off and "Device and app logs are not included." in off


# Rendering

@pytest.mark.parametrize("fmt", report_text.FORMATS)
def test_captured_text_stays_inside_one_block(env, fmt):
    body = "start\n```\n``````` long run\n{code}\n{noformat}\n{CODE:java}\nend"
    chosen = at(flow("/x", 500, body=body.encode(), response_headers={"Content-Type": "text/plain"}), 0)
    make_session(env[0], [chosen])
    text = draft(env, report.Include(chosen.id), fmt)["description"]
    section = text.split("Response body", 1)[1].split("Log lines", 1)[0]
    if fmt == "markdown":
        fence = re.search(r"^(`{3,})", section.split("\n", 2)[2], re.M).group(1)
        assert len(fence) == 8
        inner = section.split(fence)[1]
        assert "start" in inner and "end" in inner
        assert section.count(fence) == 2
    else:
        assert len(re.findall(r"(?<!\\)\{(?:code|noformat)", section, re.IGNORECASE)) == 2
        assert "\\{code}" in section and "\\{noformat}" in section and "\\{CODE:java}" in section


def test_the_body_is_cut_at_4_kb_on_a_character_boundary(env):
    body = "a" + "€" * 2000
    chosen = at(flow("/x", 500, body=body.encode(), response_headers={"Content-Type": "text/plain; charset=utf-8"}), 0)
    make_session(env[0], [chosen])
    text = draft(env, report.Include(chosen.id))["description"]
    block = text.split("```\n", 1)[1].split("\n```", 1)[0]
    assert block == "a" + "€" * 1365 and len(block.encode()) <= report.BODY_LIMIT
    assert f"```\n{report_text.CUT_NOTE}" in text


def test_jira_for_a_request_with_no_response(env):
    chosen = at(flow("/gone", error=True), 0)
    make_session(env[0], [chosen])
    data = draft(env, report.Include(chosen.id), "jira")
    assert data["title"] == "GET /gone gets no response"
    assert "h2. Response body" not in data["description"] and "h2. Failed request" in data["description"]
    assert "h2. Steps to reproduce" in data["description"] and "\n# \n" in data["description"]
    assert data["lead"]["request"] == "GET /gone → no response"


def test_markdown_inline_code_cannot_be_closed_by_a_backtick():
    assert report_text.md_code("a`b") == "``a`b``"
    assert report_text.md_code("`x`") == "`` `x` ``"
    assert report_text.jira_code("a*b{c}|d") == "{{a\\*b\\{c\\}\\|d}}"


def test_the_whole_session_draft_lists_every_failed_request(env):
    make_session(env[0], [at(flow("/ok"), 0), at(flow("/bad", 500), 1), at(flow("/gone", error=True), 2)])
    data = draft(env, report.Include())
    assert data["title"] == f"2 failed requests in session {NAME}"
    assert data["lead"]["request"] is None and data["lead"]["session"] == NAME
    rows = [line for line in data["description"].splitlines() if line.startswith("| ")][1:]
    assert len(rows) == 2 and "/bad" in rows[0] and "/gone" in rows[1]
    jira = draft(env, report.Include(), "jira")["description"]
    assert "||Time||Method||Host||Path||Status||Duration||Request ID||Wiretrace note||" in jira
