"""Proxy mode: accept only this Mac and the devices under test.

Loaded in proxy and both modes. `qa_proxy_clients` takes addresses and ranges; the
launcher always passes loopback (`127.0.0.0/8`, `::1`), because that is how the
iOS Simulator and the Android emulator connect. With `qa_proxy_pin`, the first
other address is accepted for the rest of the process and every further address is
closed. `qa_proxy_pinned` takes that place before the first connection: the window's
client switch starts a session pinned to the device it chose
(docs/specs/021-switch-to-another-phone.md).

The window can `allow` a refused address and `remove` an accepted one, the pinned one
included; at most MAX_ACCEPTED are accepted besides this Mac. `pin_used` becomes true
at the first pin and never goes back, so once the first device was accepted, every
other one has to be allowed, even after every device was removed. A removed device's
requests on a connection it still has open are killed
(docs/specs/022-more-devices-port-encrypted-hosts-breakpoints.md, slice A).

Refused addresses a session may be pinned to are kept in memory, at most MAX_WAITING,
for the window's banner. They are never printed.

A client that is not on this Mac cannot open a server connection to a loopback,
link-local or unspecified address. A server connection to the target host of a Map
remote rule is held to more, for every client, this Mac's included: no address on
this Mac's network and none of this Mac's own (spec 022, slice G). Value types stay
`NamedTuple`: a dataclass in a `-s` script fails to load (incident 2026-10-14).

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
from mitmproxy.net import local_ip
from mitmproxy.proxy import mode_specs

REFUSAL = (
    "Proxy: refused a connection from a device this session does not accept. Allow it in the "
    "Wiretrace window, restart Wiretrace, or pass --client <its IP address>."
)
MAX_WAITING = 8
MAX_ACCEPTED = 4
# Why `allow` or `remove` changed nothing. None of them names the address.
NOT_PINNING = "This session does not pin a device on the Wi-Fi proxy"
NOT_AN_ADDRESS = "Not a device address."
NOT_PINNABLE = "That address is always accepted or can never be: it is not a device on the network."
ALREADY_ACCEPTED = "That device is already accepted in this session."
NOT_WAITING = "That device is no longer waiting: ask it to connect again."
AT_MOST = (f"This session accepts {MAX_ACCEPTED} devices at most. "
           "Switch to it to start a session with only this device.")
NOT_ACCEPTED = "That device is not accepted in this session."
MAP_REFUSED = "Wiretrace refuses Map remote to an address on your network"
MAP_BLOCKED_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7"))
OWN_ADDRESSES_S = 30.0
# When this Mac's addresses were last looked up (monotonic), and what they were.
_own: list = [float("-inf"), frozenset()]


class Resolved(NamedTuple):
    """One lookup result: the address text, whether it must not be dialled for a remote client, and
    whether a Map remote rule may not send a request to it, for any client (spec 022, slice G)."""

    address: str
    blocked: bool
    map_blocked: bool = False


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


def _blocked_for_map(address: str) -> bool:
    """This Mac's network, as no Map remote target may be: loopback, private, shared, link-local,
    unique-local, unspecified and multicast addresses."""
    try:
        parsed = ipaddress.ip_address(normalize(address))
    except ValueError:
        return False
    return (parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified or parsed.is_multicast
            or any(parsed in network for network in MAP_BLOCKED_NETWORKS if network.version == parsed.version))


def own_addresses() -> frozenset[str]:
    """This Mac's own addresses on the network, looked up at most every OWN_ADDRESSES_S."""
    now = time.monotonic()
    if now - _own[0] >= OWN_ADDRESSES_S:
        found = set()
        for lookup in (local_ip.get_local_ip, local_ip.get_local_ip6):
            try:
                address = lookup()
            except OSError:
                address = None
            if address:
                found.add(normalize(address))
        _own[:] = [now, frozenset(found)]
    return _own[1]


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
    own = own_addresses()
    if literal is not None:
        return [Resolved(literal, _blocked(literal), _blocked_for_map(literal) or literal in own)]
    infos = await _lookup(host)
    found = []
    for item in infos:
        address = normalize(item[4][0])
        found.append(Resolved(address, _blocked(address), _blocked_for_map(address) or address in own))
    return found


