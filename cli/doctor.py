"""`wiretrace doctor`: checks that this Mac is ready to run Wiretrace.

Standard library only: doctor must still run, and say what is missing, when the
package install failed halfway. Output shows device counts and states only, never
serial numbers or UDIDs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"

TIMEOUT_S = 10
SOCKETFILTERFW = "/usr/libexec/ApplicationFirewall/socketfilterfw"
PORTS = [
    ("udp", "0.0.0.0", 51820, "WireGuard"),
    ("tcp", "0.0.0.0", 8080, "proxy"),
    ("tcp", "127.0.0.1", 8081, "mitmweb UI"),
]
PACKAGES = ["pyyaml", "pymobiledevice3", "httpx", "keyring"]

Run = Callable[[list[str]], str]


@dataclass(frozen=True)
class Result:
    status: str
    name: str
    detail: str


def _run(cmd: list[str]) -> str:
    """Return stdout. Raises OSError, subprocess.TimeoutExpired or CalledProcessError."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=TIMEOUT_S, check=True
    ).stdout


def _venv_bin() -> Path:
    return Path(sys.prefix) / "bin"


def _major(version: str) -> int | None:
    match = re.match(r"\d+", version)
    return int(match.group()) if match else None


# 1. Python

def check_python(version_info: tuple[int, ...] = tuple(sys.version_info[:3])) -> list[Result]:
    shown = ".".join(str(v) for v in version_info[:3])
    if tuple(version_info[:2]) >= (3, 12):
        return [Result(OK, "Python", shown)]
    return [Result(FAIL, "Python", f"{shown}; 3.12 or newer is needed. Run scripts/setup-mac.sh")]


# 2. mitmproxy

def check_mitmproxy(venv_bin: Path | None = None) -> list[Result]:
    venv_bin = venv_bin or _venv_bin()
    try:
        version = metadata.version("mitmproxy")
    except metadata.PackageNotFoundError:
        return [Result(FAIL, "mitmproxy", "not installed. Run scripts/setup-mac.sh")]
    major = _major(version)
    if major is None or major < 11:
        return [Result(FAIL, "mitmproxy", f"{version}; 11 or newer is needed. Run scripts/setup-mac.sh")]
    if not (venv_bin / "mitmweb").exists():
        return [Result(FAIL, "mitmproxy", f"{version}, but mitmweb is missing from {venv_bin}")]
    return [Result(OK, "mitmproxy", version)]


# 3. Other packages

def check_packages(names: list[str] = PACKAGES) -> list[Result]:
    found, missing = [], []
    for name in names:
        try:
            found.append(f"{name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            missing.append(name)
    if missing:
        return [Result(FAIL, "Python packages", f"missing: {', '.join(missing)}. Run scripts/setup-mac.sh")]
    return [Result(OK, "Python packages", ", ".join(found))]


# 4. adb

def find_adb(home: Path | None = None) -> str | None:
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    local = (home or Path.home()) / "tools" / "platform-tools" / "adb"
    return str(local) if os.access(local, os.X_OK) else None


def check_adb(adb: str | None) -> list[Result]:
    if adb:
        return [Result(OK, "adb", adb)]
    return [Result(WARN, "adb", "not found; Android testing is unavailable. Run scripts/setup-mac.sh")]


# 5. Ports

def check_port(proto: str, host: str, port: int, label: str) -> Result:
    name = f"Port {proto.upper()} {port} ({label})"
    kind = socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, kind) as sock:
        if proto == "tcp":
            # mitmproxy sets SO_REUSEADDR too, so TIME_WAIT leftovers are not a conflict.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return Result(FAIL, name, "in use by another program; stop it or quit the other proxy")
    return Result(OK, name, "free")


def check_ports(ports: list[tuple[str, str, int, str]] = PORTS) -> list[Result]:
    return [check_port(*p) for p in ports]


# 6 + 7. CA certificate and private key

def check_ca(mitm_dir: Path | None = None) -> list[Result]:
    mitm_dir = mitm_dir or Path.home() / ".mitmproxy"
    cert = mitm_dir / "mitmproxy-ca-cert.pem"
    key = mitm_dir / "mitmproxy-ca.pem"
    results = []

    if cert.exists():
        results.append(Result(OK, "CA certificate", str(cert)))
    else:
        results.append(Result(INFO, "CA certificate", "not created yet; mitmproxy creates it on first start"))

    if not key.exists():
        results.append(Result(INFO, "CA private key", "not created yet"))
    elif stat.S_IMODE(key.stat().st_mode) & 0o077:
        results.append(Result(WARN, "CA private key", f"readable by other users. Run: chmod 600 {key}"))
    else:
        results.append(Result(OK, "CA private key", "readable by you only"))
    return results


# 8. Firewall

