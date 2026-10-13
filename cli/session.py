"""Session folders: sessions/<YYYY-MM-DD_HHMMSS>_<preset>_<target>/ in the wiretrace folder.

meta.json says what the run was (preset, target, mode, times, versions). It never
holds device identifiers, user names or host names, and no absolute paths, which
contain the user name.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
FLOWS = "flows.mitm"
HAR = "flows.har"
META = "meta.json"


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now().astimezone()).isoformat(timespec="seconds")


def create(preset: str, target: str, meta: dict, sessions_dir: Path = SESSIONS_DIR,
           now: datetime | None = None) -> Path:
    """Create the folder and its meta.json. Raises FileExistsError if it already exists."""
    now = now or datetime.now().astimezone()
    folder = sessions_dir / f"{now:%Y-%m-%d_%H%M%S}_{preset}_{target}"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    write_meta(folder, {**meta, "started_at": timestamp(now)})
    return folder


def read_meta(folder: Path) -> dict:
    return json.loads((folder / META).read_text(encoding="utf-8"))


def write_meta(folder: Path, meta: dict) -> None:
    tmp = folder / f".{META}.tmp"
    tmp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, folder / META)


def update_meta(folder: Path, **changes: object) -> None:
    write_meta(folder, {**read_meta(folder), **changes})


def has_flows(folder: Path) -> bool:
    flows = folder / FLOWS
    return flows.is_file() and flows.stat().st_size > 0


def remove(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
