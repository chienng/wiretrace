"""`wiretrace start`: run mitmweb or mitmdump with a preset and save the session.

The launcher only builds the mitmproxy command line and supervises that child
process; QA logic belongs in mitmproxy addons. The child runs in the launcher's
process group, so a Terminal Ctrl+C or a closed window reaches both directly.

A second child, the device log collector (`python -m collectors`), runs in its own
process group so one killpg ends it and the tools it started. A Terminal Ctrl+C no
longer reaches it, so the launcher forwards every stop. It never decides the state.

With `--ui wiretrace`, a third child (`python -m menubar`) is the menu bar item.
It is also in its own session. It may send one SIGINT here, which is the same stop
as Ctrl+C. The launcher stops that child on every exit path. With `--from-app` there
is no Terminal, so the menu is the only stop: a menu that ends is a stop too
(docs/specs/014-mac-app-install-and-launcher.md).

States (docs/specs/002-start-launcher-presets-sessions.md, 004-log-collectors-and-app-log-receiver.md):
PREPARE -> RUNNING -> STOPPING -> KILLED -> FINALIZING -> DONE, or PREPARE -> ABORTED.
With `--ui wiretrace`, a session whose mitmdump exited on its own after the window wrote
`.switch.json` goes back to PREPARE with the preset and target it names
(docs/specs/013-switch-preset.md, 018-switch-device.md). A stop signal never does.
With a `client` in that file, the next session's Wi-Fi proxy accepts only that address
from its first connection (docs/specs/021-switch-to-another-phone.md). With a `proxy_port`,
the next session listens there and `.proxy-port` keeps it for later runs
(docs/specs/022-more-devices-port-encrypted-hosts-breakpoints.md, slice B).
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

from . import __version__, doctor, redact, session
from .datadir import DATA_DIR
from .preset import PRESETS_DIR, Preset, PresetError, allow_hosts_regexes, load_preset

TARGETS = ("android", "ios", "android-emu", "ios-sim", "device")
MODES = ("wireguard", "proxy", "both")
PROXY_PORT = doctor.PROXY_PORT
# Written out in both mode: `--listen-port` would otherwise be WireGuard's port too.
WIREGUARD_PORT = doctor.WIREGUARD_PORT
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
STILL_STOPPING_S = 15
COLLECTOR_STOP_S = 3
MENU_STOP_S = 2
POLL_S = 0.1
SWITCH_RETRY_S = 1.0
MAX_SWITCH_BYTES = 4096
MENU_CLOSED = "Menu bar: closed; capture continues (Ctrl+C here to stop)"
MENU_CLOSED_APP = "Menu bar closed; stopping the session (started from Wiretrace.app)."
APP_NEEDS_MENU = "--from-app needs --ui wiretrace and the menu bar item."
WIRETRACE_DIR = Path(__file__).resolve().parent.parent
# Always the addon shipped with this checkout; `data_dir` only decides where mocks and rules are read.
QA_ADDON = WIRETRACE_DIR / "addons" / "qa_tools.py"
APP_LOGS_ADDON = WIRETRACE_DIR / "addons" / "app_logs.py"
UI_ADDON = WIRETRACE_DIR / "addons" / "wiretrace_ui.py"
PROXY_GUARD = WIRETRACE_DIR / "addons" / "proxy_guard.py"
HAR_GUARD = WIRETRACE_DIR / "addons" / "har_guard.py"
# The simulator and the emulator connect from the Mac itself. Always accepted in proxy mode.
LOOPBACK_CLIENTS = ("127.0.0.0/8", "::1")
UI_PORT = 8081
RULES_DIR = "rules"
MITMWEB, WIRETRACE, NO_UI = "mitmweb", "wiretrace", "none"
RECEIVER_HOST = "qa-logs.internal"
RECEIVER_ALLOW_HOSTS = r"^qa-logs\.internal(:\d+)?$"
# mitmproxy's own certificate page; it is served only when the connection is intercepted.
ONBOARDING_HOST = "mitm.it"
ONBOARDING_ALLOW_HOSTS = r"^mitm\.it(:\d+)?$"
SAVE_FILTER = r"!~d ^qa-logs\.internal$ & !~d ^mitm\.it$"
# Which log source each target runs, and how the banner names it.
DEVICE_LOGS = {"android": "android", "android-emu": "android", "ios": "ios", "ios-sim": "ios-sim"}
DEVICE_LOG_NAMES = {"android": "Android", "ios": "iPhone", "ios-sim": "iOS Simulator"}
APP_KEYS = {"android": "android_package", "ios": "ios_process", "ios-sim": "ios_process"}
# The window's device menu, in this order.
TARGETS_SHOWN = ("ios", "android", "android-emu", "ios-sim", "device")
TARGET_LABELS = {"ios": "iPhone", "android": "Android phone", "android-emu": "Android emulator",
                 "ios-sim": "iOS Simulator", "device": "Another device"}
SIMULATOR_NEEDS_PROXY = "The iOS Simulator needs the Wi-Fi proxy: stop and start Wiretrace for it."
# Spec 021, invariant 3. Neither names the address.
CLIENT_NOT_PINNABLE = "The device to switch to does not have an address the Wi-Fi proxy can accept. Not started."
CLIENT_WITH_CLIENTS = "This run names its devices with --client, so it does not switch them. Not started."
PORT_NOT_SAVED = "Could not save the Wi-Fi proxy port: the next run starts on the port it used before."

RUNNING, STOPPING, KILLED = "RUNNING", "STOPPING", "KILLED"
STATUS = {RUNNING: "exited", STOPPING: "stopped", KILLED: "killed"}

_ANDROID = "Android needs the mitmproxy CA installed, and a QA build of the app that trusts user CAs."
_IOS = ("iOS needs the mitmproxy profile installed (Settings > General > VPN & Device Management) "
        "and then fully trusted (Settings > General > About > Certificate Trust Settings).")
TARGET_HINTS = {
    "android": _ANDROID,
    "android-emu": _ANDROID,
    "ios": _IOS,
    "ios-sim": _IOS,
    "device": "The device must trust the mitmproxy CA (docs/user-guide.md, Part 2).",
}


def say(message: str, err: bool = False) -> None:
    # The Terminal window may be gone; finishing the session matters more than the message.
    try:
        print(message, file=sys.stderr if err else sys.stdout, flush=True)
    except OSError:
        pass


# PREPARE

def ui_kind(ui: bool | str) -> str:
    """The UI as one of MITMWEB, WIRETRACE, NO_UI; a bool is the older way to say mitmweb or none."""
    if isinstance(ui, str):
        return ui
    return MITMWEB if ui else NO_UI


def needed_ports(mode: str, ui: bool | str, proxy_port: int = PROXY_PORT,
                 ui_port: int = UI_PORT) -> list[tuple[str, str, int, str]]:
    kind = ui_kind(ui)
    labels = {"wireguard": {"WireGuard"}, "both": {"proxy", "WireGuard"}}.get(mode, {"proxy"})
    if kind != NO_UI:
        labels.add("mitmweb UI")
    ports = {"proxy": proxy_port, "mitmweb UI": ui_port if kind == WIRETRACE else UI_PORT}
    return [
        (proto, host, ports.get(label, port), "Wiretrace UI" if kind == WIRETRACE and label == "mitmweb UI" else label)
        for proto, host, port, label in doctor.PORTS
        if label in labels
    ]


def busy_ports(ports: list[tuple[str, str, int, str]]) -> list[doctor.Result]:
    return [r for r in (doctor.check_port(*p) for p in ports) if r.status == doctor.FAIL]


def client_problem(addresses: Sequence[str]) -> str | None:
    """Why a `--client` value is not an IP address, or None."""
    for value in addresses:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return f"Invalid --client address {value!r}."
    return None


def resolve_proxy_port(data_dir: Path, override: int | None = None) -> int:
    """`--port`, else the port saved in `.proxy-port`, else PROXY_PORT."""
    return override if override is not None else doctor.saved_proxy_port(data_dir)


def save_proxy_port(data_dir: Path, port: int) -> None:
    """`.proxy-port`: one integer, 0600 from the start, replaced whole."""
    path = data_dir / doctor.PROXY_PORT_FILE
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(f"{port}\n")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def pinnable_client(value: str) -> str | None:
    """A client switch's address, normalized like addons/proxy_guard.py, or None when a session may not
    start pinned to it: not an IP address, or loopback, link-local, unspecified or multicast."""
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
        return None
    return str(address)


def allow_hosts_args(preset: Preset) -> list[str]:
    """mitmproxy's `allow_hosts`: the API hosts, then the receiver and the certificate page. The window's
    live update (spec 022, slice C) uses this list too, so it equals what a restart would pass."""
    # Only the receiver host, no subdomains, so its HTTPS request is decrypted.
    return [*allow_hosts_regexes(preset), RECEIVER_ALLOW_HOSTS, ONBOARDING_ALLOW_HOSTS]


def build_command(preset: Preset, mode: str, ui: bool | str, flows: Path, bin_dir: Path,
                  proxy_port: int = PROXY_PORT, data_dir: Path = DATA_DIR,
                  ui_port: int = UI_PORT, clients: Sequence[str] = (), from_app: bool = False,
                  pinned: str | None = None) -> list[str]:
    kind = ui_kind(ui)
    cmd = [str(bin_dir / ("mitmweb" if kind == MITMWEB else "mitmdump"))]
    if mode == "wireguard":
        cmd += ["--mode", "wireguard"]
    elif mode == "both":
        cmd += ["--mode", "regular", "--listen-port", str(proxy_port), "--mode", f"wireguard@{WIREGUARD_PORT}"]
    else:
        cmd += ["--mode", "regular", "--listen-port", str(proxy_port)]
    for regex in allow_hosts_args(preset):
        cmd += ["--allow-hosts", regex]
    cmd += ["--save-stream-file", str(flows)]
    cmd += ["-s", str(QA_ADDON), "-s", str(APP_LOGS_ADDON)]
    if mode in ("proxy", "both"):
        cmd += ["-s", str(PROXY_GUARD)]
    if kind == WIRETRACE:
        cmd += ["-s", str(UI_ADDON)]
    for host in preset.api_hosts:
        cmd += ["--set", f"qa_api_hosts={host}"]
    cmd += ["--set", f"qa_mocks_dir={(data_dir / preset.mocks_dir).absolute()}"]
    cmd += ["--set", f"qa_data_dir={Path(data_dir).resolve()}"]
    cmd += ["--set", f"qa_rules_file={rules_file(preset, data_dir).absolute()}"]
    cmd += ["--set", f"qa_request_id_header={preset.request_id_header}"]
    cmd += ["--set", f"qa_app_log_file={flows.parent / session.APP_LOG}"]
    # Receiver and certificate-page flows stay visible in mitmweb but are not saved: the first would
    # duplicate app.log.jsonl, the second is not app traffic.
    cmd += ["--set", f"save_stream_filter={SAVE_FILTER}"]
    if mode in ("proxy", "both"):
        # Pinning is on only when the user did not name a device: the first other address is the one.
        for address in (*LOOPBACK_CLIENTS, *clients):
            cmd += ["--set", f"qa_proxy_clients={address}"]
        cmd += ["--set", "qa_proxy_pin=" + ("false" if clients else "true")]
        if pinned and not clients:
            cmd += ["--set", f"qa_proxy_pinned={pinned}"]
    if kind == WIRETRACE:
        # The window is the only output; the token is made by the addon and never goes on a command line.
        cmd += ["--set", "flow_detail=0", "--set", f"qa_ui_port={ui_port}",
                "--set", f"qa_ui_session_dir={flows.parent}",
                "--set", f"qa_ui_default_filter={preset.default_filter or ''}",
                "--set", "qa_ui_open_browser=true", "--set", "qa_breakpoints=true"]
        if from_app:
            # Its output goes to app-start.log, a file: the link with the token must not.
            cmd += ["--set", "qa_ui_print_link=false", "--set", "qa_ui_from_app=true"]
    elif preset.default_filter:
        # An option, not mitmdump's positional filter argument, which would also limit saving.
        option = "view_filter" if kind == MITMWEB else "dumper_filter"
        cmd += ["--set", f"{option}={preset.default_filter}"]
    return cmd


def rules_file(preset: Preset, data_dir: Path = DATA_DIR) -> Path:
    """`rules/<preset>.json` in the data folder; it need not exist yet. The Wiretrace window writes it."""
    return data_dir / RULES_DIR / f"{preset.name}.json"


def har_command(bin_dir: Path, flows: Path, har: Path) -> list[str]:
    # har_guard runs before mitmproxy's savehar, so the HAR is built from trimmed flows.
    return [str(bin_dir / "mitmdump"), "-n", "-s", str(HAR_GUARD), "-r", str(flows),
            "--set", f"hardump={har}"]


def collector_command(preset: Preset, target: str, bin_dir: Path, out: Path, *,
                      find_adb: Callable[[], str | None] = doctor.find_adb,
                      which: Callable[[str], str | None] = shutil.which) -> tuple[list[str] | None, str]:
    """The collector's argument list and "", or None and why device logs are off."""
    source = DEVICE_LOGS.get(target)
    if source is None:
        return None, "--target device has no device log"
    key = APP_KEYS[source]
    app = preset.app.get(key)
    if not app:
        return None, f"add app.{key} to the preset"
    if source == "android":
        tool, found = "adb", find_adb()
    elif source == "ios":
        pymobiledevice3 = bin_dir / "pymobiledevice3"
        tool, found = "pymobiledevice3", str(pymobiledevice3) if os.access(pymobiledevice3, os.X_OK) else None
    else:
        tool, found = "xcrun", which("xcrun")
    if not found:
        return None, f"{tool} not found"
    return [sys.executable, "-m", "collectors", "--target", target, "--app", app,
            "--out", str(out), "--status", str(out.parent / session.DEVICE_STATUS), f"--{tool}", found], ""


