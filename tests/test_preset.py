import hashlib
import json
import os
import re
from pathlib import Path

import pytest
import yaml

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


def test_default_preset_loads():
    assert preset.load_preset("default").name == "default"


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


def test_a_mocks_dir_symlink_outside_the_wiretrace_folder_is_refused(tmp_path):
    root = tmp_path / "wiretrace"
    presets = root / "presets"
    presets.mkdir(parents=True)
    (root / "mocks").mkdir()
    (root / "mocks" / "out").symlink_to("/")
    (presets / "staging.yaml").write_text(GOOD + "mocks_dir: mocks/out\n")
    message = ""
    with pytest.raises(PresetError) as info:
        preset.load_preset("staging", presets)
    message = str(info.value)
    assert "mocks_dir" in message and "must be a folder inside the wiretrace folder" in message


# Editing and creating presets from the window (spec 013, extension A). The number is the spec's test number.

ALL_FIELDS = {"api_hosts": ["api.example.com", "auth.example.com"], "android_package": "com.example.app",
              "ios_process": "Example App", "request_id_header": "X-Trace-Id", "default_filter": "~d example & !~t image",
              "redact_headers": ["X-Api-Key", "X-Secret"], "redact_fields": ["otp", "login_token"]}


def fields(**over) -> dict:
    return {**preset.empty_fields(), "api_hosts": ["api.example.com"], **over}


def presets_dir(tmp_path: Path) -> Path:
    path = tmp_path / "presets"
    path.mkdir(exist_ok=True)
    return path


def render(tmp_path: Path, form: dict, old=None, name: str = "staging") -> str:
    return preset.render_file(presets_dir(tmp_path) / f"{name}.yaml", form, old)


def refused(tmp_path: Path, form: dict, old=None) -> preset.FieldError:
    with pytest.raises(preset.FieldError) as info:
        render(tmp_path, form, old)
    return info.value


def test_preset_edit_01_every_field_round_trips_through_parse_preset(tmp_path):
    text = render(tmp_path, ALL_FIELDS)
    path = presets_dir(tmp_path) / "staging.yaml"
    loaded = preset.parse_preset(text, path)
    assert loaded.api_hosts == ("api.example.com", "auth.example.com")
    assert loaded.app == {"android_package": "com.example.app", "ios_process": "Example App"}
    assert loaded.request_id_header == "X-Trace-Id" and loaded.default_filter == "~d example & !~t image"
    assert loaded.redact_headers == ("X-Api-Key", "X-Secret") and loaded.redact_fields == ("otp", "login_token")
    path.write_text(text)
    assert preset.read_preset_file(path).fields == ALL_FIELDS


def test_preset_edit_01_the_layout_is_the_documented_one(tmp_path):
    text = render(tmp_path, ALL_FIELDS, {"mocks_dir": "mocks/x", "tracker": "youtrack"})
    lines = text.splitlines()
    assert lines[0] == "# Written by the Wiretrace window."
    assert lines[1] == "# Every key is explained in presets/example.yaml."
    keys = [line.split(":")[0] for line in lines[2:] if line and line[0] not in " #"]
    assert keys == ["name", "api_hosts", "default_filter", "request_id_header", "app", "redact", "mocks_dir", "tracker"]
    assert '  - "api.example.com"' in lines and '  android_package: "com.example.app"' in lines
    assert lines.index("# Kept from the file:") < lines.index("mocks_dir: mocks/x")
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_preset_edit_01_empty_fields_leave_their_keys_out(tmp_path):
    text = render(tmp_path, fields())
    assert [line for line in text.splitlines() if not line.startswith("#")] == [
        'name: "staging"', "api_hosts:", '  - "api.example.com"']
    only_one = render(tmp_path, fields(ios_process="Example", redact_fields=["otp"]))
    assert "android_package" not in only_one and "headers" not in only_one and "default_filter" not in only_one
    assert "request_id_header" not in only_one and "Kept" not in only_one
    assert preset.fields_from_data(yaml.safe_load(only_one)) == fields(ios_process="Example", redact_fields=["otp"])


@pytest.mark.parametrize("value", [
    'a"b', "a # b", "a: b", "a\nb: c", "a\\", 'x"\napi_hosts: ["evil.example.com"]', "!!python/object:os.system", "&a *a",
    "~d x\r\nname: other", "'single'", "é ü 日本語 😀", "- item", "{a: b}", "> folded", "| literal"])
def test_preset_edit_02_a_value_cannot_add_a_key(tmp_path, value):
    form = fields(default_filter=value)
    try:
        text = render(tmp_path, form)
    except preset.FieldError:
        return
    data = yaml.safe_load(text)
    assert set(data) == {"name", "api_hosts", "default_filter"}
    assert data["default_filter"] == value and data["api_hosts"] == ["api.example.com"]


