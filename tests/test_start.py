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
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from cli import __main__ as cli_main
from cli import redact, session, start
from cli.preset import Preset

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
PRESET = "name: staging\napi_hosts:\n  - {host}\napp:\n  android_package: com.example.app\n"
OTHER_PRESET = "name: other\napi_hosts:\n  - other.example.com\n"

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

sys.exit(start.run("staging", "android", "proxy", ui=a["ui"], presets_dir=Path(a["presets"]),
                   sessions_dir=Path(a["sessions"]), bin_dir=Path(a["bin"]), proxy_port=a["port"],
                   wiretrace_dir=Path(a["wiretrace"]), collector_for=collector_for, ui_port=a["ui_port"],
                   no_menu_bar=True))
"""

# Stands in for mitmdump: records the signals it gets in FAKE_EVENTS. FAKE_MODE picks
# how it behaves, one comma-separated mode per child started; with -r it plays the HAR conversion.
# `switch:<preset>[@<target>]` writes .switch.json (target android by default) and exits on its
# own, `switch-empty:` does too without flows, `switch-wait:` writes it and then waits for SIGINT.
FAKE_MITMDUMP = """\
import json, os, signal, sys, time

events = os.environ["FAKE_EVENTS"]
modes = os.environ["FAKE_MODE"].split(",")
try:
    with open(events) as f:
        children = sum(1 for line in f if line.strip() == "started")
except FileNotFoundError:
    children = 0
mode = modes[min(children, len(modes) - 1)]
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
    if os.environ.get("FAKE_HAR_SLOW"):
        log("har started")
        time.sleep(1.5)
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
if mode != "empty" and not mode.startswith("switch-empty:"):
    with open(value("--save-stream-file"), "wb") as f:
        f.write(b"flows")
log(f"pid {os.getpid()}")
log("started")

if mode.startswith("switch"):
    kind, asked = mode.split(":", 1)
    name, _, target = asked.partition("@")
    folder = os.path.dirname(value("--save-stream-file"))
    with open(os.path.join(folder, ".switch.json"), "w") as f:
        f.write(json.dumps({"name": name, "target": target or "android"}))
    log("switch-written")
    if kind != "switch-wait":
        time.sleep(0.2)
        log("exit")
        sys.exit(0)
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
                 port: int | None = None, ui: bool | str = False, har_slow: bool = False):
        self.presets = tmp_path / "presets"
        self.sessions = tmp_path / "sessions"
        # Mocks are read from here, never from the real repo's mocks/ folder.
        self.wiretrace_dir = tmp_path / "wiretrace"
        self.events_file = tmp_path / "events.log"
        self.collector_events_file = tmp_path / "collector-events.log"
        self.presets.mkdir()
        (self.presets / "staging.yaml").write_text(PRESET.format(host=host) + preset_extra)
        (self.presets / "other.yaml").write_text(OTHER_PRESET)
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
                "collector": command, "adb": str(adb), "ui": ui, "ui_port": free_port()}
        env = {**os.environ, "PYTHONPATH": str(ROOT),
               "FAKE_EVENTS": str(self.events_file), "FAKE_MODE": fake_mode or "",
               "FAKE_COLLECTOR_EVENTS": str(self.collector_events_file),
               "FAKE_COLLECTOR_MODE": collector if isinstance(collector, str) else "",
               "FAKE_COLLECTOR_LINES": str(collector_lines), "FAKE_APP_LINES": str(app_lines),
               "FAKE_HAR": har, "FAKE_HAR_SLOW": "1" if har_slow else ""}
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

@pytest.mark.parametrize("sender", ["terminal", "menu"])
def test_sigint_stops_child_then_writes_har(launch, sender):
    run = launch("normal")
    run.wait_started()
    if sender == "terminal":
        os.kill(run.proc.pid, signal.SIGINT)  # the launcher only, as `kill -INT` would
    else:
        # A SIGINT from another process, as the menu child's Stop does.
        subprocess.run(
            [sys.executable, "-c", "import os, signal, sys; os.kill(int(sys.argv[1]), signal.SIGINT)",
             str(run.proc.pid)],
            check=True,
        )

    assert run.finish() == 0, run.output
    assert "Stopping…" in run.output
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


@pytest.mark.parametrize("mode", ["proxy", "both"])
@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
def test_port_in_use_starts_nothing(tmp_path, capsys, family, mode):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    with socket.socket(family) as holder:
        if family == socket.AF_INET6:
            holder.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        holder.bind(("0.0.0.0" if family == socket.AF_INET else "::", 0))
        holder.listen()
        port = holder.getsockname()[1]
        code = start.run("staging", "android", mode, ui=False, presets_dir=tmp_path / "presets",
                         sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "no-bin", proxy_port=port,
                         wiretrace_dir=tmp_path / "wiretrace")

    assert code == 1
    err = capsys.readouterr().err
    assert f"TCP {port}" in err and "Not started." in err
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
        "device_logs", "device_logs_off", "device_log_lines", "app_log_lines", "requests", "status",
        "started_at", "ended_at", "redact",
    }
    meta = json.loads(text)
    assert (meta["device_logs"], meta["device_log_lines"], meta["app_log_lines"]) == (None, 0, 0)
    assert isinstance(meta["requests"], int)
    # Why device logs are off, for the window's Setup; never a path.
    assert meta["device_logs_off"] and "/" not in meta["device_logs_off"]
    # Only the rule names in use, so a report still masks them if the preset changes later.
    assert meta["redact"] == {"headers": list(redact.DEFAULT_HEADERS), "json_fields": list(redact.DEFAULT_FIELDS)}


# Command line

PRESET_WITH_FILTER = Preset(name="staging", api_hosts=("a.example.com", "b.example.com"),
                            default_filter="!~t image")


def test_mitmweb_command_wireguard():
    cmd = start.build_command(PRESET_WITH_FILTER, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"))
    assert cmd[:3] == ["/v/bin/mitmweb", "--mode", "wireguard"]
    assert cmd.count("--allow-hosts") == 4
    assert cmd[cmd.index("--save-stream-file") + 1] == "/s/flows.mitm"
    assert "view_filter=!~t image" in cmd
    assert not any("dumper_filter" in arg for arg in cmd)


def test_mitmdump_filter_is_an_option_not_positional():
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"))
    assert cmd[:5] == ["/v/bin/mitmdump", "--mode", "regular", "--listen-port", "8888"]
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


@pytest.mark.parametrize("ui", ["mitmweb", "wiretrace", "none"])
def test_command_passes_the_preset_rules_file_for_every_ui(ui):
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", ui, Path("/s/flows.mitm"), Path("/v/bin"),
                              wiretrace_dir=Path("/d"))
    assert [a for a in cmd if a.startswith("qa_rules_file=")] == ["qa_rules_file=/d/rules/staging.json"]
    assert cmd[cmd.index("qa_rules_file=/d/rules/staging.json") - 1] == "--set"
    assert start.rules_file(PRESET_WITH_FILTER, Path("/d")) == Path("/d/rules/staging.json")


# Banner

def test_banner_counts_mock_files_and_shows_a_relative_path():
    text = start.banner(PRESET_WITH_FILTER, "android", "proxy", True, Path("/s"), mock_count=3)
    assert "Mocks: 3 files in mocks/staging/" in text
    assert "Faults: mitmweb > Options > qa_fault_*" in text
    assert "Rules: rules/staging.json (edit it, or use --ui wiretrace)" in text
    assert "/d/" not in text


def test_banner_without_mocks_or_mitmweb():
    text = start.banner(PRESET_WITH_FILTER, "android", "proxy", False, Path("/s"))
    assert "Mocks: none (add files under mocks/staging/<METHOD>/…)" in text
    assert "Faults:" not in text
    assert "Rules: rules/staging.json (edit it, or use --ui wiretrace)" in text


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
    assert start.needed_ports("both", False, 9999) == [
        ("udp", "0.0.0.0", 51820, "WireGuard"), ("tcp", "0.0.0.0", 9999, "proxy")]
    assert labels("both", start.WIRETRACE) == ["WireGuard", "proxy", "Wiretrace UI"]