class ProxyGuard:
    def __init__(self) -> None:
        self.pinned: str | None = None
        # Allowed from the window, in the order they were allowed.
        self.allowed: list[str] = []
        self.pin_used = False
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
        # Every options update runs this again: only the first pin of the process may take the place.
        if self._pin and pinned is not None and not self.pin_used:
            self.pinned = pinned
            self.pin_used = True

    def _listed(self, ip: str) -> bool:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(address in network for network in self._clients)

    def listed(self, ip: str) -> bool:
        """`ip` is in `qa_proxy_clients` (loopback, or a `--client` address)."""
        return self._listed(normalize(ip))

    def accepted(self) -> list[str]:
        """The devices accepted besides the listed ones: the pinned one, then the allowed ones in order."""
        return [address for address in (self.pinned, *self.allowed) if address is not None]

    def _admits(self, ip: str) -> bool:
        return self._listed(ip) or ip in self.accepted()

    def allow(self, address: str) -> str | None:
        """Accept a refused address from now on. None on success, otherwise why nothing changed."""
        if not self._pin:
            return NOT_PINNING
        try:
            ipaddress.ip_address(normalize(address))
        except ValueError:
            return NOT_AN_ADDRESS
        ip = pinnable(address)
        if ip is None:
            return NOT_PINNABLE
        if ip in self.accepted():
            return ALREADY_ACCEPTED
        if ip not in self._waiting:
            return NOT_WAITING
        if len(self.accepted()) >= MAX_ACCEPTED:
            return AT_MOST
        self.allowed.append(ip)
        del self._waiting[ip]
        return None

    def remove(self, address: str) -> str | None:
        """Refuse an accepted address from now on, its open connections' next requests included."""
        if not self._pin:
            return NOT_PINNING
        try:
            ipaddress.ip_address(normalize(address))
        except ValueError:
            return NOT_AN_ADDRESS
        ip = pinnable(address)
        if ip is None:
            return NOT_PINNABLE
        if ip == self.pinned:
            self.pinned = None
        elif ip in self.allowed:
            self.allowed.remove(ip)
        else:
            return NOT_ACCEPTED
        return None

    def client_connected(self, client) -> None:
        if not _regular(client):
            return
        peer = getattr(client, "peername", None)
        ip = normalize(peer[0]) if peer else ""
        if ip and self._admits(ip):
            return
        if ip and self._pin and not self.pin_used:
            self.pinned = ip
            self.pin_used = True
            return
        # mitmproxy closes the connection when this is set. The text has no address.
        client.error = "connection refused"
        self.refused += 1
        # The window offers a switch to each listed address, so only pinnable ones are listed.
        address = pinnable(ip) if ip else None
        if address:
            self._record(address)
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

    def requestheaders(self, flow) -> None:
        """A connection accepted before its device was removed: each further request on it is killed."""
        client = getattr(flow, "client_conn", None)
        if client is None or not _regular(client) or getattr(flow, "is_replay", None) == "request":
            return
        peer = getattr(client, "peername", None)
        ip = normalize(peer[0]) if peer else ""
        if not ip or not self._admits(ip):
            flow.kill()

    @staticmethod
    def _map_target(host: str) -> bool:
        try:
            targets = ctx.master.addons.get("qatools").map_targets()
        except Exception:
            return False
        return host.lower().rstrip(".") in targets

    async def server_connect(self, data) -> None:
        address = data.server.address
        # Before any client check: a Map remote target is refused this Mac's network for every client.
        if address and self._map_target(address[0]):
            try:
                results = await resolve(address[0])
            except OSError:
                results = []
            if any(item.map_blocked for item in results):
                data.server.error = MAP_REFUSED
                return
        if not _regular(data.client):
            return
        peer = getattr(data.client, "peername", None)
        if peer and _loopback(peer[0]):
            return
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
