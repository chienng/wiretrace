import getpass
import http.client
import http.server
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cli import __main__ as cli_main
from cli import redact, session, start
from cli.preset import Preset

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
PRESET = "name: staging\napi_hosts:\n  - {host}\napp:\n  android_package: com.example.app\n"

# Runs start.run() in its own process, so tests can signal it like a Terminal would.
DRIVER = """\
import json, sys
from pathlib import Path
from cli import start
a = json.loads(sys.argv[1])

def collector_for(preset, target, bin_dir, out):
    if a["collector"] == "real":
        return start.collector_command(preset, target, bin_dir, out, find_adb=lambda: a["adb"])
    if a["collector"]:
        return a["collector"] + [str(out)], ""
    return None, "off (test)"

sys.exit(start.run("staging", "android", "proxy", ui=False, presets_dir=Path(a["presets"]),
                   sessions_dir=Path(a["sessions"]), bin_dir=Path(a["bin"]), proxy_port=a["port"],
                   wiretrace_dir=Path(a["wiretrace"]), collector_for=collector_for))
"""

# Stands in for mitmdump: records the signals it gets in FAKE_EVENTS. FAKE_MODE picks
# how it behaves; with -r it plays the HAR conversion.
FAKE_MITMDUMP = """\
import json, os, signal, sys, time

events = os.environ["FAKE_EVENTS"]
mode = os.environ["FAKE_MODE"]
args = sys.argv[1:]

def log(event):
    with open(events, "a") as f:
        f.write(event + "\\n")

def value(flag):
    return args[args.index(flag) + 1]

if "-r" in args:
    with open(events) as f:
        pid = int(next(line for line in f if line.startswith("pid ")).split()[1])
    try:
        os.kill(pid, 0)
        log("har child-alive")
    except ProcessLookupError:
        log("har child-gone")
    if os.path.exists(os.environ["FAKE_COLLECTOR_EVENTS"]):
        with open(os.environ["FAKE_COLLECTOR_EVENTS"]) as f:
            collector_pid = int(next(line for line in f if line.startswith("pids ")).split()[1])
        try:
            os.kill(collector_pid, 0)
            log("har collector-alive")
        except ProcessLookupError:
            log("har collector-gone")
    har = value("--set").split("=", 1)[1]
    with open(har, "w") as f:
        f.write(os.environ.get("FAKE_HAR") or json.dumps({"log": {"entries": [{}]}}))
    sys.exit(0)

stopping = False

def on_sigint(*_):
    global stopping
    log("SIGINT")
    stopping = True

for flag in args:
    if flag.startswith("qa_app_log_file="):
        with open(flag.split("=", 1)[1], "a") as f:
            f.write('{"message": "app"}\\n' * int(os.environ["FAKE_APP_LINES"]))

signal.signal(signal.SIGINT, on_sigint)
if mode != "empty":
    with open(value("--save-stream-file"), "wb") as f:
        f.write(b"flows")
log(f"pid {os.getpid()}")
log("started")

if mode == "crash":
    time.sleep(0.2)
    log("exit")
    sys.exit(1)
while not (stopping and mode != "stubborn"):
    time.sleep(0.05)
time.sleep(0.3)
log("exit")
"""

# Stands in for the device log collector. It writes FAKE_COLLECTOR_LINES lines, starts a
# `sleep` as its "tool", and leaves that tool behind unless the launcher kills the group.
# FAKE_COLLECTOR_MODE: normal (writes a last line on SIGINT and exits), quiet (exits on
# SIGINT without writing), stubborn (ignores SIGINT), crash (exits with code 3 shortly after starting).
FAKE_COLLECTOR = """\
import os, signal, subprocess, sys, time

out, mode = sys.argv[1], os.environ["FAKE_COLLECTOR_MODE"]

def log(event):
    with open(os.environ["FAKE_COLLECTOR_EVENTS"], "a") as f:
        f.write(event + "\\n")

def write(text):
    if text:
        with open(out, "ab", buffering=0) as f:
            f.write(text.encode())

tool = subprocess.Popen(["sleep", "60"])
log(f"pids {os.getpid()} {tool.pid} {os.getpgrp()}")
write('{"message": "line"}\\n' * int(os.environ["FAKE_COLLECTOR_LINES"]))
log("started")

if mode == "crash":
    time.sleep(0.2)
    log("crash")
    os._exit(3)

def on_sigint(*_):
    log("SIGINT")
    if mode in ("normal", "quiet"):
        if mode == "normal":
            write('{"message": "last"}\\n')
        os._exit(0)

signal.signal(signal.SIGINT, on_sigint)
while True:
    time.sleep(0.05)
"""

# A minimal adb for the end-to-end test of the real collector.
FAKE_ADB = """\
import sys, time
args = sys.argv[1:]
if args == ["devices"]:
    print("List of devices attached\\nFAKESERIAL0001\\tdevice")
elif args[:2] == ["shell", "date"]:
    print("1728873000")
elif args[:2] == ["shell", "pidof"]:
    print("4242")
elif args[0] == "logcat":
    print("1728873005.481  4242  4242 E Orders  : SECRET-ONE")
    print("1728873006.482  4242  4242 W Orders  : SECRET-TWO", flush=True)
    time.sleep(60)
"""


def free_port() -> int:
    # mitmproxy listens on "::", so the port must be free for IPv6 as well as IPv4.
    with socket.socket(socket.AF_INET6) as probe:
        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        probe.bind(("::", 0))
        return probe.getsockname()[1]