def parse_fw_enabled(out: str) -> bool | None:
    match = re.search(r"State = (\d+)", out)
    if match:
        return int(match.group(1)) > 0
    if "is enabled" in out:
        return True
    if "is disabled" in out:
        return False
    return None


def parse_fw_block_all(out: str) -> bool | None:
    match = re.search(r"block all state set to (enabled|disabled)", out)
    return match.group(1) == "enabled" if match else None


def parse_fw_app(out: str) -> str:
    if "is permitted" in out:
        return "permitted"
    if "is blocked" in out:
        return "blocked"
    return "unknown"


def check_firewall(run: Run = _run, python: Path | None = None) -> list[Result]:
    name = "macOS firewall"
    python = python or Path(sys.executable).resolve()
    try:
        enabled = parse_fw_enabled(run([SOCKETFILTERFW, "--getglobalstate"]))
        if enabled is False:
            return [Result(OK, name, "off")]
        if parse_fw_block_all(run([SOCKETFILTERFW, "--getblockall"])):
            return [Result(FAIL, name, "blocks all incoming connections; ask IT for an allow rule (UDP 51820, TCP 8080)")]
        app = parse_fw_app(run([SOCKETFILTERFW, "--getappblocked", str(python)]))
    except (OSError, subprocess.CalledProcessError):
        return [Result(WARN, name, "could not read the firewall state")]

    if app == "blocked":
        return [Result(FAIL, name, f"blocks incoming connections to {python}; allow it in System Settings or ask IT")]
    if app == "permitted":
        return [Result(OK, name, "on; Wiretrace's Python is allowed")]
    return [Result(
        WARN, name,
        "on; macOS will ask to allow incoming connections on first start. "
        "If no prompt appears, the firewall is managed: ask IT for an allow rule (UDP 51820, TCP 8080)",
    )]


# 9. Android devices

def parse_adb_devices(out: str) -> Counter[str]:
    states: Counter[str] = Counter()
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("*") or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            states[parts[1]] += 1
    return states


def check_android(adb: str | None, run: Run = _run) -> list[Result]:
    name = "Android devices"
    if not adb:
        return [Result(INFO, name, "adb not installed")]
    try:
        states = parse_adb_devices(run([adb, "devices"]))
    except (OSError, subprocess.CalledProcessError):
        return [Result(INFO, name, "adb devices failed")]

    ready = states.pop("device", 0)
    if states:
        others = ", ".join(f"{n} {state}" for state, n in sorted(states.items()))
        hint = "; accept 'Allow USB debugging' on the phone" if "unauthorized" in states else ""
        return [Result(WARN, name, f"{ready} ready, {others}{hint}")]
    if ready:
        return [Result(OK, name, f"{ready} connected")]
    return [Result(INFO, name, "none connected")]


# 10. iOS devices

def parse_usbmux_list(out: str) -> int:
    start = out.find("[")
    if start < 0:
        raise ValueError("no JSON list in output")
    devices = json.loads(out[start:])
    if not isinstance(devices, list):
        raise ValueError("unexpected output")
    return len(devices)


def check_ios(venv_bin: Path | None = None, run: Run = _run) -> list[Result]:
    name = "iOS devices"
    tool = (venv_bin or _venv_bin()) / "pymobiledevice3"
    try:
        count = parse_usbmux_list(run([str(tool), "usbmux", "list"]))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return [Result(INFO, name, "pymobiledevice3 usbmux list failed")]
    if count:
        return [Result(OK, name, f"{count} connected")]
    return [Result(INFO, name, "none connected (the phone must 'Trust This Computer')")]


# Runner

def run_all() -> list[Result]:
    adb = find_adb()
    checks: list[tuple[str, Callable[[], list[Result]]]] = [
        ("Python", check_python),
        ("mitmproxy", check_mitmproxy),
        ("Python packages", check_packages),
        ("adb", lambda: check_adb(adb)),
        ("Ports", check_ports),
        ("CA", check_ca),
        ("macOS firewall", check_firewall),
        ("Android devices", lambda: check_android(adb)),
        ("iOS devices", check_ios),
    ]
    results: list[Result] = []
    for name, check in checks:
        try:
            results.extend(check())
        except subprocess.TimeoutExpired:
            results.append(Result(WARN, name, f"timed out after {TIMEOUT_S} s"))
    return results


def render(results: list[Result]) -> str:
    return "\n".join(f"{r.status:<4}  {r.name}: {r.detail}" for r in results)


def exit_code(results: list[Result]) -> int:
    return 1 if any(r.status == FAIL for r in results) else 0


def main() -> int:
    results = run_all()
    print(render(results))
    code = exit_code(results)
    print("\nAll required checks passed." if code == 0 else "\nSome checks failed; see FAIL lines above.")
    return code