# Both modes in one session (spec 017)

def test_both_command_runs_the_proxy_and_wireguard_and_loads_the_guard():
    cmd = start.build_command(PRESET_WITH_FILTER, "both", start.WIRETRACE, Path("/s/flows.mitm"), Path("/v/bin"),
                              proxy_port=9999)
    assert cmd[:7] == ["/v/bin/mitmdump", "--mode", "regular", "--listen-port", "9999", "--mode", "wireguard@51820"]
    assert cmd.count("--mode") == 2 and cmd.count("--listen-port") == 1
    scripts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-s"]
    assert scripts == [str(start.QA_ADDON), str(start.APP_LOGS_ADDON), str(start.PROXY_GUARD), str(start.UI_ADDON)]
    assert "qa_proxy_clients=127.0.0.0/8" in cmd and "qa_proxy_clients=::1" in cmd
    assert "qa_proxy_pin=true" in cmd
    named = start.build_command(PRESET_WITH_FILTER, "both", False, Path("/s/flows.mitm"), Path("/v/bin"),
                                clients=("192.168.1.20",))
    assert "qa_proxy_clients=192.168.1.20" in named and "qa_proxy_pin=false" in named


def test_proxy_and_wireguard_commands_are_unchanged():
    base = [
        "--allow-hosts", r"(^|\.)a\.example\.com(:\d+)?$", "--allow-hosts", r"(^|\.)b\.example\.com(:\d+)?$",
        "--allow-hosts", start.RECEIVER_ALLOW_HOSTS, "--allow-hosts", start.ONBOARDING_ALLOW_HOSTS,
        "--save-stream-file", "/s/flows.mitm", "-s", str(start.QA_ADDON), "-s", str(start.APP_LOGS_ADDON),
    ]
    options = [
        "--set", "qa_api_hosts=a.example.com", "--set", "qa_api_hosts=b.example.com",
        "--set", "qa_mocks_dir=/d/mocks/staging", "--set", f"qa_wiretrace_dir={Path('/d').resolve()}",
        "--set", "qa_rules_file=/d/rules/staging.json", "--set", "qa_request_id_header=X-Request-ID",
        "--set", "qa_app_log_file=/s/app.log.jsonl", "--set", f"save_stream_filter={start.SAVE_FILTER}",
    ]
    proxy = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"),
                                wiretrace_dir=Path("/d"))
    assert proxy == [
        "/v/bin/mitmdump", "--mode", "regular", "--listen-port", "8888", *base, "-s", str(start.PROXY_GUARD),
        *options, "--set", "qa_proxy_clients=127.0.0.0/8", "--set", "qa_proxy_clients=::1",
        "--set", "qa_proxy_pin=true", "--set", "dumper_filter=!~t image",
    ]
    wireguard = start.build_command(PRESET_WITH_FILTER, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"),
                                    wiretrace_dir=Path("/d"))
    assert wireguard == [
        "/v/bin/mitmweb", "--mode", "wireguard", *base, *options, "--set", "view_filter=!~t image",
    ]


@pytest.mark.parametrize("ui", [True, False, start.WIRETRACE])
def test_both_banner_gives_both_ways_and_the_pinning_note(ui):
    text = start.banner(PRESET_WITH_FILTER, "android", "both", ui, Path("/s"), proxy_port=9999)
    lines = text.splitlines()
    assert "Phone: set the Wi-Fi proxy to this Mac's IP address, port 9999." in lines
    tunnel = next(line for line in lines if line.startswith("Phone, if an app ignores the proxy:"))
    assert "turn the WireGuard tunnel on instead" in tunnel
    assert ("scan the QR code" in tunnel) or ("enter the configuration printed below" in tunnel)
    assert ("Wi-Fi proxy: only the first other device that connects is accepted, unless --client names it."
            in lines)
    for single in ("proxy", "wireguard"):
        assert "Phone, if an app ignores the proxy" not in start.banner(PRESET_WITH_FILTER, "android", single, ui, Path("/s"))


def test_the_default_mode_is_both_and_the_three_modes_are_accepted(monkeypatch):
    assert parse_start(monkeypatch)[0][2] == "both"
    for mode in ("both", "proxy", "wireguard"):
        assert parse_start(monkeypatch, "--mode", mode)[0][2] == mode
    assert start.PROXY_PORT == 8888 and start.WIREGUARD_PORT == 51820


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
    meta = session.read_meta(folder)
    # The window's Previous sessions shows this count without reading flows.mitm.
    assert (meta["status"], meta["requests"]) == ("stopped", 2)


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
    assert session.read_meta(folder)["requests"] is None


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
    assert ("Deleted 1 old session(s): Wiretrace keeps the 5 newest, none older than 14 days."
            in run.output)
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
    assert meta["device_logs_off"] == "the collector could not start"


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
    assert scripts == [str(start.QA_ADDON), str(start.APP_LOGS_ADDON), str(start.PROXY_GUARD)]
    assert start.APP_LOGS_ADDON.is_file()
    assert "qa_app_log_file=/s/app.log.jsonl" in cmd
    assert r"save_stream_filter=!~d ^qa-logs\.internal$ & !~d ^mitm\.it$" in cmd
    assert r"^qa-logs\.internal(:\d+)?$" in cmd
    assert all(cmd[i - 1] in ("--set", "--allow-hosts") for i, a in enumerate(cmd)
               if a.startswith(("qa_app_log_file", "save_stream_filter"))
               or a in (start.RECEIVER_ALLOW_HOSTS, start.ONBOARDING_ALLOW_HOSTS))
    # Neither the receiver nor the certificate page is ever an API host.
    assert not any(a.startswith("qa_api_hosts=") and ("qa-logs" in a or "mitm.it" in a) for a in cmd)


@pytest.mark.parametrize("mode", ["wireguard", "proxy", "both"])
@pytest.mark.parametrize("ui", [True, False, start.WIRETRACE])
def test_command_lets_the_certificate_page_load_for_every_mode_and_ui(mode, ui):
    # Regression: mitm.it was not in --allow-hosts, so the phone's browser reached the real site
    # instead of mitmproxy's certificate page, and Part 2 needed a separate plain mitmweb.
    cmd = start.build_command(PRESET_WITH_FILTER, mode, ui, Path("/s/flows.mitm"), Path("/v/bin"))
    hosts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--allow-hosts"]
    assert start.ONBOARDING_ALLOW_HOSTS in hosts
    assert not any(a.startswith(("onboarding=", "onboarding_host=")) for a in cmd)


@pytest.mark.parametrize("authority, matches", [
    ("mitm.it:80", True), ("mitm.it", True), ("MITM.IT:80", True), ("mitm.it:443", True),
    ("www.mitm.it:80", False), ("xmitm.it:80", False), ("mitm.it.evil.io:80", False), ("mitm.itx:80", False),
])
def test_onboarding_allow_hosts_matches_that_host_only(authority, matches):
    assert bool(re.search(start.ONBOARDING_ALLOW_HOSTS, authority, re.IGNORECASE)) is matches


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
    ("mitm.it", False), ("www.mitm.it", True), ("mitm.it.evil.io", True),
])
def test_save_filter_leaves_receiver_and_certificate_page_flows_out(host, saved):
    from mitmproxy import flowfilter
    from mitmproxy.test import tflow

    flow = tflow.tflow()
    flow.request.host = host
    flow.request.headers["Host"] = host
    assert bool(flowfilter.parse(start.SAVE_FILTER)(flow)) is saved


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

    # The state file goes beside the log, in the session folder, for the window.
    status = ["--status", str(out.parent / "device.status.json")]
    for target in ("android", "android-emu"):
        cmd, reason = command(target)
        assert reason == "" and tail(cmd) == ([sys.executable, "-m", "collectors"], [
            "--target", target, "--app", "com.example.myapp", "--out", str(out), *status, "--adb", "/x/adb"])
    cmd, reason = command("ios")
    assert tail(cmd)[1] == ["--target", "ios", "--app", "MyApp", "--out", str(out), *status,
                            "--pymobiledevice3", str(pmd)]
    cmd, reason = command("ios-sim")
    assert tail(cmd)[1] == ["--target", "ios-sim", "--app", "MyApp", "--out", str(out), *status,
                            "--xcrun", "/usr/bin/xcrun"]
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


