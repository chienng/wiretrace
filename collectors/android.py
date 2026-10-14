"""Android collector: follows the app's `adb logcat`, restarting it when the app's PID changes.

States: WAIT_DEVICE -> WAIT_APP -> STREAMING(pid), and back to WAIT_DEVICE when the
device goes away or logcat exits. `adb logcat --pid` never exits when the process dies,
so the PID is polled with `pidof`.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

from cli.doctor import parse_adb_devices

from . import Record, Status, Stream, Timing, Writer, failure, local_iso, run_capture

TOOL = "adb"
# `-v threadtime -v epoch`: "<sec>.<ms>  <pid>  <tid> <level> <tag padded>: <message>".
_LINE = re.compile(r"^\s*(\d+)\.(\d+)\s+\d+\s+\d+\s+([VDIWEFA])\s+(.*?)\s*:(?: (.*))?$")


def parse_logcat(line: str) -> Record | None:
    match = _LINE.match(line)
    if not match:
        return None
    seconds, fraction, level, tag, message = match.groups()
    moment = datetime.fromtimestamp(int(seconds), tz=timezone.utc)
    moment = moment.replace(microsecond=int(fraction.ljust(6, "0")[:6]))
    return {"ts": local_iso(moment), "source": "android", "level": "F" if level == "A" else level,
            "tag": tag, "message": message or ""}


class Android:
    def __init__(self, adb: str, package: str, writer: Writer, status: Status, timing: Timing) -> None:
        self.adb = adb
        self.package = package
        self.writer = writer
        self.status = status
        self.timing = timing
        # Read once, then reused by every logcat run (collector invariant 6).
        self.since: str | None = None
        self._disconnected = False

    async def run(self) -> None:
        while True:
            await self._wait_device()
            if self.since is None:
                self.since = await self._device_clock()
                if self.since is None:
                    await asyncio.sleep(self.timing.wait)
                    continue
            await self._follow_app()

    async def _device_count(self) -> tuple[int | None, int | None]:
        """(devices in state `device`, None) or (None, the tool's exit code)."""
        code, out = await run_capture([self.adb, "devices"])
        if code != 0:
            return None, code
        return parse_adb_devices(out)["device"], None

    async def _wait_device(self) -> None:
        while True:
            count, code = await self._device_count()
            if count == 1:
                self._disconnected = False
                return
            if count is None:
                self.status.say(failure(TOOL, code))
            elif count == 0:
                if not self._disconnected:
                    self.status.say("waiting for a device")
            else:
                self.status.say("more than one device connected; connect only one")
            await asyncio.sleep(self.timing.wait)

    async def _device_clock(self) -> str | None:
        code, out = await run_capture([self.adb, "shell", "date", "+%s"])
        value = out.strip()
        return value if code == 0 and value.isdigit() else None

    async def _pidof(self) -> str | None:
        code, out = await run_capture([self.adb, "shell", "pidof", "-s", self.package])
        words = out.split()
        return words[0] if code == 0 and words and words[0].isdigit() else None

    def _logcat(self, pid: str) -> Stream:
        argv = [self.adb, "logcat", "-v", "threadtime", "-v", "epoch", f"--pid={pid}", "-T", str(self.since)]
        return Stream(argv, parse_logcat, self.writer)

    async def _follow_app(self) -> None:
        """WAIT_APP and STREAMING: returns when the device is gone or logcat exited."""
        self.status.say("waiting for the app to start")
        stream: Stream | None = None
        pid: str | None = None
        last_check = time.monotonic()
        try:
            while True:
                found = await self._pidof()
                if found and found != pid:
                    # The old logcat is gone before the new one starts (collector invariant 6).
                    if stream:
                        await stream.stop()
                    stream = self._logcat(found)
                    if not await stream.start():
                        self.status.say(failure(TOOL, None))
                        await asyncio.sleep(self.timing.wait)
                        return
                    self.status.say("streaming" if pid is None else "app restarted, following the new process",
                                    repeat=pid is not None)
                    pid = found
                if stream and stream.exited:
                    code = stream.proc.returncode
                    count, _ = await self._device_count()
                    if count == 1:
                        self.status.say(failure(TOOL, code))
                        await asyncio.sleep(self.timing.wait)
                    else:
                        self._gone()
                    return
                if not found and time.monotonic() - last_check >= self.timing.wait:
                    last_check = time.monotonic()
                    count, _ = await self._device_count()
                    if count != 1:
                        self._gone()
                        return
                await asyncio.sleep(self.timing.poll)
        finally:
            if stream:
                await stream.stop()

    def _gone(self) -> None:
        self._disconnected = True
        self.status.say("device disconnected, waiting")
