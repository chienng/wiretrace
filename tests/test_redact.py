import json

import pytest

from cli import redact
from cli.preset import Preset
from cli.redact import MASK, Rules, mask_log_line, mask_text, redact_body, redact_har, redact_json_text, redact_url

RULES = redact.rules_for(None)


def har(request=None, response=None, **entry) -> dict:
    parts = {}
    if request is not None:
        parts["request"] = request
    if response is not None:
        parts["response"] = response
    return {"log": {"entries": [{**parts, **entry}]}}


def masked(request=None, response=None, rules=RULES, **entry) -> dict:
    result, _ = redact_har(har(request, response, **entry), rules)
    return result["log"]["entries"][0]


def header_values(headers: list[dict]) -> dict:
    return {h["name"]: h["value"] for h in headers}


# Rules

def test_defaults_without_a_preset():
    assert RULES.headers == redact.DEFAULT_HEADERS and RULES.fields == redact.DEFAULT_FIELDS


def test_preset_adds_to_the_defaults():
    rules = redact.rules_for(Preset(name="p", api_hosts=("a.example.com",),
                                    redact_headers=("X-Api-Key",), redact_fields=("otp",)))
    assert set(rules.headers) == {*redact.DEFAULT_HEADERS, "X-Api-Key"}
    assert set(rules.fields) == {*redact.DEFAULT_FIELDS, "otp"}


def test_defaults_are_kept_when_the_preset_lists_none():
    rules = redact.rules_for(Preset(name="p", api_hosts=("a.example.com",)))
    assert rules == RULES


def test_preset_repeating_a_default_does_not_duplicate_it():
    rules = redact.rules_for(Preset(name="p", api_hosts=("a.example.com",),
                                    redact_headers=("authorization",), redact_fields=("Access-Token",)))
    assert len(rules.headers) == len(redact.DEFAULT_HEADERS) and len(rules.fields) == len(redact.DEFAULT_FIELDS)


def test_redact_module_does_not_import_mitmproxy():
    import subprocess
    import sys

    code = "import sys; import cli.redact; sys.exit('mitmproxy' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# HAR: every location

def test_request_and_response_headers():
    entry = masked(
        request={"headers": [{"name": "Authorization", "value": "Bearer fake-a"},
                             {"name": "proxy-authorization", "value": "fake-b"},
                             {"name": "COOKIE", "value": "sid=fake-c"},
                             {"name": "Accept", "value": "*/*"}]},
        response={"headers": [{"name": "Set-Cookie", "value": "sid=fake-d; Path=/"},
                              {"name": "Content-Type", "value": "application/json"}]},
    )
    assert header_values(entry["request"]["headers"]) == {
        "Authorization": MASK, "proxy-authorization": MASK, "COOKIE": MASK, "Accept": "*/*"}
    assert header_values(entry["response"]["headers"]) == {"Set-Cookie": MASK, "Content-Type": "application/json"}


def test_every_cookie_value_is_masked():
    entry = masked(request={"cookies": [{"name": "sid", "value": "fake-1"}]},
                   response={"cookies": [{"name": "theme", "value": "dark", "path": "/"}]})
    assert entry["request"]["cookies"] == [{"name": "sid", "value": MASK}]
    assert entry["response"]["cookies"] == [{"name": "theme", "value": MASK, "path": "/"}]


def test_json_request_and_response_bodies_at_any_depth():
    body = json.dumps({"user": "ann", "password": "fake-pw", "data": [{"deep": {"refresh_token": "fake-r"}}]})
    entry = masked(request={"postData": {"mimeType": "application/json", "text": body}},
                   response={"content": {"mimeType": "application/json",
                                         "text": json.dumps({"tokens": [{"id_token": "fake-i"}], "ok": True})}})
    assert json.loads(entry["request"]["postData"]["text"]) == {
        "user": "ann", "password": MASK, "data": [{"deep": {"refresh_token": MASK}}]}
    assert json.loads(entry["response"]["content"]["text"]) == {"tokens": [{"id_token": MASK}], "ok": True}


def test_form_body_text_and_params():
    entry = masked(request={"postData": {
        "mimeType": "application/x-www-form-urlencoded; charset=utf-8",
        "text": "user=ann&password=fake-pw&client_secret=fake-s&x=1",
        "params": [{"name": "user", "value": "ann"}, {"name": "password", "value": "fake-pw"}]}})
    post = entry["request"]["postData"]
    assert post["text"] == "user=ann&password=***&client_secret=***&x=1"
    assert post["params"] == [{"name": "user", "value": "ann"}, {"name": "password", "value": MASK}]


