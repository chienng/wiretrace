import socket

import pytest

from cli import doctor
from cli.doctor import FAIL, INFO, OK, WARN, Result


def fake_run(outputs: dict[str, str]):
    """A `run` stand-in keyed by the last argument of the command."""

    def run(cmd: list[str]) -> str:
        return outputs[cmd[-1]]

    return run


# adb devices

def test_adb_devices_empty():
    assert doctor.parse_adb_devices("List of devices attached\n\n") == {}


def test_adb_devices_one_ready():
    out = "List of devices attached\nR58M123ABC\tdevice\n\n"
    assert doctor.parse_adb_devices(out) == {"device": 1}


def test_adb_devices_unauthorized():
    out = "List of devices attached\nR58M123ABC\tunauthorized\n"
    assert doctor.parse_adb_devices(out) == {"unauthorized": 1}


def test_adb_devices_mixed_with_daemon_noise():
    out = (
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "R58M123ABC\tdevice\n"
        "emulator-5554\tdevice\n"
        "0A1B2C3D\tunauthorized\n"
    )
    assert doctor.parse_adb_devices(out) == {"device": 2, "unauthorized": 1}


def test_android_check_states():
    def check(out):
        return doctor.check_android("/x/adb", run=lambda cmd: out)[0].status

    assert check("List of devices attached\n") == INFO
    assert check("List of devices attached\nA\tdevice\n") == OK
    assert check("List of devices attached\nA\tdevice\nB\tunauthorized\n") == WARN
    assert doctor.check_android(None)[0].status == INFO


def test_android_output_never_shows_serials():
    serial = "R58M123ABC"
    out = f"List of devices attached\n{serial}\tdevice\n0A1B2C3D\tunauthorized\n"
    rendered = doctor.render(doctor.check_android("/x/adb", run=lambda cmd: out))
    assert serial not in rendered
    assert "0A1B2C3D" not in rendered


def test_ios_output_never_shows_udids():
    udid = "00008110-001A2B3C4D5E801E"
    out = f'[{{"UniqueDeviceID": "{udid}", "ConnectionType": "USB"}}]'
    results = doctor.check_ios(run=lambda cmd: out)
    assert results[0].status == OK
    assert udid not in doctor.render(results)


# socketfilterfw

def test_firewall_parsers():
    assert doctor.parse_fw_enabled("Firewall is enabled. (State = 1)") is True
    assert doctor.parse_fw_enabled("Firewall is enabled. (State = 2)") is True
    assert doctor.parse_fw_enabled("Firewall is disabled. (State = 0)") is False
    assert doctor.parse_fw_block_all("Firewall has block all state set to enabled.") is True
    assert doctor.parse_fw_block_all("Firewall has block all state set to disabled.") is False
    assert doctor.parse_fw_app("Incoming connection to /p/python3.12 is permitted.") == "permitted"
    assert doctor.parse_fw_app("Incoming connection to /p/python3.12 is blocked.") == "blocked"
    assert doctor.parse_fw_app("The application is not part of the firewall") == "unknown"


def firewall_status(global_state, block_all, app):
    run = fake_run({
        "--getglobalstate": global_state,
        "--getblockall": f"Firewall has block all state set to {block_all}.",
        "/p/python3.12": app,
    })
    return doctor.check_firewall(run=run, python="/p/python3.12")[0].status


def test_firewall_check():
    on, off = "Firewall is enabled. (State = 1)", "Firewall is disabled. (State = 0)"
    permitted = "Incoming connection to /p/python3.12 is permitted."
    blocked = "Incoming connection to /p/python3.12 is blocked."
    assert firewall_status(off, "disabled", "") == OK
    assert firewall_status(on, "enabled", permitted) == FAIL
    assert firewall_status(on, "disabled", blocked) == FAIL
    assert firewall_status(on, "disabled", permitted) == OK
    assert firewall_status(on, "disabled", "not part of the firewall") == WARN


# Ports

def test_port_free():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert doctor.check_port("tcp", "127.0.0.1", port, "test").status == OK


