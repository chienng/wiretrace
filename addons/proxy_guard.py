"""Proxy mode: accept only this Mac and the device under test.

Loaded only in proxy mode. Loopback (`127.0.0.1`, `::1`) is always passed in
`qa_proxy_clients`, because that is how the iOS Simulator and the Android
emulator connect. With `qa_proxy_pin`, the first other address is remembered
for the rest of the process and every further address is closed.

A client that is not on this Mac cannot open a server connection to a loopback,
link-local or unspecified address. Value types stay `NamedTuple`: a dataclass
in a `-s` script fails to load (incident 2026-10-14).
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Sequence
from typing import NamedTuple

from mitmproxy import ctx

REFUSAL = (
    "Proxy: refused a connection from another device. Only the first device that connected "
    "is accepted; restart Wiretrace, or pass --client <its IP address>."
)


class Resolved(NamedTuple):
    """One lookup result: the address text, and whether it must not be dialled for a remote client."""

    address: str
    blocked: bool


def normalize(host: str) -> str:
    """IPv4-mapped IPv6 as IPv4; a zone id is dropped. Anything else is returned unchanged."""
    text = host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return host
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return str(mapped or address)


def _literal(host: str) -> str | None:
    text = host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return str(mapped or address)


def _blocked(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    mapped = parsed.ipv4_mapped if isinstance(parsed, ipaddress.IPv6Address) else None
    parsed = mapped or parsed
    return parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified


def _loopback(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(normalize(address))
    except ValueError:
        return False
    return parsed.is_loopback


async def _lookup(host: str):
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(host, None)


async def resolve(host: str) -> list[Resolved]:
    """IP literals as themselves; a name via the running loop's `getaddrinfo`."""
    literal = _literal(host)
    if literal is not None:
        return [Resolved(literal, _blocked(literal))]
    infos = await _lookup(host)
    found = []
    for item in infos:
        address = normalize(item[4][0])
        found.append(Resolved(address, _blocked(address)))
    return found


class ProxyGuard:
    def __init__(self) -> None:
        self.pinned: str | None = None
        self.refused = 0
        self._clients: frozenset[str] = frozenset()
        self._pin = False

    def load(self, loader) -> None:
        loader.add_option(
            "qa_proxy_clients", Sequence[str], [],
            "Client addresses always accepted. Loopback is included so the simulator and emulator work.",
        )
        loader.add_option(
            "qa_proxy_pin", bool, False,
            "Accept the first client that is not in qa_proxy_clients, and only that one afterwards.",
        )

    def configure(self, updated) -> None:
        self._clients = frozenset(normalize(address) for address in ctx.options.qa_proxy_clients if address)
        self._pin = bool(ctx.options.qa_proxy_pin)

    def client_connected(self, client) -> None:
        peer = getattr(client, "peername", None)
        ip = normalize(peer[0]) if peer else ""
        if ip and (ip in self._clients or ip == self.pinned):
            return
        if ip and self._pin and self.pinned is None:
            self.pinned = ip
            return
        # mitmproxy closes the connection when this is set. The text has no address.
        client.error = "connection refused"
        self.refused += 1
        if self.refused == 1:
            print(REFUSAL, flush=True)

    async def server_connect(self, data) -> None:
        peer = getattr(data.client, "peername", None)
        if peer and _loopback(peer[0]):
            return
        address = data.server.address
        if not address:
            return
        try:
            results = await resolve(address[0])
        except OSError:
            return
        if any(item.blocked for item in results):
            data.server.error = (
                "Wiretrace refuses a connection to a loopback, link-local or unspecified address."
            )


addons = [ProxyGuard()]
