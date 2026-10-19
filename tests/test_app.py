"""`wiretrace app state` and `wiretrace app start` (docs/specs/014-mac-app-install-and-launcher.md)."""

import json
import os
import signal
import stat
import sys
import time
from pathlib import Path

import pytest

from cli import __main__ as cli_main
from cli import app, session
from menubar import FRESH_S

PRESET = "name: {name}\napi_hosts:\n  - api.example.com\n"
FOLDER = "2026-10-16_120000_staging_android"

# Stands in for `python -m cli start`. argv: mode, sessions dir, pid file.
FAKE_START = """\
import json, os, sys, time
mode, sessions, pidfile = sys.argv[1:4]
with open(pidfile, "w") as f:
    f.write(str(os.getpid()))
print("cwd " + os.getcwd(), flush=True)
if mode == "record":
    folder = os.path.join(sessions, "2026-10-16_120001_staging_android")
    os.makedirs(folder)
    with open(os.path.join(folder, ".status.json"), "w") as f:
        f.write(json.dumps({"v": 1, "updated_at": time.time(), "preset": "staging"}))
    time.sleep(30)
elif mode == "fail":
    for i in range(20):
        print(f"line {i}", file=sys.stderr)
    sys.exit(1)
else:
    time.sleep(30)
"""


@pytest.fixture
def home(tmp_path):
    root = tmp_path / "wiretrace"
    (root / "presets").mkdir(parents=True)
    (root / "sessions").mkdir()
    for name in ("staging", "other", "example"):
        (root / "presets" / f"{name}.yaml").write_text(PRESET.format(name=name))
    return root


def write_status(sessions: Path, name: str, updated_at: float, preset: str = "staging") -> Path:
    folder = sessions / name
    folder.mkdir()
    (folder / session.STATUS).write_text(json.dumps({"v": 1, "updated_at": updated_at, "preset": preset}))
    return folder


def state(home: Path, now: float | None = None) -> list[str]:
    return app.state(home, home / "presets", home / "sessions", now=now)


# app state

def test_state_idle_lists_projects_without_example_and_the_devices(home):
    assert state(home) == ["idle", "project other", "project staging",
                           "device iPhone", "device Android phone", "device iOS Simulator on this Mac",
                           "device Android emulator on this Mac", "device Another device, with a Wi-Fi proxy",
                           "next other iPhone"]


def test_state_running_when_a_status_file_is_fresh(home):
    write_status(home / "sessions", FOLDER, 1_000.0)
    assert state(home, now=1_000.0 + FRESH_S)[0] == "running staging"


def test_state_idle_when_the_status_file_is_stale(home):
    write_status(home / "sessions", FOLDER, 1_000.0)
    assert state(home, now=1_000.0 + FRESH_S + 1)[0] == "idle"


def test_state_ignores_folders_that_are_not_sessions(home):
    write_status(home / "sessions", "not-a-session", 1_000.0)
    assert state(home, now=1_000.0)[0] == "idle"


def test_state_last_names_an_existing_project_and_a_known_device(home):
    (home / app.LAST).write_text("other Android phone\n")
    assert state(home)[-2:] == ["last other Android phone", "next other Android phone"]


@pytest.mark.parametrize("last", ["deleted Android phone", "example iPhone", "staging Toaster", "", "staging"])
def test_state_does_not_print_a_last_choice_that_no_longer_exists(home, last):
    (home / app.LAST).write_text(last)
    assert not any(line.startswith("last ") for line in state(home))


def test_state_without_presets_lists_no_project(tmp_path):
    lines = app.state(tmp_path, tmp_path / "presets", tmp_path / "sessions")
    assert lines[0] == "idle" and not any(line.startswith(("project ", "next ")) for line in lines)


# What the app starts without asking (spec 018, extension A). The number is the spec's test number.

def next_choice(home: Path):
    return app.next_choice(home, app.projects(home / "presets"))


def test_018_a1_the_last_project_is_started_while_it_is_listed(home):
    (home / "presets" / "default.yaml").write_text(PRESET.format(name="default"))
    (home / app.LAST).write_text("staging Android phone\n")
    assert next_choice(home) == ("staging", "Android phone")


def test_018_a1_a_deleted_last_project_falls_back_to_default_then_to_the_first_listed(home):
    (home / app.LAST).write_text("deleted Android phone\n")
    assert next_choice(home) == ("other", "Android phone")
    (home / "presets" / "default.yaml").write_text(PRESET.format(name="default"))
    assert next_choice(home) == ("default", "Android phone")


def test_018_a1_no_project_is_no_choice(tmp_path):
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "example.yaml").write_text(PRESET.format(name="example"))
    assert app.next_choice(tmp_path, app.projects(tmp_path / "presets")) is None


@pytest.mark.parametrize("last", ["staging Toaster", "staging", "", None, "staging iOS Simulator"])
def test_018_a2_an_unknown_or_missing_last_device_is_iphone_and_the_project_is_kept(home, last):
    if last is not None:
        (home / app.LAST).write_text(last)
    project = "staging" if last and last.startswith("staging") else "other"
    assert next_choice(home) == (project, "iPhone")


def test_018_a3_state_prints_next_last_and_never_the_example(home):
    (home / app.LAST).write_text("example Android emulator on this Mac\n")
    lines = state(home)
    assert lines[-1] == "next other Android emulator on this Mac"
    assert not any("example" in line for line in lines)


@pytest.mark.parametrize("target, device", [("ios", "iPhone"), ("android", "Android phone"),
                                            ("ios-sim", "iOS Simulator on this Mac"),
                                            ("android-emu", "Android emulator on this Mac"),
                                            ("device", "Another device, with a Wi-Fi proxy")])