def wait_for(condition, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


class Launch:
    def __init__(self, tmp_path: Path, fake_mode: str | None, host: str = "api.example.com",
                 bin_dir: Path | None = None, collector: str | list[str] | None = None,
                 collector_lines: int = 1, app_lines: int = 0, har: str = "", old_session: str = "", preset_extra: str = "",
                 port: int | None = None):
        self.presets = tmp_path / "presets"
        self.sessions = tmp_path / "sessions"
        # Mocks are read from here, never from the real repo's mocks/ folder.
        self.wiretrace_dir = tmp_path / "wiretrace"
        self.events_file = tmp_path / "events.log"
        self.collector_events_file = tmp_path / "collector-events.log"
        self.presets.mkdir()
        (self.presets / "staging.yaml").write_text(PRESET.format(host=host) + preset_extra)
        if bin_dir is None:
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "mitmdump"
            fake.write_text(f"#!{sys.executable}\n{FAKE_MITMDUMP}")
            fake.chmod(0o755)
        self.port = port or free_port()
        if old_session:
            old = self.sessions / old_session
            old.mkdir(parents=True)
            (old / session.META).write_text("{}")
        self.old_session = old_session
        # A mode name runs the fake collector in that mode; a list is used as the command as is.
        command = collector
        if isinstance(collector, str) and collector != "real":
            script = tmp_path / "fake-collector.py"
            script.write_text(FAKE_COLLECTOR)
            command = [sys.executable, str(script)]
        adb = self.adb = tmp_path / "adb"
        adb.write_text(f"#!{sys.executable}\n{FAKE_ADB}")
        adb.chmod(0o755)
        args = {"presets": str(self.presets), "sessions": str(self.sessions),
                "bin": str(bin_dir), "port": self.port, "wiretrace": str(self.wiretrace_dir),
                "collector": command, "adb": str(adb)}
        env = {**os.environ, "PYTHONPATH": str(ROOT),
               "FAKE_EVENTS": str(self.events_file), "FAKE_MODE": fake_mode or "",
               "FAKE_COLLECTOR_EVENTS": str(self.collector_events_file),
               "FAKE_COLLECTOR_MODE": collector if isinstance(collector, str) else "",
               "FAKE_COLLECTOR_LINES": str(collector_lines), "FAKE_APP_LINES": str(app_lines),
               "FAKE_HAR": har}
        self.proc = subprocess.Popen(
            [sys.executable, "-c", DRIVER, json.dumps(args)], cwd=ROOT, env=env,
            start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.output = ""

    def events(self) -> list[str]:
        if not self.events_file.exists():
            return []
        return [e for e in self.events_file.read_text().splitlines() if not e.startswith("pid ")]

    def wait_started(self) -> None:
        wait_for(lambda: "started" in self.events())

    def collector_events(self) -> list[str]:
        if not self.collector_events_file.exists():
            return []
        return [e for e in self.collector_events_file.read_text().splitlines() if not e.startswith("pids ")]

    def collector_pids(self) -> tuple[int, int, int]:
        """The collector's pid, its tool's pid and its process group."""
        wait_for(lambda: self.collector_events_file.exists() and "pids" in self.collector_events_file.read_text())
        line = next(e for e in self.collector_events_file.read_text().splitlines() if e.startswith("pids "))
        collector, tool, group = (int(v) for v in line.split()[1:])
        return collector, tool, group

    def wait_collector_started(self) -> None:
        wait_for(lambda: "started" in self.collector_events())

    def finish(self, timeout: float = 30) -> int:
        self.output, _ = self.proc.communicate(timeout=timeout)
        return self.proc.returncode

    def folders(self) -> list[Path]:
        return sorted(self.sessions.iterdir()) if self.sessions.exists() else []

    def cleanup(self) -> None:
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()


@pytest.fixture
def launch(tmp_path):
    started: list[Launch] = []

    def make(fake_mode, **kwargs) -> Launch:
        started.append(Launch(tmp_path, fake_mode, **kwargs))
        return started[-1]

    yield make
    for launched in started:
        launched.cleanup()


# State machine, with a fake child

def test_sigint_stops_child_then_writes_har(launch):
    run = launch("normal")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)  # the launcher only, as `kill -INT` would

    assert run.finish() == 0, run.output
    # The child got the launcher's SIGINT; HAR conversion ran only after the child had exited.
    assert run.events() == ["started", "SIGINT", "exit", "har child-gone"]
    [folder] = run.folders()
    assert folder.name.endswith("_staging_android")
    assert (folder / session.HAR).is_file()
    meta = session.read_meta(folder)
    assert meta["status"] == "stopped" and meta["ended_at"]
    assert str(folder) in run.output


def test_two_sigints_kill_the_child(launch):
    run = launch("stubborn")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)
    wait_for(lambda: "SIGINT" in run.events())
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 1, run.output
    assert "exit" not in run.events()
    assert run.events()[-1] == "har child-gone"
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "killed"


def test_child_exits_on_its_own(launch):
    run = launch("crash")

    assert run.finish() == 1, run.output
    assert "SIGINT" not in run.events()
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "exited"
    assert "exited on its own (exit code 1)" in run.output


def test_nothing_captured_removes_the_session_folder(launch):
    run = launch("empty")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 1, run.output
    assert run.folders() == []
    assert "Nothing was captured" in run.output


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_port_in_use_starts_nothing(tmp_path, capsys, family):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    with socket.socket(family) as holder:
        if family == socket.AF_INET6:
            holder.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        holder.bind(("0.0.0.0" if family == socket.AF_INET else "::", 0))
        holder.listen()
        port = holder.getsockname()[1]
        code = start.run("staging", "android", "proxy", ui=False, presets_dir=tmp_path / "presets",
                         sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "no-bin", proxy_port=port,
                         wiretrace_dir=tmp_path / "wiretrace")

    assert code == 1
    assert f"TCP {port}" in capsys.readouterr().err
    assert not (tmp_path / "sessions").exists()


def test_unknown_preset_starts_nothing(tmp_path, capsys):
    (tmp_path / "presets").mkdir()
    code = start.run("nope", presets_dir=tmp_path / "presets", sessions_dir=tmp_path / "sessions",
                     wiretrace_dir=tmp_path / "wiretrace")
    assert code == 1
    assert "Unknown preset 'nope'" in capsys.readouterr().err
    assert not (tmp_path / "sessions").exists()


