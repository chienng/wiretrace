"""Proxy guard: who may connect, and which server addresses a remote client may open.

The real-mitmdump test is required: a unit import does not prove a `-s` script loads
(incident 2026-10-14, dataclass) or that `client.error` actually closes the connection.
"""

from __future__ import annotations

import asyncio
import http.client
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mitmproxy.proxy import mode_specs

from addons import proxy_guard
from addons.proxy_guard import REFUSAL, ProxyGuard

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"


REGULAR = mode_specs.ProxyMode.parse("regular")
WIREGUARD = mode_specs.ProxyMode.parse("wireguard@51820")


class _Client:
    def __init__(self, ip: str, mode: mode_specs.ProxyMode | None = REGULAR) -> None:
        self.peername = (ip, 40000)
        self.error = None
        if mode is not None:
            self.proxy_mode = mode


class _Server:
    def __init__(self, host: str) -> None:
        self.address = (host, 80)
        self.error = None


class _Data:
    def __init__(self, client_ip: str, host: str, mode: mode_specs.ProxyMode | None = REGULAR) -> None:
        self.client = _Client(client_ip, mode)
        self.server = _Server(host)


def guard(*clients: str, pin: bool = True) -> ProxyGuard:
    addon = ProxyGuard()
    addon._clients = proxy_guard.parse_clients(clients)
    addon._pin = pin
    return addon


def connect(addon: ProxyGuard, ip: str, mode: mode_specs.ProxyMode | None = REGULAR) -> _Client:
    client = _Client(ip, mode)
    addon.client_connected(client)
    return client


# client_connected

def test_a_listed_address_is_accepted():
    addon = guard("127.0.0.1", "::1", pin=False)
    client = connect(addon, "127.0.0.1")
    assert client.error is None and addon.pinned is None and addon.refused == 0


def test_the_first_other_address_is_pinned_and_the_next_is_refused(capsys):
    addon = guard("127.0.0.1", "::1", pin=True)
    first = connect(addon, "192.0.2.10")
    assert first.error is None and addon.pinned == "192.0.2.10"
    again = connect(addon, "192.0.2.10")
    assert again.error is None and addon.pinned == "192.0.2.10"

    second = connect(addon, "192.0.2.11")
    third = connect(addon, "198.51.100.8")
    assert second.error and third.error
    assert addon.pinned == "192.0.2.10" and addon.refused == 2
    printed = capsys.readouterr().out
    assert printed.count(REFUSAL) == 1
    assert "192.0.2.11" not in printed and "198.51.100.8" not in printed


def test_pinning_off_accepts_nothing_beyond_the_list(capsys):
    addon = guard("127.0.0.1", pin=False)
    client = connect(addon, "192.0.2.10")
    assert client.error and addon.pinned is None and addon.refused == 1
    assert REFUSAL in capsys.readouterr().out


def test_ipv4_mapped_ipv6_matches_the_ipv4_form():
    addon = guard("192.0.2.10", pin=False)
    client = connect(addon, "::ffff:192.0.2.10")
    assert client.error is None
    assert proxy_guard.normalize("::ffff:192.0.2.10") == "192.0.2.10"


@pytest.mark.parametrize("ip", ["127.0.0.1", "127.0.0.2", "127.255.255.254", "::1", "::ffff:127.0.0.5"])
def test_every_loopback_address_is_accepted_and_never_pinned(ip):
    addon = guard("127.0.0.0/8", "::1", pin=True)
    client = connect(addon, ip)
    assert client.error is None and addon.pinned is None and addon.refused == 0
    phone = connect(addon, "192.0.2.10")
    assert phone.error is None and addon.pinned == "192.0.2.10"


def test_a_wireguard_client_is_accepted_and_does_not_use_up_the_pin(capsys):
    addon = guard("127.0.0.0/8", "::1", pin=True)
    tunnel = connect(addon, "10.0.0.1", WIREGUARD)
    assert tunnel.error is None and addon.pinned is None and addon.refused == 0
    phone = connect(addon, "192.0.2.10")
    assert phone.error is None and addon.pinned == "192.0.2.10"
    other = connect(addon, "192.0.2.11")
    assert other.error and addon.refused == 1
    assert capsys.readouterr().out.count(REFUSAL) == 1


def test_wireguard_and_lan_clients_at_the_same_address_are_told_apart_by_mode():
    addon = guard("127.0.0.0/8", "::1", pin=True)
    assert connect(addon, "192.0.2.10").error is None
    # Every tunnel client comes from the tunnel's address; it is never refused, after the pin too.
    for _ in range(3):
        assert connect(addon, "10.0.0.1", WIREGUARD).error is None
    assert addon.pinned == "192.0.2.10" and addon.refused == 0
    lan = connect(addon, "10.0.0.1")
    assert lan.error and addon.refused == 1


def test_wireguard_clients_are_not_refused_with_pinning_off():
    addon = guard("127.0.0.1", pin=False)
    assert connect(addon, "10.0.0.1", WIREGUARD).error is None
    assert addon.refused == 0


