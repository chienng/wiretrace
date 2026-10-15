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

from . import ERROR, SEVERAL, STREAMING, Parser, Record, Status, Stream, Timing, Writer, failure, local_iso, run_capture

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


Description = tuple[str, str]


def describe_usbmux(out: str) -> Description:
    """(ProductType, "iOS <ProductVersion>") of the one device; never its name, serial or UDID."""
    devices = json.loads(out[out.find("["):])
    device = devices[0] if isinstance(devices, list) and len(devices) == 1 and isinstance(devices[0], dict) else {}
    version = _text(device.get("ProductVersion"))
    return _text(device.get("ProductType")), f"iOS {version}" if version else ""


def runtime_name(runtime: str) -> str:
    """`com.apple.CoreSimulator.SimRuntime.iOS-18-0` -> `iOS 18.0`."""
    platform, _, version = runtime.rsplit(".", 1)[-1].partition("-")
    return f"{platform} {version.replace('-', '.')}" if platform and version else ""


def describe_booted(out: str) -> Description:
    """The booted Simulator's device type and runtime; never the name, which the user may have set."""
    for runtime, devices in json.loads(out)["devices"].items():
        for device in devices:
            if device.get("state") == "Booted":
                kind = _text(device.get("deviceTypeIdentifier")).rsplit(".", 1)[-1]
                return kind.replace("-", " "), runtime_name(runtime)
    return "", ""


class Streaming:
    """One tool that streams the app's log for as long as exactly one device is present."""

    def __init__(self, tool: str, count_argv: list[str], count: Callable[[str], int],
                 stream_argv: list[str], parse: Parser, writer: Writer, status: Status, timing: Timing,
                 describe: Callable[[str], Description] | None = None) -> None:
        self.tool = tool
        self.count_argv = count_argv
        self.count = count
        self.describe = describe
        self.stream_argv = stream_argv
        self.parse = parse
        self.writer = writer
        self.status = status
        self.timing = timing
        self._disconnected = False
        self._listing = ""

    async def run(self) -> None:
        while True:
            await self._wait_device()
            stream = Stream(self.stream_argv, self.parse, self.writer)
            try:
                if not await stream.start():
                    self.status.say(failure(self.tool, None), state=ERROR)
                else:
                    self.status.say("streaming", state=STREAMING)
                    code = await stream.wait()
                    present, _ = await self._device_count()
                    if present == 1:
                        self.status.say(failure(self.tool, code), state=ERROR)
                    else:
                        self._disconnected = True
                        self.status.device()
                        self.status.say("device disconnected, waiting")
            finally:
                await stream.stop()
            await asyncio.sleep(self.timing.wait)

    async def _device_count(self) -> tuple[int | None, int | None]:
        """(devices, None) or (None, the tool's exit code)."""
        code, out = await run_capture(self.count_argv)
        if code != 0:
            return None, code
        self._listing = out
        try:
            return self.count(out), None
        except (ValueError, KeyError, TypeError, AttributeError):
            return None, code

    def _describe(self) -> None:
        if self.describe is None:
            return
        try:
            self.status.device(*self.describe(self._listing))
        except (ValueError, KeyError, TypeError, AttributeError):
            self.status.device()

    async def _wait_device(self) -> None:
        while True:
            count, code = await self._device_count()
            if count == 1:
                self._disconnected = False
                self._describe()
                return
            self.status.device()
            if count is None:
                self.status.say(failure(self.tool, code), state=ERROR)
            elif count == 0:
                if not self._disconnected:
                    self.status.say("waiting for a device")
            else:
                self.status.say("more than one device connected; connect only one", state=SEVERAL)
            await asyncio.sleep(self.timing.wait)


def ios_device(pymobiledevice3: str, process: str, writer: Writer, status: Status, timing: Timing) -> Streaming:
    return Streaming(
        "pymobiledevice3", [pymobiledevice3, "usbmux", "list"], parse_usbmux_list,
        [pymobiledevice3, "syslog", "live", "-pn", process, "--format", "json"],
        parse_syslog, writer, status, timing, describe_usbmux)


def ios_simulator(xcrun: str, process: str, writer: Writer, status: Status, timing: Timing) -> Streaming:
    predicate = f'process == "{process}"'
    return Streaming(
        "xcrun", [xcrun, "simctl", "list", "devices", "booted", "-j"], count_booted,
        [xcrun, "simctl", "spawn", "booted", "log", "stream", "--style", "ndjson",
         "--level", "debug", "--predicate", predicate],
        parse_simulator_log, writer, status, timing, describe_booted)
