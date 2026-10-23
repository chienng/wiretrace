"""The window's per-device counts (spec 022, slice A)."""

from addons.client_stats import ClientStats


def test_payload_follows_the_order_it_is_given_and_lists_devices_not_seen_yet():
    stats = ClientStats()
    assert stats.seen("192.0.2.11", 100.0) is True
    assert stats.seen("192.0.2.10", 101.0) is True
    assert stats.seen("192.0.2.11", 102.0) is False
    stats.request("192.0.2.11")
    stats.request("192.0.2.11")
    stats.tls_failure("192.0.2.10")
    assert stats.payload(["192.0.2.10", "192.0.2.11", "192.0.2.12"]) == [
        {"address": "192.0.2.10", "seen_at": 101.0, "requests": 0, "tls_failures": 1},
        {"address": "192.0.2.11", "seen_at": 100.0, "requests": 2, "tls_failures": 0},
        {"address": "192.0.2.12", "seen_at": None, "requests": 0, "tls_failures": 0},
    ]


def test_addresses_are_the_connected_ones_in_the_order_first_seen():
    stats = ClientStats()
    stats.request("192.0.2.9")
    stats.seen("192.0.2.11", 100.0)
    stats.seen("192.0.2.10", 101.0)
    assert stats.addresses() == ["192.0.2.11", "192.0.2.10"]


def test_counts_stay_after_a_device_leaves_the_list_and_comes_back():
    stats = ClientStats()
    stats.seen("192.0.2.11", 100.0)
    stats.request("192.0.2.11")
    assert stats.payload([]) == []
    assert stats.payload(["192.0.2.11"])[0]["requests"] == 1
