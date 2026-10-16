"""Session folders: sessions/<YYYY-MM-DD_HHMMSS>_<preset>_<target>/ in the wiretrace folder.

meta.json says what the run was (preset, target, mode, times, versions, log line
counts). It never holds device identifiers, user names or host names, and no absolute paths, which
contain the user name.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
FLOWS = "flows.mitm"
HAR = "flows.har"
DEVICE_LOG = "device.log.jsonl"
APP_LOG = "app.log.jsonl"
# The collector's state: model and OS version only, never a serial, a UDID or the device's name.
DEVICE_STATUS = "device.status.json"
# Counts for the menu bar. Not a report member. No token, host, path, header or body.
STATUS = ".status.json"
META = "meta.json"
# The unmasked HAR exists only under this name, and is removed on every exit path.
HAR_TMP = ".flows.har.tmp"
HAR_MASKED = ".flows.har.masked"
KEEP_DAYS = 14
NAME = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{6})_[A-Za-z0-9][A-Za-z0-9_-]*_(?:android|ios|android-emu|ios-sim|device)")


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now().astimezone()).isoformat(timespec="seconds")


def _owner_only(path: Path, mode: int) -> None:
    """`mkdir` applies the umask, and an older sessions/ may be 0755. A symlink is left alone."""
    if path.is_symlink():
        return
    os.chmod(path, mode)


def create(preset: str, target: str, meta: dict, sessions_dir: Path = SESSIONS_DIR,
           now: datetime | None = None) -> Path:
    """Create the folder and its meta.json. Raises FileExistsError if it already exists.

    `sessions/` and the session folder are 0700, so a session recorded by an older
    version is no longer readable by other users of this Mac either.
    """
    now = now or datetime.now().astimezone()
    folder = sessions_dir / f"{now:%Y-%m-%d_%H%M%S}_{preset}_{target}"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    _owner_only(sessions_dir, 0o700)
    folder.mkdir()
    _owner_only(folder, 0o700)
    write_meta(folder, {**meta, "started_at": timestamp(now)})
    return folder


def read_meta(folder: Path) -> dict:
    return json.loads((folder / META).read_text(encoding="utf-8"))


def write_meta(folder: Path, meta: dict) -> None:
    tmp = folder / f".{META}.tmp"
    tmp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, folder / META)
    _owner_only(folder / META, 0o600)


def update_meta(folder: Path, **changes: object) -> None:
    write_meta(folder, {**read_meta(folder), **changes})


def has_flows(folder: Path) -> bool:
    flows = folder / FLOWS
    return flows.is_file() and flows.stat().st_size > 0


def count_lines(path: Path) -> int:
    """Complete or partial lines in a log file; 0 if it does not exist."""
    try:
        with open(path, "rb") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def has_logs(folder: Path) -> bool:
    return any(count_lines(folder / name) for name in (DEVICE_LOG, APP_LOG))


def remove(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)


def started(name: str) -> datetime | None:
    """When a session folder name says it started (naive local time, as written), or None."""
    match = NAME.fullmatch(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d_%H%M%S")
    except ValueError:
        return None


def _is_session_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and started(path.name) is not None


def list_sessions(sessions_dir: Path = SESSIONS_DIR) -> list[Path]:
    """Session folders by name, oldest first. Symlinks and anything else are left out."""
    try:
        found = [p for p in sessions_dir.iterdir() if _is_session_dir(p)]
    except OSError:
        return []
    return sorted(found, key=lambda p: (started(p.name), p.name))


def remove_old(sessions_dir: Path, now: datetime, keep_days: int = KEEP_DAYS) -> int:
    """Delete session folders that started more than `keep_days` days before `now`. Returns how many."""
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    cutoff = now - timedelta(days=keep_days)
    removed = 0
    for folder in list_sessions(sessions_dir):
        if started(folder.name) >= cutoff or not (folder / META).is_file():
            continue
        try:
            shutil.rmtree(folder)
        except OSError:
            continue
        removed += 1
    return removed
