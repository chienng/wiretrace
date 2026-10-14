import json
import re
from pathlib import Path

import pytest

from cli import preset
from cli.preset import PresetError

GOOD = """\
name: staging
api_hosts:
  - api-staging.example.com
"""


def write(tmp_path: Path, text: str, name: str = "staging") -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    return path


def load(tmp_path: Path, text: str, name: str = "staging") -> preset.Preset:
    write(tmp_path, text, name)
    return preset.load_preset(name, tmp_path)


def error(tmp_path: Path, text: str, name: str = "staging") -> str:
    with pytest.raises(PresetError) as info:
        load(tmp_path, text, name)
    return str(info.value)


# Loading

def test_good_preset(tmp_path):
    p = load(tmp_path, GOOD + 'default_filter: "!~t image"\napp:\n  ios_process: MyApp\n')
    assert p.name == "staging"
    assert p.api_hosts == ("api-staging.example.com",)
    assert p.default_filter == "!~t image"
    assert p.app == {"ios_process": "MyApp"}


def test_unknown_keys_accepted(tmp_path):
    p = load(tmp_path, GOOD + "mocks_dir: mocks/staging\nredact:\n  headers: [Cookie]\ntracker: youtrack\n")
    assert p.api_hosts == ("api-staging.example.com",)


def test_example_preset_loads():
    assert preset.load_preset("example").name == "example"


# Errors name the file and the problem

def test_missing_api_hosts(tmp_path):
    message = error(tmp_path, "name: staging\n")
    assert "staging.yaml" in message and "api_hosts" in message


def test_empty_api_hosts(tmp_path):
    message = error(tmp_path, "name: staging\napi_hosts: []\n")
    assert "staging.yaml" in message and "non-empty" in message


@pytest.mark.parametrize("host, problem", [
    ("https://api.example.com", "URL"),
    ("api.example.com/v1", "path"),
    ("api.example.com:443", "port"),
    ("*.example.com", "wildcard"),
    ("api example.com", "not a valid host name"),
    ("-api.example.com", "not a valid host name"),
])
def test_bad_host(tmp_path, host, problem):
    message = error(tmp_path, f"name: staging\napi_hosts:\n  - '{host}'\n")
    assert "staging.yaml" in message and host in message and problem in message


def test_url_suggests_host_name(tmp_path):
    message = error(tmp_path, "name: staging\napi_hosts:\n  - https://api.example.com/v1\n")
    assert "'api.example.com'" in message


def test_name_must_match_file_name(tmp_path):
    message = error(tmp_path, GOOD.replace("name: staging", "name: production"))
    assert "staging.yaml" in message and "production" in message


def test_missing_name(tmp_path):
    assert "'name'" in error(tmp_path, "api_hosts: [api.example.com]\n")


def test_invalid_yaml(tmp_path):
    assert "not valid YAML" in error(tmp_path, "name: [staging\n")


def test_not_a_mapping(tmp_path):
    assert "top level" in error(tmp_path, "- api.example.com\n")


def test_unknown_preset_lists_available(tmp_path):
    write(tmp_path, GOOD)
    write(tmp_path, GOOD.replace("staging", "dev"), "dev")
    with pytest.raises(PresetError) as info:
        preset.load_preset("prod", tmp_path)
    assert "prod" in str(info.value) and "dev, staging" in str(info.value)


def test_preset_name_cannot_leave_presets_dir(tmp_path):
    (tmp_path / "presets").mkdir()
    write(tmp_path, GOOD.replace("staging", "outside"), "outside")
    with pytest.raises(PresetError, match="Unknown preset"):
        preset.load_preset("../outside", tmp_path / "presets")


# Allow-hosts regex: mitmproxy matches it against "host:port", case-insensitively

def allowed(host: str, address: str) -> bool:
    return re.search(preset.allow_hosts_regex(host), address, re.IGNORECASE) is not None


def test_allow_hosts_accepts_host_and_subdomains():
    assert allowed("host", "host:443")
    assert allowed("host", "sub.host:443")
    assert allowed("api.example.com", "API.example.com:8443")


def test_allow_hosts_rejects_lookalikes():
    assert not allowed("host", "evilhost:443")
    assert not allowed("host", "host.evil.io:443")
    assert not allowed("api.example.com", "apixexample.com:443")


def test_allow_hosts_one_per_host(tmp_path):
    p = load(tmp_path, GOOD + "  - auth-staging.example.com\n")
    assert len(preset.allow_hosts_regexes(p)) == 2


# mocks_dir and request_id_header

def test_qa_keys_default(tmp_path):
    p = load(tmp_path, GOOD)
    assert p.mocks_dir == "mocks/staging"
    assert p.request_id_header == "X-Request-ID"


def test_qa_keys_set(tmp_path):
    p = load(tmp_path, GOOD + "mocks_dir: fixtures/api\nrequest_id_header: X-Trace-Id\n")
    assert p.mocks_dir == "fixtures/api"
    assert p.request_id_header == "X-Trace-Id"


@pytest.mark.parametrize("value", ["/etc", "'\\\\share'", "../mocks", "mocks/../../x", "5", "''", "[a]"])
def test_bad_mocks_dir(tmp_path, value):
    message = error(tmp_path, GOOD + f"mocks_dir: {value}\n")
    assert "staging.yaml" in message and "mocks_dir" in message


@pytest.mark.parametrize("value", ["''", "X Request", "X-Request:", "5", "'X-Id '", "[a]"])
def test_bad_request_id_header(tmp_path, value):
    message = error(tmp_path, GOOD + f"request_id_header: {value}\n")
    assert "staging.yaml" in message and "request_id_header" in message


