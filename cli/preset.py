"""Presets: one YAML file per project and environment, in presets/.

A preset names the API hosts Wiretrace decrypts; traffic to every other host passes
through undecrypted. Unknown keys are ignored, so presets written for later
features still load.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"

# Also part of the session folder name, so no path separators or dots.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
# An HTTP header field name is an RFC 9110 token.
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
DEFAULT_REQUEST_ID_HEADER = "X-Request-ID"


class PresetError(Exception):
    """A preset that cannot be used. The message is shown to the user as is."""


@dataclass(frozen=True)
class Preset:
    name: str
    api_hosts: tuple[str, ...]
    default_filter: str | None = None
    app: dict = field(default_factory=dict)
    # Relative to the wiretrace folder; empty means mocks/<name>.
    mocks_dir: str = ""
    request_id_header: str = DEFAULT_REQUEST_ID_HEADER

    def __post_init__(self) -> None:
        if not self.mocks_dir:
            object.__setattr__(self, "mocks_dir", f"mocks/{self.name}")


def list_presets(presets_dir: Path = PRESETS_DIR) -> list[str]:
    if not presets_dir.is_dir():
        return []
    return sorted(p.stem for p in presets_dir.glob("*.yaml") if _NAME.fullmatch(p.stem))


def load_preset(name: str, presets_dir: Path = PRESETS_DIR) -> Preset:
    path = presets_dir / f"{name}.yaml"
    if not _NAME.fullmatch(name) or not path.is_file():
        available = list_presets(presets_dir)
        listed = ", ".join(available) if available else "none yet; copy presets/example.yaml"
        raise PresetError(f"Unknown preset {name!r}. Available presets: {listed}")
    return parse_preset(path.read_text(encoding="utf-8"), path)


def parse_preset(text: str, path: Path) -> Preset:
    # Imported here so `wiretrace doctor` still runs when the package install failed.
    import yaml

    where = f"{path.parent.name}/{path.name}"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PresetError(f"{where}: not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise PresetError(f"{where}: expected 'key: value' lines at the top level")

    name = data.get("name")
    if name is None:
        raise PresetError(f"{where}: missing 'name'")
    if name != path.stem:
        raise PresetError(f"{where}: name is {name!r}, but must equal the file name without .yaml ({path.stem!r})")

    hosts = data.get("api_hosts")
    if hosts is None:
        raise PresetError(f"{where}: missing 'api_hosts' (a list of host names)")
    if not isinstance(hosts, list) or not hosts:
        raise PresetError(f"{where}: 'api_hosts' must be a non-empty list of host names")
    for host in hosts:
        problem = host_problem(host)
        if problem:
            raise PresetError(f"{where}: api_hosts entry {host!r} {problem}")

    default_filter = data.get("default_filter")
    if default_filter is not None and not isinstance(default_filter, str):
        raise PresetError(f"{where}: 'default_filter' must be a quoted filter expression")

    app = data.get("app") or {}
    if not isinstance(app, dict):
        raise PresetError(f"{where}: 'app' must be 'key: value' lines")

    mocks_dir = data.get("mocks_dir")
    if mocks_dir is not None:
        problem = mocks_dir_problem(mocks_dir)
        if problem:
            raise PresetError(f"{where}: 'mocks_dir' {problem}")

    header = data.get("request_id_header")
    if header is not None:
        problem = header_problem(header)
        if problem:
            raise PresetError(f"{where}: 'request_id_header' {problem}")

    return Preset(name=name, api_hosts=tuple(hosts), default_filter=default_filter or None, app=app,
                  mocks_dir=mocks_dir or "", request_id_header=header or DEFAULT_REQUEST_ID_HEADER)


def mocks_dir_problem(value: object) -> str | None:
    """Why `value` is not a folder inside the wiretrace folder, or None if it is one."""
    if not isinstance(value, str) or not value:
        return "must be a folder path such as mocks/staging"
    if value.startswith(("/", "\\")) or PureWindowsPath(value).is_absolute():
        return "must be relative to the wiretrace folder, not an absolute path"
    if ".." in re.split(r"[/\\]", value):
        return "must not contain '..'"
    return None


def header_problem(value: object) -> str | None:
    """Why `value` is not an HTTP header name, or None if it is one."""
    if not isinstance(value, str) or not _HEADER.fullmatch(value):
        return "must be a header name such as X-Request-ID (letters, digits and '-' only)"
    return None


def host_problem(host: object) -> str | None:
    """Why `host` is not a bare host name, or None if it is one."""
    if not isinstance(host, str) or not host:
        return "is not a host name"
    if "://" in host:
        bare = urlsplit(host).hostname
        return f"is a URL; use the host name only{f' ({bare!r})' if bare else ''}"
    if "*" in host:
        return "is a wildcard; list the parent host instead, its subdomains are included"
    if "/" in host:
        return "contains a path; use the host name only"
    if ":" in host:
        return "contains a port; use the host name only, every port is included"
    if not all(_LABEL.fullmatch(label) for label in host.split(".")):
        return "is not a valid host name"
    return None


def allow_hosts_regex(host: str) -> str:
    """mitmproxy matches --allow-hosts against 'host:port', so the port must be allowed for."""
    return rf"(^|\.){re.escape(host)}(:\d+)?$"


def allow_hosts_regexes(preset: Preset) -> list[str]:
    return [allow_hosts_regex(host) for host in preset.api_hosts]