def target_problem(target: str, mode: str) -> str | None:
    """Why a session in `mode` cannot switch to `target`, or None. The window and the launcher both ask."""
    if target not in TARGETS:
        return "Unknown device."
    if target == "ios-sim" and mode == "wireguard":
        return SIMULATOR_NEEDS_PROXY
    return None


def count_mocks(mocks_dir: Path) -> int:
    return sum(1 for p in mocks_dir.rglob("*.json") if p.is_file()) if mocks_dir.is_dir() else 0


def make_token() -> str:
    return secrets.token_urlsafe(32)


def menu_bar_text(kind: str, no_menu_bar: bool, problem: str | None) -> str | None:
    """The banner's menu bar phrase, or None when this window has no menu bar."""
    if kind != WIRETRACE:
        return None
    if no_menu_bar:
        return "off (--no-menu-bar)"
    if problem:
        return f"off ({problem})"
    return "on"


def menu_command(launcher_pid: int, port: int, status_path: Path, app: bool = False) -> list[str]:
    """Argv for the menu process. The token is not here; it is written to stdin."""
    cmd = [sys.executable, "-m", "menubar", str(launcher_pid), str(port), str(status_path)]
    return cmd + ["--app"] if app else cmd


def app_menu_problem(reason: str) -> str:
    return (f"The menu bar item could not start ({reason}). "
            "A session started from the app cannot be stopped without it.")