def test_wiretrace_banner_points_to_the_link_and_the_rules_view():
    text = start.banner(PRESET_WITH_FILTER, "android", "wireguard", "wiretrace", Path("/s"), mock_count=2)
    assert "UI: Wiretrace (link below)" in text
    assert "Rules: Wiretrace > Rules (rules/staging.json)" in text
    assert "Faults:" not in text
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
        seen.update(cmd=cmd, folder=folder, kw=kw)
        return 0

    monkeypatch.setattr(start, "supervise", supervise)
    menu_available = kwargs.pop("menu_available", lambda: "PyObjC not installed (run scripts/setup-mac.sh)")
    code = start.run("staging", "android", "proxy", "wiretrace", presets_dir=tmp_path / "presets",
                     sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "bin", proxy_port=free_port(),
                     wiretrace_dir=tmp_path / "wiretrace", collector_for=lambda *a: (None, "off (test)"),
                     menu_available=menu_available, **kwargs)
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
    assert kwargs["ui"] == "mitmweb" and args == ("staging", "device", "both")


def test_ui_wiretrace_and_mitmweb_are_accepted(monkeypatch):
    assert parse_start(monkeypatch, "--ui", "wiretrace")[1]["ui"] == "wiretrace"
    assert parse_start(monkeypatch, "--ui", "mitmweb")[1]["ui"] == "mitmweb"


def test_no_menu_bar_is_accepted_with_every_window(monkeypatch):
    assert parse_start(monkeypatch, "--ui", "wiretrace", "--no-menu-bar")[1]["no_menu_bar"] is True
    assert parse_start(monkeypatch, "--ui", "mitmweb", "--no-menu-bar")[1]["no_menu_bar"] is True
    _, kwargs = parse_start(monkeypatch, "--no-ui", "--no-menu-bar")
    assert kwargs["ui"] == "none" and kwargs["no_menu_bar"] is True


def test_the_banner_names_the_menu_bar_only_for_the_wiretrace_window():
    text = start.banner(PRESET_WITH_FILTER, "android", "wireguard", "wiretrace", Path("/s"), menu_bar="on")
    assert "Menu bar: on" in text
    assert "Menu bar: off (--no-menu-bar)" in start.banner(
        PRESET_WITH_FILTER, "android", "wireguard", "wiretrace", Path("/s"), menu_bar="off (--no-menu-bar)")
    for ui in ("mitmweb", "none", True, False):
        assert "Menu bar:" not in start.banner(PRESET_WITH_FILTER, "android", "proxy", ui, Path("/s"))


def test_wiretrace_starts_the_menu_and_gives_mitmdump_the_token(tmp_path, monkeypatch, capsys):
    code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=8123, menu_available=lambda: None)
    assert code == 0
    kw = seen["kw"]
    token = kw["menu_token"]
    assert start.menu_bar_text("wiretrace", False, None) == "on"
    assert token and len(token) == 43 and token not in " ".join(kw["menu_cmd"])
    assert kw["menu_cmd"][:3] == [sys.executable, "-m", "menubar"]
    assert kw["menu_cmd"][1:] == ["-m", "menubar", str(os.getpid()), "8123", str(seen["folder"] / session.STATUS)]
    assert kw["child_env"]["WIRETRACE_UI_TOKEN"] == token
    assert "Menu bar: on" in capsys.readouterr().out


def test_no_menu_bar_still_gives_mitmdump_the_token_and_starts_no_menu(tmp_path, monkeypatch, capsys):
    code, seen = run_wiretrace(
        tmp_path, monkeypatch, ui_port=8123, no_menu_bar=True,
        menu_available=lambda: pytest.fail("must not probe"),
    )
    assert code == 0 and seen["kw"]["menu_cmd"] is None
    assert seen["kw"]["child_env"]["WIRETRACE_UI_TOKEN"]
    assert "Menu bar: off (--no-menu-bar)" in capsys.readouterr().out


def test_a_menu_bar_that_cannot_start_is_only_a_banner_line(tmp_path, monkeypatch, capsys):
    code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=8123, menu_available=lambda: "no window server")
    assert code == 0 and seen["kw"]["menu_cmd"] is None
    assert seen["kw"]["child_env"]["WIRETRACE_UI_TOKEN"]
    assert "Menu bar: off (no window server)" in capsys.readouterr().out


@pytest.mark.parametrize("ui", ["mitmweb", "none"])
@pytest.mark.parametrize("no_menu_bar", [False, True])
def test_other_windows_start_no_menu_and_print_no_menu_line(tmp_path, monkeypatch, capsys, ui, no_menu_bar):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    seen = {}
    monkeypatch.setattr(start, "busy_ports", lambda ports: [])
    monkeypatch.setattr(start, "supervise", lambda cmd, har_cmd, folder, *a, **k: seen.update(kw=k) or 0)
    monkeypatch.setattr(start, "_menu_problem", lambda: pytest.fail("must not probe"))
    code = start.run("staging", "android", "proxy", ui, presets_dir=tmp_path / "presets",
                     sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "bin", proxy_port=free_port(),
                     wiretrace_dir=tmp_path / "wiretrace", collector_for=lambda *a: (None, "off (test)"),
                     ui_port=free_port(), no_menu_bar=no_menu_bar)
    assert code == 0 and seen["kw"]["menu_cmd"] is None and seen["kw"]["child_env"] is None
    assert "Menu bar:" not in capsys.readouterr().out


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def _menu_body(mode: str) -> str:
    head = ("import os, sys\n"
            "with open(sys.argv[2], 'w') as handle:\n"
            "    handle.write(str(os.getpid()))\n")
    if mode == "exit":
        return head + "raise SystemExit(1)\n"
    if mode == "ignore":
        return head + ("import signal, time\n"
                       "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                       "while True:\n"
                       "    time.sleep(0.05)\n")
    return head + "import time\nwhile True:\n    time.sleep(0.05)\n"


def _child_body() -> str:
    return """import signal, sys, time
mode, flows = sys.argv[1], sys.argv[2]
stopping = False

def on_sigint(*_):
    global stopping
    stopping = True

signal.signal(signal.SIGINT, on_sigint)
if mode != "empty":
    with open(flows, "wb") as handle:
        handle.write(b"flows")
if mode == "crash":
    time.sleep(0.2)
    raise SystemExit(1)
while not (stopping and mode != "stubborn"):
    time.sleep(0.05)
"""


def _har_body(fail: bool) -> str:
    if fail:
        return "import sys\nraise SystemExit(1)\n"
    return """import sys
args = sys.argv[1:]
har = args[args.index("--set") + 1].split("=", 1)[1]
open(har, "w").write('{"log": {"entries": [{}]}}')
"""