@pytest.mark.parametrize("key, value", [
    ("api_hosts", ['x.example.com"\nredact:\n  headers: [Cookie]\n#']), ("android_package", 'com.a"\nname: other'),
    ("ios_process", 'App"\n  - x'), ("request_id_header", 'X-Id"\napi_hosts: []'),
    ("redact_headers", ['X-A"\nname: other']), ("redact_fields", ['f"\nname: other'])])
def test_preset_edit_02_a_value_in_a_checked_field_is_refused_not_written(tmp_path, key, value):
    form = fields(**{key: value})
    assert refused(tmp_path, form).field == key


@pytest.mark.parametrize("char", ["\n", "\r", "\t", "\x00", "\x85", "\u2028", "\u2029", "\ud800"])
def test_preset_edit_02_control_characters_in_the_filter_are_refused(tmp_path, char):
    error = refused(tmp_path, fields(default_filter=f"~d a{char}b"))
    assert error.field == "default_filter" and "control characters" in str(error)


def test_preset_edit_03_kept_keys_survive_a_save(tmp_path):
    old = yaml.safe_load(
        "name: staging\napi_hosts: [old.example.com]\nmocks_dir: mocks/staging\ntracker:\n  project: ABC\n  ids: [1, 2]\n"
        "later_feature: true\napp:\n  android_package: com.old.app\n  future_key: 7\n  nested: {a: [1, 2]}\n"
        "redact:\n  headers: [X-Old]\n")
    text = render(tmp_path, fields(android_package="com.new.app"), old)
    data = yaml.safe_load(text)
    assert data["mocks_dir"] == "mocks/staging" and data["tracker"] == {"project": "ABC", "ids": [1, 2]}
    assert data["later_feature"] is True
    assert data["app"] == {"android_package": "com.new.app", "future_key": 7, "nested": {"a": [1, 2]}}
    assert data["api_hosts"] == ["api.example.com"] and "redact" not in data
    assert list(data) == ["name", "api_hosts", "app", "mocks_dir", "tracker", "later_feature"]


def test_preset_edit_03_an_app_block_with_only_unknown_keys_stays_without_the_form_keys(tmp_path):
    old = yaml.safe_load("name: staging\napi_hosts: [a.example.com]\napp:\n  future_key: 7\n")
    assert yaml.safe_load(render(tmp_path, fields(), old))["app"] == {"future_key": 7}


def test_preset_edit_03_what_the_old_file_had_in_the_form_keys_is_not_kept(tmp_path):
    old = {"name": "wrong", "api_hosts": "not a list", "app": 5, "redact": {"typo": []}, "default_filter": ["x"]}
    data = yaml.safe_load(render(tmp_path, fields(), old))
    assert data == {"name": "staging", "api_hosts": ["api.example.com"]}


def test_preset_edit_03_a_kept_mocks_dir_that_fails_the_check_is_refused_without_a_field(tmp_path):
    error = refused(tmp_path, fields(), {"mocks_dir": "/etc"})
    assert error.field is None and "mocks_dir" in str(error)


@pytest.mark.parametrize("form, field, text", [
    (fields(api_hosts=[]), "api_hosts", "non-empty list"),
    (fields(api_hosts=["https://api.example.com"]), "api_hosts", "is a URL"),
    (fields(api_hosts=["api.example.com", "*.example.com"]), "api_hosts", "wildcard"),
    (fields(api_hosts=["api.example.com:8443"]), "api_hosts", "port"),
    (fields(api_hosts=[""]), "api_hosts", "not a host name"),
    (fields(android_package="not a package"), "android_package", "'app.android_package' must be a package name"),
    (fields(ios_process='App"'), "ios_process", "'app.ios_process' must be a process name"),
    (fields(request_id_header="X Id"), "request_id_header", "'request_id_header' must be a header name"),
    (fields(redact_headers=["X Api"]), "redact_headers", "redact.headers"),
    (fields(redact_headers=["ok", ""]), "redact_headers", "redact.headers"),
    (fields(redact_fields=["-otp"]), "redact_fields", "redact.json_fields"),
    (fields(redact_fields=["a" * 65]), "redact_fields", "redact.json_fields"),
])
def test_preset_edit_04_a_bad_value_names_its_field_with_the_message_parse_preset_gives(tmp_path, form, field, text):
    error = refused(tmp_path, form)
    assert error.field == field and text in str(error) and str(error).startswith("presets/staging.yaml: ")


def test_preset_edit_04_the_message_is_the_one_load_preset_shows(tmp_path):
    form = fields(api_hosts=["https://api.example.com"])
    bad = presets_dir(tmp_path) / "staging.yaml"
    bad.write_text('name: staging\napi_hosts:\n  - "https://api.example.com"\n')
    with pytest.raises(PresetError) as loaded:
        preset.load_preset("staging", presets_dir(tmp_path))
    assert str(refused(tmp_path, form)) == str(loaded.value)