def mitm_env(token: str | None) -> dict[str, str] | None:
    """The mitmdump environment, with the window token, or None to inherit the launcher's."""
    if not token:
        return None
    env = os.environ.copy()
    env["WIRETRACE_UI_TOKEN"] = token
    return env


def banner(preset: Preset, target: str, mode: str, ui: bool | str, folder: Path,
           proxy_port: int = PROXY_PORT, mock_count: int = 0, device_logs: str = "off",
           menu_bar: str | None = None) -> str:
    kind = ui_kind(ui)
    lines = [
        f"Wiretrace {__version__}: preset {preset.name}, target {target}",
        f"Decrypting {', '.join(preset.api_hosts)} and their subdomains; other traffic passes through.",
    ]
    if kind == WIRETRACE:
        lines.append("UI: Wiretrace (link below)")
    if preset.default_filter:
        shown = {MITMWEB: "View filter", WIRETRACE: "Search", NO_UI: "Print filter"}[kind]
        lines.append(f"{shown}: {preset.default_filter} (every flow is still saved)")
    shown_dir = preset.mocks_dir.strip("/\\") + "/"
    if mock_count:
        lines.append(f"Mocks: {mock_count} {'file' if mock_count == 1 else 'files'} in {shown_dir}")
    else:
        lines.append(f"Mocks: none (add files under {shown_dir}<METHOD>/…)")
    if kind == MITMWEB:
        lines.append("Faults: mitmweb > Options > qa_fault_*")
    if kind == WIRETRACE:
        lines.append(f"Rules: Wiretrace > Rules ({RULES_DIR}/{preset.name}.json)")
    else:
        lines.append(f"Rules: {RULES_DIR}/{preset.name}.json (edit it, or use --ui wiretrace)")
    lines.append(f"Device logs: {device_logs}")
    lines.append(f"App logs: POST https://{RECEIVER_HOST}/log → {session.APP_LOG}")
    if mode == "wireguard":
        first_time = {MITMWEB: "scan the QR code in mitmweb", WIRETRACE: "scan the QR code in Wiretrace > Setup",
                      NO_UI: "enter the configuration printed below"}[kind]
        lines.append(f"Phone: turn the WireGuard tunnel on (first time: {first_time}).")
    elif mode == "both":
        first_time = {MITMWEB: "scan the QR code in mitmweb", WIRETRACE: "scan the QR code in Wiretrace > Setup",
                      NO_UI: "enter the configuration printed below"}[kind]
        lines.append(f"Phone: set the Wi-Fi proxy to this Mac's IP address, port {proxy_port}.")
        lines.append(f"Phone, if an app ignores the proxy: turn the WireGuard tunnel on instead "
                     f"(first time: {first_time}).")
        if kind == WIRETRACE:
            lines.append("Wi-Fi proxy: the first other device that connects is accepted; "
                         "allow more in the window, or name them with --client.")
        else:
            lines.append("Wi-Fi proxy: only the first other device that connects is accepted, "
                         "unless --client names it.")
    else:
        lines.append(f"Phone: set the Wi-Fi proxy to this Mac's IP address, port {proxy_port}.")
    lines.append(TARGET_HINTS[target])
    lines.append(f"Saving to {folder}")
    if menu_bar:
        lines.append(f"Menu bar: {menu_bar}")
    lines.append("Press Ctrl+C to stop and write flows.har.\n")
    return "\n".join(lines)