def test_missing_mitmproxy_binary_leaves_no_folder(tmp_path, capsys):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    code = start.run("staging", "android", "proxy", ui=False, presets_dir=tmp_path / "presets",
                     sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "no-bin", proxy_port=free_port(),
                     wiretrace_dir=tmp_path / "wiretrace")
    assert code == 1
    assert "Could not start mitmdump" in capsys.readouterr().err
    assert list((tmp_path / "sessions").iterdir()) == []


def process_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_meta_has_no_identifiers(launch):
    run = launch("normal")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)
    assert run.finish() == 0, run.output

    [folder] = run.folders()
    text = (folder / session.META).read_text()
    assert getpass.getuser() not in text
    assert socket.gethostname().split(".")[0] not in text
    assert str(Path.home()) not in text
    assert set(json.loads(text)) == {
        "wiretrace_version", "mitmproxy_version", "preset", "api_hosts", "target", "mode", "ui",
        "device_logs", "device_log_lines", "app_log_lines", "status", "started_at", "ended_at",
        "redact",
    }
    meta = json.loads(text)
    assert (meta["device_logs"], meta["device_log_lines"], meta["app_log_lines"]) == (None, 0, 0)
    # Only the rule names in use, so a report still masks them if the preset changes later.
    assert meta["redact"] == {"headers": list(redact.DEFAULT_HEADERS), "json_fields": list(redact.DEFAULT_FIELDS)}


# Command line

PRESET_WITH_FILTER = Preset(name="staging", api_hosts=("a.example.com", "b.example.com"),
                            default_filter="!~t image")


def test_mitmweb_command_wireguard():
    cmd = start.build_command(PRESET_WITH_FILTER, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"))
    assert cmd[:3] == ["/v/bin/mitmweb", "--mode", "wireguard"]
    assert cmd.count("--allow-hosts") == 3
    assert cmd[cmd.index("--save-stream-file") + 1] == "/s/flows.mitm"
    assert "view_filter=!~t image" in cmd
    assert not any("dumper_filter" in arg for arg in cmd)


def test_mitmdump_filter_is_an_option_not_positional():
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"))
    assert cmd[:5] == ["/v/bin/mitmdump", "--mode", "regular", "--listen-port", "8080"]
    assert cmd[-2:] == ["--set", "dumper_filter=!~t image"]


def test_no_filter_no_filter_option():
    plain = Preset(name="staging", api_hosts=("a.example.com",))
    cmd = start.build_command(plain, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"))
    assert not any(arg.startswith(("view_filter", "dumper_filter")) for arg in cmd)


def test_command_loads_the_qa_addon():
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"),
                              wiretrace_dir=Path("/d"))
    assert cmd[cmd.index("-s") + 1] == str(start.QA_ADDON)
    assert start.QA_ADDON.is_file()
    assert [a for a in cmd if a.startswith("qa_api_hosts=")] == [
        "qa_api_hosts=a.example.com", "qa_api_hosts=b.example.com"]
    assert "qa_mocks_dir=/d/mocks/staging" in cmd
    assert "qa_request_id_header=X-Request-ID" in cmd
    # Every value follows a --set, and the filter option still comes last.
    assert all(cmd[i - 1] == "--set" for i, a in enumerate(cmd) if a.startswith("qa_"))
    assert cmd[-2:] == ["--set", "dumper_filter=!~t image"]


def test_command_uses_the_preset_mocks_dir_and_header():
    custom = Preset(name="staging", api_hosts=("a.example.com",), mocks_dir="fixtures/api",
                    request_id_header="X-Trace-Id")
    cmd = start.build_command(custom, "proxy", True, Path("/s/flows.mitm"), Path("/v/bin"),
                              wiretrace_dir=Path("/d"))
    assert "qa_mocks_dir=/d/fixtures/api" in cmd
    assert "qa_request_id_header=X-Trace-Id" in cmd


# Banner

def test_banner_counts_mock_files_and_shows_a_relative_path():
    text = start.banner(PRESET_WITH_FILTER, "android", "proxy", True, Path("/s"), mock_count=3)
    assert "Mocks: 3 files in mocks/staging/" in text
    assert "Faults: mitmweb > Options > qa_fault_*" in text
    assert "/d/" not in text


def test_banner_without_mocks_or_mitmweb():
    text = start.banner(PRESET_WITH_FILTER, "android", "proxy", False, Path("/s"))
    assert "Mocks: none (add files under mocks/staging/<METHOD>/…)" in text
    assert "Faults:" not in text


def test_count_mocks_counts_json_files_in_nested_folders(tmp_path):
    assert start.count_mocks(tmp_path / "missing") == 0
    (tmp_path / "GET" / "api").mkdir(parents=True)
    (tmp_path / "GET" / "api" / "a.json").write_text("{}")
    (tmp_path / "GET" / "index.json").write_text("{}")
    (tmp_path / "GET" / "notes.txt").write_text("x")
    assert start.count_mocks(tmp_path) == 2


def test_needed_ports():
    def labels(mode, ui):
        return [p[3] for p in start.needed_ports(mode, ui)]

    assert labels("wireguard", True) == ["WireGuard", "mitmweb UI"]
    assert labels("wireguard", False) == ["WireGuard"]
    assert labels("proxy", True) == ["proxy", "mitmweb UI"]
    assert start.needed_ports("proxy", False, 9999) == [("tcp", "0.0.0.0", 9999, "proxy")]


# Integration: real mitmdump

class _Hello(http.server.BaseHTTPRequestHandler):
    paths: list[str] = []

    def do_GET(self):
        self.paths.append(self.path)
        body = b"hello"
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


@pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")
def test_real_mitmdump_two_sigints(launch):
    from mitmproxy import io

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hello)
    _Hello.paths = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run = launch(None, host="127.0.0.1", bin_dir=VENV_BIN)
        mock = run.wiretrace_dir / "mocks" / "staging" / "GET" / "mocked.json"
        mock.parent.mkdir(parents=True)
        mock.write_bytes(b'{"mocked": true}')
        wait_for(lambda: _accepts(run.port), timeout=60)

        conn = http.client.HTTPConnection("127.0.0.1", run.port, timeout=10)
        conn.request("GET", f"http://127.0.0.1:{server.server_port}/hello")
        response = conn.getresponse()
        assert (response.status, response.read()) == (200, b"hello")
        conn.request("GET", f"http://127.0.0.1:{server.server_port}/mocked?page=2",
                     headers={"X-Request-ID": "req-42"})
        response = conn.getresponse()
        assert (response.status, response.read()) == (200, b'{"mocked": true}')
        assert response.getheader("Content-Type") == "application/json"
        conn.close()
        assert _Hello.paths == ["/hello"]

        # A Terminal Ctrl+C: the whole group gets SIGINT, and the launcher sends mitmdump
        # one more, so mitmdump receives two.
        os.killpg(run.proc.pid, signal.SIGINT)
        assert run.finish(timeout=60) == 0, run.output
    finally:
        server.shutdown()

    [folder] = run.folders()
    with open(folder / session.FLOWS, "rb") as f:
        flows = list(io.FlowReader(f).stream())
    assert [flow.request.path for flow in flows] == ["/hello", "/mocked?page=2"]
    assert flows[0].marked == "" and flows[0].comment == ""
    assert flows[1].marked == ":construction:"
    assert flows[1].comment == "request-id: req-42; mock: GET/mocked.json"
    har = json.loads((folder / session.HAR).read_text())
    assert len(har["log"]["entries"]) == 2
    assert session.read_meta(folder)["status"] == "stopped"


