"""Connections Wiretrace passes through without decrypting, for the window only.

docs/specs/022-more-devices-port-encrypted-hosts-breakpoints.md, slice C. A row holds the host,
port, device, times and the CONNECT request headers. Nothing here reads, keeps or forwards a byte
the connection carries (invariant 1); the TLS server name comes from the ClientHello mitmproxy
already peeked to decide the layer. Rows live in this process only (invariant 2).
"""

from __future__ import annotations

from typing import NamedTuple

from mitmproxy.net.tls import starts_like_tls_record
from mitmproxy.proxy.layers import TCPLayer
from mitmproxy.proxy.layers.tls import parse_client_hello

MAX_TUNNELS = 2_000
# CONNECTs whose tunnel has not been decided yet, per client connection.
MAX_PENDING = 256
OWN_HOSTS = ("qa-logs.internal", "mitm.it")
MASKED = ("proxy-authorization",)
MASK = "***"
MAX_HEADERS = 64
MAX_HEADER_CHARS = 1024
CONNECT_ANSWER = "HTTP/1.1 200 Connection established"


class Tunnel(NamedTuple):
    id: str
    client_id: str
    ts: float
    closed_at: float | None
    client: str | None
    host: str
    port: int | None
    tls: bool
    # "CONNECT" on the Wi-Fi proxy; "TLS", or "TCP" when it is not TLS, on WireGuard.
    method: str
    headers: tuple[tuple[str, str], ...] | None

    def payload(self) -> dict:
        return {"id": self.id, "ts": self.ts, "closed_at": self.closed_at, "client": self.client,
                "host": self.host, "port": self.port, "tls": self.tls, "method": self.method,
                "headers": [list(h) for h in self.headers] if self.headers is not None else None,
                "answer": CONNECT_ANSWER if self.method == "CONNECT" else None}


class _Connect(NamedTuple):
    host: str
    port: int
    headers: tuple[tuple[str, str], ...]


def masked_headers(fields) -> tuple[tuple[str, str], ...]:
    out = []
    for name, value in list(fields.items(multi=True))[:MAX_HEADERS]:
        shown = MASK if name.lower() in MASKED else value
        out.append((name[:MAX_HEADER_CHARS], shown[:MAX_HEADER_CHARS]))
    return tuple(out)


def server_name(data: bytes) -> str | None:
    """The SNI of a complete ClientHello at the start of `data`, or None."""
    if not starts_like_tls_record(data):
        return None
    try:
        hello = parse_client_hello(data)
    except ValueError:
        return None
    return hello.sni if hello is not None and hello.sni else None


class Tunnels:
    def __init__(self, cap: int = MAX_TUNNELS) -> None:
        self.cap = cap
        self.rows: dict[str, Tunnel] = {}
        self._open: dict[str, str] = {}
        self._connects: dict[str, _Connect] = {}
        self._next = 0

    def connect(self, flow) -> None:
        """`http_connect`: the CONNECT target and headers, until the tunnel's layer is decided."""
        client = getattr(flow, "client_conn", None)
        request = getattr(flow, "request", None)
        if client is None or request is None:
            return
        self._connects[client.id] = _Connect(request.host, request.port, masked_headers(request.headers))
        while len(self._connects) > MAX_PENDING:
            del self._connects[next(iter(self._connects))]

    def layer(self, nextlayer, device: str | None, now: float) -> Tunnel | None:
        """`next_layer`, after mitmproxy's own NextLayer decided: a new row for a passthrough TCP layer."""
        layer = nextlayer.layer
        if not isinstance(layer, TCPLayer) or layer.flow is not None:
            return None
        client = nextlayer.context.client
        if client.id in self._open:
            return None
        connect = self._connects.pop(client.id, None)
        data = nextlayer.data_client()
        tls = starts_like_tls_record(data)
        address = nextlayer.context.server.address
        if connect is not None:
            host, port, method, headers = connect.host, connect.port, "CONNECT", connect.headers
        else:
            name = server_name(data) or client.sni
            host = name or (str(address[0]) if address else "")
            port = address[1] if address else None
            method, headers = ("TLS" if tls else "TCP"), None
        if not host or host.lower().rstrip(".") in OWN_HOSTS:
            return None
        self._next += 1
        row = Tunnel(f"tunnel-{self._next}", client.id, now, None, device, host, port, tls, method, headers)
        self.rows[row.id] = row
        self._open[client.id] = row.id
        while len(self.rows) > self.cap:
            dropped = self.rows.pop(next(iter(self.rows)))
            self._open.pop(dropped.client_id, None)
        return row

    def closed(self, client_id: str, now: float) -> Tunnel | None:
        """The client or the server side ended: the row gets its close time once."""
        self._connects.pop(client_id, None)
        row_id = self._open.pop(client_id, None)
        row = self.rows.get(row_id) if row_id else None
        if row is None:
            return None
        row = row._replace(closed_at=now)
        self.rows[row.id] = row
        return row

    def payload(self) -> list[dict]:
        return [row.payload() for row in self.rows.values()]

    def hosts(self) -> set[str]:
        return {row.host for row in self.rows.values()}