def _mitmproxy_version() -> str | None:
    try:
        return metadata.version("mitmproxy")
    except metadata.PackageNotFoundError:
        return None


def _menu_problem() -> str | None:
    from menubar import availability
    return availability()


def run(preset_name: str, target: str = "device", mode: str = "wireguard", ui: bool | str = True, *,
        presets_dir: Path = PRESETS_DIR, sessions_dir: Path = session.SESSIONS_DIR,
        bin_dir: Path | None = None, proxy_port: int | None = None, wiretrace_dir: Path = WIRETRACE_DIR,
        data_dir: Path = DATA_DIR, ui_port: int = UI_PORT, clients: Sequence[str] = (), no_menu_bar: bool = False,
        collector_for: Callable[..., tuple[list[str] | None, str]] = collector_command,
        menu_available: Callable[[], str | None] | None = None, from_app: bool = False) -> int:
    """`proxy_port`: `--port`, for this run only; None reads `.proxy-port`.

    `data_dir` holds the port, the mocks and the rules; `wiretrace_dir`, the install folder, only `.app-last`.
    """
    problem = client_problem(clients)
    if problem:
        say(problem, err=True)
        return 1
    if proxy_port is not None:
        problem = doctor.port_problem(proxy_port, ui_port)
        if problem:
            say(f"--port: {problem} Not started.", err=True)
            return 1
    proxy_port = resolve_proxy_port(data_dir, proxy_port)
    kind = ui_kind(ui)
    if from_app and (kind != WIRETRACE or no_menu_bar):
        say(APP_NEEDS_MENU, err=True)
        return 1
    try:
        preset = load_preset(preset_name, presets_dir)
    except PresetError as e:
        say(str(e), err=True)
        return 1

    if ports_busy(mode, kind, proxy_port, ui_port):
        return 1

    probe_menu = menu_available or _menu_problem
    # Asked once before any folder exists; the first session reuses the answer.
    menu_probed = False
    if from_app:
        reason = probe_menu()
        if reason:
            say(app_menu_problem(reason), err=True)
            return 1
        menu_probed = True

    remove_old_sessions(sessions_dir)

    bin_dir = bin_dir or Path(sys.prefix) / "bin"

    # Installed before the folder exists, so no stop signal can leave a folder without a child.
    stops: list[int] = []
    # Every stop signal of this run. `stops` is emptied as signals are handled; this count never is.
    signals = [0]

    def on_stop(signum: int, _frame: object) -> None:
        stops.append(signum)
        signals[0] += 1

    previous = {s: signal.signal(s, on_stop) for s in STOP_SIGNALS}
    try:
        switched = False
        code = 0
        # The address the next session's Wi-Fi proxy is pinned to: only ever from a client switch.
        pinned: str | None = None
        while True:
            # A switch starts a session without a new run: the cap holds across switches too.
            if switched:
                remove_old_sessions(sessions_dir)
            rules = redact.rules_for(preset)
            folder = create_folder(preset, target, session_meta(preset, target, mode, kind, rules),
                                   sessions_dir, retry=switched)
            if folder is None:
                return 1
            flows = folder / session.FLOWS
            mock_count = count_mocks(data_dir / preset.mocks_dir)
            collector_cmd, problem = collector_for(preset, target, bin_dir, folder / session.DEVICE_LOG)
            source = DEVICE_LOGS.get(target) if collector_cmd else None
            if source:
                session.update_meta(folder, device_logs=source)
                device_logs = f"{DEVICE_LOG_NAMES[source]}, {preset.app[APP_KEYS[source]]} → {session.DEVICE_LOG}"
            else:
                session.update_meta(folder, device_logs_off=problem)
                device_logs = f"off ({problem})"
            token = make_token() if kind == WIRETRACE else None
            menu_problem = None
            menu_cmd = None
            if kind == WIRETRACE and not no_menu_bar:
                menu_problem = None if menu_probed else probe_menu()
                menu_probed = False
                if from_app and menu_problem:
                    session.remove(folder)
                    say(app_menu_problem(menu_problem), err=True)
                    return 1
                if menu_problem is None and token:
                    menu_cmd = menu_command(os.getpid(), ui_port, folder / session.STATUS, app=from_app)
            # Invariant 1: every stop signal ends the run, so any signal at all means no next child.
            if switched and signals[0]:
                session.remove(folder)
                return code
            say(banner(preset, target, mode, kind, folder, proxy_port, mock_count, device_logs,
                       menu_bar_text(kind, no_menu_bar, menu_problem)))
            child_cmd = build_command(preset, mode, kind, flows, bin_dir, proxy_port, data_dir, ui_port, clients,
                                      from_app=from_app, pinned=pinned)
            har_cmd = har_command(bin_dir, flows, folder / session.HAR_TMP)
            # Checked again as late as possible: a signal during the banner must not start the child.
            if switched and signals[0]:
                session.remove(folder)
                return code
            outcome = Outcome()
            code = supervise(
                child_cmd,
                har_cmd,
                folder,
                stops,
                collector_cmd,
                rules,
                menu_cmd=menu_cmd,
                menu_token=token,
                child_env=mitm_env(token),
                switch=kind == WIRETRACE,
                outcome=outcome,
                from_app=from_app,
                target=target,
            )
            # Invariant 9: only the Wiretrace window loops.
            if kind != WIRETRACE or outcome.state != RUNNING or outcome.switch_to is None or signals[0]:
                return code
            # Invariant 3: the preset and the target are checked again here, before anything is spawned.
            try:
                preset = load_preset(outcome.switch_to.name, presets_dir)
            except PresetError as e:
                say(str(e), err=True)
                return 1
            problem = target_problem(outcome.switch_to.target, mode)
            if problem:
                say(problem, err=True)
                return 1
            # Spec 021, invariant 3: the client is checked again; a switch without one pins nothing.
            pinned = None
            if outcome.switch_to.client is not None:
                if clients:
                    say(CLIENT_WITH_CLIENTS, err=True)
                    return 1
                pinned = pinnable_client(outcome.switch_to.client)
                if pinned is None:
                    say(CLIENT_NOT_PINNABLE, err=True)
                    return 1
            # Spec 022, slice B, invariant 2: the port is checked again; a switch without one keeps the port.
            next_port = outcome.switch_to.proxy_port
            if next_port is not None:
                problem = doctor.port_problem(next_port, ui_port)
                if problem:
                    say(f"{problem} Not started.", err=True)
                    return 1
            target = outcome.switch_to.target
            # Invariant 8.
            if ports_busy(mode, kind, proxy_port if next_port is None else next_port, ui_port):
                return 1
            if next_port is not None:
                # Spec 022, slice B, invariant 3: saved only once both checks passed.
                proxy_port = next_port
                try:
                    save_proxy_port(data_dir, proxy_port)
                except OSError:
                    say(PORT_NOT_SAVED, err=True)
            if from_app:
                remember_for_app(wiretrace_dir, preset.name, target)
            switched = True
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def remember_for_app(wiretrace_dir: Path, preset: str, target: str) -> None:
    """What Wiretrace.app starts next time. Imported here: `cli/app.py` imports this module."""
    from .app import remember
    remember(wiretrace_dir, preset, target)