# Masking, report hint and old-session cleanup

HAR_WITH_SECRETS = json.dumps({"log": {"entries": [{
    "request": {"url": "https://api.example.com/login?access_token=fake-q",
                "headers": [{"name": "Authorization", "value": "Bearer fake-token"},
                            {"name": "Accept", "value": "*/*"}],
                "postData": {"mimeType": "application/json", "text": '{"password": "fake-pw", "user": "ann"}'}},
    "response": {"headers": [{"name": "Set-Cookie", "value": "sid=fake-sid"}],
                 "content": {"text": '{"refresh_token": "fake-rt"}'}},
}]}})
TEMP_FILES = (session.HAR_TMP, session.HAR_MASKED)


def test_har_is_masked_and_no_temporary_file_is_left(launch):
    run = launch("normal", har=HAR_WITH_SECRETS)
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    [folder] = run.folders()
    text = (folder / session.HAR).read_text()
    for secret in ("fake-token", "fake-pw", "fake-sid", "fake-rt", "fake-q"):
        assert secret not in text
    entry = json.loads(text)["log"]["entries"][0]
    assert entry["request"]["headers"] == [{"name": "Authorization", "value": "***"},
                                           {"name": "Accept", "value": "*/*"}]
    assert json.loads(entry["request"]["postData"]["text"]) == {"password": "***", "user": "ann"}
    assert entry["request"]["url"].endswith("?access_token=***")
    assert not any((folder / name).exists() for name in TEMP_FILES)
    assert not [p.name for p in folder.iterdir() if p.name.startswith(".")]


def test_preset_additions_are_applied_to_the_har(launch):
    har = json.dumps({"log": {"entries": [{"request": {"headers": [{"name": "X-Api-Key", "value": "fake-key"}]}}]}})
    run = launch("normal", har=har, preset_extra="redact:\n  headers: [X-Api-Key]\n")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    [folder] = run.folders()
    assert "fake-key" not in (folder / session.HAR).read_text()


def test_flows_mitm_keeps_the_original_values(launch):
    run = launch("normal", har=HAR_WITH_SECRETS)
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)
    assert run.finish() == 0, run.output
    [folder] = run.folders()
    assert (folder / session.FLOWS).read_bytes() == b"flows"


@pytest.mark.parametrize("har", ["not json at all", "[1, 2]", '{"log": '])
def test_a_har_that_cannot_be_masked_is_a_har_failure(launch, har):
    run = launch("normal", har=har)
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 1, run.output
    [folder] = run.folders()
    assert not (folder / session.HAR).exists()
    assert not any((folder / name).exists() for name in TEMP_FILES)
    assert (folder / session.FLOWS).is_file()
    assert "flows.har was not written (could not mask it); flows.mitm is kept." in run.output
    assert session.read_meta(folder)["status"] == "stopped"


def test_the_report_command_is_printed_after_the_session_is_saved(launch):
    run = launch("normal")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    [folder] = run.folders()
    lines = run.output.splitlines()
    saved = lines.index(f"Session saved: {folder}")
    assert lines[saved + 1] == f"For a bug ticket: ./wiretrace report {folder.name}"


def test_old_sessions_are_deleted_before_the_new_one_and_counted(launch):
    run = launch("normal", old_session="2020-01-01_000000_staging_android")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert "Deleted 1 old session(s) (older than 14 days)." in run.output
    assert run.output.index("Deleted 1 old session") < run.output.index("Saving to")
    assert not (run.sessions / "2020-01-01_000000_staging_android").exists()
    assert len(run.folders()) == 1


def test_nothing_is_said_when_no_session_is_old(launch):
    run = launch("normal")
    run.wait_started()
    os.kill(run.proc.pid, signal.SIGINT)
    assert run.finish() == 0, run.output
    assert "Deleted" not in run.output


