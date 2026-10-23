"""Presets: one YAML file per project and environment, in presets/.

A preset names the API hosts Wiretrace decrypts; traffic to every other host passes
through undecrypted. Unknown top-level keys are ignored, so presets written for later
features still load; inside `redact` they are an error, because a typo would turn masking off.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import secrets
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"

# Also part of the session folder name, so no path separators or dots.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
# `ios_process` is placed inside a `log stream` predicate: quotes and backslashes are rejected.
_JAVA_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")
_IOS_PROCESS = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
# An HTTP header field name is an RFC 9110 token.
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
DEFAULT_REQUEST_ID_HEADER = "X-Request-ID"
_FIELD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
REDACT_KEYS = ("headers", "json_fields")


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
    # Added to the default masking rules in cli/redact.py; they can never remove one.
    redact_headers: tuple[str, ...] = ()
    redact_fields: tuple[str, ...] = ()

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
    problem = app_problem(app)
    if problem:
        raise PresetError(f"{where}: {problem}")

    mocks_dir = data.get("mocks_dir")
    wiretrace = path.parent.parent
    checked = mocks_dir if mocks_dir is not None else f"mocks/{name}"
    problem = mocks_dir_problem(checked, wiretrace)
    if problem:
        raise PresetError(f"{where}: 'mocks_dir' {problem}")

    header = data.get("request_id_header")
    if header is not None:
        problem = header_problem(header)
        if problem:
            raise PresetError(f"{where}: 'request_id_header' {problem}")

    redact = data.get("redact")
    if redact is not None:
        problem = redact_problem(redact)
        if problem:
            raise PresetError(f"{where}: {problem}")
    redact = redact or {}

    return Preset(name=name, api_hosts=tuple(hosts), default_filter=default_filter or None, app=app,
                  mocks_dir=mocks_dir or "", request_id_header=header or DEFAULT_REQUEST_ID_HEADER,
                  redact_headers=tuple(redact.get("headers") or ()),
                  redact_fields=tuple(redact.get("json_fields") or ()))


def redact_problem(redact: object) -> str | None:
    """Why a `redact` block cannot be used, or None. A list left empty counts as an empty list."""
    if not isinstance(redact, dict):
        return "'redact' must be a block with 'headers' and 'json_fields' lists"
    for key in redact:
        if key not in REDACT_KEYS:
            return f"'redact.{key}' is not a known key; use 'headers' or 'json_fields'"
    for key, pattern, example in (("headers", _HEADER, "X-Api-Key"), ("json_fields", _FIELD, "login_token")):
        names = redact.get(key)
        if names is None:
            continue
        if not isinstance(names, list):
            return f"'redact.{key}' must be a list such as [{example}]"
        for name in names:
            if not (isinstance(name, str) and pattern.fullmatch(name)):
                what = "a header name (letters, digits and '-' only)" if key == "headers" else (
                    "a field name: up to 64 letters, digits, '_', '.' or '-', starting with a letter or digit")
                return f"'redact.{key}' entry {name!r} must be {what}"
    return None


def app_problem(app: dict) -> str | None:
    """Why an `app` value cannot be used, or None. A key left empty counts as not set."""
    checks = {
        "android_package": (_JAVA_PACKAGE, "must be a package name such as com.example.myapp"),
        "ios_process": (_IOS_PROCESS, "must be a process name: up to 64 letters, digits, spaces, '.', '_' or '-'"),
    }
    for key, (pattern, message) in checks.items():
        value = app.get(key)
        if value is not None and not (isinstance(value, str) and pattern.fullmatch(value)):
            return f"'app.{key}' {message}"
    return None


def mocks_dir_problem(value: object, root: Path | None = None) -> str | None:
    """Why `value` is not a folder inside the wiretrace folder, or None if it is one.

    `root` is the wiretrace folder. A path that is relative and free of `..` can still
    leave that folder through a symlink, so the resolved path is checked too.
    """
    if not isinstance(value, str) or not value:
        return "must be a folder path such as mocks/staging"
    if value.startswith(("/", "\\")) or PureWindowsPath(value).is_absolute():
        return "must be relative to the wiretrace folder, not an absolute path"
    if ".." in re.split(r"[/\\]", value):
        return "must not contain '..'"
    base = (root if root is not None else PRESETS_DIR.parent).resolve()
    try:
        resolved = (base / value).resolve()
    except OSError:
        return "must be a folder inside the wiretrace folder"
    if not resolved.is_relative_to(base):
        return "must be a folder inside the wiretrace folder"
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


# A two-label parent whose first label is one of these is a public suffix such as co.uk, not a domain.
SECOND_LEVEL_SUFFIXES = ("co", "com", "net", "org", "gov", "edu", "ac")


def decrypt_choices(host: str) -> list[str]:
    """What the window offers to decrypt for a passed-through host: the host, then its parent domain
    when that is a domain (spec 022, slice C). An IP address is offered alone."""
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    labels = host.split(".")
    parent = labels[1:]
    if len(parent) < 2 or (len(parent) == 2 and parent[0] in SECOND_LEVEL_SUFFIXES):
        return [host]
    return [host, ".".join(parent)]


def covers(api_hosts: Sequence[str], host: str) -> bool:
    """Whether an API host already decrypts `host`: it is that host or one of its subdomains."""
    host = host.lower()
    return any(host == h.lower() or host.endswith("." + h.lower()) for h in api_hosts)


# The window's form (spec 013, extension A). It edits fields; the file is rendered whole from them.

TEMPLATE = "example"
MAX_NAME = 64
MAX_ENTRIES = 50
MAX_FILTER = 512
STRING_FIELDS = ("android_package", "ios_process", "request_id_header", "default_filter")
LIST_FIELDS = ("api_hosts", "redact_headers", "redact_fields")
# Top-level keys the form shows; every other key of an old file is kept.
_FORM_KEYS = ("name", "api_hosts", "default_filter", "request_id_header", "app", "redact")
_APP_KEYS = ("android_package", "ios_process")
_HEADER_LINES = ("# Written by the Wiretrace window.", "# Every key is explained in presets/example.yaml.")


class FieldError(PresetError):
    """A form value that cannot be saved. `field` names the form field, or is None."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class PresetFile:
    revision: str
    fields: dict
    # The `load_preset` message, or None when the file loads.
    error: str | None
    # The parsed YAML, or None when it does not parse; the rendering keeps what the form does not show.
    data: object