@pytest.mark.parametrize("menu_mode", ["exit", "term", "ignore"])
@pytest.mark.parametrize("how", ["normal", "child_exit", "force", "har_fail"])
def test_no_exit_path_leaves_the_menu_running(tmp_path, menu_mode, how):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    pidfile = tmp_path / f"menu-{menu_mode}-{how}.pid"
    child = _script(tmp_path, f"child-{how}.py", _child_body())
    menu = _script(tmp_path, f"menu-{menu_mode}.py", _menu_body(menu_mode))
    har = _script(tmp_path, f"har-{how}.py", _har_body(how == "har_fail"))
    stops: list[int] = []
    if how == "force":
        child_mode = "stubborn"
    elif how == "child_exit":
        child_mode = "crash"
    else:
        child_mode = "normal"
    if how != "child_exit":
        def stop_when_ready() -> None:
            flows = folder / session.FLOWS
            deadline = time.monotonic() + 5
            while not flows.is_file() and time.monotonic() < deadline:
                time.sleep(0.02)
            stops.append(signal.SIGINT)
            if how == "force":
                time.sleep(0.3)
                stops.append(signal.SIGINT)

        threading.Thread(target=stop_when_ready, daemon=True).start()
    code = start.supervise(
        [sys.executable, str(child), child_mode, str(folder / session.FLOWS)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, stops, menu_cmd=[sys.executable, str(menu), menu_mode, str(pidfile)], menu_token="menu-token",
    )
    pid = int(pidfile.read_text())
    assert process_gone(pid)
    if how == "normal":
        assert code == 0 and session.read_meta(folder)["status"] == "stopped"
        assert (folder / session.HAR).is_file()
    elif how == "har_fail":
        assert code == 1 and session.read_meta(folder)["status"] == "stopped"
        assert not (folder / session.HAR).is_file()
    elif how == "child_exit":
        assert code == 1 and session.read_meta(folder)["status"] == "exited"
    else:
        assert code == 1 and session.read_meta(folder)["status"] == "killed"


def test_a_menu_that_exits_prints_the_closed_line_once_and_capture_continues(tmp_path, capsys):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    pidfile = tmp_path / "menu.pid"
    child = _script(tmp_path, "child.py", _child_body())
    menu = _script(tmp_path, "menu.py", _menu_body("exit"))
    har = _script(tmp_path, "har.py", _har_body(False))
    stops: list[int] = []

    def stop_when_ready() -> None:
        flows = folder / session.FLOWS
        deadline = time.monotonic() + 5
        while not flows.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)
        stops.append(signal.SIGINT)

    threading.Thread(target=stop_when_ready, daemon=True).start()
    code = start.supervise(
        [sys.executable, str(child), "normal", str(folder / session.FLOWS)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, stops, menu_cmd=[sys.executable, str(menu), "exit", str(pidfile)], menu_token="menu-token",
    )
    assert code == 0, capsys.readouterr()
    assert capsys.readouterr().out.count(start.MENU_CLOSED) == 1
    assert session.read_meta(folder)["status"] == "stopped"
    assert (folder / session.HAR).is_file()
    assert process_gone(int(pidfile.read_text()))


def test_stopping_the_menu_does_not_print_the_closed_line(tmp_path, capsys):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    pidfile = tmp_path / "menu.pid"
    child = _script(tmp_path, "child.py", _child_body())
    menu = _script(tmp_path, "menu.py", _menu_body("term"))
    har = _script(tmp_path, "har.py", _har_body(False))
    stops: list[int] = []

    def stop_when_ready() -> None:
        flows = folder / session.FLOWS
        deadline = time.monotonic() + 5
        while not flows.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        stops.append(signal.SIGINT)

    threading.Thread(target=stop_when_ready, daemon=True).start()
    code = start.supervise(
        [sys.executable, str(child), "normal", str(folder / session.FLOWS)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, stops, menu_cmd=[sys.executable, str(menu), "term", str(pidfile)], menu_token="menu-token",
    )
    assert code == 0
    assert start.MENU_CLOSED not in capsys.readouterr().out
    assert process_gone(int(pidfile.read_text()))


def test_the_menu_gets_the_token_on_stdin_only_and_in_its_own_session(tmp_path):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    record = tmp_path / "menu.txt"
    envfile = tmp_path / "mitm-token.txt"
    token = "a" * 43
    menu_body = (
        "import os, sys, time\n"
        "token = sys.stdin.readline().rstrip('\\n')\n"
        f"with open({str(record)!r}, 'w') as out:\n"
        "    out.write('\\n'.join([\n"
        "        ' '.join(sys.argv),\n"
        "        'env ' + ('yes' if 'WIRETRACE_UI_TOKEN' in os.environ else 'no'),\n"
        "        'stdin ' + token,\n"
        "        'pgrp ' + str(os.getpgrp()),\n"
        "        'pid ' + str(os.getpid()),\n"
        "    ]))\n"
        "while True:\n"
        "    time.sleep(0.05)\n"
    )
    child_body = """import os, signal, sys, time
mode, flows, envfile = sys.argv[1], sys.argv[2], sys.argv[3]
with open(envfile, "w") as handle:
    handle.write(os.environ.get("WIRETRACE_UI_TOKEN", ""))
stopping = False

def on_sigint(*_):
    global stopping
    stopping = True

signal.signal(signal.SIGINT, on_sigint)
with open(flows, "wb") as handle:
    handle.write(b"flows")
while not stopping:
    time.sleep(0.05)
"""
    child = _script(tmp_path, "child.py", child_body)
    menu = _script(tmp_path, "menu.py", menu_body)
    har = _script(tmp_path, "har.py", _har_body(False))
    stops: list[int] = []

    def stop_when_ready() -> None:
        flows = folder / session.FLOWS
        deadline = time.monotonic() + 5
        while not (flows.is_file() and envfile.is_file()) and time.monotonic() < deadline:
            time.sleep(0.02)
        stops.append(signal.SIGINT)

    threading.Thread(target=stop_when_ready, daemon=True).start()
    code = start.supervise(
        [sys.executable, str(child), "normal", str(folder / session.FLOWS), str(envfile)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, stops,
        menu_cmd=[sys.executable, str(menu)], menu_token=token,
        child_env={**os.environ, "WIRETRACE_UI_TOKEN": token},
    )
    assert code == 0
    text = record.read_text()
    argv, env_line, stdin_line, pgrp_line, pid_line = text.splitlines()
    assert token not in argv
    assert env_line == "env no"
    assert stdin_line == "stdin " + token
    assert int(pgrp_line.split()[1]) != os.getpgrp()
    assert process_gone(int(pid_line.split()[1]))
    assert envfile.read_text() == token


def test_a_menu_command_that_cannot_start_does_not_stop_capture(tmp_path, capsys):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    child = _script(tmp_path, "child.py", _child_body())
    har = _script(tmp_path, "har.py", _har_body(False))
    stops: list[int] = []

    def stop_when_ready() -> None:
        flows = folder / session.FLOWS
        deadline = time.monotonic() + 5
        while not flows.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        stops.append(signal.SIGINT)

    threading.Thread(target=stop_when_ready, daemon=True).start()
    code = start.supervise(
        [sys.executable, str(child), "normal", str(folder / session.FLOWS)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, stops, menu_cmd=["/no/such/wiretrace-menubar"], menu_token="tok",
    )
    assert code == 0
    assert "Menu bar: off (could not start)" in capsys.readouterr().out
    assert session.read_meta(folder)["status"] == "stopped"
    assert (folder / session.HAR).is_file()


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


def test_the_version_is_0_7_2():
    from cli import __version__

    assert __version__ == "0.9.1"


def test_main_sets_a_private_umask(monkeypatch):
    import os
    monkeypatch.setattr("cli.doctor.main", lambda: 0)
    previous = os.umask(0o022)
    try:
        assert cli_main.main(["doctor"]) == 0
        current = os.umask(0o022)
        assert current == 0o077
    finally:
        os.umask(previous)


def test_proxy_guard_is_loaded_only_in_proxy_mode_and_pins_without_a_client():
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"))
    assert str(start.PROXY_GUARD) in cmd
    assert "qa_proxy_clients=127.0.0.0/8" in cmd and "qa_proxy_clients=::1" in cmd
    assert "qa_proxy_pin=true" in cmd
    wireguard = start.build_command(PRESET_WITH_FILTER, "wireguard", True, Path("/s/flows.mitm"), Path("/v/bin"))
    assert "proxy_guard" not in " ".join(wireguard) and "qa_proxy_" not in " ".join(wireguard)


def test_client_addresses_are_accepted_and_pinning_is_off():
    cmd = start.build_command(PRESET_WITH_FILTER, "proxy", False, Path("/s/flows.mitm"), Path("/v/bin"),
                              clients=("192.168.1.20", "192.168.1.21"))
    assert "qa_proxy_clients=192.168.1.20" in cmd and "qa_proxy_clients=192.168.1.21" in cmd
    assert "qa_proxy_pin=false" in cmd
    assert "qa_proxy_clients=127.0.0.0/8" in cmd


def test_an_invalid_client_address_is_refused(tmp_path, capsys):
    code = start.run("staging", clients=("not-an-ip",), presets_dir=tmp_path, sessions_dir=tmp_path / "sessions")
    assert code == 1
    assert "not-an-ip" in capsys.readouterr().err
    assert not (tmp_path / "sessions").exists()


def test_har_command_loads_the_har_guard():
    cmd = start.har_command(Path("/v/bin"), Path("/s/flows.mitm"), Path("/s/.flows.har.tmp"))
    assert cmd[cmd.index("-s") + 1] == str(start.HAR_GUARD)
    assert "-r" in cmd and any(arg.startswith("hardump=") for arg in cmd)


def test_a_start_writes_flows_mitm_readable_only_by_the_owner(launch):
    import os
    previous = os.umask(0o077)
    try:
        run = launch("normal")
        run.wait_started()
        os.kill(run.proc.pid, signal.SIGINT)
        assert run.finish() == 0, run.output
        [folder] = run.folders()
        assert (folder / session.FLOWS).stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(previous)


# Switching the preset from the window (spec 013)

def started_count(run: Launch) -> int:
    return run.events().count("started")


def no_switch_file(run: Launch) -> bool:
    return not any(run.sessions.rglob(f"*{session.SWITCH}*")) if run.sessions.exists() else True


def test_a_switch_saves_the_session_and_starts_the_named_preset(launch):
    run = launch("switch:other,normal", ui="wiretrace")
    wait_for(lambda: started_count(run) == 2)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert started_count(run) == 2
    # Both folders may carry the same second, so the name order is not the start order.
    folders = run.folders()
    assert len(folders) == 2
    [first] = [f for f in folders if f.name.endswith("_staging_android")]
    [second] = [f for f in folders if f.name.endswith("_other_android")]
    assert no_switch_file(run)
    old, new = session.read_meta(first), session.read_meta(second)
    assert old["status"] == "stopped" and (first / session.HAR).is_file()
    assert (new["preset"], new["api_hosts"], new["status"]) == ("other", ["other.example.com"], "stopped")
    assert (old["target"], old["mode"]) == (new["target"], new["mode"]) == ("android", "proxy")
    assert "Switching presets: saving this session first." in run.output
    assert "exited on its own" not in run.output
    assert "preset other, target android" in run.output and "Decrypting other.example.com" in run.output


def test_a_switch_keeps_only_the_five_newest_previous_sessions(launch, tmp_path):
    now = datetime.now()
    previous = []
    for hours in range(5, 0, -1):
        folder = tmp_path / "sessions" / f"{now - timedelta(hours=hours):%Y-%m-%d_%H%M%S}_staging_android"
        folder.mkdir(parents=True)
        (folder / session.META).write_text("{}")
        previous.append(folder)
    run = launch("switch:other,normal", ui="wiretrace")
    wait_for(lambda: started_count(run) == 2)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    # Five previous at the start: none deleted. At the switch the first session is one of
    # six, so the oldest goes before the next folder is made.
    assert run.output.count("Deleted 1 old session(s)") == 1
    assert not previous[0].exists() and all(folder.is_dir() for folder in previous[1:])
    assert len(run.folders()) == 6


def test_a_stop_signal_wins_over_a_switch_file_on_disk(launch):
    run = launch("switch-wait:other", ui="wiretrace")
    wait_for(lambda: "switch-written" in run.events())
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert started_count(run) == 1
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "stopped"
    assert no_switch_file(run)
    assert "Switching presets" not in run.output


def test_a_stop_during_the_har_write_cancels_the_switch(launch):
    run = launch("switch:other,normal", ui="wiretrace", har_slow=True)
    wait_for(lambda: "har started" in run.events())
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 1, run.output
    assert started_count(run) == 1
    [folder] = run.folders()
    assert folder.name.endswith("_staging_android")
    assert no_switch_file(run)
    assert "flows.har was not written (interrupted)" in run.output


def test_a_wiretrace_child_that_exits_without_a_switch_file_is_one_session(launch):
    run = launch("crash", ui="wiretrace")

    assert run.finish() == 1, run.output
    assert started_count(run) == 1
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "exited"
    assert "exited on its own (exit code 1)" in run.output


def test_a_switch_to_an_unknown_preset_exits_1_and_starts_nothing(launch):
    run = launch("switch:nope,normal", ui="wiretrace")

    assert run.finish() == 1, run.output
    assert started_count(run) == 1
    assert "Unknown preset 'nope'. Available presets: other, staging" in run.output
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "stopped"
    assert no_switch_file(run)


def test_an_empty_session_is_still_removed_and_the_next_preset_still_starts(launch):
    run = launch("switch-empty:other,normal", ui="wiretrace")
    wait_for(lambda: started_count(run) == 2)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert "Nothing was captured; the session folder was removed." in run.output
    [folder] = run.folders()
    assert folder.name.endswith("_other_android")
    assert no_switch_file(run)


def test_without_the_wiretrace_window_a_switch_file_is_not_read_and_nothing_loops(launch):
    run = launch("switch:other,normal", ui=False)

    assert run.finish() == 1, run.output
    assert started_count(run) == 1
    [folder] = run.folders()
    assert session.read_meta(folder)["status"] == "exited"
    assert (folder / session.SWITCH).is_file()


def switching_run(tmp_path, monkeypatch, outcomes, ui="wiretrace", mode="proxy", **kwargs):
    """start.run with a supervise double that reports `outcomes` in turn, then "no switch".

    An outcome's switch is a `start.Switch`, or a preset name for a switch that keeps target android.
    """
    (tmp_path / "presets").mkdir(exist_ok=True)
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    (tmp_path / "presets" / "other.yaml").write_text(OTHER_PRESET)
    calls = []
    pending = list(outcomes)

    def supervise(cmd, har_cmd, folder, *args, **kw):
        calls.append({"cmd": cmd, "folder": folder, "kw": kw})
        if pending:
            state, switch = pending.pop(0)
            if isinstance(switch, str):
                switch = start.Switch(switch, "android")
            kw["outcome"].state, kw["outcome"].switch_to = state, switch
        return 0

    monkeypatch.setattr(start, "supervise", supervise)
    monkeypatch.setattr(start, "busy_ports", kwargs.pop("busy_ports", lambda ports: []))
    code = start.run("staging", "android", mode, ui, presets_dir=tmp_path / "presets",
                     sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "bin", proxy_port=free_port(),
                     wiretrace_dir=tmp_path / "wiretrace", ui_port=free_port(),
                     collector_for=kwargs.pop("collector_for", lambda *a: (None, "off (test)")),
                     menu_available=lambda: None, **kwargs)
    return code, calls


def test_each_session_gets_its_own_folder_token_and_menu(tmp_path, monkeypatch):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")])
    assert code == 0 and len(calls) == 2
    first, second = (c["kw"] for c in calls)
    assert calls[0]["folder"] != calls[1]["folder"]
    assert first["menu_token"] != second["menu_token"]
    assert first["child_env"]["WIRETRACE_UI_TOKEN"] == first["menu_token"]
    assert second["child_env"]["WIRETRACE_UI_TOKEN"] == second["menu_token"]
    assert second["menu_cmd"][-1] == str(calls[1]["folder"] / session.STATUS)
    assert f"qa_rules_file={tmp_path / 'wiretrace' / 'rules' / 'other.json'}" in calls[1]["cmd"]
    assert first["switch"] is True and second["switch"] is True


@pytest.mark.parametrize("state", [start.STOPPING, start.KILLED, None])
def test_only_a_child_that_exited_on_its_own_switches(tmp_path, monkeypatch, state):
    code, calls = switching_run(tmp_path, monkeypatch, [(state, "other")])
    assert code == 0 and len(calls) == 1


def test_the_mitmweb_window_never_switches(tmp_path, monkeypatch):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")], ui="mitmweb")
    assert code == 0 and len(calls) == 1 and calls[0]["kw"]["switch"] is False


def test_a_busy_port_before_the_next_session_starts_nothing_more(tmp_path, monkeypatch, capsys):
    checks = []

    def busy_ports(ports):
        checks.append(ports)
        return [] if len(checks) == 1 else [start.doctor.Result(start.doctor.FAIL, "Port TCP 1 (proxy)", "in use")]

    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")], busy_ports=busy_ports)
    assert code == 1 and len(calls) == 1 and len(checks) == 2
    assert "Not started." in capsys.readouterr().err
    assert [p.name.endswith("_staging_android") for p in (tmp_path / "sessions").iterdir()] == [True]


def test_a_stop_signal_after_the_switch_was_decided_removes_the_new_folder(tmp_path, monkeypatch):
    seen = []

    def collector_for(preset, *args):
        seen.append(preset.name)
        if preset.name == "other":
            os.kill(os.getpid(), signal.SIGINT)
        return None, "off (test)"

    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")], collector_for=collector_for)
    assert code == 0 and len(calls) == 1 and seen == ["staging", "other"]
    assert [p.name.endswith("_staging_android") for p in (tmp_path / "sessions").iterdir()] == [True]


def test_a_stop_signal_during_the_next_banner_starts_nothing(tmp_path, monkeypatch):
    banner = start.banner

    def stopping_banner(preset, *args):
        if preset.name == "other":
            os.kill(os.getpid(), signal.SIGINT)
        return banner(preset, *args)

    monkeypatch.setattr(start, "banner", stopping_banner)
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")])
    assert code == 0 and len(calls) == 1
    assert [p.name.endswith("_staging_android") for p in (tmp_path / "sessions").iterdir()] == [True]


def test_a_folder_name_taken_by_the_switch_is_tried_once_more(tmp_path, monkeypatch):
    create = session.create
    tries = []

    def flaky(*args, **kwargs):
        tries.append(args[0])
        if len(tries) == 2:
            raise FileExistsError
        return create(*args, **kwargs)

    monkeypatch.setattr(start, "SWITCH_RETRY_S", 0)
    monkeypatch.setattr(session, "create", flaky)
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")])
    assert code == 0 and len(calls) == 2 and tries == ["staging", "other", "other"]


def test_a_folder_name_still_taken_after_the_retry_exits_1(tmp_path, monkeypatch, capsys):
    create = session.create

    def taken(*args, **kwargs):
        if args[0] == "other":
            raise FileExistsError
        return create(*args, **kwargs)

    monkeypatch.setattr(start, "SWITCH_RETRY_S", 0)
    monkeypatch.setattr(session, "create", taken)
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")])
    assert code == 1 and len(calls) == 1
    assert "A session folder with this name already exists" in capsys.readouterr().err


@pytest.mark.parametrize("raw", ['{"name": "other", "target": "ios", "token": "x"}', '["other", "ios"]',
                                 '{"name": 3, "target": "ios"}', '{"name": "other", "target": 3}',
                                 '{"name": "other"}', '{"target": "ios"}', "not json",
                                 '{"name": "' + "a" * 5000 + '", "target": "ios"}'])
def test_a_switch_file_that_is_not_one_name_and_one_target_is_no_switch_and_is_deleted(tmp_path, raw):
    (tmp_path / session.SWITCH).write_text(raw)
    assert start.take_switch(tmp_path) is None
    assert not (tmp_path / session.SWITCH).exists()


def test_a_symlinked_switch_file_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text('{"name": "other", "target": "ios"}')
    (tmp_path / session.SWITCH).symlink_to(target)
    assert start.take_switch(tmp_path) is None
    assert not (tmp_path / session.SWITCH).exists() and target.is_file()


def test_a_valid_switch_file_names_the_preset_and_the_target_and_is_deleted(tmp_path):
    (tmp_path / session.SWITCH).write_text('{"name": "other", "target": "ios"}')
    assert start.take_switch(tmp_path) == start.Switch("other", "ios")
    assert not (tmp_path / session.SWITCH).exists()
    assert start.take_switch(tmp_path) is None


# Switching to another phone on the Wi-Fi proxy (spec 021)

PHONE_A, PHONE_B = "192.0.2.71", "192.0.2.72"


def test_021_a_switch_file_with_a_client_names_it_and_is_deleted(tmp_path):
    (tmp_path / session.SWITCH).write_text(json.dumps({"name": "staging", "target": "ios", "client": PHONE_B}))
    assert start.take_switch(tmp_path) == start.Switch("staging", "ios", PHONE_B)
    assert not (tmp_path / session.SWITCH).exists()
    assert start.Switch("staging", "ios").client is None


@pytest.mark.parametrize("raw", [{"name": "staging", "target": "ios", "client": 3},
                                 {"name": "staging", "target": "ios", "client": None},
                                 {"name": "staging", "target": "ios", "client": [PHONE_B]},
                                 {"name": "staging", "target": "ios", "client": PHONE_B, "x": 1},
                                 {"name": "staging", "client": PHONE_B}])
def test_021_a_switch_file_with_a_client_of_another_shape_is_no_switch_and_is_deleted(tmp_path, raw):
    (tmp_path / session.SWITCH).write_text(json.dumps(raw))
    assert start.take_switch(tmp_path) is None
    assert not (tmp_path / session.SWITCH).exists()


@pytest.mark.parametrize("value, expected", [(PHONE_B, PHONE_B), (f"::ffff:{PHONE_B}", PHONE_B),
                                             ("2001:db8::7", "2001:db8::7"), ("127.0.0.1", None), ("::1", None),
                                             ("169.254.3.3", None), ("fe80::1%en0", None), ("0.0.0.0", None),
                                             ("::", None), ("239.1.1.1", None), ("not-an-ip", None), ("", None),
                                             ("192.0.2.0/24", None)])
def test_021_pinnable_client_matches_the_guard(value, expected):
    from addons import proxy_guard

    assert start.pinnable_client(value) == expected == proxy_guard.pinnable(value)


def test_021_the_pinned_option_is_on_the_command_only_with_pinning_in_a_proxy_mode():
    preset = Preset("staging", ("api.example.com",))
    for mode in ("proxy", "both"):
        cmd = start.build_command(preset, mode, "wiretrace", Path("/tmp/s/flows.mitm"), Path("/venv/bin"),
                                  pinned=PHONE_B)
        assert cmd[cmd.index("qa_proxy_pin=true") + 1:cmd.index("qa_proxy_pin=true") + 3] == [
            "--set", f"qa_proxy_pinned={PHONE_B}"]
    named = start.build_command(preset, "both", "wiretrace", Path("/tmp/s/flows.mitm"), Path("/venv/bin"),
                                clients=("192.168.1.20",), pinned=PHONE_B)
    wireguard = start.build_command(preset, "wireguard", "wiretrace", Path("/tmp/s/flows.mitm"), Path("/venv/bin"),
                                    pinned=PHONE_B)
    plain = start.build_command(preset, "both", "wiretrace", Path("/tmp/s/flows.mitm"), Path("/venv/bin"))
    assert not any("qa_proxy_pinned" in part for part in (*named, *wireguard, *plain))


def test_021_only_the_session_after_a_client_switch_is_pinned(tmp_path, monkeypatch, capsys):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios", PHONE_B)),
                                                        (start.RUNNING, start.Switch("staging", "ios")),
                                                        (start.RUNNING, "other")], mode="both")
    assert code == 0 and len(calls) == 4
    pinned = [[part for part in c["cmd"] if part.startswith("qa_proxy_pinned=")] for c in calls]
    assert pinned == [[], [f"qa_proxy_pinned={PHONE_B}"], [], []]
    assert all("qa_proxy_pin=true" in c["cmd"] for c in calls)
    printed = capsys.readouterr()
    assert PHONE_B not in printed.out + printed.err
    for folder in (c["folder"] for c in calls):
        assert PHONE_B not in (folder / session.META).read_text()


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.1.1", "0.0.0.0", "ff02::1", "nope"])
def test_021_a_client_the_launcher_cannot_pin_ends_wiretrace(tmp_path, monkeypatch, capsys, address):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios", address))])
    assert code == 1 and len(calls) == 1
    printed = capsys.readouterr()
    assert start.CLIENT_NOT_PINNABLE in printed.err and address not in printed.out + printed.err
    assert [p.name.endswith("_staging_android") for p in (tmp_path / "sessions").iterdir()] == [True]


def test_021_a_run_started_with_client_does_not_take_a_client_switch(tmp_path, monkeypatch, capsys):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios", PHONE_B))],
                                clients=("192.168.1.20",))
    assert code == 1 and len(calls) == 1
    assert start.CLIENT_WITH_CLIENTS in capsys.readouterr().err


def test_021_a_stop_signal_after_a_client_switch_was_decided_starts_nothing(tmp_path, monkeypatch):
    def collector_for(preset, target, *args):
        if target == "ios":
            os.kill(os.getpid(), signal.SIGINT)
        return None, "off (test)"

    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios", PHONE_B))],
                                collector_for=collector_for)
    assert code == 0 and len(calls) == 1
    assert [p.name.endswith("_staging_android") for p in (tmp_path / "sessions").iterdir()] == [True]