# app: android_package and ios_process feed the log collectors

def app_text(**app) -> str:
    # JSON is valid YAML, so any value, quotes and backslashes included, can be written as is.
    return GOOD + f"app: {json.dumps(app)}\n"


@pytest.mark.parametrize("package", ["com.example.myapp", "com.example.my_app2", "A.b", "a.b.c.d.e"])
def test_good_android_package(tmp_path, package):
    assert load(tmp_path, app_text(android_package=package)).app == {"android_package": package}


@pytest.mark.parametrize("package", [
    "myapp", "com.", ".com.example", "com..example", "1com.example", "com.1example", "com.exa-mple",
    "com.example.my app", "com.example.myapp\n", 'com.example"; rm', "", 5, ["com.example"], True,
])
def test_bad_android_package(tmp_path, package):
    message = error(tmp_path, app_text(android_package=package))
    assert "staging.yaml" in message and "app.android_package" in message


@pytest.mark.parametrize("process", ["MyApp", "My App", "my.app_2-x", "9lives", "A" * 64])
def test_good_ios_process(tmp_path, process):
    assert load(tmp_path, app_text(ios_process=process)).app == {"ios_process": process}


@pytest.mark.parametrize("process", [
    'My"App', "My'App", "My\\App", 'x" OR process == "y', " MyApp", ".MyApp", "My/App", "My;App", "My\nApp",
    "A" * 65, "", 5, ["MyApp"], False,
])
def test_bad_ios_process(tmp_path, process):
    message = error(tmp_path, app_text(ios_process=process))
    assert "staging.yaml" in message and "app.ios_process" in message


def test_app_keys_left_empty_count_as_not_set(tmp_path):
    p = load(tmp_path, GOOD + "app:\n  android_package:\n  ios_process:\n")
    assert p.app == {"android_package": None, "ios_process": None}


def test_unknown_app_keys_are_still_ignored(tmp_path):
    p = load(tmp_path, app_text(android_package="com.example.app", build_flavor="qa", anything=[1, 2]))
    assert p.app["android_package"] == "com.example.app"


def test_app_without_keys_or_missing_still_loads(tmp_path):
    assert load(tmp_path, GOOD).app == {}
    assert load(tmp_path, GOOD + "app: {}\n").app == {}


# redact: names added to the default masking rules

def test_redact_defaults_to_nothing_added(tmp_path):
    p = load(tmp_path, GOOD)
    assert p.redact_headers == () and p.redact_fields == ()


def test_good_redact_block(tmp_path):
    p = load(tmp_path, GOOD + "redact:\n  headers: [X-Api-Key, X-Session]\n  json_fields: [otp, login_token, user.pin]\n")
    assert p.redact_headers == ("X-Api-Key", "X-Session")
    assert p.redact_fields == ("otp", "login_token", "user.pin")


def test_redact_with_only_one_list(tmp_path):
    assert load(tmp_path, GOOD + "redact:\n  headers: [X-Api-Key]\n").redact_fields == ()
    assert load(tmp_path, GOOD + "redact:\n  json_fields: [otp]\n").redact_headers == ()


def test_redact_empty_lists_are_allowed(tmp_path):
    p = load(tmp_path, GOOD + "redact:\n  headers: []\n  json_fields: []\n")
    assert p.redact_headers == () and p.redact_fields == ()
    assert load(tmp_path, GOOD + "redact:\n  headers:\n  json_fields:\n").redact_headers == ()
    assert load(tmp_path, GOOD + "redact: {}\n").redact_fields == ()


@pytest.mark.parametrize("value", ["secret", "[a]", "5", "true"])
def test_redact_must_be_a_mapping(tmp_path, value):
    message = error(tmp_path, GOOD + f"redact: {value}\n")
    assert "staging.yaml" in message and "'redact'" in message


def test_redact_unknown_key_is_named(tmp_path):
    message = error(tmp_path, GOOD + "redact:\n  header: [X-Api-Key]\n")
    assert "staging.yaml" in message and "redact.header" in message


@pytest.mark.parametrize("key", ["headers", "json_fields"])
@pytest.mark.parametrize("value", ["X-Api-Key", "5", "{a: b}"])
def test_redact_lists_must_be_lists(tmp_path, key, value):
    message = error(tmp_path, GOOD + f"redact:\n  {key}: {value}\n")
    assert f"redact.{key}" in message and "list" in message


@pytest.mark.parametrize("name", ["X Api", "X-Api:", "''", "5", "[a]", "X-Api\\n"])
def test_redact_bad_header(tmp_path, name):
    message = error(tmp_path, GOOD + f"redact:\n  headers: [{name}]\n")
    assert "staging.yaml" in message and "redact.headers" in message


@pytest.mark.parametrize("name", ["''", "-otp", ".otp", "my field", "a" * 65, "a;b", "5", "[a]", "otp\\n"])
def test_redact_bad_field(tmp_path, name):
    message = error(tmp_path, GOOD + f"redact:\n  json_fields: [{name}]\n")
    assert "staging.yaml" in message and "redact.json_fields" in message


def test_redact_field_of_64_characters_is_good(tmp_path):
    assert load(tmp_path, GOOD + f"redact:\n  json_fields: [{'a' * 64}]\n").redact_fields == ("a" * 64,)


def test_unknown_top_level_keys_stay_ignored_next_to_redact(tmp_path):
    p = load(tmp_path, GOOD + "reddact:\n  anything: 1\nredact:\n  headers: [X-Id]\n")
    assert p.redact_headers == ("X-Id",)
