"""CLI of the device log collector: `python -m collectors --target … --app … --out …`."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from . import ERROR, Status, Timing, Writer
from .android import Android
from .ios import ios_device, ios_simulator

TARGETS = ("android", "android-emu", "ios", "ios-sim")
SOURCES = {"android": "android", "android-emu": "android", "ios": "ios", "ios-sim": "ios-sim"}
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="collectors", description="Write the app's device log to a JSONL file.")
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--app", required=True, help="Android package name or iOS process name")
    parser.add_argument("--out", required=True, type=Path, help="log file, opened in append mode on the first line")
    parser.add_argument("--status", type=Path, help="state file (device.status.json), replaced on every change")
    parser.add_argument("--adb", help="path of adb")
    parser.add_argument("--pymobiledevice3", help="path of pymobiledevice3")
    parser.add_argument("--xcrun", help="path of xcrun")
    parser.add_argument("--tick", type=float, default=1.0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    needed = {"android": "adb", "android-emu": "adb", "ios": "pymobiledevice3", "ios-sim": "xcrun"}[args.target]
    if not getattr(args, needed):
        parser.error(f"--{needed} is required with --target {args.target}")
    return args


def build(args: argparse.Namespace, writer: Writer, status: Status):
    timing = Timing(poll=args.tick, wait=2 * args.tick)
    if args.target in ("android", "android-emu"):
        return Android(args.adb, args.app, writer, status, timing)
    if args.target == "ios":
        return ios_device(args.pymobiledevice3, args.app, writer, status, timing)
    return ios_simulator(args.xcrun, args.app, writer, status, timing)


async def serve(collector, status: Status) -> int:
    """Run until a stop signal; the cancellation unwinds into each tool's `finally`."""
    loop = asyncio.get_running_loop()
    work = asyncio.ensure_future(collector.run())
    stopping = False

    def stop() -> None:
        nonlocal stopping
        # One stop is enough; a repeat must not cancel the cleanup it started.
        if not stopping:
            stopping = True
            work.cancel()

    for sig in STOP_SIGNALS:
        loop.add_signal_handler(sig, stop)
    try:
        await work
    except asyncio.CancelledError:
        status.stopped()
        return 0
    except Exception as e:
        # The class name only: a message or traceback could carry paths or log content.
        status.say(f"stopped after an internal error ({type(e).__name__})", state=ERROR)
        return 1
    status.stopped()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    writer, status = Writer(args.out), Status(args.status, SOURCES[args.target], args.app)
    try:
        return asyncio.run(serve(build(args, writer, status), status))
    finally:
        writer.close()


if __name__ == "__main__":
    sys.exit(main())
