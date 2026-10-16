"""Menu bar status: what the item shows, and what a click does.

No AppKit here, so the tests run anywhere. The process in ``menubar/__main__.py``
draws whatever :func:`render` returns. Spec: docs/specs/011-menu-bar-status.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# A status file older than this is a frozen session, not a quiet one.
FRESH_S = 5.0
STARTING, LIVE, STALE, STOPPING = "STARTING", "LIVE", "STALE", "STOPPING"
CHECK_ARGV = "--check"
MAX_STATUS_BYTES = 65_536
# The Wiretrace icon, a template image built from app/menubar-icon.svg.
ICON_PATH = Path(__file__).with_name("icon.tiff")
ICON_HEIGHT_PT = 16.0

TARGET_LABELS = {
    "android": "Android",
    "ios": "iOS",
    "android-emu": "Android emulator",
    "ios-sim": "iOS Simulator",
    "device": "Device",
}
MODE_LABELS = {"wireguard": "WireGuard", "proxy": "Proxy"}


@dataclass(frozen=True)
class Row:
    """One menu line. ``enabled`` matters for actions; info lines are not clickable."""

    kind: str
    label: str
    value: str = ""
    action: str = ""
    enabled: bool = True
    alert: bool = False
    shortcut: str = ""


@dataclass(frozen=True)
class MenuView:
    """``title`` is shown when the icon cannot be loaded; ``badge`` is the text next to the icon."""

    state: str
    title: str
    rows: tuple[Row, ...]
    last_error: str | None = None
    badge: str = ""


def is_fresh(status: dict | None, now: float) -> bool:
    """True when ``updated_at`` is at most FRESH_S seconds before ``now`` (exactly FRESH_S counts)."""
    if not isinstance(status, dict):
        return False
    updated = status.get("updated_at")
    if isinstance(updated, bool) or not isinstance(updated, (int, float)):
        return False
    return now - float(updated) <= FRESH_S


def _count(status: dict, key: str) -> int:
    value = status.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0


def _text(status: dict, key: str) -> str:
    value = status.get(key)
    return value if isinstance(value, str) else ""


def device_line(status: dict) -> str:
    """Target, mode, and the device model when the collector reported one."""
    target = TARGET_LABELS.get(_text(status, "target"), _text(status, "target"))
    mode = MODE_LABELS.get(_text(status, "mode"), _text(status, "mode"))
    parts = [part for part in (target, mode) if part]
    model = _text(status, "device_model").strip()
    if model:
        parts.append(model)
    return " · ".join(parts)


def format_duration(started_at: object, now: float) -> str:
    if isinstance(started_at, bool) or not isinstance(started_at, (int, float)):
        return "00:00:00"
    total = max(0, int(now - float(started_at)))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _info(label: str, value: str) -> Row:
    return Row("info", label, value, enabled=False)


def _action(label: str, action: str, *, enabled: bool = True, shortcut: str = "") -> Row:
    return Row("action", label, action=action, enabled=enabled, shortcut=shortcut)


def render(status: dict | None, now: float, stopping: bool, *, seen: bool = False, app: bool = False) -> MenuView:
    """The title and the menu for one tick.

    ``seen`` is true once a status file has been read. A missing file before that
    is STARTING; after that it is STALE (the file vanished). STOPPING never leaves.
    ``app``: the session was started from Wiretrace.app, so this menu is its only stop:
    no Quit, and Stop session in every state.
    """
    if stopping:
        return MenuView(STOPPING, "Wiretrace · stopping", (Row("note", "Wiretrace · stopping", enabled=False),))
    view = _render(status, now, seen)
    if not app:
        return view
    rows = tuple(row for row in view.rows if row.action != "quit")
    if not any(row.action == "stop" for row in rows):
        rows += (_action("Stop session", "stop"),)
    return MenuView(view.state, view.title, rows, view.last_error, view.badge)


def _render(status: dict | None, now: float, seen: bool) -> MenuView:
    if is_fresh(status, now) and isinstance(status, dict):
        errors = _count(status, "errors")
        title = f"Wiretrace · {errors}" if errors else "Wiretrace"
        last = _text(status, "last_error") or None
        rows = (
            _info("Wiretrace", "Recording"),
            _info("Preset", _text(status, "preset")),
            _info("Device", device_line(status)),
            _info("Duration", format_duration(status.get("started_at"), now)),
            Row("stat", "requests", str(_count(status, "requests")), enabled=False),
            Row("stat", "errors", str(errors), enabled=False, alert=errors > 0),
            Row("stat", "rules on", str(_count(status, "rules_on")), enabled=False),
            Row("separator", ""),
            _action("Open Wiretrace", "open", shortcut="o"),
            _action("Show last error", "last_error", enabled=errors > 0, shortcut="r"),
            Row("separator", ""),
            _action("Stop session", "stop"),
            _action("Quit", "quit"),
        )
        return MenuView(LIVE, title, rows, last_error=last if errors else None, badge=str(errors) if errors else "")

    if seen or status is not None:
        rows = (
            Row("note", "No status from Wiretrace", enabled=False),
            _action("Open Wiretrace", "open", shortcut="o"),
            _action("Stop session", "stop"),
            _action("Quit", "quit"),
        )
        return MenuView(STALE, "Wiretrace · ?", rows, badge="?")

    rows = (
        Row("note", "Starting…", enabled=False),
        _action("Open Wiretrace", "open", shortcut="o"),
        _action("Quit", "quit"),
    )
    return MenuView(STARTING, "Wiretrace", rows)


def stop_effect(parent: int, launcher: int, signalled: bool) -> str:
    """What Stop does: ``signal`` once, then ``none``. ``exit`` when this is no longer the launcher's menu.

    ``exit`` is never a signal, so a reused process id is not signalled.
    """
    if parent != launcher:
        return "exit"
    if signalled:
        return "none"
    return "signal"


def window_url(port: int, token: str, flow_id: str | None = None) -> str:
    url = f"http://127.0.0.1:{port}/?token={token}"
    if flow_id:
        url += "#flow=" + quote(flow_id, safe="")
    return url


def row_text(row: Row) -> str:
    """The line the menu shows for ``row``."""
    if row.kind == "stat":
        return f"{row.value} {row.label}"
    if row.kind == "info" and row.value:
        return f"{row.label}    {row.value}"
    return row.label


def read_status(path: Path) -> dict | None:
    """The version-1 status file, or None when it is missing, unreadable or not one."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_STATUS_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    return data


def availability() -> str | None:
    """None when the menu bar can start. Otherwise the reason, for the banner and for doctor.

    The probe is a child process: importing AppKit in the launcher would make
    that process a GUI app.
    """
    root = str(Path(__file__).resolve().parent.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(part for part in (root, env.get("PYTHONPATH")) if part)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "menubar", CHECK_ARGV],
            capture_output=True, text=True, timeout=5, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "could not start"
    if result.returncode == 0:
        return None
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    return lines[-1] if lines else "could not start"