def ports_busy(mode: str, kind: str, proxy_port: int, ui_port: int) -> bool:
    """Say which ports are in use, and whether any is."""
    busy = busy_ports(needed_ports(mode, kind, proxy_port, ui_port))
    for result in busy:
        say(f"{result.name}: {result.detail}", err=True)
    if busy:
        say("Not started.", err=True)
    return bool(busy)


def session_meta(preset: Preset, target: str, mode: str, kind: str, rules: redact.Rules) -> dict:
    return {
        "wiretrace_version": __version__,
        "mitmproxy_version": _mitmproxy_version(),
        "preset": preset.name,
        "api_hosts": list(preset.api_hosts),
        "target": target,
        "mode": mode,
        "ui": "mitmdump" if kind == NO_UI else kind,
        "device_logs": None,
        "status": "running",
        # So `wiretrace report` still masks these names if the preset is later changed or deleted.
        "redact": {"headers": list(rules.headers), "json_fields": list(rules.fields)},
    }


def remove_old_sessions(sessions_dir: Path) -> None:
    removed = session.remove_old(sessions_dir, datetime.now())
    if removed:
        say(f"Deleted {removed} old session(s): Wiretrace keeps the {session.KEEP_SESSIONS} newest, "
            f"none older than {session.KEEP_DAYS} days.")