def test_query_string_and_url():
    entry = masked(request={
        "url": "https://api.example.com/a?page=2&access_token=fake-t",
        "queryString": [{"name": "page", "value": "2"}, {"name": "access_token", "value": "fake-t"}]})
    assert entry["request"]["url"] == "https://api.example.com/a?page=2&access_token=***"
    assert entry["request"]["queryString"] == [{"name": "page", "value": "2"}, {"name": "access_token", "value": MASK}]


def test_location_header_and_redirect_url_query_and_fragment():
    entry = masked(response={
        "headers": [{"name": "Location", "value": "https://app.example.com/cb?code=1&id_token=fake-i#access_token=fake-a&s=x"}],
        "redirectURL": "https://app.example.com/cb?code=1&id_token=fake-i#access_token=fake-a&s=x"})
    expected = "https://app.example.com/cb?code=1&id_token=***#access_token=***&s=x"
    assert entry["response"]["headers"][0]["value"] == expected
    assert entry["response"]["redirectURL"] == expected


def test_websocket_text_is_masked_and_binary_is_not():
    entry = masked(_webSocketMessages=[
        {"type": "send", "opcode": 1, "data": json.dumps({"password": "fake-pw", "n": 1})},
        {"type": "send", "opcode": 1, "data": "not json password=fake"},
        {"type": "receive", "opcode": 2, "data": "eyJwYXNzd29yZCI6ImZha2UifQ=="},
    ])
    first, second, binary = entry["_webSocketMessages"]
    assert json.loads(first["data"]) == {"password": MASK, "n": 1}
    assert second["data"] == "not json password=fake"
    assert binary["data"] == "eyJwYXNzd29yZCI6ImZha2UifQ=="


# Names

@pytest.mark.parametrize("key", ["access_token", "accessToken", "AccessToken", "access-token", "ACCESS_TOKEN"])
def test_field_names_match_ignoring_case_underscore_and_dash(key):
    text, count = redact_json_text(json.dumps({key: "fake", "other": "keep"}), RULES)
    assert json.loads(text) == {key: MASK, "other": "keep"} and count == 1


@pytest.mark.parametrize("value", ["fake", 12345, True, None, {"a": 1}, ["x"]])
def test_a_non_string_value_is_masked_too(value):
    text, _ = redact_json_text(json.dumps({"password": value}), RULES)
    assert json.loads(text) == {"password": MASK}


def test_preset_additions_are_masked_and_defaults_stay():
    rules = redact.rules_for(Preset(name="p", api_hosts=("a.example.com",),
                                    redact_headers=("X-Api-Key",), redact_fields=("login_token",)))
    entry = masked(request={"headers": [{"name": "x-api-key", "value": "fake"}, {"name": "Cookie", "value": "fake"}],
                            "postData": {"text": json.dumps({"loginToken": "fake", "password": "fake"})}},
                   rules=rules)
    assert header_values(entry["request"]["headers"]) == {"x-api-key": MASK, "Cookie": MASK}
    assert json.loads(entry["request"]["postData"]["text"]) == {"loginToken": MASK, "password": MASK}


# Left as it was

def test_non_json_body_is_unchanged():
    text = "<xml><password>fake-pw</password></xml>"
    entry = masked(request={"postData": {"mimeType": "application/xml", "text": text}},
                   response={"content": {"mimeType": "text/plain", "text": "password=fake-pw"}})
    assert entry["request"]["postData"]["text"] == text
    assert entry["response"]["content"]["text"] == "password=fake-pw"


def test_base64_content_is_unchanged():
    encoded = "eyJwYXNzd29yZCI6ImZha2UifQ=="
    content = {"mimeType": "application/octet-stream", "text": encoded, "encoding": "base64"}
    assert masked(response={"content": content})["response"]["content"] == content


def test_json_with_nothing_to_mask_keeps_its_exact_text():
    text = '{ "a" :   1,\n "b":[1,  2] , "caf\\u00e9": "x" }'
    assert redact_json_text(text, RULES) == (text, 0)
    assert redact_body(text, "application/json", RULES) == (text, 0)


def test_form_body_with_nothing_to_mask_keeps_its_exact_text():
    text = "a=1&b=%20x+y&c"
    assert redact_body(text, "application/x-www-form-urlencoded", RULES) == (text, 0)