def test_port_in_use():
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        assert doctor.check_port("tcp", "127.0.0.1", port, "test").status == FAIL


def ipv6_only(kind):
    sock = socket.socket(socket.AF_INET6, kind)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.bind(("::", 0))
    return sock


def test_tcp_port_in_use_on_ipv6_only():
    # mitmproxy listens on "::" as well, so this would make it fail to start.
    with ipv6_only(socket.SOCK_STREAM) as holder:
        holder.listen()
        port = holder.getsockname()[1]
        assert doctor.check_port("tcp", "0.0.0.0", port, "test").status == FAIL


def test_udp_port_in_use_on_ipv6_only_is_not_a_conflict():
    # mitmproxy's UDP servers fall back to IPv4 when "::" is taken.
    with ipv6_only(socket.SOCK_DGRAM) as holder:
        port = holder.getsockname()[1]
        assert doctor.check_port("udp", "0.0.0.0", port, "test").status == OK


def test_udp_port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as holder:
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        assert doctor.check_port("udp", "127.0.0.1", port, "test").status == FAIL


# CA

def test_ca_absent(tmp_path):
    cert, key = doctor.check_ca(tmp_path)
    assert (cert.status, key.status) == (INFO, INFO)


def test_ca_key_owner_only(tmp_path):
    (tmp_path / "mitmproxy-ca-cert.pem").write_text("cert")
    (tmp_path / "mitmproxy-ca.pem").write_text("key")
    (tmp_path / "mitmproxy-ca.pem").chmod(0o600)
    cert, key = doctor.check_ca(tmp_path)
    assert (cert.status, key.status) == (OK, OK)


def test_ca_key_readable_by_others(tmp_path):
    (tmp_path / "mitmproxy-ca.pem").write_text("key")
    (tmp_path / "mitmproxy-ca.pem").chmod(0o644)
    assert doctor.check_ca(tmp_path)[1].status == WARN


# Python version and exit code

def test_python_version():
    assert doctor.check_python((3, 12, 4))[0].status == OK
    assert doctor.check_python((3, 11, 9))[0].status == FAIL


def test_exit_code():
    assert doctor.exit_code([Result(OK, "a", ""), Result(WARN, "b", ""), Result(INFO, "c", "")]) == 0
    assert doctor.exit_code([Result(OK, "a", ""), Result(FAIL, "b", "")]) == 1


def test_setup_installs_with_the_dependency_overrides():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    script = (root / "scripts" / "setup-mac.sh").read_text()
    assert "--overrides overrides.txt" in script
    overrides = (root / "overrides.txt").read_text()
    assert 'cryptography>=50.0.0,<=50.0.2; platform_machine == "arm64"' in overrides
    assert 'cryptography>=48.0.1,<49; platform_machine == "x86_64"' in overrides
    assert "h2>=4.4.1,<=4.4.1" in overrides
    assert "tornado>=6.5.9,<=6.5.10" in overrides
    assert "msgpack>=1.2.1" in overrides


@pytest.mark.parametrize("machine, translated, expected", [
    ("x86_64", None, "x86_64"),
    ("arm64", "0", "arm64"),
    ("x86_64", "1", "arm64"),
])
def test_setup_picks_the_native_cpu_even_under_rosetta(tmp_path, machine, translated, expected):
    import re
    import subprocess
    from pathlib import Path
    script = (Path(__file__).resolve().parent.parent / "scripts" / "setup-mac.sh").read_text()
    function = re.search(r"^host_cpu\(\) \{\n.*?^\}\n", script, re.S | re.M).group(0)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sysctl = f"echo {translated}" if translated else "echo \"sysctl: unknown oid\" >&2; exit 1"
    for name, body in (("uname", f"echo {machine}"), ("sysctl", sysctl)):
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    result = subprocess.run(["/bin/bash", "-c", function + "host_cpu"], env={"PATH": str(bin_dir)},
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == expected


def run_setup_finish(tmp_path, app_made, status, open_app, open_works=True):
    import re
    import subprocess
    from pathlib import Path
    script = (Path(__file__).resolve().parent.parent / "scripts" / "setup-mac.sh").read_text()
    function = re.search(r"^finish\(\) \{\n.*?^\}\n", script, re.S | re.M).group(0)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    opened = tmp_path / "opened"
    stub = bin_dir / "open"
    stub.write_text(f'#!/bin/sh\necho "$@" >> {opened}\nexit {0 if open_works else 1}\n')
    stub.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", "-c", function + f'finish {app_made} {status} {open_app} "/Apps/Wiretrace.app"'],
        env={"PATH": str(bin_dir)}, capture_output=True, text=True, check=True)
    return result.stdout, opened.read_text().split("\n")[:-1] if opened.exists() else []