def create_folder(preset: Preset, target: str, meta: dict, sessions_dir: Path, *, retry: bool) -> Path | None:
    """The new session folder, or None after saying why. `retry`: wait once when the name is taken."""
    for attempt in range(2 if retry else 1):
        if attempt:
            time.sleep(SWITCH_RETRY_S)
        try:
            return session.create(preset.name, target, meta, sessions_dir)
        except FileExistsError:
            pass
    say("A session folder with this name already exists; start again in a second.", err=True)
    return None


class Switch(NamedTuple):
    """What `.switch.json` asks for: the next session's preset and target, and the address its Wi-Fi
    proxy accepts (None: the first device to connect) or its Wi-Fi proxy port (None: the same)."""

    name: str
    target: str
    client: str | None = None
    proxy_port: int | None = None


@dataclass
class Outcome:
    """What `supervise` saw, for the loop in `run`. Left as it is, it means "no switch"."""

    state: str | None = None
    switch_to: Switch | None = None


def switch_line(switch: Switch, target: str) -> str:
    if switch.proxy_port is not None:
        return "Changing the Wi-Fi proxy port: saving this session first."
    if switch.client is not None:
        return "Switching to another device on the Wi-Fi proxy: saving this session first."
    if switch.target != target and switch.target in TARGET_LABELS:
        return f"Switching to {TARGET_LABELS[switch.target]}: saving this session first."
    return "Switching presets: saving this session first."


def take_switch(folder: Path) -> Switch | None:
    """The preset and target, and a client or a port, in `.switch.json`, or None. The file is deleted
    whatever it holds (invariant 6). The port is only shape-checked here; the loop checks its value."""
    path = folder / session.SWITCH
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            raw = f.read(MAX_SWITCH_BYTES + 1)
    except OSError:
        return None
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    if len(raw) > MAX_SWITCH_BYTES:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    shapes = ({"name", "target"}, {"name", "target", "client"}, {"name", "target", "proxy_port"})
    if not isinstance(data, dict) or set(data) not in shapes:
        return None
    if not isinstance(data["name"], str) or not isinstance(data["target"], str):
        return None
    client = data.get("client")
    if "client" in data and not isinstance(client, str):
        return None
    port = data.get("proxy_port")
    if "proxy_port" in data and (not isinstance(port, int) or isinstance(port, bool)):
        return None
    return Switch(data["name"], data["target"], client, port)


# RUNNING, STOPPING, KILLED

class _Collector:
    """The device log collector: a child in its own process group, so one killpg ends all of it."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self.interrupted_at: float | None = None
        self.exit_reported = False
        self.closed = False

    @classmethod
    def start(cls, cmd: list[str]) -> _Collector | None:
        pythonpath = os.pathsep.join(p for p in (str(WIRETRACE_DIR), os.environ.get("PYTHONPATH")) if p)
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True,
                                    env={**os.environ, "PYTHONPATH": pythonpath})
        except OSError:
            say("Device logs: could not start the collector", err=True)
            return None
        return cls(proc)

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def interrupt(self) -> None:
        """The one SIGINT (launcher invariant 4)."""
        if self.interrupted_at is None:
            self.interrupted_at = time.monotonic()
            self._signal_group(signal.SIGINT)

    def kill(self) -> None:
        self._signal_group(signal.SIGKILL)

    def notice_exit(self) -> None:
        """The collector ended by itself while RUNNING: say so once, clean up its tools, go on."""
        code = self.proc.poll()
        if code is not None and not self.exit_reported:
            self.exit_reported = True
            self.kill()
            say(f"Device logs: collector stopped (exit code {code}); capture continues", err=True)

    def stop(self, stops: list[int], killed: bool) -> None:
        """After the mitm child is gone: SIGINT, then SIGKILL after COLLECTOR_STOP_S, then reap."""
        if killed:
            self.kill()
        else:
            self.interrupt()
        deadline = (self.interrupted_at or time.monotonic()) + COLLECTOR_STOP_S
        while self.proc.poll() is None and not stops and time.monotonic() < deadline:
            time.sleep(POLL_S / 2)
        stops.clear()
        self.close()

    def close(self) -> None:
        """Invariant 1: whatever the path, nothing in the collector's group stays alive."""
        # Once only: after the reap below, an empty group's ID is free for the system to reuse.
        if self.closed:
            return
        self.closed = True
        self.kill()
        self.proc.wait()