def test_unchanged_url_is_returned_as_it_was():
    url = "https://api.example.com/a?x=%20y&z"
    assert redact_url(url, RULES) == (url, 0)


def test_masking_keeps_non_ascii_text():
    text, _ = redact_json_text(json.dumps({"name": "Nguyễn", "password": "x"}, ensure_ascii=False), RULES)
    assert "Nguyễn" in text


def test_missing_keys_are_tolerated():
    assert redact_har({}, RULES) == ({}, 0)
    assert redact_har({"log": {}}, RULES) == ({"log": {}}, 0)
    result, count = redact_har({"log": {"entries": [{}]}}, RULES)
    assert result == {"log": {"entries": [{}]}} and count == 0
    entry = masked(request={"headers": [{"name": "Cookie", "value": "x"}]}, response={"status": 0, "content": {}})
    assert entry["response"] == {"status": 0, "content": {}}
    assert masked(response={"headers": [], "cookies": []})["response"] == {"headers": [], "cookies": []}


def test_input_is_not_modified_and_count_is_reported():
    original = har(request={"headers": [{"name": "Authorization", "value": "fake"}],
                            "url": "https://a.example.com/?password=fake"})
    before = json.dumps(original)
    result, count = redact_har(original, RULES)
    assert json.dumps(original) == before and count == 2
    assert result != original


# Idempotence

def test_redact_har_is_idempotent():
    document = har(
        request={"url": "https://a.example.com/?password=fake#id_token=x",
                 "headers": [{"name": "Authorization", "value": "fake"}],
                 "cookies": [{"name": "s", "value": "fake"}],
                 "queryString": [{"name": "password", "value": "fake"}],
                 "postData": {"mimeType": "application/x-www-form-urlencoded", "text": "password=fake&a=1",
                              "params": [{"name": "password", "value": "fake"}]}},
        response={"headers": [{"name": "Location", "value": "https://a.example.com/?access_token=fake"}],
                  "content": {"text": json.dumps({"accessToken": "fake", "list": [{"password": 1}]})}},
        _webSocketMessages=[{"opcode": 1, "data": '{"password": "fake"}'}])
    once, count = redact_har(document, RULES)
    twice, again = redact_har(once, RULES)
    assert twice == once and count > 0 and again == 0


LOG_SAMPLES = [
    "Authorization: Bearer abc.def-ghi", "Set-Cookie: a=b; c=d", "login password=fake&x=1",
    '{"accessToken": "a\\"b", "refresh-token": 5, "n": null}', "token Bearer abc.def== end",
    'password: "two words"', "password='x y' ok", "client_secret=***", '"password": "***"',
    "nothing to see here",
]


@pytest.mark.parametrize("text", LOG_SAMPLES)
def test_mask_text_is_idempotent(text):
    once = mask_text(text, RULES)
    assert mask_text(once, RULES) == once


# mask_text

def test_header_line_is_masked_to_the_end_of_the_line():
    assert mask_text("sent Authorization: Bearer a b c\nnext", RULES) == "sent Authorization: ***\nnext"
    assert mask_text("authorization :   Basic fake", RULES) == "authorization: ***"


def test_set_cookie_value_with_attributes():
    assert mask_text("Set-Cookie: a=b; c=d", RULES) == "Set-Cookie: ***"


def test_bearer_token():
    assert mask_text("got Bearer abc.def-ghi_jkl+/= then", RULES) == "got Bearer *** then"
    assert mask_text("bearer abc", RULES) == "Bearer ***"


def test_json_pairs_in_text_for_strings_numbers_and_literals():
    text = '{"password": "a \\"b\\" c", "id-token":12.5, "refresh_token" : null, "keep": "x"}'
    assert mask_text(text, RULES) == (
        '{"password": "***", "id-token":"***", "refresh_token" : "***", "keep": "x"}')


def test_json_pair_for_a_header_name():
    assert mask_text('{"Authorization": "Bearer fake"}', RULES) == '{"Authorization": "***"}'


def test_key_value_pairs():
    assert mask_text("password=fake&user=ann", RULES) == "password=***&user=ann"
    assert mask_text("access_token: fake, next", RULES) == "access_token: ***, next"
    assert mask_text("AccessToken=fake;", RULES) == "AccessToken=***;"
    assert mask_text("access-token = fake", RULES) == "access-token = ***"


def test_quoted_value_is_masked_up_to_its_closing_quote():
    assert mask_text('password="two words" next', RULES) == 'password="***" next'