def test_old_sessions_are_kept_when_the_start_is_refused(launch):
    busy = socket.socket(socket.AF_INET6)
    busy.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    busy.bind(("::", 0))
    busy.listen()
    try:
        run = launch("normal", old_session="2020-01-01_000000_staging_android", port=busy.getsockname()[1])
        assert run.finish() == 1, run.output
    finally:
        busy.close()
    assert (run.sessions / "2020-01-01_000000_staging_android").is_dir()


# Collector supervision, with a fake collector command

def test_sigint_stops_both_children_and_counts_match_the_files(launch):
    run = launch("normal", collector="normal", app_lines=3)
    run.wait_started()
    run.wait_collector_started()
    collector, tool, group = run.collector_pids()
    # Its own process group, so a Terminal Ctrl+C does not reach it.
    assert group == collector != os.getpgid(run.proc.pid)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert run.events() == ["started", "SIGINT", "exit", "har child-gone", "har collector-gone"]
    assert run.collector_events() == ["started", "SIGINT"]
    # The collector exited on SIGINT and left its tool behind; the group kill took it.
    wait_for(lambda: process_gone(collector) and process_gone(tool), timeout=5)
    [folder] = run.folders()
    meta = session.read_meta(folder)
    assert meta["status"] == "stopped" and meta["device_logs"] == "android"
    # One line at start, one written on SIGINT: counted after the collector was reaped.
    assert (meta["device_log_lines"], meta["app_log_lines"]) == (2, 3)
    assert len((folder / session.DEVICE_LOG).read_text().splitlines()) == 2
    assert len((folder / session.APP_LOG).read_text().splitlines()) == 3
    assert "Device logs: Android, com.example.app → device.log.jsonl" in run.output
    assert "App logs: POST https://qa-logs.internal/log → app.log.jsonl" in run.output


def test_two_sigints_kill_a_collector_that_ignores_sigint(launch):
    run = launch("stubborn", collector="stubborn")
    run.wait_started()
    run.wait_collector_started()
    collector, tool, group = run.collector_pids()
    os.kill(run.proc.pid, signal.SIGINT)
    wait_for(lambda: "SIGINT" in run.events() and "SIGINT" in run.collector_events())
    assert not process_gone(collector)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 1, run.output
    wait_for(lambda: process_gone(collector) and process_gone(tool), timeout=5)
    # Each child got exactly one SIGINT from the launcher.
    assert run.events().count("SIGINT") == 1 and run.collector_events().count("SIGINT") == 1
    assert "exit" not in run.events() and run.events()[-2:] == ["har child-gone", "har collector-gone"]
    [folder] = run.folders()
    meta = session.read_meta(folder)
    assert meta["status"] == "killed" and meta["device_log_lines"] == 1


def test_collector_that_ignores_sigint_is_killed_after_the_grace_period(launch):
    run = launch("normal", collector="stubborn")
    run.wait_started()
    run.wait_collector_started()
    collector, tool, _ = run.collector_pids()
    stopped_at = time.monotonic()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    waited = time.monotonic() - stopped_at
    # mitmdump was done after ~0.3 s; the collector got COLLECTOR_STOP_S from the SIGINT.
    assert start.COLLECTOR_STOP_S <= waited < start.COLLECTOR_STOP_S + 5
    assert run.events()[-1] == "har collector-gone"
    wait_for(lambda: process_gone(collector) and process_gone(tool), timeout=5)


def test_collector_crash_leaves_the_session_alone(launch):
    run = launch("normal", collector="crash")
    run.wait_started()
    wait_for(lambda: "crash" in run.collector_events())
    collector, tool, _ = run.collector_pids()
    # Its leftover tool is cleaned up at once; mitmdump keeps running.
    wait_for(lambda: process_gone(tool), timeout=5)
    time.sleep(0.3)
    assert run.events() == ["started"] and run.proc.poll() is None
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert run.output.count("Device logs: collector stopped (exit code 3); capture continues") == 1
    [folder] = run.folders()
    meta = session.read_meta(folder)
    assert meta["status"] == "stopped" and meta["device_log_lines"] == 1


def test_mitmdump_decides_the_status_when_the_collector_crashes_too(launch):
    run = launch("crash", collector="crash")
    assert run.finish() == 1, run.output
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "exited"


def test_missing_collector_command_prints_one_line_and_the_session_continues(launch):
    run = launch("normal", collector=["/nonexistent/collector"])
    run.wait_started()
    time.sleep(0.3)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert [line for line in run.output.splitlines() if line.startswith("Device logs:") and "→" not in line] == [
        "Device logs: could not start the collector"]
    [folder] = run.folders()
    meta = session.read_meta(folder)
    assert meta["status"] == "stopped" and meta["device_logs"] is None and meta["device_log_lines"] == 0


def test_collector_does_not_start_when_mitmdump_cannot(launch, tmp_path):
    run = launch("normal", collector="normal", bin_dir=tmp_path / "no-bin")
    assert run.finish() == 1
    assert "Could not start mitmdump" in run.output
    assert run.collector_events() == [] and not run.collector_events_file.exists()
    assert run.folders() == []


def test_collector_group_is_signalled_once_after_the_reap(monkeypatch):
    collector = start._Collector(subprocess.Popen(["true"], start_new_session=True))
    calls = []
    real_killpg = os.killpg
    monkeypatch.setattr(start.os, "killpg", lambda pgid, sig: (calls.append(sig), real_killpg(pgid, sig)))
    collector.stop([], killed=False)
    collector.close()
    collector.close()
    assert collector.proc.returncode is not None
    # SIGINT, then the one SIGKILL of `close`; repeated closes never signal a reaped group.
    assert calls == [signal.SIGINT, signal.SIGKILL]


