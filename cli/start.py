"""`wiretrace start`: run mitmweb or mitmdump with a preset and save the session.

The launcher only builds the mitmproxy command line and supervises that child
process; QA logic belongs in mitmproxy addons. The child runs in the launcher's
process group, so a Terminal Ctrl+C or a closed window reaches both directly.

A second child, the device log collector (`python -m collectors`), runs in its own
process group so one killpg ends it and the tools it started. A Terminal Ctrl+C no
longer reaches it, so the launcher forwards every stop. It never decides the state.

States (docs/specs/002-start-launcher-presets-sessions.md, 004-log-collectors-and-app-log-receiver.md):
PREPARE -> RUNNING -> STOPPING -> KILLED -> FINALIZING -> DONE, or PREPARE -> ABORTED.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from importlib import metadata
from pathlib import Path

from . import __version__, doctor, redact, session
from .preset import PRESETS_DIR, Preset, PresetError, allow_hosts_regexes, load_preset

TARGETS = ("android", "ios", "android-emu", "ios-sim", "device")
MODES = ("wireguard", "proxy")
PROXY_PORT = 8080
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
STILL_STOPPING_S = 15
COLLECTOR_STOP_S = 3
POLL_S = 0.1
WIRETRACE_DIR = Path(__file__).resolve().parent.parent
# Always the addon shipped with this checkout; `wiretrace_dir` only decides where mocks are read.
QA_ADDON = WIRETRACE_DIR / "addons" / "qa_tools.py"
APP_LOGS_ADDON = WIRETRACE_DIR / "addons" / "app_logs.py"
UI_ADDON = WIRETRACE_DIR / "addons" / "wiretrace_ui.py"
UI_PORT = 8081
MITMWEB, WIRETRACE, NO_UI = "mitmweb", "wiretrace", "none"
RECEIVER_HOST = "qa-logs.internal"
RECEIVER_ALLOW_HOSTS = r"^qa-logs\.internal(:\d+)?$"
RECEIVER_SAVE_FILTER = r"!~d ^qa-logs\.internal$"
# Which log source each target runs, and how the banner names it.
DEVICE_LOGS = {"android": "android", "android-emu": "android", "ios": "ios", "ios-sim": "ios-sim"}
DEVICE_LOG_NAMES = {"android": "Android", "ios": "iPhone", "ios-sim": "iOS Simulator"}
APP_KEYS = {"android": "android_package", "ios": "ios_process", "ios-sim": "ios_process"}

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

def ui_kind(ui: bool | str) -> str:
    """The UI as one of MITMWEB, WIRETRACE, NO_UI; a bool is the older way to say mitmweb or none."""
    if isinstance(ui, str):
        return ui
    return MITMWEB if ui else NO_UI


def needed_ports(mode: str, ui: bool | str, proxy_port: int = PROXY_PORT,
                 ui_port: int = UI_PORT) -> list[tuple[str, str, int, str]]:
    kind = ui_kind(ui)
    labels = {"WireGuard"} if mode == "wireguard" else {"proxy"}
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


def build_command(preset: Preset, mode: str, ui: bool | str, flows: Path, bin_dir: Path,
                  proxy_port: int = PROXY_PORT, wiretrace_dir: Path = WIRETRACE_DIR,
                  ui_port: int = UI_PORT) -> list[str]:
    kind = ui_kind(ui)
    cmd = [str(bin_dir / ("mitmweb" if kind == MITMWEB else "mitmdump"))]
    if mode == "wireguard":
        cmd += ["--mode", "wireguard"]
    else:
        cmd += ["--mode", "regular", "--listen-port", str(proxy_port)]
    for regex in allow_hosts_regexes(preset):
        cmd += ["--allow-hosts", regex]
    # Only the receiver host, no subdomains, so its HTTPS request is decrypted.
    cmd += ["--allow-hosts", RECEIVER_ALLOW_HOSTS]
    cmd += ["--save-stream-file", str(flows)]
    cmd += ["-s", str(QA_ADDON), "-s", str(APP_LOGS_ADDON)]
    if kind == WIRETRACE:
        cmd += ["-s", str(UI_ADDON)]
    for host in preset.api_hosts:
        cmd += ["--set", f"qa_api_hosts={host}"]
    cmd += ["--set", f"qa_mocks_dir={(wiretrace_dir / preset.mocks_dir).absolute()}"]
    cmd += ["--set", f"qa_request_id_header={preset.request_id_header}"]
    cmd += ["--set", f"qa_app_log_file={flows.parent / session.APP_LOG}"]
    # Receiver flows stay visible in mitmweb but are not saved: they would duplicate app.log.jsonl.
    cmd += ["--set", f"save_stream_filter={RECEIVER_SAVE_FILTER}"]
    if kind == WIRETRACE:
        # The window is the only output; the token is made by the addon and never goes on a command line.
        cmd += ["--set", "flow_detail=0", "--set", f"qa_ui_port={ui_port}",
                "--set", f"qa_ui_session_dir={flows.parent}",
                "--set", f"qa_ui_default_filter={preset.default_filter or ''}",
                "--set", "qa_ui_open_browser=true"]
    elif preset.default_filter:
        # An option, not mitmdump's positional filter argument, which would also limit saving.
        option = "view_filter" if kind == MITMWEB else "dumper_filter"
        cmd += ["--set", f"{option}={preset.default_filter}"]
    return cmd


def har_command(bin_dir: Path, flows: Path, har: Path) -> list[str]:
    return [str(bin_dir / "mitmdump"), "-n", "-r", str(flows), "--set", f"hardump={har}"]


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
            "--out", str(out), f"--{tool}", found], ""


def count_mocks(mocks_dir: Path) -> int:
    return sum(1 for p in mocks_dir.rglob("*.json") if p.is_file()) if mocks_dir.is_dir() else 0


def banner(preset: Preset, target: str, mode: str, ui: bool | str, folder: Path,
           proxy_port: int = PROXY_PORT, mock_count: int = 0, device_logs: str = "off") -> str:
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
    elif kind == WIRETRACE:
        lines.append("Faults: Wiretrace > Faults")
    lines.append(f"Device logs: {device_logs}")
    lines.append(f"App logs: POST https://{RECEIVER_HOST}/log → {session.APP_LOG}")
    if mode == "wireguard":
        first_time = {MITMWEB: "scan the QR code in mitmweb", WIRETRACE: "scan the QR code in Wiretrace > Setup",
                      NO_UI: "enter the configuration printed below"}[kind]
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


def run(preset_name: str, target: str = "device", mode: str = "wireguard", ui: bool | str = True, *,
        presets_dir: Path = PRESETS_DIR, sessions_dir: Path = session.SESSIONS_DIR,
        bin_dir: Path | None = None, proxy_port: int = PROXY_PORT, wiretrace_dir: Path = WIRETRACE_DIR,
        ui_port: int = UI_PORT, collector_for: Callable[..., tuple[list[str] | None, str]] = collector_command) -> int:
    try:
        preset = load_preset(preset_name, presets_dir)
    except PresetError as e:
        say(str(e), err=True)
        return 1

    kind = ui_kind(ui)
    busy = busy_ports(needed_ports(mode, kind, proxy_port, ui_port))
    if busy:
        for result in busy:
            say(f"{result.name}: {result.detail}", err=True)
        say("Not started.", err=True)
        return 1

    removed = session.remove_old(sessions_dir, datetime.now())
    if removed:
        say(f"Deleted {removed} old session(s) (older than {session.KEEP_DAYS} days).")

    bin_dir = bin_dir or Path(sys.prefix) / "bin"
    rules = redact.rules_for(preset)
    meta = {
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
        collector_cmd, problem = collector_for(preset, target, bin_dir, folder / session.DEVICE_LOG)
        source = DEVICE_LOGS.get(target) if collector_cmd else None
        if source:
            session.update_meta(folder, device_logs=source)
            device_logs = f"{DEVICE_LOG_NAMES[source]}, {preset.app[APP_KEYS[source]]} → {session.DEVICE_LOG}"
        else:
            device_logs = f"off ({problem})"
        say(banner(preset, target, mode, kind, folder, proxy_port, mock_count, device_logs))
        return supervise(
            build_command(preset, mode, kind, flows, bin_dir, proxy_port, wiretrace_dir, ui_port),
            har_command(bin_dir, flows, folder / session.HAR_TMP),
            folder,
            stops,
            collector_cmd,
            rules,
        )
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


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


def supervise(child_cmd: list[str], har_cmd: list[str], folder: Path, stops: list[int],
              collector_cmd: list[str] | None = None, rules: redact.Rules | None = None) -> int:
    """Spawn the child and take it to DONE. The stop-signal handlers must already append to `stops`."""
    tool = Path(child_cmd[0]).name
    try:
        child = subprocess.Popen(child_cmd)
    except OSError as e:
        session.remove(folder)
        say(f"Could not start {tool}: {e.strerror or e}", err=True)
        return 1

    collector = None
    try:
        # Invariant 2: only after the child started; a collector that cannot start is skipped.
        if collector_cmd:
            collector = _Collector.start(collector_cmd)
            if collector is None:
                session.update_meta(folder, device_logs=None)
        state = _wait(child, stops, collector)
        ended_at = session.timestamp()
        if state == RUNNING:
            say(f"{tool} exited on its own (exit code {child.returncode}).", err=True)
        if collector:
            collector.stop(stops, state == KILLED)
    finally:
        # Invariant 1: no exit path leaves the child, or anything in the collector's group, running.
        if child.poll() is None:
            child.kill()
            child.wait()
        if collector:
            collector.close()

    return _finalize(folder, har_cmd, STATUS[state], ended_at, stops, rules or redact.rules_for(None))


def _wait(child: subprocess.Popen, stops: list[int], collector: _Collector | None = None) -> str:
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
    if flows:
        say("Writing flows.har…")
        har_error = write_masked_har(har_cmd, folder, rules, stops)
    else:
        say("No traffic was captured; flows.har was not written.")
    session.update_meta(folder, ended_at=ended_at, status=status, **counts)
    say(f"Session saved: {folder}")
    say(f"For a bug ticket: ./wiretrace report {folder.name}")
    if har_error:
        say(f"flows.har was not written ({har_error}); flows.mitm is kept.", err=True)
    return 0 if status == "stopped" and not har_error else 1


def write_masked_har(har_cmd: list[str], folder: Path, rules: redact.Rules, stops: list[int]) -> str | None:
    """flows.har, masked. The unmasked HAR is `.flows.har.tmp`, removed on every path. Return why it failed."""
    tmp, masked = folder / session.HAR_TMP, folder / session.HAR_MASKED
    try:
        error = convert_har(har_cmd, tmp, stops)
        if error:
            return error
        try:
            har = json.loads(tmp.read_text(encoding="utf-8"))
            if not isinstance(har, dict):
                return "could not mask it"
            masked.write_text(json.dumps(redact.redact_har(har, rules)[0], indent=4), encoding="utf-8")
            os.replace(masked, folder / session.HAR)
        except Exception:
            # Whatever went wrong, flows.har must not exist unmasked.
            return "could not mask it"
        return None
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