@pytest.mark.parametrize("name", ["", "a/b", "../x", "a.b", ".hidden", "-a", "_a", "a b", "a" * 65, "é", "a\n"])
def test_preset_edit_04_a_name_that_breaks_the_file_name_rule_never_becomes_a_path(tmp_path, name):
    with pytest.raises(preset.FieldError) as info:
        preset.preset_path(presets_dir(tmp_path), name)
    assert info.value.field == "name"


@pytest.mark.parametrize("name", ["a", "0", "Staging-2_x", "a" * 64])
def test_preset_edit_04_a_name_that_follows_the_rule_is_a_path_in_the_presets_folder(tmp_path, name):
    assert preset.preset_path(presets_dir(tmp_path), name) == presets_dir(tmp_path) / f"{name}.yaml"


def test_preset_edit_04_the_limits_are_50_hosts_50_names_and_512_characters(tmp_path):
    many = [f"h{i}.example.com" for i in range(50)]
    render(tmp_path, fields(api_hosts=many, redact_headers=[f"X-{i}" for i in range(50)],
                            redact_fields=[f"f{i}" for i in range(50)], default_filter="~d " + "a" * 509))
    assert refused(tmp_path, fields(api_hosts=many + ["x.example.com"])).field == "api_hosts"
    assert refused(tmp_path, fields(redact_headers=[f"X-{i}" for i in range(51)])).field == "redact_headers"
    assert refused(tmp_path, fields(redact_fields=[f"f{i}" for i in range(51)])).field == "redact_fields"
    assert refused(tmp_path, fields(default_filter="a" * 513)).field == "default_filter"


def test_preset_edit_04_a_text_that_does_not_read_back_as_the_fields_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(preset, "render_preset",
                        lambda name, form, old=None: f'name: "{name}"\napi_hosts: [a.example.com]\n')
    error = refused(tmp_path, fields())
    assert error.field is None and "could not be saved as entered" in str(error)


def test_preset_edit_04_a_text_that_parse_preset_refuses_is_not_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(preset, "render_preset", lambda name, form, old=None: f'name: "{name}"\n')
    assert "missing 'api_hosts'" in str(refused(tmp_path, fields()))


def test_preset_edit_17_a_file_that_does_not_load_gives_its_error_and_the_values_that_can_be_read(tmp_path):
    path = presets_dir(tmp_path) / "staging.yaml"
    path.write_text(
        "name: staging\napi_hosts:\n  - good.example.com\n  - 5\n  - https://bad.example.com\n"
        "default_filter: [not, a, string]\nrequest_id_header: X-Id\napp:\n  android_package: 7\n  ios_process: App\n"
        "redact:\n  headers: X-Not-A-List\n  json_fields: [otp, 3]\n")
    read = preset.read_preset_file(path)
    assert read.error.startswith("presets/staging.yaml: ") and "api_hosts entry 5" in read.error
    assert read.fields == {"api_hosts": ["good.example.com", "https://bad.example.com"], "android_package": "",
                           "ios_process": "App", "request_id_header": "X-Id", "default_filter": "",
                           "redact_headers": [], "redact_fields": ["otp"]}
    assert read.revision == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("raw", [b"", b"just text", b"- a\n- b\n", b"key: [unclosed", b"\xff\xfe\x00bad",
                                 b"name: a\n\ttab: 1"])
def test_preset_edit_17_a_file_that_is_not_a_mapping_or_not_text_gives_empty_fields_and_an_error(tmp_path, raw):
    path = presets_dir(tmp_path) / "staging.yaml"
    path.write_bytes(raw)
    read = preset.read_preset_file(path)
    assert read.fields == preset.empty_fields() and read.error and read.revision == hashlib.sha256(raw).hexdigest()


def test_preset_edit_17_a_good_file_has_no_error_and_its_revision_follows_its_bytes(tmp_path):
    path = presets_dir(tmp_path) / "staging.yaml"
    path.write_text(GOOD)
    first = preset.read_preset_file(path)
    assert first.error is None and first.fields == fields(api_hosts=["api-staging.example.com"])
    path.write_text(GOOD + "\n")
    assert preset.read_preset_file(path).revision != first.revision


def test_preset_edit_shape_of_the_fields_is_exact():
    assert preset.fields_shape_ok(preset.empty_fields())
    assert not preset.fields_shape_ok({**preset.empty_fields(), "extra": ""})
    assert not preset.fields_shape_ok({k: v for k, v in preset.empty_fields().items() if k != "api_hosts"})
    for bad in ({"api_hosts": "a"}, {"api_hosts": [1]}, {"android_package": None}, {"redact_fields": [["a"]]},
                {"ios_process": 5}):
        assert not preset.fields_shape_ok({**preset.empty_fields(), **bad})
    assert not preset.fields_shape_ok([]) and not preset.fields_shape_ok(None)