def test_a_client_without_proxy_mode_is_treated_as_regular():
    addon = guard("127.0.0.0/8", "::1", pin=True)
    first = connect(addon, "192.0.2.10", None)
    assert first.error is None and addon.pinned == "192.0.2.10"
    second = connect(addon, "192.0.2.11", None)
    assert second.error and addon.refused == 1
    data = _Data("192.0.2.10", "127.0.0.1", None)
    asyncio.run(addon.server_connect(data))
    assert data.server.error


def test_a_bad_client_entry_is_an_options_error():
    from mitmproxy import exceptions
    from mitmproxy.test import taddons

    addon = ProxyGuard()
    with taddons.context(addon) as tctx:
        with pytest.raises(exceptions.OptionsError):
            tctx.configure(addon, qa_proxy_clients=["not-an-ip"])
        tctx.configure(addon, qa_proxy_clients=["127.0.0.0/8", "::1", "192.168.1.20"])
        assert addon._listed("127.0.0.9") and addon._listed("192.168.1.20")
        assert not addon._listed("192.168.1.21")


# server_connect

def _run(addon: ProxyGuard, client_ip: str, host: str, mode: mode_specs.ProxyMode | None = REGULAR) -> _Data:
    data = _Data(client_ip, host, mode)
    asyncio.run(addon.server_connect(data))
    return data


def test_a_loopback_client_may_reach_loopback():
    data = _run(guard(), "127.0.0.1", "127.0.0.1")
    assert data.server.error is None
    data = _run(guard(), "::1", "127.0.0.1")
    assert data.server.error is None


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "169.254.1.1", "0.0.0.0"])
def test_a_remote_client_is_refused_for_a_blocked_literal(host):
    data = _run(guard(pin=False), "192.0.2.10", host)
    assert data.server.error


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "169.254.1.1", "0.0.0.0"])
def test_a_wireguard_client_is_not_checked_for_the_server_address(host, monkeypatch):
    async def lookup(host: str):
        raise AssertionError(host)

    monkeypatch.setattr(proxy_guard, "_lookup", lookup)
    data = _run(guard(pin=False), "10.0.0.1", host, WIREGUARD)
    assert data.server.error is None


def test_a_name_that_resolves_to_loopback_is_refused(monkeypatch):
    async def lookup(host: str):
        assert host == "rebind.test"
        return [(0, 0, 0, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(proxy_guard, "_lookup", lookup)
    data = _run(guard(pin=False), "192.0.2.10", "rebind.test")
    assert data.server.error


def test_localhost_is_refused_for_a_remote_client(monkeypatch):
    async def lookup(host: str):
        assert host == "localhost"
        return [(0, 0, 0, "", ("::1", 0))]

    monkeypatch.setattr(proxy_guard, "_lookup", lookup)
    data = _run(guard(pin=False), "192.0.2.10", "localhost")
    assert data.server.error


def test_a_public_name_is_allowed(monkeypatch):
    async def lookup(host: str):
        assert host == "example.com"
        return [(0, 0, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(proxy_guard, "_lookup", lookup)
    data = _run(guard(pin=False), "192.0.2.10", "example.com")
    assert data.server.error is None


def test_a_literal_does_not_call_the_resolver(monkeypatch):
    async def lookup(host: str):
        raise AssertionError(host)

    monkeypatch.setattr(proxy_guard, "_lookup", lookup)
    data = _run(guard(pin=False), "192.0.2.10", "127.0.0.1")
    assert data.server.error


# Real mitmdump: the script loads, and client.error closes the connection.

def _free_port() -> int:
    with socket.socket(socket.AF_INET6) as probe:
        probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        probe.bind(("::", 0))
        return probe.getsockname()[1]


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("0.0.0.0", 0))
        return probe.getsockname()[1]


def _accepts(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        return True
    except OSError:
        return False


needs_mitmdump = pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")


@needs_mitmdump
@pytest.mark.parametrize("both", [False, True], ids=["proxy", "both"])
def test_real_mitmdump_refuses_loopback_when_it_is_not_allowed(tmp_path, both):
    port = _free_port()
    log = tmp_path / "mitmdump.log"
    wireguard = ["--mode", f"wireguard@{_free_udp_port()}"] if both else []
    args = [
        str(VENV_BIN / "mitmdump"), "--mode", "regular", "--listen-port", str(port), *wireguard,
        "--set", f"confdir={tmp_path / 'confdir'}",
        "-s", str(ROOT / "addons" / "proxy_guard.py"),
        "--set", "qa_proxy_clients=192.0.2.1", "--set", "qa_proxy_pin=false",
    ]
    with open(log, "w") as out:
        proc = subprocess.Popen(args, stdout=out, stderr=subprocess.STDOUT, cwd=ROOT,
                                env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"})
    try:
        deadline = time.monotonic() + 60
        while not _accepts(port):
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(log.read_text()[-2000:])
            time.sleep(0.05)
        refused = False
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "http://example.com/")
            response = conn.getresponse()
            refused = response.status >= 400
            response.read()
        except (OSError, http.client.HTTPException):
            refused = True
        finally:
            if conn is not None:
                conn.close()
        assert refused
        text = log.read_text()
        assert text.count(REFUSAL) == 1
        line = next(line for line in text.splitlines() if line.startswith("Proxy: refused"))
        assert "127.0.0.1" not in line and "192.0.2.1" not in line
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
