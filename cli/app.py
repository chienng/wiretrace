"""`wiretrace app …`: what Wiretrace.app asks for. The applet only shows lists and dialogs.

`state` says whether a session is recording and lists the projects and the devices;
`start` starts a session detached and returns once it records, fails, or takes too
long. Spec: docs/specs/014-mac-app-install-and-launcher.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from menubar import is_fresh, read_status

from . import session
from .preset import PRESETS_DIR, list_presets
from .start import WIRETRACE_DIR

# What the app lists, in this order, and what each choice starts.
DEVICES = {
    "iPhone": ("ios", "wireguard"),
    "Android phone": ("android", "wireguard"),
    "iOS Simulator on this Mac": ("ios-sim", "proxy"),
    "Android emulator on this Mac": ("android-emu", "wireguard"),
    "Another device, with a Wi-Fi proxy": ("device", "proxy"),
}
# The shipped example is a template, not a project.
HIDDEN_PRESETS = ("example",)
LAST = ".app-last"
START_LOG = "app-start.log"
POLL_S = 0.25
START_TIMEOUT_S = 90.0
TAIL_LINES = 15


def projects(presets_dir: Path = PRESETS_DIR) -> list[str]:
    return [name for name in list_presets(presets_dir) if name not in HIDDEN_PRESETS]


def recording(sessions_dir: Path = session.SESSIONS_DIR, now: float | None = None) -> str | None:
    """The preset of a session whose status file is fresh, from the app or from Terminal, or None."""
    now = time.time() if now is None else now
    for folder in session.list_sessions(sessions_dir):
        status = read_status(folder / session.STATUS)
        if is_fresh(status, now):
            preset = status.get("preset")
            if isinstance(preset, str) and preset.isprintable() and preset.strip():
                return preset.strip()
            return "a session"
    return None


def read_last(wiretrace_dir: Path, names: list[str]) -> tuple[str, str] | None:
    """The project and device used last, when both still exist."""
    try:
        text = (wiretrace_dir / LAST).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    project, _, device = text.strip().partition(" ")
    if project in names and device in DEVICES:
        return project, device
    return None


def write_last(wiretrace_dir: Path, project: str, device: str) -> None:
    path = wiretrace_dir / LAST
    tmp = path.with_name(f"{LAST}.tmp")
    tmp.write_text(f"{project} {device}\n", encoding="utf-8")
    os.replace(tmp, path)


def state(wiretrace_dir: Path = WIRETRACE_DIR, presets_dir: Path = PRESETS_DIR,
          sessions_dir: Path = session.SESSIONS_DIR, now: float | None = None) -> list[str]:
    preset = recording(sessions_dir, now)
    lines = [f"running {preset}" if preset else "idle"]
    names = projects(presets_dir)
    lines += [f"project {name}" for name in names]
    lines += [f"device {label}" for label in DEVICES]
    last = read_last(wiretrace_dir, names)
    if last:
        lines.append(f"last {last[0]} {last[1]}")
    return lines


def start_command(project: str, device: str) -> list[str]:
    target, mode = DEVICES[device]
    return [sys.executable, "-m", "cli", "start", "--preset", project, "--target", target,
            "--mode", mode, "--ui", "wiretrace", "--from-app"]


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _tail(path: Path, count: int = TAIL_LINES) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Wiretrace did not start."
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-count:]) or "Wiretrace did not start."


def _open_log(path: Path) -> int:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    # An older file keeps its mode through O_CREAT.
    os.fchmod(fd, 0o600)
    return fd


def _started(sessions_dir: Path, before: set[Path], now: float) -> bool:
    for folder in session.list_sessions(sessions_dir):
        if folder not in before and is_fresh(read_status(folder / session.STATUS), now):
            return True
    return False


def start(project: str, device: str, *, wiretrace_dir: Path = WIRETRACE_DIR, presets_dir: Path = PRESETS_DIR,
          sessions_dir: Path = session.SESSIONS_DIR, timeout: float = START_TIMEOUT_S,
          command_for: Callable[[str, str], list[str]] = start_command,
          out: Callable[[str], None] = print, err: Callable[[str], None] = _stderr) -> int:
    """Start a session detached. 0 with `started` or `starting`; 1 with the log's last lines; 2 for a bad choice.

    Failures go to `err`: the applet's `do shell script` shows stderr when the exit code is not 0.
    """
    if device not in DEVICES:
        err(f"Unknown device {device!r}.")
        return 2
    if project not in projects(presets_dir):
        err(f"Unknown project {project!r}.")
        return 1
    before = set(session.list_sessions(sessions_dir))
    log = wiretrace_dir / START_LOG
    try:
        fd = _open_log(log)
    except OSError as e:
        err(f"Could not write {START_LOG}: {e.strerror or e}")
        return 1
    pythonpath = os.pathsep.join(p for p in (str(wiretrace_dir), os.environ.get("PYTHONPATH")) if p)
    try:
        child = subprocess.Popen(command_for(project, device), cwd=wiretrace_dir, stdin=subprocess.DEVNULL,
                                 stdout=fd, stderr=fd, start_new_session=True,
                                 env={**os.environ, "PYTHONPATH": pythonpath})
    except OSError as e:
        err(f"Could not start Wiretrace: {e.strerror or e}")
        return 1
    finally:
        os.close(fd)
    deadline = time.monotonic() + timeout
    while True:
        if _started(sessions_dir, before, time.time()):
            write_last(wiretrace_dir, project, device)
            out("started")
            return 0
        if child.poll() is not None:
            err(_tail(log))
            return 1
        if time.monotonic() >= deadline:
            out("starting")
            return 0
        time.sleep(POLL_S)