def temporary_files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def test_preset_edit_06_create_writes_the_file_and_leaves_no_temporary_file(tmp_path):
    folder = presets_dir(tmp_path)
    path = folder / "staging.yaml"
    text = render(tmp_path, ALL_FIELDS)
    preset.create_file(path, text)
    assert path.read_text() == text and temporary_files(folder) == []
    assert preset.load_preset("staging", folder).api_hosts == ("api.example.com", "auth.example.com")
    assert path.stat().st_mode & 0o600 == 0o600


def test_preset_edit_06_create_never_overwrites_a_file_of_that_name(tmp_path):
    folder = presets_dir(tmp_path)
    (folder / "staging.yaml").write_text(GOOD)
    with pytest.raises(FileExistsError):
        preset.create_file(folder / "staging.yaml", "name: staging\n")
    assert (folder / "staging.yaml").read_text() == GOOD and temporary_files(folder) == []


def test_preset_edit_06_create_refuses_a_name_that_differs_only_in_capitals(tmp_path):
    folder = presets_dir(tmp_path)
    (folder / "staging.yaml").write_text(GOOD)
    for other in ("Staging", "STAGING"):
        with pytest.raises(FileExistsError):
            preset.create_file(folder / f"{other}.yaml", "name: x\n")
    assert sorted(p.name for p in folder.iterdir()) == ["staging.yaml"]


def test_preset_edit_06_create_uses_a_link_so_a_file_that_appears_meanwhile_is_not_overwritten(tmp_path, monkeypatch):
    folder = presets_dir(tmp_path)
    real_link = os.link

    def racing_link(src, dst, **kwargs):
        Path(dst).write_text(GOOD)
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(preset.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        preset.create_file(folder / "staging.yaml", "name: staging\n")
    assert (folder / "staging.yaml").read_text() == GOOD and temporary_files(folder) == []


def test_preset_edit_06_a_failed_create_leaves_no_temporary_file(tmp_path, monkeypatch):
    folder = presets_dir(tmp_path)
    monkeypatch.setattr(preset.os, "link", mock_raise(OSError("disk")))
    with pytest.raises(OSError):
        preset.create_file(folder / "staging.yaml", "name: staging\n")
    assert list(folder.iterdir()) == []


def mock_raise(error: Exception):
    def raiser(*args, **kwargs):
        raise error
    return raiser


def test_preset_edit_16_replace_writes_the_whole_new_file_and_leaves_no_temporary_file(tmp_path):
    folder = presets_dir(tmp_path)
    path = folder / "staging.yaml"
    path.write_text(GOOD)
    preset.replace_file(path, "name: staging\napi_hosts: [new.example.com]\n")
    assert path.read_text() == "name: staging\napi_hosts: [new.example.com]\n"
    assert [p.name for p in folder.iterdir()] == ["staging.yaml"]


def test_preset_edit_16_a_failed_replace_keeps_the_old_file_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    folder = presets_dir(tmp_path)
    path = folder / "staging.yaml"
    path.write_text(GOOD)
    monkeypatch.setattr(preset.os, "replace", mock_raise(OSError("disk")))
    with pytest.raises(OSError):
        preset.replace_file(path, "name: staging\napi_hosts: [new.example.com]\n")
    assert path.read_text() == GOOD and [p.name for p in folder.iterdir()] == ["staging.yaml"]


def test_preset_edit_16_a_failed_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    folder = presets_dir(tmp_path)
    monkeypatch.setattr(preset.os, "fsync", mock_raise(OSError("disk")))
    with pytest.raises(OSError):
        preset.replace_file(folder / "staging.yaml", "name: staging\n")
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("write", [preset.replace_file, preset.create_file])
def test_preset_edit_16_a_link_at_the_temporary_path_is_not_followed(tmp_path, monkeypatch, write):
    folder = presets_dir(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched")
    monkeypatch.setattr(preset.secrets, "token_hex", lambda n: "abcd1234")
    (folder / ".staging.abcd1234.tmp").symlink_to(victim)
    with pytest.raises(OSError):
        write(folder / "staging.yaml", "name: staging\napi_hosts: [new.example.com]\n")
    assert victim.read_text() == "untouched" and not (folder / "staging.yaml").exists()
    assert (folder / ".staging.abcd1234.tmp").is_symlink()


def test_preset_edit_16_a_new_temporary_name_is_hidden_from_the_preset_list(tmp_path, monkeypatch):
    folder = presets_dir(tmp_path)
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(preset.list_presets(folder))
        return real_replace(src, dst)

    monkeypatch.setattr(preset.os, "replace", spy)
    preset.replace_file(folder / "staging.yaml", "name: staging\n")
    assert seen == [[]]