def test_021_the_switch_line_has_no_address():
    line = start.switch_line(start.Switch("staging", "ios", PHONE_B), "ios")
    assert line == "Switching to another device on the Wi-Fi proxy: saving this session first."
    assert start.switch_line(start.Switch("staging", "ios"), "android") == "Switching to iPhone: saving this session first."
    assert start.switch_line(start.Switch("other", "ios"), "ios") == "Switching presets: saving this session first."


# Started from Wiretrace.app (spec 014)

@pytest.mark.parametrize("ui, no_menu_bar", [("mitmweb", False), ("none", False), ("wiretrace", True)])
def test_from_app_without_the_wiretrace_window_and_its_menu_starts_nothing(tmp_path, monkeypatch, capsys,
                                                                           ui, no_menu_bar):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "staging.yaml").write_text(PRESET.format(host="api.example.com"))
    monkeypatch.setattr(start, "supervise", lambda *a, **k: pytest.fail("must not start"))
    code = start.run("staging", "android", "proxy", ui, presets_dir=tmp_path / "presets",
                     sessions_dir=tmp_path / "sessions", bin_dir=tmp_path / "bin", proxy_port=free_port(),
                     wiretrace_dir=tmp_path / "wiretrace", ui_port=free_port(), no_menu_bar=no_menu_bar,
                     menu_available=lambda: None, from_app=True)
    assert code == 1
    assert start.APP_NEEDS_MENU in capsys.readouterr().err
    assert not (tmp_path / "sessions").exists()


