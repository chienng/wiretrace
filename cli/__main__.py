import argparse
import os
import sys

from . import __version__, app, doctor, report, session, start
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
    start_cmd.add_argument("--mode", choices=start.MODES, default="both",
                           help=f"both (Wi-Fi proxy on TCP {start.PROXY_PORT} and WireGuard on UDP "
                                f"{start.WIREGUARD_PORT}), proxy (Wi-Fi proxy only) or wireguard (WireGuard "
                                "only); default: %(default)s")
    start_cmd.add_argument("--port", type=int, metavar="N",
                           help=f"Wi-Fi proxy port for this run only (default: the port chosen last in the "
                                f"Wiretrace window, else {start.PROXY_PORT})")
    ui_choice = start_cmd.add_mutually_exclusive_group()
    ui_choice.add_argument("--ui", choices=(start.MITMWEB, start.WIRETRACE), default=start.MITMWEB,
                           help="window to open: mitmweb, or wiretrace (preview); default: %(default)s")
    ui_choice.add_argument("--no-ui", action="store_true",
                           help="run mitmdump in this Terminal instead of mitmweb")
    start_cmd.add_argument("--client", action="append", default=[], metavar="ADDR",
                           help="IP address allowed to use the proxy, besides this Mac (repeatable). "
                                "Without it, only the first other device that connects is accepted")
    start_cmd.add_argument("--no-menu-bar", action="store_true",
                           help="with --ui wiretrace, do not show the menu bar item")
    # Wiretrace.app's sessions: no link printed, the menu bar is the stop.
    start_cmd.add_argument("--from-app", action="store_true", help=argparse.SUPPRESS)

    app_cmd = commands.add_parser("app", help="used by Wiretrace.app")
    app_commands = app_cmd.add_subparsers(dest="app_command", required=True)
    app_commands.add_parser("state", help="whether a session is recording, the projects and the devices")
    app_start = app_commands.add_parser("start", help="start a session detached")
    app_start.add_argument("--project", required=True)
    app_start.add_argument("--device", required=True, choices=tuple(app.DEVICES))

    report_cmd = commands.add_parser(
        "report", help="write a bug report zip of a session (secrets masked) into its folder")
    report_cmd.add_argument("session", nargs="?",
                            help="session folder name or path (default: the most recent session)")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor.main()
    if args.command == "start":
        return start.run(args.preset, args.target, args.mode, ui=start.NO_UI if args.no_ui else args.ui,
                         proxy_port=args.port, clients=tuple(args.client), no_menu_bar=args.no_menu_bar,
                         from_app=args.from_app)
    if args.command == "app":
        if args.app_command == "state":
            print("\n".join(app.state()))
            return 0
        return app.start(args.project, args.device)
    if args.command == "report":
        return report.run(args.session, session.SESSIONS_DIR, PRESETS_DIR)
    return 2


if __name__ == "__main__":
    sys.exit(main())
