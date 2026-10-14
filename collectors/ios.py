"""iOS device (`pymobiledevice3 syslog live`) and Simulator (`log stream`) collectors.

States: WAIT_DEVICE -> STREAMING -> (tool exits) -> wait -> WAIT_DEVICE. The tool itself
follows the app across restarts, because it filters by process name.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime

from cli.doctor import parse_usbmux_list

from . import Parser, Record, Status, Stream, Timing, Writer, failure, local_iso, run_capture

DEVICE_LEVELS = {"DEBUG": "D", "INFO": "I", "NOTICE": "I", "ERROR": "E", "FAULT": "F"}
SIMULATOR_LEVELS = {"debug": "D", "info": "I", "default": "I", "error": "E", "fault": "F"}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _timestamp(value: object) -> str:
    """ISO 8601 in this Mac's time zone; the time of reading if the tool's value is unusable."""
    try:
        return local_iso(datetime.fromisoformat(_text(value)))
    except ValueError:
        return local_iso(datetime.now())


def _json_object(line: str) -> dict | None:
    try:
        data = json.loads(line)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_syslog(line: str) -> Record | None:
    """One `pymobiledevice3 syslog live --format json` line."""
    data = _json_object(line)
    if data is None or not isinstance(data.get("message"), str):
        return None
    label = data.get("label") if isinstance(data.get("label"), dict) else {}
    tag = _text(label.get("category")) or _text(label.get("subsystem")) or _text(data.get("image_name"))
    return {"ts": _timestamp(data.get("timestamp")), "source": "ios",
            "level": DEVICE_LEVELS.get(_text(data.get("level")).upper(), "I"),
            "tag": tag, "message": data["message"]}


def parse_simulator_log(line: str) -> Record | None:
    """One `log stream --style ndjson` line. Its header line is not JSON, so it is skipped."""
    data = _json_object(line)
    if data is None or not isinstance(data.get("eventMessage"), str):
        return None
    return {"ts": _timestamp(data.get("timestamp")), "source": "ios-sim",
            "level": SIMULATOR_LEVELS.get(_text(data.get("messageType")).lower(), "I"),
            "tag": _text(data.get("category")) or _text(data.get("subsystem")),
            "message": data["eventMessage"]}


def count_booted(out: str) -> int:
    devices = json.loads(out)["devices"]
    return sum(1 for runtime in devices.values() for d in runtime if d.get("state") == "Booted")


class Streaming:
    """One tool that streams the app's log for as long as exactly one device is present."""

    def __init__(self, tool: str, count_argv: list[str], count: Callable[[str], int],
                 stream_argv: list[str], parse: Parser, writer: Writer, status: Status, timing: Timing) -> None:
        self.tool = tool
        self.count_argv = count_argv
        self.count = count
        self.stream_argv = stream_argv
        self.parse = parse
        self.writer = writer
        self.status = status
        self.timing = timing
        self._disconnected = False

    async def run(self) -> None:
        while True:
            await self._wait_device()
            stream = Stream(self.stream_argv, self.parse, self.writer)
            try:
                if not await stream.start():
                    self.status.say(failure(self.tool, None))
                else:
                    self.status.say("streaming")
                    code = await stream.wait()
                    present, _ = await self._device_count()
                    if present == 1:
                        self.status.say(failure(self.tool, code))
                    else:
                        self._disconnected = True
                        self.status.say("device disconnected, waiting")
            finally:
                await stream.stop()
            await asyncio.sleep(self.timing.wait)

    async def _device_count(self) -> tuple[int | None, int | None]:
        """(devices, None) or (None, the tool's exit code)."""
        code, out = await run_capture(self.count_argv)
        if code != 0:
            return None, code
        try:
            return self.count(out), None
        except (ValueError, KeyError, TypeError, AttributeError):
            return None, code

    async def _wait_device(self) -> None:
        while True:
            count, code = await self._device_count()
            if count == 1:
                self._disconnected = False
                return
            if count is None:
                self.status.say(failure(self.tool, code))
            elif count == 0:
                if not self._disconnected:
                    self.status.say("waiting for a device")
            else:
                self.status.say("more than one device connected; connect only one")
            await asyncio.sleep(self.timing.wait)


def ios_device(pymobiledevice3: str, process: str, writer: Writer, status: Status, timing: Timing) -> Streaming:
    return Streaming(
        "pymobiledevice3", [pymobiledevice3, "usbmux", "list"], parse_usbmux_list,
        [pymobiledevice3, "syslog", "live", "-pn", process, "--format", "json"],
        parse_syslog, writer, status, timing)


def ios_simulator(xcrun: str, process: str, writer: Writer, status: Status, timing: Timing) -> Streaming:
    predicate = f'process == "{process}"'
    return Streaming(
        "xcrun", [xcrun, "simctl", "list", "devices", "booted", "-j"], count_booted,
        [xcrun, "simctl", "spawn", "booted", "log", "stream", "--style", "ndjson",
         "--level", "debug", "--predicate", predicate],
        parse_simulator_log, writer, status, timing)
