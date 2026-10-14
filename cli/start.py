"""`wiretrace start`: run mitmweb or mitmdump with a preset and save the session.

The launcher only builds the mitmproxy command line and supervises that one child
process; QA logic belongs in mitmproxy addons. The child runs in the launcher's
process group, so a Terminal Ctrl+C or a closed window reaches both directly.

States (docs/specs/002-start-launcher-presets-sessions.md):
PREPARE -> RUNNING -> STOPPING -> KILLED -> FINALIZING -> DONE, or PREPARE -> ABORTED.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

from . import __version__, doctor, session
from .preset import PRESETS_DIR, Preset, PresetError, allow_hosts_regexes, load_preset

TARGETS = ("android", "ios", "android-emu", "ios-sim", "device")
MODES = ("wireguard", "proxy")
PROXY_PORT = 8080
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
STILL_STOPPING_S = 15
POLL_S = 0.1
WIRETRACE_DIR = Path(__file__).resolve().parent.parent
# Always the addon shipped with this checkout; `wiretrace_dir` only decides where mocks are read.
QA_ADDON = WIRETRACE_DIR / "addons" / "qa_tools.py"

RUNNING, STOPPING, KILLED = "RUNNING", "STOPPING", "KILLED"
STATUS = {RUNNING: "exited", STOPPING: "stopped", KILLED: "killed"}

_ANDROID = "Android needs the mitmproxy CA installed, and a QA build of the app that trusts user CAs."
_IOS = ("iOS needs the mitmproxy profile installed and fully trusted "
        "(Settings > General > About > Certificate Trust Settings).")
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

def needed_ports(mode: str, ui: bool, proxy_port: int = PROXY_PORT) -> list[tuple[str, str, int, str]]:
    labels = {"WireGuard"} if mode == "wireguard" else {"proxy"}
    if ui:
        labels.add("mitmweb UI")
    return [
        (proto, host, proxy_port if label == "proxy" else port, label)
        for proto, host, port, label in doctor.PORTS
        if label in labels
    ]


def busy_ports(ports: list[tuple[str, str, int, str]]) -> list[doctor.Result]:
    return [r for r in (doctor.check_port(*p) for p in ports) if r.status == doctor.FAIL]


def build_command(preset: Preset, mode: str, ui: bool, flows: Path, bin_dir: Path,
                  proxy_port: int = PROXY_PORT, wiretrace_dir: Path = WIRETRACE_DIR) -> list[str]:
    cmd = [str(bin_dir / ("mitmweb" if ui else "mitmdump"))]
    if mode == "wireguard":
        cmd += ["--mode", "wireguard"]
    else:
        cmd += ["--mode", "regular", "--listen-port", str(proxy_port)]
    for regex in allow_hosts_regexes(preset):
        cmd += ["--allow-hosts", regex]
    cmd += ["--save-stream-file", str(flows)]
    cmd += ["-s", str(QA_ADDON)]
    for host in preset.api_hosts:
        cmd += ["--set", f"qa_api_hosts={host}"]
    cmd += ["--set", f"qa_mocks_dir={(wiretrace_dir / preset.mocks_dir).absolute()}"]
    cmd += ["--set", f"qa_request_id_header={preset.request_id_header}"]
    if preset.default_filter:
        # An option, not mitmdump's positional filter argument, which would also limit saving.
        option = "view_filter" if ui else "dumper_filter"
        cmd += ["--set", f"{option}={preset.default_filter}"]
    return cmd


def har_command(bin_dir: Path, flows: Path, har: Path) -> list[str]:
    return [str(bin_dir / "mitmdump"), "-n", "-r", str(flows), "--set", f"hardump={har}"]


def count_mocks(mocks_dir: Path) -> int:
    return sum(1 for p in mocks_dir.rglob("*.json") if p.is_file()) if mocks_dir.is_dir() else 0


def banner(preset: Preset, target: str, mode: str, ui: bool, folder: Path,
           proxy_port: int = PROXY_PORT, mock_count: int = 0) -> str:
    lines = [
        f"Wiretrace {__version__}: preset {preset.name}, target {target}",
        f"Decrypting {', '.join(preset.api_hosts)} and their subdomains; other traffic passes through.",
    ]
    if preset.default_filter:
        shown = "View filter" if ui else "Print filter"
        lines.append(f"{shown}: {preset.default_filter} (every flow is still saved)")
    shown_dir = preset.mocks_dir.strip("/\\") + "/"
    if mock_count:
        lines.append(f"Mocks: {mock_count} {'file' if mock_count == 1 else 'files'} in {shown_dir}")
    else:
        lines.append(f"Mocks: none (add files under {shown_dir}<METHOD>/…)")
    if ui:
        lines.append("Faults: mitmweb > Options > qa_fault_*")
    if mode == "wireguard":
        first_time = "scan the QR code in mitmweb" if ui else "enter the configuration printed below"
        lines.append(f"Phone: turn the WireGuard tunnel on (first time: {first_time}).")
    else:
        lines.append(f"Phone: set the Wi-Fi proxy to this Mac's IP address, port {proxy_port}.")
    lines.append(TARGET_HINTS[target])
    lines.append(f"Saving to {folder}")
    lines.append("Press Ctrl+C to stop and write flows.har.\n")
    return "\n".join(lines)


def _mitmproxy_version() -> str | None:
    try:
        return metadata.version("mitmproxy")
    except metadata.PackageNotFoundError:
        return None


def run(preset_name: str, target: str = "device", mode: str = "wireguard", ui: bool = True, *,
        presets_dir: Path = PRESETS_DIR, sessions_dir: Path = session.SESSIONS_DIR,
        bin_dir: Path | None = None, proxy_port: int = PROXY_PORT, wiretrace_dir: Path = WIRETRACE_DIR) -> int:
    try:
        preset = load_preset(preset_name, presets_dir)
    except PresetError as e:
        say(str(e), err=True)
        return 1

    busy = busy_ports(needed_ports(mode, ui, proxy_port))
    if busy:
        for result in busy:
            say(f"{result.name}: {result.detail}", err=True)
        say("Not started.", err=True)
        return 1

    bin_dir = bin_dir or Path(sys.prefix) / "bin"
    meta = {
        "wiretrace_version": __version__,
        "mitmproxy_version": _mitmproxy_version(),
        "preset": preset.name,
        "api_hosts": list(preset.api_hosts),
        "target": target,
        "mode": mode,
        "ui": "mitmweb" if ui else "mitmdump",
        "status": "running",
    }

    # Installed before the folder exists, so no stop signal can leave a folder without a child.
    stops: list[int] = []
    previous = {s: signal.signal(s, lambda signum, _frame: stops.append(signum)) for s in STOP_SIGNALS}
    try:
        try:
            folder = session.create(preset.name, target, meta, sessions_dir)
        except FileExistsError:
            say("A session folder with this name already exists; start again in a second.", err=True)
            return 1
        flows = folder / session.FLOWS
        mock_count = count_mocks(wiretrace_dir / preset.mocks_dir)
        say(banner(preset, target, mode, ui, folder, proxy_port, mock_count))
        return supervise(
            build_command(preset, mode, ui, flows, bin_dir, proxy_port, wiretrace_dir),
            har_command(bin_dir, flows, folder / session.HAR),
            folder,
            stops,
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


# RUNNING, STOPPING, KILLED

def supervise(child_cmd: list[str], har_cmd: list[str], folder: Path, stops: list[int]) -> int:
    """Spawn the child and take it to DONE. The stop-signal handlers must already append to `stops`."""
    tool = Path(child_cmd[0]).name
    try:
        child = subprocess.Popen(child_cmd)
    except OSError as e:
        session.remove(folder)
        say(f"Could not start {tool}: {e.strerror or e}", err=True)
        return 1

    try:
        state = _wait(child, stops)
    finally:
        # Invariant 1: no exit path leaves the child running.
        if child.poll() is None:
            child.kill()
            child.wait()

    ended_at = session.timestamp()
    if state == RUNNING:
        say(f"{tool} exited on its own (exit code {child.returncode}).", err=True)
    return _finalize(folder, har_cmd, STATUS[state], ended_at, stops)


def _wait(child: subprocess.Popen, stops: list[int]) -> str:
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
            elif state == STOPPING:
                state = KILLED
                say("Force-stopping.")
                child.kill()
        if state == STOPPING and not warned and time.monotonic() - stopping_since >= STILL_STOPPING_S:
            say("still stopping — press Ctrl+C again to force")
            warned = True
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

def _finalize(folder: Path, har_cmd: list[str], status: str, ended_at: str, stops: list[int]) -> int:
    if not session.has_flows(folder):
        session.remove(folder)
        say("Nothing was captured; the session folder was removed.")
        return 1

    say("Writing flows.har…")
    har_error = convert_har(har_cmd, folder / session.HAR, stops)
    session.update_meta(folder, ended_at=ended_at, status=status)
    say(f"Session saved: {folder}")
    if har_error:
        say(f"flows.har was not written ({har_error}); flows.mitm is kept.", err=True)
    return 0 if status == "stopped" and not har_error else 1


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
