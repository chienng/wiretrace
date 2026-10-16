"""The menu bar model: titles, rows and the stop decision. No AppKit."""

import json
from pathlib import Path

import pytest

from menubar import (
    FRESH_S,
    LIVE,
    STALE,
    STARTING,
    STOPPING,
    MenuView,
    is_fresh,
    read_status,
    render,
    stop_effect,
    window_url,
)


def status(**over) -> dict:
    base = {
        "v": 1, "updated_at": 1_000.0, "started_at": 900.0, "preset": "staging",
        "target": "android", "mode": "wireguard", "device_state": "streaming",
        "device_model": "Pixel 8", "requests": 248, "errors": 6, "rules_on": 2,
        "last_error": "flow-1",
    }
    base.update(over)
    return base


def labels(view: MenuView) -> list[str]:
    return [row.label for row in view.rows]


def row(view: MenuView, label: str):
    return next(item for item in view.rows if item.label == label)


def enabled_actions(view: MenuView) -> set[str]:
    return {item.action for item in view.rows if item.action and item.enabled}


def test_starting_until_a_status_file_has_been_read():
    view = render(None, 1_000.0, False)
    assert view.state == STARTING
    assert view.title == "Wiretrace"
    assert labels(view) == ["Starting…", "Open Wiretrace", "Quit"]
    assert enabled_actions(view) == {"open", "quit"}


def test_live_menu_matches_the_counts_and_hides_a_zero():
    view = render(status(), 1_000.0, False)
    assert view.state == LIVE
    assert view.title == "● Wiretrace · 6"
    assert row(view, "Wiretrace").value == "Recording"
    assert row(view, "Preset").value == "staging"
    assert row(view, "Device").value == "Android · WireGuard · Pixel 8"
    assert row(view, "Duration").value == "00:01:40"
    assert (row(view, "requests").value, row(view, "errors").value, row(view, "rules on").value) == ("248", "6", "2")
    assert row(view, "errors").alert is True
    assert enabled_actions(view) == {"open", "last_error", "stop", "quit"}
    assert row(view, "Open Wiretrace").shortcut == "o"
    assert row(view, "Show last error").shortcut == "r"
    assert view.last_error == "flow-1"


def test_zero_errors_has_no_count_in_the_title_and_show_last_error_is_grey():
    view = render(status(errors=0, last_error=None), 1_000.0, False)
    assert view.title == "● Wiretrace"
    assert "· 0" not in view.title
    assert row(view, "errors").alert is False
    assert row(view, "Show last error").enabled is False
    assert "last_error" not in enabled_actions(view)
    assert view.last_error is None


@pytest.mark.parametrize("model", [None, "", "  "])
def test_a_missing_device_model_is_left_out(model):
    view = render(status(device_model=model), 1_000.0, False)
    assert row(view, "Device").value == "Android · WireGuard"


def test_other_targets_and_proxy_mode():
    assert row(render(status(target="ios", mode="proxy", device_model="iPhone"), 1_000.0, False), "Device").value == (
        "iOS · Proxy · iPhone")


def test_updated_at_exactly_five_seconds_old_is_live_and_older_is_stale():
    fresh = status(updated_at=1_000.0)
    assert is_fresh(fresh, 1_000.0 + FRESH_S)
    live = render(fresh, 1_000.0 + FRESH_S, False)
    assert live.state == LIVE and live.title == "● Wiretrace · 6"
    stale = render(fresh, 1_000.0 + FRESH_S + 0.001, False)
    assert stale.state == STALE
    assert stale.title == "Wiretrace · ?"
    assert labels(stale) == ["No status from Wiretrace", "Open Wiretrace", "Stop session", "Quit"]
    assert enabled_actions(stale) == {"open", "stop", "quit"}


def test_a_file_that_vanished_after_it_was_seen_is_stale_and_recovers():
    stale = render(None, 1_000.0, False, seen=True)
    assert stale.state == STALE and stale.title == "Wiretrace · ?"
    live = render(status(), 1_000.0, False, seen=True)
    assert live.state == LIVE


def test_stopping_shows_only_that_line_and_does_not_go_back():
    view = render(status(), 1_000.0, True, seen=True)
    assert view.state == STOPPING
    assert view.title == "Wiretrace · stopping"
    assert labels(view) == ["Wiretrace · stopping"]
    assert enabled_actions(view) == set()
    assert render(None, 1_000.0, True).state == STOPPING


def test_stop_signals_once_and_never_when_the_parent_is_not_the_launcher():
    assert stop_effect(5, 5, False) == "signal"
    assert stop_effect(5, 5, True) == "none"
    assert stop_effect(1, 5, False) == "exit"
    assert stop_effect(1, 5, True) == "exit"


def test_the_open_urls_carry_the_token_and_the_flow_only_as_a_fragment():
    assert window_url(8081, "tok") == "http://127.0.0.1:8081/?token=tok"
    assert window_url(8081, "tok", "flow/1") == "http://127.0.0.1:8081/?token=tok#flow=flow%2F1"


def test_read_status_rejects_anything_that_is_not_version_1(tmp_path: Path):
    path = tmp_path / ".status.json"
    assert read_status(path) is None
    path.write_text("{", encoding="utf-8")
    assert read_status(path) is None
    path.write_text(json.dumps({"v": 2}), encoding="utf-8")
    assert read_status(path) is None
    path.write_text(json.dumps(status()), encoding="utf-8")
    assert read_status(path)["preset"] == "staging"
    path.write_bytes(b"{" + b"x" * 70_000)
    assert read_status(path) is None