def test_no_traffic_but_log_lines_keeps_the_session(launch):
    run = launch("empty", collector="normal", app_lines=2)
    run.wait_started()
    run.wait_collector_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    [folder] = run.folders()
    assert "No traffic was captured; flows.har was not written." in run.output
    assert "Writing flows.har" not in run.output and "Nothing was captured" not in run.output
    assert not (folder / session.HAR).exists() and not (folder / session.FLOWS).exists()
    meta = session.read_meta(folder)
    assert meta["status"] == "stopped" and (meta["device_log_lines"], meta["app_log_lines"]) == (2, 2)
    assert str(folder) in run.output
    assert "har child-gone" not in run.events()


def test_no_traffic_and_no_log_lines_removes_the_session(launch):
    run = launch("empty", collector="quiet", collector_lines=0)
    run.wait_started()
    run.wait_collector_started()
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 1, run.output
    assert run.folders() == []
    assert "Nothing was captured; the session folder was removed." in run.output


@pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")
def test_real_collector_through_the_launcher_with_a_fake_adb(launch):
    run = launch("normal", collector="real")
    run.wait_started()

    def device_log_lines() -> int:
        return sum(len(f.read_text().splitlines()) for f in run.sessions.glob(f"*/{session.DEVICE_LOG}"))

    wait_for(lambda: device_log_lines() == 2)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    [folder] = run.folders()
    records = [json.loads(line) for line in (folder / session.DEVICE_LOG).read_text().splitlines()]
    assert [(r["source"], r["level"], r["tag"], r["message"]) for r in records] == [
        ("android", "E", "Orders", "SECRET-ONE"), ("android", "W", "Orders", "SECRET-TWO")]
    meta = session.read_meta(folder)
    assert (meta["device_logs"], meta["device_log_lines"], meta["status"]) == ("android", 2, "stopped")
    assert "Device logs: Android, com.example.app → device.log.jsonl" in run.output
    assert "Device logs: streaming" in run.output
    # Nothing the Terminal showed or meta.json holds names the device or quotes the log.
    shown = run.output + (folder / session.META).read_text()
    assert "FAKESERIAL" not in shown and "SECRET" not in shown
    # No `adb` of this test is left running (its path is unique to this test).
    wait_for(lambda: subprocess.run(["pgrep", "-f", str(run.adb)], capture_output=True).returncode == 1, timeout=5)


# Receiver arguments and the collector command

def test_command_loads_the_receiver_and_keeps_its_flows_out_of_the_session():
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"))
    scripts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-s"]
    assert scripts == [str(start.QA_ADDON), str(start.APP_LOGS_ADDON)] and start.APP_LOGS_ADDON.is_file()
    assert "qa_app_log_file=/s/app.log.jsonl" in cmd
    assert r"save_stream_filter=!~d ^qa-logs\.internal$" in cmd
    assert r"^qa-logs\.internal(:\d+)?$" in cmd
    assert all(cmd[i - 1] in ("--set", "--allow-hosts") for i, a in enumerate(cmd)
               if a.startswith(("qa_app_log_file", "save_stream_filter")) or a == start.RECEIVER_ALLOW_HOSTS)
    # The receiver is never an API host.
    assert not any(a.startswith("qa_api_hosts=") and "qa-logs" in a for a in cmd)
    assert cmd[-2:] == ["--set", "dumper_filter=!~t image"]


@pytest.mark.parametrize("authority, matches", [
    ("qa-logs.internal:443", True), ("qa-logs.internal", True), ("qa-logs.internal:8443", True),
    ("sub.qa-logs.internal:443", False), ("xqa-logs.internal:443", False), ("qa-logs.internal.evil.io:443", False),
    ("qa-logs.internal:abc", False),
])
def test_receiver_allow_hosts_matches_that_host_only(authority, matches):
    assert bool(re.search(start.RECEIVER_ALLOW_HOSTS, authority)) is matches


@pytest.mark.parametrize("host, saved", [
    ("qa-logs.internal", False), ("api.example.com", True), ("sub.qa-logs.internal", True),
    ("qa-logs.internal.evil.io", True), ("127.0.0.1", True),
])
def test_save_filter_leaves_receiver_flows_out(host, saved):
    from mitmproxy import flowfilter
    from mitmproxy.test import tflow

    flow = tflow.tflow()
    flow.request.host = host
    flow.request.headers["Host"] = host
    assert bool(flowfilter.parse(start.RECEIVER_SAVE_FILTER)(flow)) is saved


def app_preset(**app) -> Preset:
    return Preset(name="staging", api_hosts=("api.example.com",), app=app)


def make_tool(folder: Path, name: str) -> Path:
    folder.mkdir(exist_ok=True)
    tool = folder / name
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    return tool


def test_collector_command_per_target(tmp_path):
    bin_dir = tmp_path / "bin"
    pmd = make_tool(bin_dir, "pymobiledevice3")
    out = tmp_path / "s" / "device.log.jsonl"
    preset = app_preset(android_package="com.example.myapp", ios_process="MyApp")

    def command(target):
        return start.collector_command(preset, target, bin_dir, out, find_adb=lambda: "/x/adb",
                                       which=lambda name: f"/usr/bin/{name}")

    def tail(cmd):
        return cmd[:3], cmd[3:]

    for target in ("android", "android-emu"):
        cmd, reason = command(target)
        assert reason == "" and tail(cmd) == ([sys.executable, "-m", "collectors"], [
            "--target", target, "--app", "com.example.myapp", "--out", str(out), "--adb", "/x/adb"])
    cmd, reason = command("ios")
    assert tail(cmd)[1] == ["--target", "ios", "--app", "MyApp", "--out", str(out), "--pymobiledevice3", str(pmd)]
    cmd, reason = command("ios-sim")
    assert tail(cmd)[1] == ["--target", "ios-sim", "--app", "MyApp", "--out", str(out), "--xcrun", "/usr/bin/xcrun"]
    assert command("device") == (None, "--target device has no device log")


