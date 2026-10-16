"""Screenshots for the bug report form (spec 012): fake adb and xcrun scripts on PATH."""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from cli import screenshot, session

PNG = screenshot.PNG + b"\x00\x00\x00\rIHDR fake image data"
NOW = datetime(2026, 10, 14, 19, 41, 20)

FAKE_ADB = """#!/bin/sh
echo "adb $*" >> "$FAKE_LOG"
case "$1" in
  devices) printf 'List of devices attached\\n'; printf "$FAKE_DEVICES" ;;
  exec-out)
    [ -n "$FAKE_HANG" ] && exec sleep 30
    [ -n "$FAKE_STDERR" ] && printf "$FAKE_STDERR" >&2
    [ -n "$FAKE_EXIT" ] && exit "$FAKE_EXIT"
    exec cat "$FAKE_OUT" ;;
esac
"""

FAKE_XCRUN = """#!/bin/sh
echo "xcrun $*" >> "$FAKE_LOG"
case "$2" in
  list) cat "$FAKE_LIST" ;;
  io) exec cat "$FAKE_OUT" ;;
esac
"""


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A bin folder first on PATH with adb and xcrun, a session folder, and the calls made."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("adb", FAKE_ADB), ("xcrun", FAKE_XCRUN)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    calls, out = tmp_path / "calls.log", tmp_path / "out.bin"
    out.write_bytes(PNG)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(calls))
    monkeypatch.setenv("FAKE_OUT", str(out))
    monkeypatch.setenv("FAKE_DEVICES", "serial-1\\tdevice\\n")
    for name in ("FAKE_HANG", "FAKE_EXIT", "FAKE_STDERR"):
        monkeypatch.delenv(name, raising=False)
    folder = tmp_path / "2026-10-14_190000_staging_android"
    folder.mkdir()

    class Fake:
        session = folder
        output = out

        @staticmethod
        def calls() -> list[str]:
            return calls.read_text().splitlines() if calls.exists() else []

        @staticmethod
        def simulators(booted: int) -> None:
            listing = tmp_path / "list.json"
            devices = [{"state": "Booted", "name": f"Phone {i}"} for i in range(booted)]
            listing.write_text(json.dumps({"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-18-0": devices}}))
            monkeypatch.setenv("FAKE_LIST", str(listing))

    return Fake


def saved(folder: Path) -> list[str]:
    shots = folder / session.SCREENSHOTS
    return sorted(p.name for p in shots.iterdir()) if shots.exists() else []


def test_android_capture_is_saved_owner_only_under_a_server_made_name(fake):
    previous = os.umask(0o022)
    try:
        name = screenshot.capture("android", fake.session, NOW)
    finally:
        os.umask(previous)
    shots = fake.session / session.SCREENSHOTS
    assert name == "20261014-194120.png" and screenshot.NAME.fullmatch(name)
    assert (shots / name).read_bytes() == PNG
    assert shots.stat().st_mode & 0o777 == 0o700
    assert (shots / name).stat().st_mode & 0o777 == 0o600
    assert fake.calls() == ["adb devices", "adb exec-out screencap -p"]
    assert screenshot.capture("android-emu", fake.session, NOW) == "20261014-194120-1.png"
    assert screenshot.listing(fake.session) == [
        {"name": "20261014-194120.png", "size": len(PNG), "time": "19:41:20"},
        {"name": "20261014-194120-1.png", "size": len(PNG), "time": "19:41:20"}]


def test_an_existing_screenshots_folder_is_made_owner_only(fake):
    (fake.session / session.SCREENSHOTS).mkdir(mode=0o755)
    screenshot.capture("android", fake.session, NOW)
    assert (fake.session / session.SCREENSHOTS).stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("devices, reason", [
    ("", "No Android device connected"),
    ("serial-1\\tdevice\\nserial-2\\tdevice\\n", "More than one device connected; connect only one"),
    ("serial-1\\tdevice\\nserial-2\\tunauthorized\\n", "More than one device connected; connect only one"),
    ("serial-1\\tunauthorized\\n", "adb: device unauthorized"),
])
def test_android_needs_exactly_one_ready_device(fake, monkeypatch, devices, reason):
    monkeypatch.setenv("FAKE_DEVICES", devices)
    with pytest.raises(screenshot.Unavailable, match=reason):
        screenshot.capture("android", fake.session, NOW)
    assert saved(fake.session) == []
    assert fake.calls() == ["adb devices"]
    assert screenshot.availability("android") == ("off", reason)