def test_setup_opens_the_app_when_the_check_passes(tmp_path):
    out, opened = run_setup_finish(tmp_path, app_made=1, status=0, open_app=1)
    assert opened == ["/Apps/Wiretrace.app"]
    assert "the Wiretrace app is opening" in out
    # The app quits once the session starts, so its Dock icon is gone too soon to right-click.
    assert "drag Wiretrace onto the Dock" in out and "Keep in Dock" not in out
    assert "choose your project and device" not in out
    assert "To type adb or uv yourself, open a new Terminal window" in out
    assert "so the PATH changes apply" not in out


@pytest.mark.parametrize("app_made, status, open_app, expected", [
    (1, 1, 1, "Fix the FAIL lines above"),
    (1, 0, 0, "open Wiretrace from Launchpad or Spotlight"),
    (0, 0, 1, "start it with ./wiretrace start"),
])
def test_setup_does_not_open_the_app_after_a_fail_with_no_open_or_without_the_app(
        tmp_path, app_made, status, open_app, expected):
    out, opened = run_setup_finish(tmp_path, app_made, status, open_app)
    assert opened == []
    assert expected in out
    assert "is opening" not in out


def test_setup_says_where_the_app_is_when_it_cannot_open_it(tmp_path):
    out, opened = run_setup_finish(tmp_path, app_made=1, status=0, open_app=1, open_works=False)
    assert opened == ["/Apps/Wiretrace.app"]
    assert "is opening" not in out
    assert "Wiretrace is ready: open Wiretrace from Launchpad or Spotlight" in out


def test_setup_opens_the_app_only_from_a_terminal_and_without_no_open():
    from pathlib import Path
    script = (Path(__file__).resolve().parent.parent / "scripts" / "setup-mac.sh").read_text()
    assert "--no-open) open_app=0 ;;" in script
    assert "[ -t 1 ] || open_app=0\n" in script
    assert 'finish "$app_made" "$status" "$open_app" "$HOME/Applications/Wiretrace.app"' in script


def test_setup_asks_uv_for_the_python_of_that_cpu():
    from pathlib import Path
    script = (Path(__file__).resolve().parent.parent / "scripts" / "setup-mac.sh").read_text()
    assert 'PYTHON_REQUEST="cpython-3.12-macos-$python_arch-none"' in script
    assert '"$UV" python install "$PYTHON_REQUEST"' in script
    assert '"$UV" venv --python "$PYTHON_REQUEST" .venv' in script
    assert 'if [ "$venv_cpu" != "$cpu" ]; then' in script


def test_menu_bar_check_reports_availability_as_info():
    available = doctor.check_menu_bar(lambda: None)
    assert available == [Result(INFO, "Menu bar", "available")]
    assert "INFO  Menu bar: available" in doctor.render(available)
    missing = doctor.check_menu_bar(lambda: "PyObjC not installed (run scripts/setup-mac.sh)")
    assert missing == [Result(INFO, "Menu bar", "PyObjC not installed (run scripts/setup-mac.sh)")]
    assert "INFO  Menu bar: PyObjC not installed (run scripts/setup-mac.sh)" in doctor.render(missing)
    assert doctor.exit_code(doctor.check_menu_bar(lambda: "no window server")) == 0
