"""Screenshots of the phone for the bug report form: Android over adb, and the iOS Simulator.

Spec: docs/specs/012-bug-report-form.md. A capture needs exactly one device, runs for at most
TIMEOUT_S, and keeps the output only if it is a PNG of at most MAX_BYTES. Files go only into the
session's screenshots/ folder (0700, files 0600), under names made here. What the tools print is
never shown as is, since it can hold a device serial: only a reason chosen here.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from collectors.ios import count_booted

from . import doctor, session

TIMEOUT_S = 10
MAX_BYTES = 20 << 20
PNG = b"\x89PNG\r\n\x1a\n"
NAME = re.compile(r"\d{8}-\d{6}(?:-\d)?\.png")
TMP = ".capture.tmp"
IPHONE_NOTE = ("Take the screenshot on the iPhone (side button and volume up) "
               "and add it in the tracker yourself.")
PREVIOUS = "Screenshots are off for a previous session"
TIMED_OUT = f"timed out after {TIMEOUT_S} seconds"

Run = Callable[..., subprocess.CompletedProcess]


class Unavailable(Exception):
    """Why no screenshot can be taken. The message is shown in the form as is."""


def _list(argv: list[str], tool: str, run: Run) -> str:
    try:
        result = run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"{tool}: {TIMED_OUT}") from None
    except OSError:
        raise Unavailable(f"{tool} could not be started") from None
    if result.returncode != 0:
        raise Unavailable(f"{tool} exited with code {result.returncode}")
    return result.stdout


def command(target: str, *, find_adb: Callable[[], str | None] = doctor.find_adb,
            which: Callable[[str], str | None] = shutil.which, run: Run = subprocess.run) -> list[str]:
    """The capture command for `target`, once exactly one device is there. Raises Unavailable."""
    if target in ("android", "android-emu"):
        adb = find_adb()
        if not adb:
            raise Unavailable("adb not found; run scripts/setup-mac.sh")
        states = doctor.parse_adb_devices(_list([adb, "devices"], "adb", run))
        total = sum(states.values())
        if total == 0:
            raise Unavailable("No Android device connected")
        if total > 1:
            raise Unavailable("More than one device connected; connect only one")
        state = next(iter(states))
        if state != "device":
            raise Unavailable(f"adb: device {state}")
        return [adb, "exec-out", "screencap", "-p"]
    if target == "ios-sim":
        xcrun = which("xcrun")
        if not xcrun:
            raise Unavailable("xcrun not found; install Xcode's command line tools")
        out = _list([xcrun, "simctl", "list", "devices", "booted", "-j"], "xcrun simctl", run)
        try:
            booted = count_booted(out)
        except (ValueError, KeyError, AttributeError, TypeError):
            raise Unavailable("xcrun simctl gave a device list Wiretrace cannot read") from None
        if booted == 0:
            raise Unavailable("No Simulator booted")
        if booted > 1:
            raise Unavailable("More than one Simulator booted; leave only one running")
        return [xcrun, "simctl", "io", "booted", "screenshot", "--type=png", "-"]
    if target == "ios":
        raise Unavailable(IPHONE_NOTE)
    raise Unavailable("Screenshots need --target android, android-emu or ios-sim")


def availability(target: str, previous: bool = False, **tools) -> tuple[str, str | None]:
    """("available", None), ("manual", the iPhone note) for --target ios, or ("off", the reason)."""
    if previous:
        return "off", PREVIOUS
    if target == "ios":
        return "manual", IPHONE_NOTE
    try:
        command(target, **tools)
    except Unavailable as e:
        return "off", str(e)
    return "available", None


def folder_of(session_folder: Path) -> Path:
    return session_folder / session.SCREENSHOTS


def _make_folder(session_folder: Path) -> Path:
    shots = folder_of(session_folder)
    if shots.is_symlink():
        raise Unavailable("screenshots/ in the session folder is a link; Wiretrace does not follow it")
    shots.mkdir(mode=0o700, exist_ok=True)
    os.chmod(shots, 0o700)
    return shots


def _failure(tool: str, code: int, stderr: bytes) -> str:
    text = stderr.decode("utf-8", "replace").lower()
    for phrase, reason in (("no devices are booted", "No Simulator booted"),
                           ("unauthorized", "adb: device unauthorized"), ("offline", "adb: device offline"),
                           ("more than one", "More than one device connected; connect only one"),
                           ("no devices", "No Android device connected")):
        if phrase in text:
            return reason
    return f"{tool} exited with code {code}"


def _free_name(shots: Path, now: datetime) -> str:
    base = now.strftime("%Y%m%d-%H%M%S")
    for name in (f"{base}.png", *(f"{base}-{n}.png" for n in range(1, 10))):
        if not os.path.lexists(shots / name):
            return name
    raise Unavailable("Too many screenshots in the same second")


def capture(target: str, session_folder: Path, now: datetime | None = None, *,
            find_adb: Callable[[], str | None] = doctor.find_adb,
            which: Callable[[str], str | None] = shutil.which, run: Run = subprocess.run) -> str:
    """Take one screenshot into the session's screenshots/ and return its name. Raises Unavailable."""
    argv = command(target, find_adb=find_adb, which=which, run=run)
    tool = "adb" if target in ("android", "android-emu") else "xcrun simctl"
    shots = _make_folder(session_folder)
    tmp = shots / TMP
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise Unavailable("Could not write in the session's screenshots folder") from None
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                result = run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE, timeout=TIMEOUT_S)
            except subprocess.TimeoutExpired:
                raise Unavailable(TIMED_OUT) from None
            except OSError:
                raise Unavailable(f"{tool} could not be started") from None
        if result.returncode != 0:
            raise Unavailable(_failure(tool, result.returncode, result.stderr or b""))
        if tmp.lstat().st_size > MAX_BYTES:
            raise Unavailable(f"The screenshot is larger than {MAX_BYTES >> 20} MB")
        with open(tmp, "rb") as f:
            if f.read(len(PNG)) != PNG:
                raise Unavailable("The screenshot is not a PNG image")
        name = _free_name(shots, now or datetime.now())
        os.chmod(tmp, 0o600)
        os.replace(tmp, shots / name)
        return name
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def listing(session_folder: Path) -> list[dict]:
    """The screenshots of a session, oldest first: name, size and the time it was taken (HH:MM:SS)."""
    shots = folder_of(session_folder)
    if shots.is_symlink() or not shots.is_dir():
        return []
    found = []
    try:
        entries = list(os.scandir(shots))
    except OSError:
        return []
    for entry in entries:
        if not NAME.fullmatch(entry.name):
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            clock = entry.name[9:15]
            found.append({"name": entry.name, "size": info.st_size,
                          "time": f"{clock[:2]}:{clock[2:4]}:{clock[4:]}"})
    # `-1.png` sorts before `.png`: the second, then the suffix's length, keeps the order taken.
    return sorted(found, key=lambda item: (item["name"][:15], len(item["name"]), item["name"]))


def find(session_folder: Path, name: str) -> Path | None:
    """The listed screenshot called `name`, or None. `name` is compared with the listing, never joined."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        return None
    listed = next((item["name"] for item in listing(session_folder) if item["name"] == name), None)
    return folder_of(session_folder) / listed if listed else None


def download_name(session_name: str, name: str) -> str:
    """`<session>-screenshot-<HHMMSS>.png`, with the same-second suffix when there is one."""
    return f"{session_name}-screenshot-{name[9:-4]}.png"