def test_preset_names_apply_to_text():
    rules = redact.rules_for(Preset(name="p", api_hosts=("a.example.com",),
                                    redact_headers=("X-Api-Key",), redact_fields=("otp",)))
    assert mask_text("X-Api-Key: fake otp=123456", rules) == "X-Api-Key: ***"
    assert mask_text("otp=123456 ok", rules) == "otp=*** ok"


def test_no_change_gives_the_same_text():
    text = "GET /orders 200 in 35 ms"
    assert mask_text(text, RULES) == text


def test_text_masking_with_no_headers_or_fields():
    assert mask_text("Bearer abc", Rules((), ())) == "Bearer ***"


# mask_log_line

def test_json_log_line_masks_only_the_message():
    line = json.dumps({"ts": "2026-10-14T10:00:00+07:00", "source": "app", "level": "I", "tag": "Net",
                       "message": "sent Authorization: Bearer fake"})
    assert json.loads(mask_log_line(line, RULES)) == {
        "ts": "2026-10-14T10:00:00+07:00", "source": "app", "level": "I", "tag": "Net",
        "message": "sent Authorization: ***"}


def test_json_in_a_log_message():
    line = json.dumps({"message": 'body {"password": "fake", "user": "ann"}'})
    assert json.loads(mask_log_line(line, RULES))["message"] == 'body {"password": "***", "user": "ann"}'


def test_log_line_that_is_not_json_is_masked_as_a_whole():
    assert mask_log_line("D/Net: Cookie: sid=fake", RULES) == "D/Net: Cookie: ***"
    assert mask_log_line('["password=fake"]', RULES) == '["password=***"]'
    assert mask_log_line('{"cut": "off password=fake', RULES) == '{"cut": "off password=***'


def test_json_log_line_masks_matching_keys_and_every_text_value():
    assert json.loads(mask_log_line('{"ts": 1,  "password": "fake"}', RULES)) == {"ts": 1, "password": MASK}
    line = json.dumps({"tag": "Net", "extra": {"note": "Bearer fake", "list": ["token=fake"]}})
    assert json.loads(mask_log_line(line, RULES)) == {
        "tag": "Net", "extra": {"note": "Bearer ***", "list": ["token=***"]}}
    assert mask_log_line('{"message": 5}', RULES) == '{"message": 5}'


def test_json_looking_body_that_does_not_parse_is_masked_by_pattern():
    cut_off = '{"user": "ann", "password": "fake", "more": '
    assert redact_json_text(cut_off, RULES) == ('{"user": "ann", "password": "***", "more": ', 1)
    lines = '{"access_token": "fake"}\n{"id": 2}'
    assert redact_json_text(lines, RULES)[0] == '{"access_token": "***"}\n{"id": 2}'
    deep = "[" * 100_000 + '"password=fake"'
    assert "fake" not in redact_json_text(deep, RULES)[0]
    assert redact_json_text("plain password=fake", RULES) == ("plain password=fake", 0)


def test_fragment_parameters_after_a_route_are_masked():
    assert redact_url("https://app/#/callback?access_token=fake&state=1", RULES) == (
        "https://app/#/callback?access_token=***&state=1", 1)
    assert redact_url("https://app/#/callback?state=1", RULES) == ("https://app/#/callback?state=1", 0)
    location = masked(response={"headers": [{"name": "Location", "value": "https://app/#/cb?id_token=fake"}],
                                "redirectURL": "https://app/#/cb?id_token=fake"})["response"]
    assert location["headers"][0]["value"] == location["redirectURL"] == "https://app/#/cb?id_token=***"


def test_semicolons_separate_query_pairs_too():
    assert redact_url("https://h/p?a=1;password=fake&b=2", RULES) == ("https://h/p?a=1;password=***&b=2", 1)


def test_generic_token_names_are_masked_by_default():
    body = json.dumps({"token": "fake", "apiKey": "fake", "secret": "fake", "login_token": "kept"})
    assert json.loads(redact_json_text(body, RULES)[0]) == {
        "token": MASK, "apiKey": MASK, "secret": MASK, "login_token": "kept"}


def test_names_recorded_in_meta_are_added_and_bad_entries_ignored():
    rules = redact.with_names(RULES, ["X-Api-Key", 5, ""], "not a list")
    assert "X-Api-Key" in rules.headers and set(RULES.headers) <= set(rules.headers)
    assert rules.fields == RULES.fields


def test_unchanged_log_line_keeps_its_exact_text():
    line = '{"ts":1,  "message": "plain caf\\u00e9"}'
    assert mask_log_line(line, RULES) == line
