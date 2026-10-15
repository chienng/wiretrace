import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collectors import Status, Stream, Writer, android, describe, ios, local_iso

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "com.example.app"
PROCESS = "ExampleApp"
# Fake identifiers and log text: none of them may ever reach the Terminal.
SERIAL = "FAKESERIAL0001"
UDID = "00008030-FAKEUDID0001"
SECRET = "SECRET-LOG-TEXT"
TICK = 0.05

# The fakes read FAKE_SCENARIO on every call, so a test can change the world while the
# collector runs, and append what they were asked to do to FAKE_EVENTS.
PRELUDE = """\
import json, os, signal, sys, time

def scenario():
    with open(os.environ["FAKE_SCENARIO"]) as f:
        return json.load(f)

def log(event):
    with open(os.environ["FAKE_EVENTS"], "a") as f:
        f.write(f"{time.time():.3f} {event}\\n")

def alive_others(marker):
    count = 0
    with open(os.environ["FAKE_EVENTS"]) as f:
        for line in f:
            if marker in line and "me=" in line:
                other = int(line.split("me=")[1].split()[0])
                if other != os.getpid():
                    try:
                        os.kill(other, 0)
                        count += 1
                    except ProcessLookupError:
                        pass
    return count

def serve_until_terminated(name, scn, lines, exit_code=None):
    log(f"{name} start args={' '.join(sys.argv[1:])} me={os.getpid()} others={alive_others(name + ' start')}")
    def stop(*_):
        log(f"{name} stop")
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    for line in lines:
        print(line, flush=True)
    if exit_code is not None:
        sys.exit(exit_code)
    while True:
        time.sleep(0.05)
"""

FAKE_ADB = PRELUDE + """
args = sys.argv[1:]
scn = scenario()
if args == ["devices"]:
    print("* daemon not running; starting now at tcp:5037")
    print("List of devices attached")
    for serial in scn["devices"]:
        print(f"{serial}\\tdevice")
elif args == ["shell", "date", "+%s"]:
    print(scn["clock"])
elif args[:3] == ["shell", "pidof", "-s"]:
    if scn["pid"]:
        print(scn["pid"])
    else:
        sys.exit(1)
elif args[:2] == ["shell", "getprop"]:
    print({"ro.product.model": "Pixel 8", "ro.build.version.release": "15",
           "ro.serialno": scn["devices"][0] if scn["devices"] else ""}.get(args[2], ""))
elif args[0] == "logcat":
    pid = next(a.split("=")[1] for a in args if a.startswith("--pid="))
    log(f"logcat start since={args[args.index('-T') + 1]} pid={pid} me={os.getpid()} "
        f"others={alive_others('logcat start')}")
    def stop(*_):
        log(f"logcat stop pid={pid}")
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    print("--------- beginning of main", flush=True)
    for line in scn["lines"].get(pid, []):
        print(line, flush=True)
    while scenario()["devices"]:
        time.sleep(0.05)
    sys.exit(1)
"""

FAKE_PMD = PRELUDE + """
args = sys.argv[1:]
scn = scenario()
if args[:2] == ["usbmux", "list"]:
    print(json.dumps([{"Identifier": udid, "UniqueDeviceID": udid, "SerialNumber": "FAKESERIAL-IOS",
                       "DeviceName": "FAKENAME's iPhone", "ConnectionType": "USB", "ProductType": "iPhone15,2",
                       "ProductVersion": "18.6"} for udid in scn["devices"]]))
elif args[:2] == ["syslog", "live"]:
    serve_until_terminated("syslog", scn, ["banner line, not JSON", *scn["lines"]], scn.get("exit_code"))
"""

FAKE_XCRUN = PRELUDE + """
args = sys.argv[1:]
scn = scenario()
if args[:3] == ["simctl", "list", "devices"]:
    print(json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-0": [
        {"udid": udid, "state": "Booted", "name": "FAKENAME Simulator",
         "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"} for udid in scn["devices"]]}}))
elif args[:3] == ["simctl", "spawn", "booted"]:
    serve_until_terminated("log", scn, ['Filtering the log data using "process == ..."', *scn["lines"]],
                           scn.get("exit_code"))
"""


