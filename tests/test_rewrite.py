import json

import pytest
from mitmproxy import http

from addons import rewrite


def ops(*raw):
    parsed, problem = rewrite.parse_ops(list(raw))
    assert problem is None, problem
    return parsed


def header(kind, name, value="", on="request"):
    out = {"on": on, "op": kind, "name": name}
    if kind != "remove_header":
        out["value"] = value
    return out


def field(kind, path, value=None, on="response"):
    out = {"on": on, "op": kind, "path": path}
    if kind == "set_json":
        out["value"] = value
    return out


@pytest.mark.parametrize("text, parts", [
    ("data.user.isPremium", ("data", "user", "isPremium")),
    ("items[0].price", ("items", 0, "price")),
    ('["a.b"].c', ("a.b", "c")),
    ('data["x[1]"][12]', ("data", "x[1]", 12)),
    ("[3]", (3,)),
    ("a-b.c_d", ("a-b", "c_d")),
])
def test_paths_parse_dots_indexes_and_quoted_keys(text, parts):
    assert rewrite.parse_path(text) == parts


@pytest.mark.parametrize("text", ["", ".a", "a.", "a..b", "a[01]", "a[-1]", "a[x]", 'a["b"', "a]b", "a b\"c",
                                  "a[0]b", "x" * 257, ".".join(["k"] * 21), 7])
def test_paths_that_do_not_parse(text):
    assert rewrite.parse_path(text) is None


def test_header_ops_are_case_insensitive_and_handle_several_values():
    headers = http.Headers([(b"X-Flag", b"a"), (b"x-flag", b"b"), (b"Accept", b"*/*")])
    results = rewrite.apply_header_ops(headers, ops(
        header("set_header", "x-FLAG", "on"), header("add_header", "X-Extra", "1"), header("add_header", "x-extra", "2"),
        header("remove_header", "accept"), header("remove_header", "x-missing")))
    assert headers.get_all("x-flag") == ["on"] and headers.get_all("X-Extra") == ["1", "2"]
    assert "Accept" not in headers
    assert [(r.applied, r.reason) for r in results] == [(True, "")] * 4 + [(False, "not found")]


def test_json_ops_set_add_and_remove_in_order_and_write_back_compactly():
    body = '{"data": {"user": {"isPremium": false, "price": 1.50}, "items": [{"id": 1}, {"id": 2}]}, "z": 0}'
    new, results = rewrite.apply_json_ops(body, ops(
        field("set_json", "data.user.isPremium", "true"),
        field("set_json", "data.user.badge", '{"level": 2}'),
        field("set_json", "data.items[1].id", '"two"'),
        field("remove_json", "data.items[0]"),
        field("remove_json", "z")))
    assert [r.applied for r in results] == [True] * 5
    assert new == '{"data":{"user":{"isPremium":true,"price":1.5,"badge":{"level":2}},"items":[{"id":"two"}]}}'


@pytest.mark.parametrize("path", ["data.missing.flag", "data.items[5].id", "data.items[2]", "data.user[0]",
                                  "data.items.id"])
def test_a_missing_parent_or_item_is_skipped_and_never_created(path):
    body = '{"data": {"user": {}, "items": [{"id": 1}, {"id": 2}]}}'
    new, results = rewrite.apply_json_ops(body, ops(field("set_json", path, "1")))
    assert new is None and [(r.applied, r.reason) for r in results] == [(False, "not found")]


def test_removing_what_is_not_there_is_skipped_and_other_changes_still_apply():
    new, results = rewrite.apply_json_ops('{"a": 1}', ops(field("remove_json", "b"), field("set_json", "a", "2")))
    assert new == '{"a":2}' and [r.applied for r in results] == [False, True]


def test_a_rule_value_is_copied_into_each_body():
    changes = ops(field("set_json", "a", '{"n": 1}'), field("set_json", "a.n", "2"))
    first, _ = rewrite.apply_json_ops('{"a": 0}', changes)
    second, _ = rewrite.apply_json_ops('{"b": 0}', changes[:1])
    assert json.loads(first) == {"a": {"n": 2}} and json.loads(second) == {"b": 0, "a": {"n": 1}}


@pytest.mark.parametrize("body", ["<html>", '{"a": NaN}', "", '{"a": 1'])
def test_a_body_that_is_not_strict_json_skips_every_change(body):
    new, results = rewrite.apply_json_ops(body, ops(field("set_json", "a", "1"), field("remove_json", "b")))
    assert new is None and [r.reason for r in results] == ["body is not JSON"] * 2


@pytest.mark.parametrize("name", ["Host", "content-length", "Transfer-Encoding", "Connection", "keep-alive", "TE",
                                  "Trailer", "Upgrade", "Proxy-Authorization", "proxy-anything", ":authority",
                                  "two words", "", "x" * 257, 7])
def test_every_refused_header_name(name):
    _, problem = rewrite.parse_ops([header("set_header", name, "v")])
    assert problem is not None and problem[0] == "ops.0.name"


@pytest.mark.parametrize("value", ["a\r\nb", "a\nb", "a\0b", "x" * 4097, 5, None])
def test_every_refused_header_value(value):
    _, problem = rewrite.parse_ops([header("add_header", "X-A", value)])
    assert problem is not None and problem[0] == "ops.0.value"


@pytest.mark.parametrize("value", ["true,", "NaN", "{'a': 1}", "", '"' + "x" * (64 << 10) + '"', 1])
def test_every_refused_json_value(value):
    _, problem = rewrite.parse_ops([field("set_json", "a", value)])
    assert problem is not None and problem[0] == "ops.0.value"


@pytest.mark.parametrize("raw, where", [
    ([], "ops"), ([header("set_header", "X-A", "v")] * 21, "ops"), ("x", "ops"), ([7], "ops.0"),
    ([{"on": "request", "op": "replace"}], "ops.0.op"), ([{**header("set_header", "X-A", "v"), "extra": 1}], "ops.0.extra"),
    ([{"on": "request", "op": "set_json", "path": "a"}], "ops.0.value"), ([header("set_header", "X-A", "v", on="both")], "ops.0.on"),
    ([field("remove_json", "a..b")], "ops.0.path"),
])
def test_the_list_and_each_change_shape(raw, where):
    _, problem = rewrite.parse_ops(raw)
    assert problem is not None and problem[0] == where


def test_messages_never_hold_a_value():
    for raw in ([header("set_header", "Host", "secret-value-1")], [header("add_header", "X-A", "secret\nvalue")],
                [field("set_json", "a", "secret-value-2")]):
        _, problem = rewrite.parse_ops(raw)
        assert "secret" not in problem[1]


def test_json_bodies_are_recognised_by_type_or_by_their_first_character():
    assert rewrite.is_json_body("application/vnd.api+json; charset=utf-8", "x")
    assert rewrite.is_json_body("text/plain", '  [1, 2]')
    assert not rewrite.is_json_body("text/html", "<html>")