def empty_fields() -> dict:
    return {"api_hosts": [], "android_package": "", "ios_process": "", "request_id_header": "",
            "default_filter": "", "redact_headers": [], "redact_fields": []}


def fields_shape_ok(fields: object) -> bool:
    if not isinstance(fields, dict) or set(fields) != set(STRING_FIELDS + LIST_FIELDS):
        return False
    return (all(isinstance(fields[key], str) for key in STRING_FIELDS)
            and all(isinstance(fields[key], list) and all(isinstance(item, str) for item in fields[key])
                    for key in LIST_FIELDS))


def fields_from_data(data: object) -> dict:
    """The form's values in a parsed file; a value of the wrong type counts as not set."""
    data = data if isinstance(data, dict) else {}
    app = data.get("app") if isinstance(data.get("app"), dict) else {}
    redact = data.get("redact") if isinstance(data.get("redact"), dict) else {}

    def text(value: object) -> str:
        return value if isinstance(value, str) else ""

    def names(value: object) -> list[str]:
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    return {"api_hosts": names(data.get("api_hosts")), "android_package": text(app.get("android_package")),
            "ios_process": text(app.get("ios_process")), "request_id_header": text(data.get("request_id_header")),
            "default_filter": text(data.get("default_filter")), "redact_headers": names(redact.get("headers")),
            "redact_fields": names(redact.get("json_fields"))}


def file_revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def name_problem(name: object) -> str | None:
    if not (isinstance(name, str) and len(name) <= MAX_NAME and _NAME.fullmatch(name)):
        return (f"The name must be letters, digits, '_' and '-', starting with a letter or a digit, "
                f"at most {MAX_NAME} characters")
    return None


def preset_path(presets_dir: Path, name: object) -> Path:
    """The file of a preset named `name`; a name that breaks the file-name rule never becomes a path."""
    problem = name_problem(name)
    if problem:
        raise FieldError(problem, "name")
    return presets_dir / f"{name}.yaml"


def is_listed(presets_dir: Path, name: str) -> bool:
    """Whether a file of exactly this name exists: a case-insensitive disk would also open `Staging`."""
    return f"{name}.yaml" in os.listdir(presets_dir)


def read_preset_file(path: Path) -> PresetFile:
    """The file's revision, its error, and the form values that can be read from it, however broken it is."""
    import yaml

    raw = path.read_bytes()
    revision = file_revision(raw)
    where = f"{path.parent.name}/{path.name}"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return PresetFile(revision, empty_fields(), f"{where}: not valid UTF-8 text", None)
    try:
        parse_preset(text, path)
        error = None
    except PresetError as e:
        error = str(e)
    except ValueError:
        error = f"{where}: not valid YAML"
    try:
        data = yaml.safe_load(text)
    except (yaml.YAMLError, ValueError):
        data = None
    return PresetFile(revision, fields_from_data(data), error, data)