def test_from_app_with_the_menu_bar_unavailable_starts_nothing(tmp_path, monkeypatch, capsys):
    code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=free_port(),
                               menu_available=lambda: "no window server", from_app=True)
    assert code == 1 and seen == {}
    assert ("The menu bar item could not start (no window server). "
            "A session started from the app cannot be stopped without it.") in capsys.readouterr().err
    assert not (tmp_path / "sessions").exists()


def test_from_app_hides_the_link_and_starts_the_menu_in_app_mode(tmp_path, monkeypatch):
    probes = []
    code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=8123,
                               menu_available=lambda: probes.append(1), from_app=True)
    assert code == 0 and len(probes) == 1
    cmd, kw = seen["cmd"], seen["kw"]
    assert cmd[cmd.index("qa_ui_print_link=false") - 1] == "--set"
    assert kw["menu_cmd"] == [sys.executable, "-m", "menubar", str(os.getpid()), "8123",
                              str(seen["folder"] / session.STATUS), "--app"]
    assert kw["from_app"] is True and kw["menu_token"] not in " ".join(kw["menu_cmd"])


def test_without_from_app_the_link_is_printed_and_the_menu_is_as_before(tmp_path, monkeypatch):
    code, seen = run_wiretrace(tmp_path, monkeypatch, ui_port=8123, menu_available=lambda: None)
    assert code == 0
    assert not any(arg.startswith("qa_ui_print_link") for arg in seen["cmd"])
    assert "--app" not in seen["kw"]["menu_cmd"] and seen["kw"]["from_app"] is False
    assert wiretrace_command() == wiretrace_command(from_app=False)
    assert "qa_ui_print_link=false" in wiretrace_command(from_app=True)


