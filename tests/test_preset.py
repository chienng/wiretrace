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