def check_fields(path: Path, fields: dict) -> None:
    """Every form value against the rule `parse_preset` applies to it, in the form's order.

    The messages are `parse_preset`'s; `FieldError.field` names the form field.
    """
    where = f"{path.parent.name}/{path.name}"
    hosts = fields["api_hosts"]
    if not hosts:
        raise FieldError(f"{where}: 'api_hosts' must be a non-empty list of host names", "api_hosts")
    if len(hosts) > MAX_ENTRIES:
        raise FieldError(f"{where}: 'api_hosts' has more than {MAX_ENTRIES} hosts", "api_hosts")
    for host in hosts:
        problem = host_problem(host)
        if problem:
            raise FieldError(f"{where}: api_hosts entry {host!r} {problem}", "api_hosts")
    for key in _APP_KEYS:
        if fields[key]:
            problem = app_problem({key: fields[key]})
            if problem:
                raise FieldError(f"{where}: {problem}", key)
    if fields["request_id_header"]:
        problem = header_problem(fields["request_id_header"])
        if problem:
            raise FieldError(f"{where}: 'request_id_header' {problem}", "request_id_header")
    expr = fields["default_filter"]
    if len(expr) > MAX_FILTER:
        raise FieldError(f"{where}: 'default_filter' must be at most {MAX_FILTER} characters", "default_filter")
    if any(unicodedata.category(c) in ("Cc", "Cs", "Zl", "Zp") for c in expr):
        raise FieldError(f"{where}: 'default_filter' must not contain control characters", "default_filter")
    for field_name, key in (("redact_headers", "headers"), ("redact_fields", "json_fields")):
        if len(fields[field_name]) > MAX_ENTRIES:
            raise FieldError(f"{where}: 'redact.{key}' has more than {MAX_ENTRIES} names", field_name)
        problem = redact_problem({key: fields[field_name]})
        if problem:
            raise FieldError(f"{where}: {problem}", field_name)


def _quote(value: str) -> str:
    # A JSON string is a YAML double-quoted scalar: no value can end the scalar and start another key.
    return json.dumps(value, ensure_ascii=False)


def render_preset(name: str, fields: dict, old: object = None) -> str:
    """The whole file for `fields`. Keys of `old` that the form does not show are written under 'Kept'."""
    import yaml

    old = old if isinstance(old, dict) else {}
    lines = [*_HEADER_LINES, f"name: {_quote(name)}"]
    if fields["api_hosts"]:
        lines += ["api_hosts:", *(f"  - {_quote(host)}" for host in fields["api_hosts"])]
    for key in ("default_filter", "request_id_header"):
        if fields[key]:
            lines.append(f"{key}: {_quote(fields[key])}")
    app = [f"  {key}: {_quote(fields[key])}" for key in _APP_KEYS if fields[key]]
    if isinstance(old.get("app"), dict):
        other_app = {k: v for k, v in old["app"].items() if k not in _APP_KEYS}
        if other_app:
            app += [f"  {line}" for line in yaml.safe_dump(other_app, sort_keys=False).splitlines()]
    if app:
        lines += ["app:", *app]
    redact = [(key, fields[field_name]) for key, field_name in
              (("headers", "redact_headers"), ("json_fields", "redact_fields")) if fields[field_name]]
    if redact:
        lines.append("redact:")
        for key, names in redact:
            lines += [f"  {key}:", *(f"    - {_quote(item)}" for item in names)]
    kept = {k: v for k, v in old.items() if k not in _FORM_KEYS}
    if kept:
        lines += ["", "# Kept from the file:", *yaml.safe_dump(kept, sort_keys=False).splitlines()]
    return "\n".join(lines) + "\n"


def render_file(path: Path, fields: dict, old: object = None) -> str:
    """The text to write, or a FieldError. Invariant A1: it passes `parse_preset` and reads back as `fields`."""
    import yaml

    check_fields(path, fields)
    text = render_preset(path.stem, fields, old)
    try:
        parse_preset(text, path)
        data = yaml.safe_load(text)
    except PresetError as e:
        raise FieldError(str(e)) from None
    except (yaml.YAMLError, ValueError):
        raise FieldError(f"{path.parent.name}/{path.name}: the values could not be saved as entered") from None
    if fields_from_data(data) != fields:
        raise FieldError(f"{path.parent.name}/{path.name}: the values could not be saved as entered")
    return text


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_temp(path: Path, text: str) -> Path:
    """A new file next to `path`, never a file or link that already exists (A2)."""
    tmp = path.with_name(f".{path.stem}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        _remove(tmp)
        raise
    return tmp


def replace_file(path: Path, text: str) -> None:
    """Invariant A2: the file is replaced whole, or not at all, and no temporary file is left."""
    tmp = _write_temp(path, text)
    try:
        os.replace(tmp, path)
    except BaseException:
        _remove(tmp)
        raise


def create_file(path: Path, text: str) -> None:
    """Invariant A3: FileExistsError when the name is taken, also by a name that differs only in capitals."""
    if any(entry.casefold() == path.name.casefold() for entry in os.listdir(path.parent)):
        raise FileExistsError(path.name)
    tmp = _write_temp(path, text)
    try:
        os.link(tmp, path)
    finally:
        _remove(tmp)
