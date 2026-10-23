import ssl
from types import SimpleNamespace

import pytest
from mitmproxy import options
from mitmproxy.proxy import layers
from mitmproxy.proxy.context import Context
from mitmproxy.test import tflow, tutils

from addons import tunnels

# Spec 022, slice C.


def client_hello(server_name: str) -> bytes:
    """The first bytes a TLS client sends to `server_name`."""
    context = ssl.create_default_context()
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    tls = context.wrap_bio(incoming, outgoing, server_hostname=server_name)
    with pytest.raises(ssl.SSLWantReadError):
        tls.do_handshake()
    return outgoing.read()


def bare_client():
    client = tflow.tclient_conn()
    client.sni = None
    return client


def decided(data: bytes = b"", *, ignore=True, address=("203.0.113.9", 443), client=None, layer=True):
    client = client or bare_client()
    context = Context(client, options.Options())
    context.server = tflow.tserver_conn()
    context.server.address = address
    chosen = layers.TCPLayer(context, ignore=ignore) if layer else None
    return SimpleNamespace(layer=chosen, context=context, data_client=lambda: data, data_server=lambda: b"")


def connect_flow(host: str, client=None, headers=()):
    flow = tflow.tflow()
    flow.client_conn = client or flow.client_conn
    flow.request = tutils.treq(method=b"CONNECT", host=host, port=443, path=b"", authority=f"{host}:443".encode(),
                               headers=((b"Host", f"{host}:443".encode()), *headers))
    return flow


def test_a_connect_tunnel_is_recorded_with_its_host_and_masked_headers():
    rows = tunnels.Tunnels()
    client = bare_client()
    rows.connect(connect_flow("cdn.example.net", client, ((b"Proxy-Authorization", b"Basic c2VjcmV0"),
                                                          (b"User-Agent", b"App/1.0"))))
    row = rows.layer(decided(client_hello("cdn.example.net"), client=client, address=("cdn.example.net", 443)),
                     "192.0.2.71", 100.0)
    assert row is not None
    assert (row.method, row.host, row.port, row.tls, row.client, row.ts, row.closed_at) == (
        "CONNECT", "cdn.example.net", 443, True, "192.0.2.71", 100.0, None)
    assert row.headers == (("Host", "cdn.example.net:443"), ("Proxy-Authorization", "***"), ("User-Agent", "App/1.0"))
    payload = row.payload()
    assert payload["answer"] == "HTTP/1.1 200 Connection established"
    assert "c2VjcmV0" not in repr(payload)


def test_a_wireguard_tunnel_takes_the_server_name_from_the_client_hello():
    rows = tunnels.Tunnels()
    row = rows.layer(decided(client_hello("images.example-cdn.com")), "wireguard", 1.0)
    assert (row.method, row.host, row.port, row.tls, row.headers) == ("TLS", "images.example-cdn.com", 443, True, None)
    assert row.payload()["answer"] is None


def test_without_a_connect_or_a_server_name_the_host_is_the_address():
    rows = tunnels.Tunnels()
    row = rows.layer(decided(b"\x00\x01binary", address=("203.0.113.9", 5222)), "wireguard", 1.0)
    assert (row.method, row.host, row.port, row.tls) == ("TCP", "203.0.113.9", 5222, False)


def test_the_client_sni_counts_when_the_hello_is_not_in_the_data():
    client = tflow.tclient_conn()
    client.sni = "push.example.org"
    row = tunnels.Tunnels().layer(decided(b"", client=client), "wireguard", 1.0)
    assert row.host == "push.example.org"


@pytest.mark.parametrize("host", ["qa-logs.internal", "mitm.it", "MITM.IT"])
def test_wiretraces_own_hosts_are_never_listed(host):
    rows = tunnels.Tunnels()
    client = bare_client()
    rows.connect(connect_flow(host, client))
    assert rows.layer(decided(client=client, address=(host, 443)), None, 1.0) is None
    assert rows.rows == {}


def test_only_a_passthrough_tcp_layer_is_a_row():
    rows = tunnels.Tunnels()
    assert rows.layer(decided(ignore=False), None, 1.0) is None
    assert rows.layer(decided(layer=False), None, 1.0) is None
    assert rows.rows == {}


def test_a_connection_is_one_row_and_closing_sets_the_time_once():
    rows = tunnels.Tunnels()
    client = bare_client()
    first = rows.layer(decided(client=client), None, 1.0)
    assert rows.layer(decided(client=client), None, 2.0) is None
    closed = rows.closed(client.id, 5.0)
    assert closed.id == first.id and closed.closed_at == 5.0
    assert rows.closed(client.id, 6.0) is None
    assert rows.rows[first.id].closed_at == 5.0
    assert rows.closed("unknown", 7.0) is None


def test_the_list_keeps_the_newest_2000():
    rows = tunnels.Tunnels()
    for i in range(tunnels.MAX_TUNNELS + 5):
        rows.layer(decided(), None, float(i))
    assert len(rows.rows) == tunnels.MAX_TUNNELS
    assert [r.ts for r in rows.rows.values()][:2] == [5.0, 6.0]


def test_pending_connects_are_bounded():
    rows = tunnels.Tunnels()
    for _ in range(tunnels.MAX_PENDING + 10):
        rows.connect(connect_flow("cdn.example.net"))
    assert len(rows._connects) == tunnels.MAX_PENDING


def test_a_row_holds_no_payload():
    assert set(tunnels.Tunnel._fields) == {"id", "client_id", "ts", "closed_at", "client", "host", "port", "tls",
                                           "method", "headers"}
    row = tunnels.Tunnels().layer(decided(client_hello("cdn.example.net")), None, 1.0)
    assert set(row.payload()) == {"id", "ts", "closed_at", "client", "host", "port", "tls", "method", "headers",
                                  "answer"}
    assert "client_id" not in row.payload()