class _MenuBar:
    """The menu bar item: its own session, so a Terminal Ctrl+C reaches the launcher, not it.

    The token is the first line on stdin and is not in argv or the environment.
    """

    def __init__(self, proc: subprocess.Popen, app: bool = False) -> None:
        self.proc = proc
        self.app = app
        self.exit_reported = False
        self.closed = False
        self._err: str | None = None

    @classmethod
    def start(cls, cmd: list[str], token: str, app: bool = False) -> _MenuBar | None:
        pythonpath = os.pathsep.join(p for p in (str(WIRETRACE_DIR), os.environ.get("PYTHONPATH")) if p)
        env = os.environ.copy()
        env.pop("WIRETRACE_UI_TOKEN", None)
        env["PYTHONPATH"] = pythonpath
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                start_new_session=True, env=env,
            )
        except OSError:
            say("Menu bar: off (could not start)")
            return None
        try:
            assert proc.stdin is not None
            proc.stdin.write((token + "\n").encode())
            proc.stdin.close()
        except OSError:
            proc.kill()
            proc.wait()
            say("Menu bar: off (could not start)")
            return None
        return cls(proc, app)

    def _reason(self) -> str:
        if self._err is not None:
            return self._err or "could not start"
        if self.proc.stderr is None:
            self._err = ""
            return "could not start"
        try:
            text = self.proc.stderr.read().decode(errors="replace").strip()
        except OSError:
            text = ""
        self._err = text.splitlines()[-1].strip() if text else ""
        return self._err or "could not start"

    def notice_exit(self) -> bool:
        """The menu ended by itself while RUNNING: say so once and do not start it again.

        True the one time the exit is noticed.
        """
        code = self.proc.poll()
        if code is None or self.exit_reported:
            return False
        self.exit_reported = True
        if code == 2:
            say(f"Menu bar: off ({self._reason()})")
        if self.app:
            say(MENU_CLOSED_APP)
        elif code != 2:
            say(MENU_CLOSED)
        return True

    def stop(self) -> None:
        """After the session is saved: SIGTERM, wait up to MENU_STOP_S, SIGKILL, reap."""
        if self.closed:
            return
        self.closed = True
        if self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGTERM)
            except OSError:
                pass
            deadline = time.monotonic() + MENU_STOP_S
            while self.proc.poll() is None and time.monotonic() < deadline:
                time.sleep(POLL_S / 2)
            if self.proc.poll() is None:
                try:
                    self.proc.kill()
                except OSError:
                    pass
        self.proc.wait()
        self._reason()


def supervise(child_cmd: list[str], har_cmd: list[str], folder: Path, stops: list[int],
              collector_cmd: list[str] | None = None, rules: redact.Rules | None = None, *,
              menu_cmd: list[str] | None = None, menu_token: str | None = None,
              child_env: dict[str, str] | None = None, switch: bool = False,
              outcome: Outcome | None = None, from_app: bool = False, target: str = "") -> int:
    """Spawn the child and take it to DONE. The stop-signal handlers must already append to `stops`.

    `switch`: read and delete `.switch.json` once the child has exited. `outcome` gets the state
    the child exited in and what that file asked for. `from_app`: a menu that ends, or that
    cannot start, stops the session. `target`: this session's, so a device switch is named as one.
    """
    tool = Path(child_cmd[0]).name
    try:
        child = subprocess.Popen(child_cmd, env=child_env)
    except OSError as e:
        session.remove(folder)
        say(f"Could not start {tool}: {e.strerror or e}", err=True)
        return 1

    collector = None
    menu = None
    try:
        # Invariant 2: only after the child started; a collector that cannot start is skipped.
        if collector_cmd:
            collector = _Collector.start(collector_cmd)
            if collector is None:
                session.update_meta(folder, device_logs=None, device_logs_off="the collector could not start")
        if menu_cmd and menu_token:
            menu = _MenuBar.start(menu_cmd, menu_token, app=from_app)
            if menu is None and from_app:
                say(MENU_CLOSED_APP)
                stops.append(signal.SIGINT)
        state = _wait(child, stops, collector, menu)
        ended_at = session.timestamp()
        # Invariant 6: read before `_finalize` may remove an empty folder.
        switch_to = take_switch(folder) if switch else None
        if outcome is not None:
            outcome.state, outcome.switch_to = state, switch_to
        switching = state == RUNNING and switch_to is not None
        if switching:
            say(switch_line(switch_to, target))
        elif state == RUNNING:
            say(f"{tool} exited on its own (exit code {child.returncode}).", err=True)
        if collector:
            collector.stop(stops, state == KILLED)
        # The window asked for this exit, so it is saved as a stop.
        status = STATUS[STOPPING] if switching else STATUS[state]
        # The menu stays up through the HAR write, then the finally block stops it.
        return _finalize(folder, har_cmd, status, ended_at, stops, rules or redact.rules_for(None))
    finally:
        # Invariant 1: no exit path leaves the child, the collector's group, or the menu running.
        if child.poll() is None:
            child.kill()
            child.wait()
        if collector:
            collector.close()
        if menu:
            menu.stop()