def test_a_capture_that_hangs_is_stopped_and_saves_nothing(fake, monkeypatch):
    monkeypatch.setenv("FAKE_HANG", "1")
    monkeypatch.setattr(screenshot, "TIMEOUT_S", 0.5)
    started = time.monotonic()
    with pytest.raises(screenshot.Unavailable, match="timed out after 10 seconds"):
        screenshot.capture("android", fake.session, NOW)
    assert time.monotonic() - started < 5
    assert saved(fake.session) == []


def test_output_that_is_not_a_png_saves_nothing(fake):
    fake.output.write_bytes(b"<html>not an image</html>")
    with pytest.raises(screenshot.Unavailable, match="not a PNG"):
        screenshot.capture("android", fake.session, NOW)
    assert saved(fake.session) == []


def test_output_over_the_limit_saves_nothing(fake, monkeypatch):
    monkeypatch.setattr(screenshot, "MAX_BYTES", len(PNG) - 1)
    with pytest.raises(screenshot.Unavailable, match="larger than"):
        screenshot.capture("android", fake.session, NOW)
    assert saved(fake.session) == []


def test_a_failed_capture_gives_a_chosen_reason_never_the_tool_output(fake, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    monkeypatch.setenv("FAKE_STDERR", "error: device 'SERIAL-XYZ' unauthorized\\n")
    with pytest.raises(screenshot.Unavailable) as e:
        screenshot.capture("android", fake.session, NOW)
    assert str(e.value) == "adb: device unauthorized"
    monkeypatch.setenv("FAKE_STDERR", "something odd about SERIAL-XYZ\\n")
    with pytest.raises(screenshot.Unavailable) as e:
        screenshot.capture("android", fake.session, NOW)
    assert str(e.value) == "adb exited with code 1" and "SERIAL" not in str(e.value)
    assert saved(fake.session) == []


def test_the_simulator_is_captured_with_simctl(fake):
    fake.simulators(1)
    assert screenshot.capture("ios-sim", fake.session, NOW) == "20261014-194120.png"
    assert fake.calls()[-1] == "xcrun simctl io booted screenshot --type=png -"


@pytest.mark.parametrize("booted, reason", [(0, "No Simulator booted"),
                                            (2, "More than one Simulator booted; leave only one running")])
def test_the_simulator_needs_exactly_one_booted(fake, booted, reason):
    fake.simulators(booted)
    with pytest.raises(screenshot.Unavailable, match=reason):
        screenshot.capture("ios-sim", fake.session, NOW)
    assert saved(fake.session) == []


def test_no_command_runs_for_a_previous_session_an_iphone_or_device(fake):
    assert screenshot.availability("android", previous=True) == ("off", screenshot.PREVIOUS)
    assert screenshot.availability("ios") == ("manual", screenshot.IPHONE_NOTE)
    state, reason = screenshot.availability("device")
    assert state == "off" and "android, android-emu or ios-sim" in reason
    for target in ("ios", "device"):
        with pytest.raises(screenshot.Unavailable):
            screenshot.capture(target, fake.session, NOW)
    assert fake.calls() == [] and saved(fake.session) == []


def test_without_adb_the_reason_says_how_to_install_it(fake):
    state, reason = screenshot.availability("android", find_adb=lambda: None)
    assert state == "off" and "adb not found" in reason


def test_a_screenshots_link_is_not_followed(fake, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (fake.session / session.SCREENSHOTS).symlink_to(elsewhere)
    with pytest.raises(screenshot.Unavailable, match="link"):
        screenshot.capture("android", fake.session, NOW)
    assert list(elsewhere.iterdir()) == [] and screenshot.listing(fake.session) == []


@pytest.mark.parametrize("name", ["../meta.json", "x.png", "20261014-000000.png", "%2e%2e%2fmeta.json",
                                  "20261014-194120.png/../x", ".capture.tmp"])
def test_a_name_that_is_not_listed_is_not_found(fake, name):
    screenshot.capture("android", fake.session, NOW)
    (fake.session / session.META).write_text("{}")
    assert screenshot.find(fake.session, name) is None


def test_a_listed_name_is_found_and_a_link_with_a_valid_name_is_not_listed(fake, tmp_path):
    name = screenshot.capture("android", fake.session, NOW)
    assert screenshot.find(fake.session, name) == fake.session / session.SCREENSHOTS / name
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (fake.session / session.SCREENSHOTS / "20261014-000001.png").symlink_to(outside)
    assert screenshot.find(fake.session, "20261014-000001.png") is None
    assert [item["name"] for item in screenshot.listing(fake.session)] == [name]


def test_download_names():
    assert screenshot.download_name("s", "20261014-194120.png") == "s-screenshot-194120.png"
    assert screenshot.download_name("s", "20261014-194120-2.png") == "s-screenshot-194120-2.png"
