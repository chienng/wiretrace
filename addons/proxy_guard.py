"""Proxy mode: accept only this Mac and the device under test.

Loaded in proxy and both modes. `qa_proxy_clients` takes addresses and ranges; the
launcher always passes loopback (`127.0.0.0/8`, `::1`), because that is how the
iOS Simulator and the Android emulator connect. With `qa_proxy_pin`, the first
other address is remembered for the rest of the process and every further
address is closed. `qa_proxy_pinned` takes that slot before the first connection:
the window's client switch starts a session pinned to the device it chose
(docs/specs/021-switch-to-another-phone.md).

Refused addresses are kept in memory, at most MAX_WAITING, for the window's banner.
They are never printed.

A client that is not on this Mac cannot open a server connection to a loopback,
link-local or unspecified address. Value types stay `NamedTuple`: a dataclass
in a `-s` script fails to load (incident 2026-10-14).

Only clients of the regular (Wi-Fi proxy) listener are checked. In both mode a
WireGuard client is never pinned or refused here: the tunnel key is its access
control, and every tunnel client has the same address. A client without
`proxy_mode` is treated as a regular one.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections.abc import Sequence
from typing import NamedTuple

from mitmproxy import ctx, exceptions
from mitmproxy.proxy import mode_specs

REFUSAL = (
    "Proxy: refused a connection from another device. Only the first device that connected "
    "is accepted; restart Wiretrace, or pass --client <its IP address>."
)
MAX_WAITING = 8


class Resolved(NamedTuple):
    """One lookup result: the address text, and whether it must not be dialled for a remote client."""

    address: str
    blocked: bool


class Waiting(NamedTuple):
    """A refused address: when it was first and last refused (Unix seconds), and how many times."""

    address: str
    first_at: float
    last_at: float
    count: int


def normalize(host: str) -> str:
    """IPv4-mapped IPv6 as IPv4; a zone id is dropped. Anything else is returned unchanged."""
    text = host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return host
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    return str(mapped or address)


def parse_clients(entries: Sequence[str]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Each entry is an address or a range such as `127.0.0.0/8`. Raises ValueError on a bad entry."""
    return tuple(ipaddress.ip_network(normalize(entry), strict=False) for entry in entries if entry)


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


def pinnable(value: str) -> str | None:
    """The address normalized, or None when it is not one a session may start pinned to."""
    try:
        address = ipaddress.ip_address(normalize(value))
    except ValueError:
        return None
    if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
        return None
    return str(address)


def _loopback(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(normalize(address))
    except ValueError:
        return False
    return parsed.is_loopback


def _regular(client) -> bool:
    mode = getattr(client, "proxy_mode", None)
    return mode is None or isinstance(mode, mode_specs.RegularMode)


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
        self._clients: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
        self._pin = False
        self._waiting: dict[str, Waiting] = {}

    def load(self, loader) -> None:
        loader.add_option(
            "qa_proxy_clients", Sequence[str], [],
            "Client addresses or ranges always accepted, e.g. 127.0.0.0/8. "
            "The launcher includes loopback so the simulator and emulator work.",
        )
        loader.add_option(
            "qa_proxy_pin", bool, False,
            "Accept the first client that is not in qa_proxy_clients, and only that one afterwards.",
        )
        loader.add_option(
            "qa_proxy_pinned", str, "",
            "With qa_proxy_pin: the client accepted from the start, instead of the first one to connect.",
        )

    def configure(self, updated) -> None:
        try:
            self._clients = parse_clients(ctx.options.qa_proxy_clients)
        except ValueError:
            raise exceptions.OptionsError("qa_proxy_clients: each entry must be an IP address or range") from None
        pinned = None
        if ctx.options.qa_proxy_pinned:
            pinned = pinnable(ctx.options.qa_proxy_pinned)
            if pinned is None:
                raise exceptions.OptionsError(
                    "qa_proxy_pinned must be an IP address that is not loopback, link-local, unspecified or multicast")
        self._pin = bool(ctx.options.qa_proxy_pin)
        # Invariant 1: only the empty slot is taken; a running session never gets a second address.
        if self._pin and pinned is not None and self.pinned is None:
            self.pinned = pinned

    def _listed(self, ip: str) -> bool:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(address in network for network in self._clients)

    def client_connected(self, client) -> None:
        if not _regular(client):
            return
        peer = getattr(client, "peername", None)
        ip = normalize(peer[0]) if peer else ""
        if ip and (self._listed(ip) or ip == self.pinned):
            return
        if ip and self._pin and self.pinned is None:
            self.pinned = ip
            return
        # mitmproxy closes the connection when this is set. The text has no address.
        client.error = "connection refused"
        self.refused += 1
        if ip:
            self._record(ip)
        if self.refused == 1:
            print(REFUSAL, flush=True)

    def _record(self, ip: str) -> None:
        now = time.time()
        seen = self._waiting.get(ip)
        if seen is None:
            self._waiting[ip] = Waiting(ip, now, now, 1)
        else:
            self._waiting[ip] = seen._replace(last_at=now, count=seen.count + 1)
        while len(self._waiting) > MAX_WAITING:
            oldest = min(self._waiting.values(), key=lambda w: w.last_at)
            del self._waiting[oldest.address]

    def waiting(self) -> list[Waiting]:
        """The refused addresses, the most recently refused first."""
        return sorted(self._waiting.values(), key=lambda w: w.last_at, reverse=True)

    async def server_connect(self, data) -> None:
        if not _regular(data.client):
            return
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