@pytest.mark.parametrize("target, app, reason", [
    ("android", {"ios_process": "MyApp"}, "add app.android_package to the preset"),
    ("android-emu", {}, "add app.android_package to the preset"),
    ("ios", {"android_package": "com.example.myapp"}, "add app.ios_process to the preset"),
    ("ios-sim", {"android_package": "com.example.myapp"}, "add app.ios_process to the preset"),
    ("android", {"android_package": ""}, "add app.android_package to the preset"),
])
def test_collector_command_without_the_app_key(tmp_path, target, app, reason):
    make_tool(tmp_path / "bin", "pymobiledevice3")
    cmd, why = start.collector_command(app_preset(**app), target, tmp_path / "bin", tmp_path / "o",
                                       find_adb=lambda: "/x/adb", which=lambda name: "/x/xcrun")
    assert cmd is None and why == reason


def test_collector_command_without_the_tool(tmp_path):
    preset = app_preset(android_package="com.example.myapp", ios_process="MyApp")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pymobiledevice3").write_text("not executable")

    def command(target):
        return start.collector_command(preset, target, tmp_path / "bin", tmp_path / "o",
                                       find_adb=lambda: None, which=lambda name: None)

    assert command("android") == (None, "adb not found")
    assert command("android-emu") == (None, "adb not found")
    assert command("ios") == (None, "pymobiledevice3 not found")
    assert command("ios-sim") == (None, "xcrun not found")


# Banner and session helpers

def test_banner_names_the_log_sources():
    text = start.banner(PRESET_WITH_FILTER, "android", "proxy", False, Path("/s"),
                        device_logs="Android, com.example.myapp → device.log.jsonl")
    assert "Device logs: Android, com.example.myapp → device.log.jsonl" in text
    assert "App logs: POST https://qa-logs.internal/log → app.log.jsonl" in text
    off = start.banner(PRESET_WITH_FILTER, "device", "proxy", False, Path("/s"),
                       device_logs="off (add app.android_package to the preset)")
    assert "Device logs: off (add app.android_package to the preset)" in off


def test_count_lines_and_has_logs(tmp_path):
    assert session.count_lines(tmp_path / "missing") == 0 and not session.has_logs(tmp_path)
    (tmp_path / session.DEVICE_LOG).write_bytes(b'{"a": 1}\n\n{"a": 2}\n{"a": 3')
    assert session.count_lines(tmp_path / session.DEVICE_LOG) == 3
    assert session.has_logs(tmp_path)
    (tmp_path / session.DEVICE_LOG).write_bytes(b"")
    assert not session.has_logs(tmp_path)
    (tmp_path / session.APP_LOG).write_text('{"a": 1}\n')
    assert session.has_logs(tmp_path)


# Wiretrace window (--ui wiretrace)

def wiretrace_command(preset=PRESET_WITH_FILTER, mode="wireguard", **kwargs):
    return start.build_command(preset, mode, "wiretrace", Path("/s/flows.mitm"), Path("/v/bin"), **kwargs)


def test_wiretrace_command_is_mitmdump_with_the_ui_addon_after_the_other_two():
    cmd = wiretrace_command(wiretrace_dir=Path("/d"))
    assert cmd[:3] == ["/v/bin/mitmdump", "--mode", "wireguard"]
    scripts = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-s"]
    assert scripts == [str(start.QA_ADDON), str(start.APP_LOGS_ADDON), str(start.UI_ADDON)]
    assert start.UI_ADDON.is_file() and start.UI_ADDON.name == "wiretrace_ui.py"
    assert cmd[cmd.index("--save-stream-file") + 1] == "/s/flows.mitm"


def test_wiretrace_command_sets_the_four_ui_options_and_no_view_or_print_filter():
    cmd = wiretrace_command()
    options = {arg.split("=", 1)[0]: arg.split("=", 1)[1] for arg in cmd if arg.startswith("qa_ui_")}
    assert options == {"qa_ui_port": "8081", "qa_ui_session_dir": "/s", "qa_ui_default_filter": "!~t image",
                       "qa_ui_open_browser": "true"}
    assert "flow_detail=0" in cmd
    assert all(cmd[i - 1] == "--set" for i, a in enumerate(cmd) if a.startswith(("qa_ui_", "flow_detail")))
    assert not any(arg.startswith(("view_filter", "dumper_filter")) for arg in cmd)
    # The launcher's other options are the same as for the other windows.
    assert "qa_app_log_file=/s/app.log.jsonl" in cmd and "qa_request_id_header=X-Request-ID" in cmd


def test_wiretrace_command_in_proxy_mode_with_a_custom_ui_port_and_no_filter():
    plain = Preset(name="staging", api_hosts=("a.example.com",))
    cmd = wiretrace_command(plain, "proxy", proxy_port=9999, ui_port=9001)
    assert cmd[1:5] == ["--mode", "regular", "--listen-port", "9999"]
    assert "qa_ui_port=9001" in cmd and "qa_ui_default_filter=" in cmd


def test_the_token_is_never_on_the_command_line():
    assert not any("token" in arg.lower() for arg in wiretrace_command())


