"""Device log collectors: `python -m collectors`, one child process of `wiretrace start`.

The collector runs in its own process group, so the launcher can kill it and every tool
it started with one killpg. Nothing here prints or stores a device serial, a UDID or log
content outside the log file. Spec: docs/specs/004-log-collectors-and-app-log-receiver.md.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PREFIX = "Device logs: "
TERM_GRACE_S = 1.0
DRAIN_S = 0.3
TOOL_TIMEOUT_S = 10
# A longer line is skipped, not stored.
LINE_LIMIT = 1 << 24

Record = dict[str, str]
Parser = Callable[[str], Record | None]


@dataclass(frozen=True)
class Timing:
    poll: float = 1.0  # Android: `pidof` interval
    wait: float = 2.0  # device count while waiting, and the delay before a retry


class Status:
    """Collector state lines, printed on a change only."""

    def __init__(self) -> None:
        self._last: str | None = None

    def say(self, message: str, repeat: bool = False) -> None:
        if message == self._last and not repeat:
            return
        self._last = message
        # The Terminal window may be gone; the log matters more than the message.
        try:
            print(PREFIX + message, flush=True)
        except OSError:
            pass


class Writer:
    """Appends records to the log file, one `write` per line. No record, no file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.written = 0
        self.skipped = 0
        self.failed = 0
        self._file = None

    def write(self, record: Record) -> None:
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            if self._file is None:
                self._file = open(self.path, "ab", buffering=0)
            self._file.write(line)
        except OSError:
            self.failed += 1
            return
        self.written += 1

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def local_iso(moment: datetime) -> str:
    return moment.astimezone().isoformat(timespec="milliseconds")


def failure(tool: str, code: int | None) -> str:
    if code is None:
        return f"{tool} did not run or answer; retrying in 2 s"
    return f"{tool} failed (exit code {code}); retrying in 2 s"


async def run_capture(argv: list[str], timeout: float = TOOL_TIMEOUT_S) -> tuple[int | None, str]:
    """Run a short tool to the end. The code is None if it could not run or timed out."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        return None, ""
    finally:
        # Also on cancellation: invariant 2, no tool child outlives the collector.
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return proc.returncode, out.decode("utf-8", "replace")


class Stream:
    """A long-running tool child and the task that turns its stdout lines into records."""

    def __init__(self, argv: list[str], parse: Parser, writer: Writer) -> None:
        self.argv = argv
        self.parse = parse
        self.writer = writer
        self.proc: asyncio.subprocess.Process | None = None
        self._pump: asyncio.Task | None = None

    async def start(self) -> bool:
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, limit=LINE_LIMIT)
        except OSError:
            return False
        self._pump = asyncio.create_task(self._read())
        return True

    @property
    def exited(self) -> bool:
        return self.proc is not None and self.proc.returncode is not None

    async def wait(self) -> int:
        assert self.proc
        return await self.proc.wait()

    async def stop(self) -> None:
        """SIGTERM, then SIGKILL after TERM_GRACE_S; keeps what was already read."""
        proc = self.proc
        if proc is None:
            return
        try:
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), TERM_GRACE_S)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        finally:
            if proc.returncode is None:
                proc.kill()
            if self._pump:
                # A grandchild may keep the pipe open; do not wait for it.
                await asyncio.wait({self._pump}, timeout=DRAIN_S)
                self._pump.cancel()

    async def _read(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            try:
                raw = await self.proc.stdout.readline()
            except ValueError:
                self.writer.skipped += 1
                continue
            if not raw:
                return
            record = self.parse(raw.decode("utf-8", "replace").rstrip("\r\n"))
            if record is None:
                self.writer.skipped += 1
            else:
                self.writer.write(record)