def test_018_remember_writes_the_project_and_the_app_label_of_the_target(home, target, device):
    app.remember(home, "staging", target)
    assert (home / app.LAST).read_text() == f"staging {device}\n"


def test_018_remember_ignores_an_unknown_target_and_a_failed_write(home, tmp_path):
    app.remember(home, "staging", "phone")
    assert not (home / app.LAST).exists()
    app.remember(tmp_path / "missing", "staging", "ios")
    assert not (tmp_path / "missing").exists()


# app start

@pytest.mark.parametrize("device, target, mode", [
    ("iPhone", "ios", "both"),
    ("Android phone", "android", "both"),
    ("iOS Simulator on this Mac", "ios-sim", "both"),
    ("Android emulator on this Mac", "android-emu", "both"),
    ("Another device, with a Wi-Fi proxy", "device", "both"),
])
def test_each_device_starts_its_target_and_mode_in_app_mode(device, target, mode):
    assert app.start_command("staging", device) == [
        sys.executable, "-m", "cli", "start", "--preset", "staging", "--target", target, "--mode", mode,
        "--ui", "wiretrace", "--from-app"]


def test_every_device_starts_both_modes():
    assert {mode for _, mode in app.DEVICES.values()} == {"both"}


def test_an_unknown_device_is_exit_2(home):
    out, err = [], []
    assert app.start("staging", "Toaster", wiretrace_dir=home, presets_dir=home / "presets",
                     sessions_dir=home / "sessions", out=out.append, err=err.append) == 2
    assert out == [] and err == ["Unknown device 'Toaster'."]
    with pytest.raises(SystemExit) as raised:
        cli_main.main(["app", "start", "--project", "staging", "--device", "Toaster"])
    assert raised.value.code == 2


@pytest.mark.parametrize("project", ["example", "nope", "--ui"])
def test_an_unknown_project_starts_nothing(home, project):
    err = []
    code = app.start(project, "iPhone", wiretrace_dir=home, presets_dir=home / "presets",
                     sessions_dir=home / "sessions", command_for=lambda *a: pytest.fail("must not start"),
                     out=lambda line: pytest.fail("not stdout"), err=err.append)
    assert code == 1 and err == [f"Unknown project {project!r}."]
    assert not (home / app.START_LOG).exists()


class Fake:
    def __init__(self, tmp_path: Path, home: Path, mode: str):
        self.script = tmp_path / "fake-start.py"
        self.script.write_text(FAKE_START)
        self.pidfile = tmp_path / f"{mode}.pid"
        self.home, self.mode = home, mode

    def command(self, project: str, device: str) -> list[str]:
        return [sys.executable, str(self.script), self.mode, str(self.home / "sessions"), str(self.pidfile)]

    def run(self, **kwargs) -> tuple[int, list[str]]:
        """The exit code, and what went to stdout, or to stderr when the code is not 0."""
        out: list[str] = []
        err: list[str] = []
        code = app.start("staging", "Android phone", wiretrace_dir=self.home, presets_dir=self.home / "presets",
                         sessions_dir=self.home / "sessions", command_for=self.command, out=out.append,
                         err=err.append, **kwargs)
        assert not (out if code else err)
        return code, err if code else out

    def pid(self) -> int:
        return int(self.pidfile.read_text())

    def kill(self) -> None:
        if self.pidfile.exists():
            try:
                os.killpg(self.pid(), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.fixture
def fake(tmp_path, home):
    made: list[Fake] = []

    def make(mode: str) -> Fake:
        made.append(Fake(tmp_path, home, mode))
        return made[-1]

    yield make
    for one in made:
        one.kill()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_session_that_records_is_started_and_remembered(home, fake):
    (home / app.LAST).write_text("other iPhone\n")
    run = fake("record")
    code, out = run.run()
    assert (code, out) == (0, ["started"])
    assert (home / app.LAST).read_text() == "staging Android phone\n"
    # Detached: its own session, still running after `start` returned.
    pid = run.pid()
    assert alive(pid) and os.getpgid(pid) == pid != os.getpgrp()
    assert f"cwd {home}" in (home / app.START_LOG).read_text()


def test_a_status_file_from_before_the_start_is_not_this_session(home, fake):
    write_status(home / "sessions", FOLDER, time.time() + 60)
    code, out = fake("wait").run(timeout=0.5)
    assert (code, out) == (0, ["starting"])
    assert not (home / app.LAST).exists()


def test_a_start_that_fails_prints_the_last_lines_and_remembers_nothing(home, fake):
    (home / app.LAST).write_text("other iPhone\n")
    code, out = fake("fail").run()
    assert code == 1
    assert out == ["\n".join(f"line {i}" for i in range(5, 20))]
    assert (home / app.LAST).read_text() == "other iPhone\n"


def test_a_slow_start_returns_starting_and_leaves_the_child_running(home, fake):
    run = fake("wait")
    began = time.monotonic()
    code, out = run.run(timeout=0.5)
    assert (code, out) == (0, ["starting"])
    assert time.monotonic() - began < 5
    assert alive(run.pid())
    assert not (home / app.LAST).exists()


def test_the_start_log_is_truncated_and_private(home, fake):
    log = home / app.START_LOG
    log.write_text("old line from another start\n" * 100)
    log.chmod(0o644)
    fake("fail").run()
    assert "old line" not in log.read_text()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_the_start_log_is_not_followed_through_a_symlink(home, tmp_path, fake):
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep")
    (home / app.START_LOG).symlink_to(target)
    run = fake("fail")
    code, out = run.run()
    assert code == 1 and out[0].startswith(f"Could not write {app.START_LOG}:")
    assert target.read_text() == "keep" and not run.pidfile.exists()
