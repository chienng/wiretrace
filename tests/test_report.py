import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from mitmproxy import io
from mitmproxy.test import tflow

from cli import report, session

NOW = datetime(2026, 10, 14, 12, 0, 0)
NAME = "2026-10-14_091500_staging_android"
PRESET = "name: staging\napi_hosts:\n  - api.example.com\nredact:\n  headers: [X-Api-Key]\n  json_fields: [otp]\n"


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
                     "Faulted by Wiretrace: 0", "Log lines: 3", "X-Api-Key", "Set-Cookie", "otp", "access_token"):
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
        request_headers={"Authorization": "Bearer fake-token", "X-Api-Key": "fake-key"})],
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
    folder = make_session(env[0], [flow(request_headers={"X-Api-Key": "fake-key"})],
                          meta={"preset": "gone", "redact": {"headers": ["X-Api-Key"], "json_fields": ["otp"]}})
    assert run(env) == 0
    assert "recorded" in capsys.readouterr().err
    with open_zip(folder) as archive:
        assert "fake-key" not in member(archive, "flows.har")
        assert "X-Api-Key" in member(archive, "summary.md")


def test_preset_that_no_longer_loads_warns(env, capsys):
    (env[1] / "staging.yaml").write_text("name: staging\n")
    make_session(env[0], [flow()])
    assert run(env) == 0
    assert "Warning" in capsys.readouterr().err


def test_preset_rules_are_used_as_they_are_now(env):
    folder = make_session(env[0], [flow(request_headers={"X-Api-Key": "fake-key"})])
    (env[1] / "staging.yaml").write_text(PRESET.replace("X-Api-Key", "X-Other"))
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
    (env[1] / "staging.yaml").write_text(PRESET.replace("X-Api-Key", "X-Request-ID"))
    make_session(env[0], [flow("/boom", 500, request_headers={"X-Request-ID": "fake-id"})])
    assert run(env) == 0
    with open_zip(env[0] / NAME) as archive:
        assert "fake-id" not in member(archive, "summary.md")


def test_report_command_is_registered():
    from cli import __main__ as cli_main

    with pytest.raises(SystemExit) as info:
        cli_main.main(["report", "--help"])
    assert info.value.code == 0