def test_from_app_is_hidden_and_passed_to_run(monkeypatch, capsys):
    assert parse_start(monkeypatch, "--ui", "wiretrace", "--from-app")[1]["from_app"] is True
    assert parse_start(monkeypatch, "--ui", "wiretrace")[1]["from_app"] is False
    with pytest.raises(SystemExit):
        cli_main.main(["start", "--help"])
    assert "--from-app" not in capsys.readouterr().out


def test_after_a_switch_from_the_app_the_next_session_is_in_app_mode_too(tmp_path, monkeypatch):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")], from_app=True)
    assert code == 0 and len(calls) == 2
    for call in calls:
        assert call["kw"]["from_app"] is True and call["kw"]["menu_cmd"][-1] == "--app"
        assert "qa_ui_print_link=false" in call["cmd"]
        # Spec 019, test 3: the new window still shows the app hint.
        assert "qa_ui_from_app=true" in call["cmd"]


def test_019_02_only_an_app_session_tells_the_window_it_came_from_the_app():
    cmd = wiretrace_command(from_app=True)
    assert cmd[cmd.index("qa_ui_from_app=true") - 1] == "--set"
    assert not any(arg.startswith("qa_ui_from_app") for arg in wiretrace_command())


def _switching_child_body() -> str:
    return """import json, os, signal, sys, time
flows = sys.argv[1]
stopping = False

def on_sigint(*_):
    global stopping
    stopping = True

signal.signal(signal.SIGINT, on_sigint)
with open(flows, "wb") as handle:
    handle.write(b"flows")
with open(os.path.join(os.path.dirname(flows), ".switch.json"), "w") as handle:
    handle.write(json.dumps({"name": "other", "target": "android"}))
while not stopping:
    time.sleep(0.05)
"""