def test_the_other_windows_do_not_load_the_ui_addon():
    for ui in (True, False, "mitmweb", "none"):
        cmd = start.build_command(PRESET_WITH_FILTER, "wireguard", ui, Path("/s/flows.mitm"), Path("/v/bin"))
        assert str(start.UI_ADDON) not in cmd
        assert not any(arg.startswith(("qa_ui_", "flow_detail")) for arg in cmd)
    web = start.build_command(PRESET_WITH_FILTER, "wireguard", "mitmweb", Path("/s/flows.mitm"), Path("/v/bin"))
    assert web == start.build_command(PRESET_WITH_FILTER, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"))
    assert web[0] == "/v/bin/mitmweb" and "view_filter=!~t image" in web


def test_wiretrace_port_check_is_labelled_wiretrace_ui():
    def checks(mode, ui, **kwargs):
        return [(p[2], p[3]) for p in start.needed_ports(mode, ui, **kwargs)]

    assert checks("wireguard", "wiretrace") == [(51820, "WireGuard"), (8081, "Wiretrace UI")]
    assert checks("proxy", "wiretrace", proxy_port=9999, ui_port=9001) == [(9999, "proxy"), (9001, "Wiretrace UI")]
    assert start.needed_ports("proxy", "wiretrace")[1] == ("tcp", "127.0.0.1", 8081, "Wiretrace UI")
    assert checks("wireguard", "mitmweb") == [(51820, "WireGuard"), (8081, "mitmweb UI")]
    assert checks("wireguard", "none") == [(51820, "WireGuard")]


def test_wiretrace_banner_points_to_the_link_and_the_faults_dialog():
    text = start.banner(PRESET_WITH_FILTER, "android", "wireguard", "wiretrace", Path("/s"), mock_count=2)
    assert "UI: Wiretrace (link below)" in text
    assert "Faults: Wiretrace > Faults" in text
    assert "mitmweb" not in text
    assert "scan the QR code in Wiretrace > Setup" in text
    assert "Search: !~t image (every flow is still saved)" in text
    for ui in ("mitmweb", "none"):
        assert "UI: Wiretrace" not in start.banner(PRESET_WITH_FILTER, "android", "proxy", ui, Path("/s"))
    assert "Faults: Wiretrace" not in start.banner(PRESET_WITH_FILTER, "android", "proxy", "mitmweb", Path("/s"))


def run_wiretrace(tmp_path, monkeypatch, **kwargs):
    """start.run with --ui wiretrace, stopping before the child would start."""
    (tmp_path / "presets").mkdir(exist_ok=True)
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    seen = {}

    def supervise(cmd, har_cmd, folder, *args, **kw):
        seen.update(cmd=cmd, folder=folder)
        return 0

    monkeypatch.setattr(start, "supervise", supervise)
    code = start.run("staging", "android", "proxy", "wiretrace", presets_dir=tmp_path / "presets",
                     sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "bin", proxy_port=free_port(),
                     wiretrace_dir=tmp_path / "wiretrace", collector_for=lambda *a: (None, "off (test)"), **kwargs)
    return code, seen


def test_run_with_wiretrace_records_the_ui_and_points_the_addon_at_the_session(tmp_path, monkeypatch, capsys):
    code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=free_port())
    assert code == 0
    meta = session.read_meta(seen["folder"])
    assert meta["ui"] == "wiretrace"
    assert f"qa_ui_session_dir={seen['folder']}" in seen["cmd"]
    assert seen["cmd"][0] == str(tmp_path / "bin" / "mitmdump")
    assert "UI: Wiretrace (link below)" in capsys.readouterr().out


def test_run_records_the_other_uis_as_before(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    metas = {}
    # mitmweb's fixed port 8081 may be in use on this Mac; nothing here may touch it.
    monkeypatch.setattr(start, "busy_ports", lambda ports: [])
    for ui in (True, False, "mitmweb", "none"):
        monkeypatch.setattr(start, "supervise", lambda cmd, har_cmd, folder, *a, **k: metas.update({ui: folder}) or 0)
        start.run("staging", "android", "proxy", ui, presets_dir=tmp_path / "presets",
                  sessions_dir=tmp_path / f"sessions-{ui}", bin_dir=tmp_path / "bin", proxy_port=free_port(),
                  wiretrace_dir=tmp_path / "wiretrace", collector_for=lambda *a: (None, "off (test)"),
                  ui_port=free_port())
    assert {ui: session.read_meta(folder)["ui"] for ui, folder in metas.items()} == {
        True: "mitmweb", False: "mitmdump", "mitmweb": "mitmweb", "none": "mitmdump"}


def test_a_busy_ui_port_starts_nothing_and_names_wiretrace_ui(tmp_path, monkeypatch, capsys):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=port)
    assert code == 1 and seen == {}
    err = capsys.readouterr().err
    assert f"Port TCP {port} (Wiretrace UI): in use" in err and "Not started." in err
    assert not (tmp_path / "sessions").exists()


# Command line

def parse_start(monkeypatch, *argv):
    calls = []
    monkeypatch.setattr(start, "run", lambda *args, **kwargs: calls.append((args, kwargs)) or 0)
    assert cli_main.main(["start", "--preset", "staging", *argv]) == 0
    return calls[0]


def test_ui_defaults_to_mitmweb(monkeypatch):
    args, kwargs = parse_start(monkeypatch)
    assert kwargs["ui"] == "mitmweb" and args == ("staging", "device", "wireguard")


def test_ui_wiretrace_and_mitmweb_are_accepted(monkeypatch):
    assert parse_start(monkeypatch, "--ui", "wiretrace")[1]["ui"] == "wiretrace"
    assert parse_start(monkeypatch, "--ui", "mitmweb")[1]["ui"] == "mitmweb"


def test_no_ui_is_unchanged(monkeypatch):
    assert parse_start(monkeypatch, "--no-ui")[1]["ui"] == "none"


@pytest.mark.parametrize("argv", [["--ui", "wiretrace", "--no-ui"], ["--no-ui", "--ui", "wiretrace"],
                                  ["--ui", "mitmweb", "--no-ui"]])
def test_ui_and_no_ui_conflict(monkeypatch, capsys, argv):
    monkeypatch.setattr(start, "run", lambda *a, **k: pytest.fail("must not start"))
    with pytest.raises(SystemExit) as e:
        cli_main.main(["start", "--preset", "staging", *argv])
    assert e.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_an_unknown_ui_is_an_error(monkeypatch, capsys):
    monkeypatch.setattr(start, "run", lambda *a, **k: pytest.fail("must not start"))
    with pytest.raises(SystemExit) as e:
        cli_main.main(["start", "--preset", "staging", "--ui", "tauri"])
    assert e.value.code == 2


def test_the_version_is_0_6_0():
    from cli import __version__

    assert __version__ == "0.6.0"