def wait_for(condition, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


def logcat_line(seconds: int, level: str, tag: str, message: str, ms: int = 481) -> str:
    return f"{seconds}.{ms:03d}  1234  5678 {level} {tag:<8}: {message}"


class World:
    """Fake adb, pymobiledevice3 and xcrun in a temp folder, and the collector under test."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.scenario_file = tmp_path / "scenario.json"
        self.events_file = tmp_path / "events.log"
        self.out = tmp_path / "device.log.jsonl"
        self.status_file = tmp_path / "device.status.json"
        self.stdout_file = tmp_path / "stdout.log"
        self.events_file.touch()
        self.scenario: dict = {"devices": [], "clock": "1728873000", "pid": "", "lines": {}, "exit_code": None}
        self.set()
        self.tools = {}
        for name, body in (("adb", FAKE_ADB), ("pymobiledevice3", FAKE_PMD), ("xcrun", FAKE_XCRUN)):
            tool = tmp_path / name
            tool.write_text(f"#!{sys.executable}\n{body}")
            tool.chmod(0o755)
            self.tools[name] = str(tool)
        self.proc: subprocess.Popen | None = None

    def set(self, **changes) -> None:
        self.scenario.update(changes)
        tmp = self.tmp / "scenario.tmp"
        tmp.write_text(json.dumps(self.scenario))
        os.replace(tmp, self.scenario_file)

    def events(self, prefix: str = "") -> list[str]:
        lines = [line.split(" ", 1)[1] for line in self.events_file.read_text().splitlines()]
        return [line for line in lines if line.startswith(prefix)]

    def times(self, prefix: str) -> list[float]:
        return [float(line.split(" ", 1)[0]) for line in self.events_file.read_text().splitlines()
                if line.split(" ", 1)[1].startswith(prefix)]

    def start(self, target: str, app: str) -> None:
        args = [sys.executable, "-m", "collectors", "--target", target, "--app", app, "--out", str(self.out),
                "--status", str(self.status_file), "--adb", self.tools["adb"], "--pymobiledevice3", self.tools["pymobiledevice3"],
                "--xcrun", self.tools["xcrun"], "--tick", str(TICK)]
        env = {**os.environ, "PYTHONPATH": str(ROOT), "FAKE_SCENARIO": str(self.scenario_file),
               "FAKE_EVENTS": str(self.events_file), "PYTHONUNBUFFERED": "1"}
        with open(self.stdout_file, "w") as out:
            self.proc = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True)

    def status(self) -> list[str]:
        return self.stdout_file.read_text().splitlines()

    def device_status(self) -> dict | None:
        try:
            return json.loads(self.status_file.read_text())
        except (OSError, ValueError):
            return None

    def records(self) -> list[dict]:
        if not self.out.exists():
            return []
        return [json.loads(line) for line in self.out.read_text().splitlines()]

    def stop(self) -> float:
        """SIGINT, as the launcher sends it. Returns the seconds the collector took to exit."""
        started = time.monotonic()
        self.proc.send_signal(signal.SIGINT)
        assert self.proc.wait(timeout=10) == 0
        return time.monotonic() - started

    def cleanup(self) -> None:
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        elif self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.fixture
def world(tmp_path):
    made = World(tmp_path)
    yield made
    made.cleanup()


def pid_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def tool_pids(world: World) -> list[int]:
    return [int(line.split("me=")[1].split()[0]) for line in world.events() if "me=" in line]


# Parsers

def epoch_iso(seconds: int, micro: int) -> str:
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=micro)
    return moment.astimezone().isoformat(timespec="milliseconds")


def test_logcat_line_becomes_a_record():
    record = android.parse_logcat(logcat_line(1728873012, "E", "OkHttp", "Request failed: 500"))
    assert record == {"ts": epoch_iso(1728873012, 481000), "source": "android", "level": "E",
                      "tag": "OkHttp", "message": "Request failed: 500"}


def test_logcat_message_keeps_its_colons_and_spaces():
    record = android.parse_logcat(logcat_line(1728873012, "I", "Orders", "  a: b  : c"))
    assert record["tag"] == "Orders" and record["message"] == "  a: b  : c"


def test_logcat_tag_with_a_colon_and_an_empty_message():
    assert android.parse_logcat("1728873012.5  1  2 W A:B     : text")["tag"] == "A:B"
    empty = android.parse_logcat("1728873012.5  1  2 D Quiet   :")
    assert empty["message"] == "" and empty["ts"] == epoch_iso(1728873012, 500000)


@pytest.mark.parametrize("printed, stored", [("V", "V"), ("D", "D"), ("I", "I"), ("W", "W"), ("E", "E"),
                                             ("F", "F"), ("A", "F")])
def test_logcat_levels(printed, stored):
    assert android.parse_logcat(logcat_line(1728873012, printed, "T", "m"))["level"] == stored


@pytest.mark.parametrize("line", [
    "--------- beginning of main", "--------- switch to system", "", "garbage",
    "1728873012.481  1234  5678 X Tag     : unknown level", "01-02 03:04:05.678  1  2 I Tag: not epoch",
])
def test_logcat_lines_that_do_not_parse(line):
    assert android.parse_logcat(line) is None


SYSLOG = {"pid": 77, "procid": 77, "thread_id": 1, "timestamp": "2026-10-14T09:30:12.481000+07:00",
          "level": "ERROR", "image_name": "/System/Lib/Foundation", "filename": "x.m", "message": "Boom",
          "label": {"subsystem": "com.example.app", "category": "net"}}


def syslog(**changes) -> str:
    return json.dumps({**SYSLOG, **changes})


def test_syslog_line_becomes_a_record():
    assert ios.parse_syslog(syslog()) == {
        "ts": local_iso(datetime.fromisoformat(SYSLOG["timestamp"])), "source": "ios", "level": "E",
        "tag": "net", "message": "Boom"}


@pytest.mark.parametrize("level, stored", [("DEBUG", "D"), ("INFO", "I"), ("NOTICE", "I"), ("ERROR", "E"),
                                           ("FAULT", "F"), ("USER_ACTION", "I"), ("", "I"), (None, "I")])
def test_syslog_levels(level, stored):
    assert ios.parse_syslog(syslog(level=level))["level"] == stored


@pytest.mark.parametrize("changes, tag", [
    ({}, "net"),
    ({"label": {"subsystem": "com.example.app", "category": ""}}, "com.example.app"),
    ({"label": {"subsystem": "com.example.app"}}, "com.example.app"),
    ({"label": None}, "/System/Lib/Foundation"),
    ({"label": None, "image_name": None}, ""),
])
def test_syslog_tag_falls_back(changes, tag):
    assert ios.parse_syslog(syslog(**changes))["tag"] == tag


@pytest.mark.parametrize("line", ["banner, not JSON", "{broken", "[1, 2]", "", syslog(message=None),
                                  json.dumps({"level": "INFO"})])
def test_syslog_lines_that_do_not_parse(line):
    assert ios.parse_syslog(line) is None


SIMLOG = {"timestamp": "2026-10-14 09:30:12.481234+0700", "messageType": "Error", "eventMessage": "Boom",
          "subsystem": "com.example.app", "category": "net", "processImagePath": "/x/ExampleApp"}


def simlog(**changes) -> str:
    return json.dumps({**SIMLOG, **changes})


def test_simulator_line_becomes_a_record():
    record = ios.parse_simulator_log(simlog())
    moment = datetime.fromisoformat(SIMLOG["timestamp"])
    assert record == {"ts": local_iso(moment), "source": "ios-sim", "level": "E", "tag": "net", "message": "Boom"}
    assert ".481" in record["ts"]


@pytest.mark.parametrize("kind, stored", [("Debug", "D"), ("Info", "I"), ("Default", "I"), ("Error", "E"),
                                          ("Fault", "F"), ("Other", "I"), (None, "I")])
def test_simulator_levels(kind, stored):
    assert ios.parse_simulator_log(simlog(messageType=kind))["level"] == stored


def test_simulator_tag_falls_back_to_the_subsystem():
    assert ios.parse_simulator_log(simlog(category=""))["tag"] == "com.example.app"
    assert ios.parse_simulator_log(simlog(category="", subsystem=None))["tag"] == ""


@pytest.mark.parametrize("line", ['Filtering the log data using "process == \\"X\\""', "{broken", "",
                                  simlog(eventMessage=5)])
def test_simulator_lines_that_do_not_parse(line):
    assert ios.parse_simulator_log(line) is None


def test_unusable_timestamp_falls_back_to_the_time_of_reading():
    record = ios.parse_syslog(syslog(timestamp="yesterday"))
    assert datetime.fromisoformat(record["ts"]).tzinfo is not None


def test_stream_counts_lines_that_do_not_parse(tmp_path):
    script = "import sys\nfor line in ['--------- beginning of main', 'x', '1728873012.481  1  2 I T       : ok']:\n" \
             "    print(line)"
    writer = Writer(tmp_path / "out.jsonl")

    async def main():
        stream = Stream([sys.executable, "-c", script], android.parse_logcat, writer)
        assert await stream.start()
        await stream.wait()
        await stream.stop()

    asyncio.run(main())
    writer.close()
    assert (writer.written, writer.skipped) == (1, 2)
    assert len((tmp_path / "out.jsonl").read_text().splitlines()) == 1


def test_no_record_no_file(tmp_path):
    writer = Writer(tmp_path / "out.jsonl")
    assert writer.skipped == 0
    writer.close()
    assert not (tmp_path / "out.jsonl").exists()


def test_writer_appends_one_complete_line_per_record(tmp_path):
    path = tmp_path / "out.jsonl"
    path.write_text('{"earlier": true}\n')
    writer = Writer(path)
    writer.write({"message": "one"})
    # Read before close: every record is already on disk, as a kill would leave it.
    assert path.read_text().splitlines() == ['{"earlier": true}', '{"message": "one"}']
    writer.close()


# Android

def test_android_without_a_device_or_with_two_it_waits(world):
    world.start("android", PACKAGE)
    wait_for(lambda: "Device logs: waiting for a device" in world.status())
    world.set(devices=[SERIAL, "FAKESERIAL0002"])
    wait_for(lambda: "Device logs: more than one device connected; connect only one" in world.status())
    assert not world.events("logcat") and not world.out.exists()
    world.set(devices=[SERIAL], pid="1234")
    wait_for(lambda: world.events("logcat start"))
    assert world.stop() < 2


def test_android_streams_the_app_from_the_device_clock(world):
    lines = [logcat_line(1728873005, "I", "Orders", "Order list loaded"),
             logcat_line(1728873006, "A", "Crash", "FATAL EXCEPTION")]
    world.set(devices=[SERIAL], pid="1234", lines={"1234": lines})
    world.start("android", PACKAGE)
    wait_for(lambda: len(world.records()) == 2)

    [start] = world.events("logcat start")
    assert " pid=1234 " in start and " since=1728873000 " in start
    assert [(r["level"], r["tag"], r["source"]) for r in world.records()] == [("I", "Orders", "android"),
                                                                              ("F", "Crash", "android")]
    assert world.status() == ["Device logs: waiting for the app to start", "Device logs: streaming"]
    world.stop()


def test_android_follows_a_new_process_with_the_same_start_time(world):
    world.set(devices=[SERIAL], pid="1234", lines={
        "1234": [logcat_line(1728873005, "I", "Old", "first process")],
        "5678": [logcat_line(1728873020, "E", "New", "second process")]})
    world.start("android", PACKAGE)
    wait_for(lambda: len(world.records()) == 1)

    # The device clock moves on; the second logcat must still start from the first reading.
    world.set(clock="1728879999", pid="")
    time.sleep(TICK * 6)
    assert len(world.events("logcat start")) == 1
    world.set(pid="5678")
    wait_for(lambda: len(world.records()) == 2)

    first, second = world.events("logcat start")
    assert "since=1728873000" in first and "since=1728873000" in second and "pid=5678" in second
    # The first logcat was stopped, and gone, before the second started (collector invariant 6).
    assert second.endswith("others=0") and "logcat stop pid=1234" in world.events()
    assert world.events().index("logcat stop pid=1234") < world.events().index(second)
    assert "Device logs: app restarted, following the new process" in world.status()
    world.stop()


def test_android_unplugged_device_resumes(world):
    world.set(devices=[SERIAL], pid="1234", lines={"1234": [logcat_line(1728873005, "I", "T", "before")]})
    world.start("android", PACKAGE)
    wait_for(lambda: len(world.records()) == 1)

    world.set(devices=[])
    wait_for(lambda: "Device logs: device disconnected, waiting" in world.status())
    world.set(devices=[SERIAL], pid="1234")
    wait_for(lambda: len(world.status()) == 5)

    assert world.status() == ["Device logs: waiting for the app to start", "Device logs: streaming",
                              "Device logs: device disconnected, waiting",
                              "Device logs: waiting for the app to start", "Device logs: streaming"]
    # The device clock is read once; the restart reuses it.
    assert all("since=1728873000" in line for line in world.events("logcat start"))
    world.stop()


def test_android_app_exit_keeps_logcat_until_a_new_process(world):
    world.set(devices=[SERIAL], pid="1234", lines={"1234": [logcat_line(1728873005, "E", "T", "crash trace")]})
    world.start("android", PACKAGE)
    wait_for(lambda: len(world.records()) == 1)
    world.set(pid="")
    time.sleep(TICK * 8)
    assert len(world.events("logcat start")) == 1 and not world.events("logcat stop")
    world.stop()


def test_android_stop_leaves_no_tool_and_writes_what_was_read(world):
    world.set(devices=[SERIAL], pid="1234", lines={"1234": [logcat_line(1728873005, "I", "T", "read")]})
    world.start("android", PACKAGE)
    wait_for(lambda: world.events("logcat start") and len(world.records()) == 1)

    assert world.stop() < 2
    assert all(pid_gone(pid) for pid in tool_pids(world))
    assert [r["message"] for r in world.records()] == ["read"]


def test_android_waiting_for_a_device_stops_quickly(world):
    world.start("android", PACKAGE)
    wait_for(lambda: world.status())
    assert world.stop() < 2


def test_android_status_never_shows_serial_or_log_text(world):
    world.set(devices=[SERIAL], pid="1234", lines={"1234": [logcat_line(1728873005, "I", "T", SECRET)]})
    world.start("android", PACKAGE)
    wait_for(lambda: len(world.records()) == 1)
    world.set(devices=[])
    wait_for(lambda: "Device logs: device disconnected, waiting" in world.status())
    world.stop()

    shown = world.stdout_file.read_text()
    assert shown and SERIAL not in shown and "FAKESERIAL" not in shown and SECRET not in shown
    assert SERIAL not in world.out.read_text()


def test_android_without_log_lines_writes_no_file(world):
    world.set(devices=[SERIAL], pid="1234")
    world.start("android", PACKAGE)
    wait_for(lambda: world.events("logcat start"))
    time.sleep(TICK * 4)
    world.stop()
    assert not world.out.exists()


# iOS device and Simulator

IOS_CASES = {
    "ios": dict(app=PROCESS, ident=UDID, lines=[syslog(message=SECRET), "{broken", syslog(level="DEBUG")],
                start="syslog start", name="pymobiledevice3", source="ios"),
    "ios-sim": dict(app=PROCESS, ident=UDID, lines=[simlog(eventMessage=SECRET), "{broken", simlog(messageType="Debug")],
                    start="log start", name="xcrun", source="ios-sim"),
}


@pytest.fixture(params=sorted(IOS_CASES))
def ios_case(request, world):
    case = IOS_CASES[request.param]
    return request.param, case, world


def test_ios_streams_one_device(ios_case):
    target, case, world = ios_case
    world.set(devices=[case["ident"]], lines=case["lines"])
    world.start(target, case["app"])
    wait_for(lambda: len(world.records()) == 2)

    assert [(r["source"], r["level"]) for r in world.records()] == [(case["source"], "E"), (case["source"], "D")]
    [start] = world.events(case["start"])
    if target == "ios":
        assert "syslog live -pn ExampleApp --format json" in start
    else:
        assert "spawn booted log stream --style ndjson --level debug --predicate process == \"ExampleApp\"" in start
    assert world.status() == ["Device logs: streaming"]
    world.stop()


def test_ios_waits_for_exactly_one_device(ios_case):
    target, case, world = ios_case
    world.start(target, case["app"])
    wait_for(lambda: "Device logs: waiting for a device" in world.status())
    world.set(devices=[case["ident"], "SECOND-" + case["ident"]])
    wait_for(lambda: "Device logs: more than one device connected; connect only one" in world.status())
    assert not world.events(case["start"])
    world.set(devices=[case["ident"]], lines=case["lines"])
    wait_for(lambda: world.events(case["start"]))
    world.stop()


def test_ios_restarts_the_tool_after_the_delay(ios_case):
    target, case, world = ios_case
    world.set(devices=[case["ident"]], lines=case["lines"], exit_code=3)
    world.start(target, case["app"])
    wait_for(lambda: len(world.events(case["start"])) == 1)
    world.set(exit_code=None)
    wait_for(lambda: len(world.events(case["start"])) == 2)

    first, second = world.times(case["start"])
    # The delay is two ticks: the 2 s of the spec, scaled for the test.
    assert second - first >= 2 * TICK - 0.01
    assert f"Device logs: {case['name']} failed (exit code 3); retrying in 2 s" in world.status()
    world.stop()


def test_ios_device_unplugged_waits_then_resumes(ios_case):
    target, case, world = ios_case
    world.set(devices=[case["ident"]], lines=case["lines"], exit_code=1)
    world.start(target, case["app"])
    wait_for(lambda: world.events(case["start"]))
    world.set(devices=[])
    wait_for(lambda: "Device logs: device disconnected, waiting" in world.status())
    world.set(devices=[case["ident"]], exit_code=None)
    wait_for(lambda: len(world.events(case["start"])) >= 2)
    wait_for(lambda: world.status()[-1] == "Device logs: streaming")
    world.stop()


def test_ios_stop_leaves_no_tool_and_status_is_clean(ios_case):
    target, case, world = ios_case
    world.set(devices=[case["ident"]], lines=case["lines"])
    world.start(target, case["app"])
    wait_for(lambda: len(world.records()) == 2)

    assert world.stop() < 2
    assert all(pid_gone(pid) for pid in tool_pids(world))
    shown = world.stdout_file.read_text()
    assert case["ident"] not in shown and "UDID" not in shown and SECRET not in shown


# Stop behavior with a tool that ignores SIGTERM

def test_stop_kills_a_tool_that_ignores_sigterm(world):
    stubborn = world.tmp / "stubborn-adb"
    stubborn.write_text(f"""#!{sys.executable}
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
args = sys.argv[1:]
if args == ["devices"]:
    print("List of devices attached\\nFAKESERIAL0001\\tdevice")
elif args[:2] == ["shell", "date"]:
    print("1728873000")
elif args[:2] == ["shell", "pidof"]:
    print("1234")
elif args[0] == "logcat":
    open(os.environ["FAKE_EVENTS"], "a").write(f"0 logcat start me={{os.getpid()}}\\n")
    time.sleep(60)
""")
    stubborn.chmod(0o755)
    world.tools["adb"] = str(stubborn)
    world.start("android", PACKAGE)
    wait_for(lambda: world.events("logcat start"))
    assert world.stop() < 2
    assert all(pid_gone(pid) for pid in tool_pids(world))


# Device status file (spec 008 slice C)

STATUS_KEYS = {"state", "message", "source", "app", "model", "os", "updated_at"}


def test_status_file_is_replaced_whole_on_every_change_only(tmp_path):
    path = tmp_path / "device.status.json"
    status = Status(path, "android", PACKAGE)
    status.say("waiting for a device")
    first = json.loads(path.read_text())
    assert set(first) == STATUS_KEYS
    assert (first["state"], first["message"], first["source"], first["app"], first["model"], first["os"]) == (
        "waiting", "waiting for a device", "android", PACKAGE, "", "")
    assert datetime.fromisoformat(first["updated_at"]).tzinfo is not None

    mtime = path.stat().st_mtime_ns
    time.sleep(0.01)
    status.say("waiting for a device")
    assert path.stat().st_mtime_ns == mtime
    status.device("Pixel 8", "Android 15")
    status.say("streaming", state="streaming")
    status.stopped()
    assert json.loads(path.read_text())["state"] == "stopped"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["device.status.json"]


def test_status_without_a_path_writes_nothing(tmp_path, capsys):
    Status().say("streaming", state="streaming")
    assert capsys.readouterr().out == "Device logs: streaming\n"
    assert not list(tmp_path.iterdir())


def test_status_file_that_cannot_be_written_is_skipped(tmp_path, capsys):
    status = Status(tmp_path / "missing" / "device.status.json")
    status.say("waiting for a device")
    assert capsys.readouterr().out == "Device logs: waiting for a device\n"


def test_device_description_is_one_short_printable_line():
    assert describe("  Pixel\n8\t Pro ") == "Pixel 8 Pro"
    assert describe("x" * 200) == "x" * 64
    assert describe("\x1b[31mred") == "[31mred"
    assert describe(None) == describe(7) == ""


def test_iphone_model_and_os_without_name_serial_or_udid():
    out = 'banner\n[{"DeviceName": "FAKENAME", "SerialNumber": "S1", "UniqueDeviceID": "U1", ' \
          '"ProductType": "iPhone15,2", "ProductVersion": "18.6"}]'
    assert ios.describe_usbmux(out) == ("iPhone15,2", "iOS 18.6")
    assert ios.describe_usbmux("[]") == ("", "")
    assert ios.describe_usbmux('[{"ProductType": "a"}, {"ProductType": "b"}]') == ("", "")


def test_simulator_type_and_runtime_without_its_name():
    out = json.dumps({"devices": {
        "com.apple.CoreSimulator.SimRuntime.watchOS-11-0": [{"state": "Shutdown", "name": "W"}],
        "com.apple.CoreSimulator.SimRuntime.iOS-18-0": [
            {"state": "Booted", "name": "My renamed sim",
             "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro"}]}})
    assert ios.describe_booted(out) == ("iPhone 16 Pro", "iOS 18.0")
    assert ios.runtime_name("com.apple.CoreSimulator.SimRuntime.iOS-17-5") == "iOS 17.5"
    assert ios.runtime_name("garbage") == ""


def test_android_status_file_follows_the_states_with_model_and_os(world):
    world.start("android", PACKAGE)
    wait_for(lambda: (world.device_status() or {}).get("state") == "waiting")
    world.set(devices=[SERIAL, "FAKESERIAL0002"])
    wait_for(lambda: (world.device_status() or {}).get("state") == "several")
    world.set(devices=[SERIAL], pid="1234", lines={"1234": [logcat_line(1728873005, "I", "T", SECRET)]})
    wait_for(lambda: (world.device_status() or {}).get("state") == "streaming")
    streaming = world.device_status()
    assert (streaming["model"], streaming["os"], streaming["source"], streaming["app"]) == (
        "Pixel 8", "Android 15", "android", PACKAGE)
    world.set(devices=[])
    wait_for(lambda: (world.device_status() or {}).get("message") == "device disconnected, waiting")
    assert (world.device_status()["model"], world.device_status()["os"]) == ("", "")
    world.stop()
    assert world.device_status()["state"] == "stopped"
    text = world.status_file.read_text()
    assert SERIAL not in text and "FAKESERIAL" not in text and SECRET not in text


def test_ios_status_file_has_model_and_os_and_no_identifier(ios_case):
    target, case, world = ios_case
    world.set(devices=[case["ident"]], lines=case["lines"])
    world.start(target, case["app"])
    wait_for(lambda: (world.device_status() or {}).get("state") == "streaming")
    status = world.device_status()
    expected = ("iPhone15,2", "iOS 18.6") if target == "ios" else ("iPhone 16", "iOS 18.0")
    assert (status["model"], status["os"], status["source"]) == (*expected, case["source"])
    world.stop()
    text = world.status_file.read_text()
    assert json.loads(text)["state"] == "stopped"
    for secret in (case["ident"], "FAKENAME", "FAKESERIAL", SECRET):
        assert secret not in text


def test_cli_requires_the_tool_of_its_target(tmp_path):
    result = subprocess.run([sys.executable, "-m", "collectors", "--target", "ios", "--app", "X",
                             "--out", str(tmp_path / "o")], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2 and "--pymobiledevice3 is required" in result.stderr