def test_from_app_a_menu_that_exits_stops_and_saves_the_session_and_never_switches(tmp_path, capsys):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    pidfile = tmp_path / "menu.pid"
    child = _script(tmp_path, "child.py", _switching_child_body())
    # Exits once the child is recording and has asked for a switch: a crash, or a force quit.
    menu = _script(tmp_path, "menu.py", (
        "import os, sys, time\n"
        "with open(sys.argv[1], 'w') as handle:\n"
        "    handle.write(str(os.getpid()))\n"
        "while not os.path.exists(sys.argv[2]):\n"
        "    time.sleep(0.02)\n"
        "time.sleep(0.2)\n"
        "raise SystemExit(1)\n"))
    har = _script(tmp_path, "har.py", _har_body(False))
    outcome = start.Outcome()
    code = start.supervise(
        [sys.executable, str(child), str(folder / session.FLOWS)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, [], menu_cmd=[sys.executable, str(menu), str(pidfile), str(folder / session.SWITCH)],
        menu_token="menu-token",
        switch=True, outcome=outcome, from_app=True,
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.count(start.MENU_CLOSED_APP) == 1 and start.MENU_CLOSED not in out
    assert "Switching presets" not in out
    # STOPPING is never a switch in `run`, whatever `.switch.json` said.
    assert outcome.state == start.STOPPING
    assert session.read_meta(folder)["status"] == "stopped"
    assert (folder / session.HAR).is_file()
    assert not (folder / session.SWITCH).exists()
    assert process_gone(int(pidfile.read_text()))


def test_from_app_a_menu_that_cannot_start_stops_the_session(tmp_path, capsys):
    folder = session.create("staging", "android", {"preset": "staging", "status": "running"}, tmp_path / "sessions")
    child = _script(tmp_path, "child.py", _child_body())
    har = _script(tmp_path, "har.py", _har_body(False))
    code = start.supervise(
        [sys.executable, str(child), "normal", str(folder / session.FLOWS)],
        [sys.executable, str(har), "--set", f"hardump={folder / session.HAR_TMP}"],
        folder, [], menu_cmd=["/no/such/wiretrace-menubar"], menu_token="tok", from_app=True,
    )
    out = capsys.readouterr().out
    assert start.MENU_CLOSED_APP in out and "Stopping…" in out
    # The stop can reach the child before it wrote anything; then the folder is removed as usual.
    if folder.exists():
        assert code == 0 and session.read_meta(folder)["status"] == "stopped"
    else:
        assert code == 1 and "Nothing was captured" in out


# Switching the device from the window (spec 018). The number is the spec's test number.

def test_018_01_a_device_switch_saves_the_session_and_starts_the_same_preset_for_the_new_target(launch):
    run = launch("switch:staging@ios,normal", ui="wiretrace")
    wait_for(lambda: started_count(run) == 2)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    folders = run.folders()
    [first] = [f for f in folders if f.name.endswith("_staging_android")]
    [second] = [f for f in folders if f.name.endswith("_staging_ios")]
    assert no_switch_file(run)
    old, new = session.read_meta(first), session.read_meta(second)
    assert old["status"] == "stopped" and (first / session.HAR).is_file()
    assert (old["target"], new["target"]) == ("android", "ios")
    assert old["preset"] == new["preset"] == "staging" and old["mode"] == new["mode"] == "proxy"
    assert "Switching to iPhone: saving this session first." in run.output
    assert "Switching presets" not in run.output
    assert "preset staging, target ios" in run.output


def test_018_01_the_next_session_builds_its_collector_for_the_new_target(tmp_path, monkeypatch):
    seen = []

    def collector_for(preset, target, *args):
        seen.append((preset.name, target))
        return None, "off (test)"

    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios"))],
                                collector_for=collector_for)
    assert code == 0 and len(calls) == 2
    assert seen == [("staging", "android"), ("staging", "ios")]
    assert calls[0]["folder"].name.endswith("_staging_android") and calls[1]["folder"].name.endswith("_staging_ios")
    assert [c["kw"]["target"] for c in calls] == ["android", "ios"]


def test_018_02_a_stop_signal_wins_over_a_device_switch_file(launch):
    run = launch("switch-wait:staging@ios", ui="wiretrace")
    wait_for(lambda: "switch-written" in run.events())
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert started_count(run) == 1
    [folder] = run.folders()
    assert folder.name.endswith("_staging_android") and session.read_meta(folder)["status"] == "stopped"
    assert no_switch_file(run)
    assert "Switching to" not in run.output


@pytest.mark.parametrize("target", ["phone", "", "../ios"])
def test_018_04_a_switch_to_an_unknown_target_exits_1_and_starts_nothing(tmp_path, monkeypatch, capsys, target):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", target))])
    assert code == 1 and len(calls) == 1
    assert "Unknown device." in capsys.readouterr().err
    assert [p.name.endswith("_staging_android") for p in (tmp_path / "sessions").iterdir()] == [True]


def test_018_05_the_ios_simulator_is_refused_in_wireguard_mode(tmp_path, monkeypatch, capsys):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios-sim"))],
                                mode="wireguard")
    assert code == 1 and len(calls) == 1
    assert start.SIMULATOR_NEEDS_PROXY in capsys.readouterr().err


@pytest.mark.parametrize("mode", ["both", "proxy"])
def test_018_05_the_ios_simulator_is_started_with_the_wi_fi_proxy(tmp_path, monkeypatch, mode):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios-sim"))],
                                mode=mode)
    assert code == 0 and len(calls) == 2 and calls[1]["kw"]["target"] == "ios-sim"


def test_018_06_a_preset_switch_keeps_the_target(launch):
    run = launch("switch:other,normal", ui="wiretrace")
    wait_for(lambda: started_count(run) == 2)
    os.kill(run.proc.pid, signal.SIGINT)

    assert run.finish() == 0, run.output
    assert {f.name.split("_", 2)[2] for f in run.folders()} == {"staging_android", "other_android"}
    assert "Switching presets: saving this session first." in run.output


def test_018_07_mode_ports_clients_and_app_mode_do_not_change_across_a_device_switch(tmp_path, monkeypatch):
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios"))],
                                mode="both", clients=("192.0.2.7",), from_app=True)
    assert code == 0 and len(calls) == 2

    def without_folder(call):
        return [arg for arg in call["cmd"] if str(call["folder"]) not in arg]

    first, second = calls
    # Only the session folder differs: the same preset, mode, ports, clients and app mode.
    assert without_folder(first) == without_folder(second)
    assert "qa_proxy_clients=192.0.2.7" in first["cmd"] and "qa_ui_print_link=false" in first["cmd"]
    assert "wireguard@51820" in " ".join(first["cmd"])
    assert first["kw"]["from_app"] is second["kw"]["from_app"] is True
    assert first["kw"]["menu_cmd"][4] == second["kw"]["menu_cmd"][4]


def test_018_switch_line_names_the_device_only_when_the_target_changes():
    assert start.switch_line(start.Switch("staging", "ios"), "android") == (
        "Switching to iPhone: saving this session first.")
    assert start.switch_line(start.Switch("other", "android"), "android") == (
        "Switching presets: saving this session first.")


@pytest.mark.parametrize("target, mode, problem", [
    ("ios", "wireguard", None), ("android", "both", None), ("device", "wireguard", None),
    ("ios-sim", "both", None), ("ios-sim", "proxy", None),
    ("ios-sim", "wireguard", start.SIMULATOR_NEEDS_PROXY), ("phone", "both", "Unknown device."),
])
def test_018_target_problem(target, mode, problem):
    assert start.target_problem(target, mode) == problem


def test_018_every_target_has_a_label_and_is_shown_once():
    assert sorted(start.TARGETS_SHOWN) == sorted(start.TARGETS) == sorted(start.TARGET_LABELS)


# Extension A: what Wiretrace.app starts next time

def last_choice(tmp_path) -> str | None:
    path = tmp_path / "wiretrace" / ".app-last"
    return path.read_text() if path.exists() else None


def test_018_a4_a_device_switch_from_the_app_remembers_the_new_device_before_the_next_spawn(tmp_path, monkeypatch):
    seen = []

    def collector_for(preset, target, *args):
        seen.append(last_choice(tmp_path))
        return None, "off (test)"

    (tmp_path / "wiretrace").mkdir()
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios"))],
                                from_app=True, collector_for=collector_for)
    assert code == 0 and len(calls) == 2
    # Already written when the next session was being prepared.
    assert seen == [None, "staging iPhone\n"]


def test_018_a5_a_preset_switch_from_the_app_remembers_the_new_project_and_the_same_device(tmp_path, monkeypatch):
    (tmp_path / "wiretrace").mkdir()
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, "other")], from_app=True)
    assert code == 0 and len(calls) == 2
    assert last_choice(tmp_path) == "other Android phone\n"


def test_018_a6_a_switch_in_a_terminal_session_leaves_the_app_choice_alone(tmp_path, monkeypatch):
    (tmp_path / "wiretrace").mkdir()
    (tmp_path / "wiretrace" / ".app-last").write_text("staging iPhone\n")
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "android-emu"))])
    assert code == 0 and len(calls) == 2
    assert last_choice(tmp_path) == "staging iPhone\n"


def test_018_a7_a_switch_refused_by_a_re_check_leaves_the_app_choice_alone(tmp_path, monkeypatch):
    (tmp_path / "wiretrace").mkdir()
    (tmp_path / "wiretrace" / ".app-last").write_text("staging iPhone\n")
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("nope", "android"))],
                                from_app=True)
    assert code == 1 and len(calls) == 1
    assert last_choice(tmp_path) == "staging iPhone\n"


def test_018_a8_an_app_choice_that_cannot_be_written_does_not_stop_the_next_session(tmp_path, monkeypatch):
    # No wiretrace folder: the write fails.
    code, calls = switching_run(tmp_path, monkeypatch, [(start.RUNNING, start.Switch("staging", "ios"))],
                                from_app=True)
    assert code == 0 and len(calls) == 2
    assert last_choice(tmp_path) is None
