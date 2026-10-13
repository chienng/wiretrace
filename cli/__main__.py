import argparse
import sys

from . import __version__, doctor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wiretrace",
        description="Wiretrace: mobile traffic and log inspection for QA.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check that this Mac is ready to run Wiretrace")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return doctor.main()
    return 2


if __name__ == "__main__":
    sys.exit(main())
