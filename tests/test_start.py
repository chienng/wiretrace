import getpass
import http.client
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cli import session, start
from cli.preset import Preset

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
PRESET = "name: staging\napi_hosts:\n  - {host}\n"

# Runs start.run() in its own process, so tests can signal it like a Terminal would.
DRIVER = """\
import json, sys
from pathlib import Path
from cli import start
a = json.loads(sys.argv[1])
sys.exit(start.run("staging", "android", "proxy", ui=False, presets_dir=Path(a["presets"]),
                   sessions_dir=Path(a["sessions"]), bin_dir=Path(a["bin"]), proxy_port=a["port"],
                   wiretrace_dir=Path(a["wiretrace"])))
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
    har = value("--set").split("=", 1)[1]
    with open(har, "w") as f:
        json.dump({"log": {"entries": [{}]}}, f)
    sys.exit(0)

stopping = False

def on_sigint(*_):
    global stopping
    log("SIGINT")
    stopping = True

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
                 bin_dir: Path | None = None):
        self.presets = tmp_path / "presets"
        self.sessions = tmp_path / "sessions"
        # Mocks are read from here, never from the real repo's mocks/ folder.
        self.wiretrace_dir = tmp_path / "wiretrace"
        self.events_file = tmp_path / "events.log"
        self.presets.mkdir()
        (self.presets / "staging.yaml").write_text(PRESET.format(host=host))
        if bin_dir is None:
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "mitmdump"
            fake.write_text(f"#!{sys.executable}\n{FAKE_MITMDUMP}")
            fake.chmod(0o755)
        self.port = free_port()
        args = {"presets": str(self.presets), "sessions": str(self.sessions),
                "bin": str(bin_dir), "port": self.port, "wiretrace": str(self.wiretrace_dir)}
        env = {**os.environ, "PYTHONPATH": str(ROOT),
               "FAKE_EVENTS": str(self.events_file), "FAKE_MODE": fake_mode or ""}
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
        "status", "started_at", "ended_at",
    }


# Command line

PRESET_WITH_FILTER = Preset(name="staging", api_hosts=("a.example.com", "b.example.com"),
                            default_filter="!~t image")


def test_mitmweb_command_wireguard():
    cmd = start.build_command(PRESET_WITH_FILTER, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"))
    assert cmd[:3] == ["/v/bin/mitmweb", "--mode", "wireguard"]
    assert cmd.count("--allow-hosts") == 2
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
