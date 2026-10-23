"""Per device on the Wi-Fi proxy: when it first connected, its requests, and its failed TLS handshakes.

Kept in the window's process memory for the sidebar's device list, and dropped with it. The
address is the key: it reaches only the window's token-protected API and WebSocket
(docs/specs/022-more-devices-port-encrypted-hosts-breakpoints.md, slice A, invariant 6).
"""

from __future__ import annotations

from collections.abc import Sequence


class ClientStats:
    def __init__(self) -> None:
        # Address -> [first seen (Unix seconds) or None, requests, TLS failures], in the order first seen.
        self._by_address: dict[str, list] = {}

    def _entry(self, address: str) -> list:
        return self._by_address.setdefault(address, [None, 0, 0])

    def seen(self, address: str, when: float) -> bool:
        """Note a connection; True the first time this address connects."""
        entry = self._entry(address)
        if entry[0] is not None:
            return False
        entry[0] = when
        return True

    def request(self, address: str) -> None:
        """Called from the `request` hook only, which runs once per request."""
        self._entry(address)[1] += 1

    def tls_failure(self, address: str) -> None:
        self._entry(address)[2] += 1

    def addresses(self) -> list[str]:
        """The addresses that connected, in the order they first did."""
        return [address for address, entry in self._by_address.items() if entry[0] is not None]

    def payload(self, accepted: Sequence[str]) -> list[dict]:
        """One entry per address in `accepted`, in that order."""
        out = []
        for address in accepted:
            seen_at, requests, failures = self._by_address.get(address, (None, 0, 0))
            out.append({"address": address, "seen_at": seen_at, "requests": requests, "tls_failures": failures})
        return out