def _wait(child: subprocess.Popen, stops: list[int], collector: _Collector | None = None,
          menu: _MenuBar | None = None) -> str:
    """Return the state the child exited in."""
    state, stopping_since, warned = RUNNING, 0.0, False
    while True:
        while stops:
            stops.pop(0)
            if state == RUNNING:
                state, stopping_since = STOPPING, time.monotonic()
                say("\nStopping… press Ctrl+C again to force.")
                # The one SIGINT of our own: the stop may not have come from the Terminal.
                child.send_signal(signal.SIGINT)
                if collector:
                    collector.interrupt()
            elif state == STOPPING:
                state = KILLED
                say("Force-stopping.")
                child.kill()
                if collector:
                    collector.kill()
        if state == STOPPING and not warned and time.monotonic() - stopping_since >= STILL_STOPPING_S:
            say("still stopping — press Ctrl+C again to force")
            warned = True
        if collector and state == RUNNING:
            collector.notice_exit()
        if menu and state == RUNNING and menu.notice_exit() and menu.app:
            # The same stop as the menu's own SIGINT: it lands in `stops`, so it is never a switch.
            stops.append(signal.SIGINT)
            continue
        try:
            child.wait(timeout=POLL_S)
        except subprocess.TimeoutExpired:
            continue
        # A Terminal Ctrl+C can end the child before its signal was handled here.
        if stops and state == RUNNING:
            state = STOPPING
        stops.clear()
        return state


# FINALIZING

def _finalize(folder: Path, har_cmd: list[str], status: str, ended_at: str, stops: list[int],
              rules: redact.Rules) -> int:
    flows = session.has_flows(folder)
    if not flows and not session.has_logs(folder):
        session.remove(folder)
        say("Nothing was captured; the session folder was removed.")
        return 1

    # Both log files are complete here: the collector is reaped and mitmproxy has exited.
    counts = {"device_log_lines": session.count_lines(folder / session.DEVICE_LOG),
              "app_log_lines": session.count_lines(folder / session.APP_LOG)}
    har_error = None
    # The window's Previous sessions lists it; None when flows.har could not be written.
    requests: int | None = 0
    if flows:
        say("Writing flows.har…")
        har_error, requests = write_masked_har(har_cmd, folder, rules, stops)
    else:
        say("No traffic was captured; flows.har was not written.")
    session.update_meta(folder, ended_at=ended_at, status=status, requests=requests, **counts)
    say(f"Session saved: {folder}")
    say(f"For a bug ticket: ./wiretrace report {folder.name}")
    if har_error:
        say(f"flows.har was not written ({har_error}); flows.mitm is kept.", err=True)
    return 0 if status == "stopped" and not har_error else 1


def write_masked_har(har_cmd: list[str], folder: Path, rules: redact.Rules,
                     stops: list[int]) -> tuple[str | None, int | None]:
    """flows.har, masked. The unmasked HAR is `.flows.har.tmp`, removed on every path.

    Return why it failed, or None, and the number of requests in it (None when it failed)."""
    tmp, masked = folder / session.HAR_TMP, folder / session.HAR_MASKED
    try:
        error = convert_har(har_cmd, tmp, stops)
        if error:
            return error, None
        try:
            har = json.loads(tmp.read_text(encoding="utf-8"))
            if not isinstance(har, dict):
                return "could not mask it", None
            masked.write_text(json.dumps(redact.redact_har(har, rules)[0], indent=4), encoding="utf-8")
            os.replace(masked, folder / session.HAR)
            os.chmod(folder / session.HAR, 0o600)
            entries = har.get("log", {}).get("entries") if isinstance(har.get("log"), dict) else None
        except Exception:
            # Whatever went wrong, flows.har must not exist unmasked.
            return "could not mask it", None
        return None, len(entries) if isinstance(entries, list) else None
    finally:
        for leftover in (tmp, masked):
            try:
                leftover.unlink(missing_ok=True)
            except OSError:
                pass


def convert_har(har_cmd: list[str], har: Path, stops: list[int]) -> str | None:
    """Run the conversion after the child has exited. Return why it failed, or None."""
    try:
        result = subprocess.run(har_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    except OSError as e:
        return str(e.strerror or e)
    if stops:
        # mitmdump writes the HAR on shutdown, so an interrupted run leaves a partial file.
        har.unlink(missing_ok=True)
        return "interrupted"
    if result.returncode != 0:
        har.unlink(missing_ok=True)
        lines = result.stderr.strip().splitlines()
        return lines[-1] if lines else f"exit code {result.returncode}"
    if not har.is_file() or har.stat().st_size == 0:
        return "no output"
    return None
