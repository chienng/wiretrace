import argparse
import os
import sys

from . import __version__, doctor, report, session, start
from .preset import PRESETS_DIR


def main(argv: list[str] | None = None) -> int:
    # Before any file is created, including by mitmdump and the collectors this process starts.
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        prog="wiretrace",
        description="Wiretrace: mobile traffic and log inspection for QA.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check that this Mac is ready to run Wiretrace")

    start_cmd = commands.add_parser("start", help="capture traffic with a preset, saved in sessions/")
    start_cmd.add_argument("--preset", required=True, help="preset name: presets/<name>.yaml")
    start_cmd.add_argument("--target", choices=start.TARGETS, default="device",
                           help="device under test (default: %(default)s)")
    start_cmd.add_argument("--mode", choices=start.MODES, default="wireguard",
                           help="wireguard (UDP 51820) or proxy (Wi-Fi proxy, TCP 8080); default: %(default)s")
    ui_choice = start_cmd.add_mutually_exclusive_group()
    ui_choice.add_argument("--ui", choices=(start.MITMWEB, start.WIRETRACE), default=start.MITMWEB,
                           help="window to open: mitmweb, or wiretrace (preview); default: %(default)s")
    ui_choice.add_argument("--no-ui", action="store_true",
                           help="run mitmdump in this Terminal instead of mitmweb")
    start_cmd.add_argument("--client", action="append", default=[], metavar="ADDR",
                           help="IP address allowed to use the proxy, besides this Mac (repeatable). "
                                "Without it, only the first other device that connects is accepted")

    report_cmd = commands.add_parser(
        "report", help="write a bug report zip of a session (secrets masked) into its folder")
    report_cmd.add_argument("session", nargs="?",
                            help="session folder name or path (default: the most recent session)")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor.main()
    if args.command == "start":
        return start.run(args.preset, args.target, args.mode, ui=start.NO_UI if args.no_ui else args.ui,
                         clients=tuple(args.client))
    if args.command == "report":
        return report.run(args.session, session.SESSIONS_DIR, PRESETS_DIR)
    return 2


if __name__ == "__main__":
    sys.exit(main())
