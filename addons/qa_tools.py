"""Wiretrace QA addon: rules, mock files, fault injection and request ID comments.

Configured only through mitmproxy options (`qa_*`), so it also works in a plain
mitmproxy command. It imports nothing from cli/ and never writes files: the rules
file is written by the Wiretrace window, and read here.
Specs: docs/specs/003-qa-addon-mocks-faults-request-ids.md, 008-window-like-the-mockups.md,
022-more-devices-port-encrypted-hosts-breakpoints.md (pause, rewrite and map remote rules).

States of one API flow in `request`: TAGGED -> RULE (first applying rule, then DONE)
or DELAYING -> FAULTING -> MOCKING -> DONE, or DELAYING -> GONE when the client left or
mitmproxy is stopping.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import zlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

from mitmproxy import ctx, exceptions, flowfilter, http

# mitmdump does not have the wiretrace folder on sys.path.
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from addons import proxy_guard as guard  # noqa: E402
from addons import rewrite  # noqa: E402

logger = logging.getLogger(__name__)

MOCK_MARK = ":construction:"
FAULT_MARK = ":boom:"
FAULT_BODY = b'{"error": "injected by Wiretrace"}'
JSON = {"Content-Type": "application/json"}
MAX_ID_LENGTH = 128

RULES_VERSION = 1
MAX_RULES = 200
MAX_NAME = 80
MAX_PATH = 512
MAX_BODY_CONTAINS = 256
MAX_RULE_BODY = 1 << 20
MAX_RULE_DELAY_MS = 120_000
MIN_NTH, MAX_NTH = 2, 1_000
MAX_METHOD = 16
MOCK_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
RULE_ID = re.compile(r"[a-z0-9]{6,32}")
METHOD = re.compile(r"[A-Z]+")
ACTIONS = ("mock", "status", "delay", "drop", "pause", "rewrite", "map_remote")
# Spec 022: these change a request instead of answering it; they stack, and do not end the walk.
CHANGE_ACTIONS = ("rewrite", "map_remote")
APPLY_MODES = ("always", "once", "every_nth")
PAUSE_AT = ("request", "response", "both")
RULE_KEYS = {"id", "name", "enabled", "match", "action", "apply"}
MATCH_KEYS = {"method", "host", "path", "body_contains"}
ACTION_KEYS = {"type", "status", "body", "mock_file", "delay_ms"}
# Spec 022: keys of the newer actions. Missing ones default, so a 0.9.1 file loads unchanged; a rule
# keeps only the keys of its own action, so a file without the newer actions still loads in 0.9.1.
OPTIONAL_ACTION_KEYS: dict[str, Any] = {"pause_at": "request", "ops": [], "target": {}}
ACTION_OF_KEY = {"pause_at": "pause", "ops": "rewrite", "target": "map_remote"}
TARGET_KEYS = {"scheme", "host", "port"}
DEFAULT_PORTS = {"https": 443, "http": 80}
DNS_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
MAP_REFUSED = "Wiretrace refuses Map remote to an address on your network"
# Where a Map remote rule sent the request: {"from": the host the app asked for, "to": the target URL,
# "from_scheme", "from_port": the scheme and port it asked for}.
MAPPED_KEY = "wiretrace_mapped"
APPLY_KEYS = {"mode", "n"}
RELOAD_CHECK_S = 1.0
# The phase a pause rule still has to pause at, from the request hook to the response hook.
PAUSE_KEY = "wiretrace_pause"
NO_WINDOW = "no window"
# Response changes still to apply (rule names and their ops), and what each change did, for the window.
REWRITE_KEY = "wiretrace_rewrite"
CHANGES_KEY = "wiretrace_changes"


# NamedTuple, not dataclass: mitmproxy loads this file without registering it in
# sys.modules, which dataclasses cannot handle under `from __future__ import annotations`.
class Faults(NamedTuple):
    matcher: flowfilter.TFilter | None
    status: int
    delay_ms: int
    drop: bool

    @property
    def on(self) -> bool:
        return self.matcher is not None and bool(self.status or self.delay_ms or self.drop)


class Snapshot(NamedTuple):
    """Everything one request needs, validated; replaced as a whole, never edited."""

    api_hosts: tuple[str, ...] = ()
    mocks_dir: str = ""
    request_id_header: str = "X-Request-ID"
    faults: Faults = Faults(None, 0, 0, False)


def build_snapshot(hosts: Sequence[str], mocks_dir: str, header: str, fault_filter: str,
                   status: int, delay_ms: int, drop: bool) -> Snapshot:
    """Raise OptionsError if a value is invalid."""
    matcher = None
    if fault_filter.strip():
        try:
            matcher = flowfilter.parse(fault_filter.strip())
        except Exception as e:
            raise exceptions.OptionsError(f"qa_fault_filter: {e}") from None
        if not matcher:
            raise exceptions.OptionsError("qa_fault_filter: not a valid filter expression")
    if status != 0 and not 100 <= status <= 599:
        raise exceptions.OptionsError("qa_fault_status must be 0 (off) or 100 to 599")
    if delay_ms < 0:
        raise exceptions.OptionsError("qa_fault_delay_ms must not be negative")
    return Snapshot(
        api_hosts=tuple(h.strip().lower() for h in hosts if h.strip()),
        mocks_dir=mocks_dir,
        request_id_header=header,
        faults=Faults(matcher, status, delay_ms, drop),
    )


def is_api_host(host: str, api_hosts: Sequence[str]) -> bool:
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in api_hosts)


# The folder this checkout lives in. Mock files are served only from inside it.
WIRETRACE = Path(__file__).resolve().parent.parent


def _mocks_root(mocks_dir: str, wiretrace: str = "") -> Path | None:
    """The resolved mocks folder when it is a real directory inside the wiretrace folder.

    `wiretrace` is that folder when the launcher names one; otherwise this checkout.
    """
    if not mocks_dir:
        return None
    try:
        base = Path(wiretrace).resolve() if wiretrace else WIRETRACE.resolve()
        root = Path(mocks_dir).resolve()
        if root.is_dir() and root.is_relative_to(base):
            return root
    except (OSError, ValueError):
        return None
    return None


def request_method(request: http.Request) -> str:
    """The method as the client spelled it. `request.method` is always upper case."""
    return request.data.method.decode("utf-8", "surrogateescape")


def mock_file(mocks_dir: str, method: str, raw_path: str, wiretrace: str = "") -> tuple[Path, str] | None:
    """The mock file for a request and its label, or None. Never leaves `mocks_dir` or the wiretrace folder."""
    if method not in MOCK_METHODS:
        return None
    path = raw_path.split("?", 1)[0]
    if path == "/":
        segments = ["index"]
    elif path.startswith("/"):
        body = path[1:]
        segments = (body[:-1] if body.endswith("/") else body).split("/")
    else:
        return None
    if any(s in ("", ".", "..") for s in segments):
        return None
    label = "/".join([method, *segments]) + ".json"
    try:
        root = _mocks_root(mocks_dir, wiretrace)
        if root is None:
            return None
        file = (root / label).resolve()
        if file.is_relative_to(root) and file.is_file():
            return file, label
    except (OSError, ValueError):
        pass
    return None


def is_websocket_handshake(request: http.Request) -> bool:
    return request.headers.get("upgrade", "").strip().lower() == "websocket"


def asked_host(flow: http.HTTPFlow) -> str:
    """The host the app asked for: a Map remote rule may have sent the request elsewhere."""
    mapped = flow.metadata.get(MAPPED_KEY)
    if isinstance(mapped, dict) and isinstance(mapped.get("from"), str):
        return mapped["from"]
    return flow.request.pretty_host


def header_value(headers: http.Headers, name: str) -> str | None:
    value = headers.get(name)
    return value[:MAX_ID_LENGTH] if value else None


def _set_comment(flow: http.HTTPFlow, parts: list[str]) -> None:
    flow.comment = "; ".join(parts)


def replay_parts(comment: str) -> list[str]:
    return [part.strip() for part in (comment or "").split("; ") if part.strip().startswith("replay:")]


# Rules

class Target(NamedTuple):
    """Where a Map remote rule sends a request (spec 022, slice G)."""

    scheme: str
    host: str
    port: int

    @property
    def hostport(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == DEFAULT_PORTS[self.scheme] else f"{host}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.hostport}"


def parse_target(raw: object, match_host: str) -> tuple[Target | None, tuple[str, str] | None]:
    """A Map remote target, or the field and message of its first problem. Never this Mac or its network."""
    if not isinstance(raw, dict):
        return None, ("target", "must be {scheme, host, port}")
    if set(raw) != TARGET_KEYS:
        extra = sorted(set(raw) - TARGET_KEYS)
        return None, (f"target.{(extra or sorted(TARGET_KEYS - set(raw)))[0]}",
                      "is not a target field" if extra else "is missing")
    scheme, host, port = raw["scheme"], raw["host"], raw["port"]
    if scheme not in DEFAULT_PORTS:
        return None, ("target.scheme", "must be https or http")
    if not _is_int(port) or not 1 <= port <= 65535:
        return None, ("target.port", "must be 1 to 65535")
    if not isinstance(host, str):
        return None, ("target.host", "must be a DNS name or an IP address")
    host = host.strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    literal = guard._literal(host) if "%" not in host else None
    if literal is not None:
        host = literal
        if guard._blocked_for_map(host):
            return None, ("target.host", "must not be this Mac or an address on your network")
    elif host == "localhost" or host.endswith((".localhost", ".local")):
        return None, ("target.host", "must not be this Mac or an address on your network")
    else:
        labels = host.split(".")
        if len(host) > 253 or len(labels) < 2 or not all(DNS_LABEL.fullmatch(label) for label in labels) \
                or labels[-1].isdigit():
            return None, ("target.host", "must be a DNS name or an IP address")
    if match_host and host == match_host.lower() and port == DEFAULT_PORTS[scheme]:
        return None, ("target.host", "must differ from the host the rule matches")
    return Target(scheme, host, port), None


class Rule(NamedTuple):
    """One validated rule; `key` is its id plus a hash of its content, so new content means new counters."""

    id: str
    name: str
    enabled: bool
    method: str
    host: str
    path: re.Pattern
    with_query: bool
    body_contains: bytes
    action: str
    status: int
    body: bytes
    mock_file: str
    delay_ms: int
    mode: str
    n: int
    key: str
    data: dict
    pause_at: str = "request"
    ops: tuple = ()
    target: Target | None = None


class Rules(NamedTuple):
    """The rules in effect, in order; replaced as a whole, never edited."""

    rules: tuple[Rule, ...] = ()
    revision: str = ""


class RuleError(NamedTuple):
    message: str
    index: int | None = None
    field: str = ""


def _canonical(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _path_pattern(path: str) -> re.Pattern:
    return re.compile(".*".join(re.escape(part) for part in path.split("*")), re.DOTALL)


def resolve_mock(mocks_dir: str, label: str, wiretrace: str = "") -> Path | None:
    """The file `label` names inside `mocks_dir`, or None. Same rule as `mock_file()`: never leaves the folder."""
    if not mocks_dir or not label or "\\" in label or label.startswith("/"):
        return None
    if any(s in ("", ".", "..") for s in label.split("/")):
        return None
    try:
        root = _mocks_root(mocks_dir, wiretrace)
        if root is None:
            return None
        file = (root / label).resolve()
        if file.is_relative_to(root) and file.is_file():
            return file
    except (OSError, ValueError):
        pass
    return None


MOCK_NAME_PART = re.compile(r"[A-Za-z0-9._-]{1,80}")
MOCK_NAME_PROBLEM = ("The file name needs parts of 1 to 80 letters, digits, . _ or - joined by /, "
                     "none starting with a dot, and must end with .json.")


def mock_name_problem(label: object) -> str | None:
    """Why Wiretrace will not write a mock file named `label` (spec 022, slice F), or None."""
    if not isinstance(label, str) or not label.endswith(".json"):
        return MOCK_NAME_PROBLEM
    if any(not MOCK_NAME_PART.fullmatch(part) or part.startswith(".") for part in label.split("/")):
        return MOCK_NAME_PROBLEM
    return None


def mock_dir_for_write(mocks_dir: str, label: str, wiretrace: str = "") -> Path | None:
    """The folder of the mock file `label` names, created 0700 as needed; None when it would leave `mocks_dir`.

    The write-side twin of `resolve_mock`: no folder on the way may be a symlink, and the result stays
    inside the mocks folder, which itself stays inside the wiretrace folder.
    """
    if not mocks_dir or mock_name_problem(label):
        return None
    try:
        base = Path(wiretrace).resolve() if wiretrace else WIRETRACE.resolve()
        wanted = Path(mocks_dir).resolve()
        if not wanted.is_relative_to(base):
            return None
        if not wanted.exists():
            wanted.mkdir(mode=0o700, parents=True)
        root = _mocks_root(mocks_dir, wiretrace)
        if root is None:
            return None
        folder = root
        for part in label.split("/")[:-1]:
            folder = folder / part
            if folder.is_symlink():
                return None
            if not folder.exists():
                folder.mkdir(mode=0o700)
            elif not folder.is_dir():
                return None
        return folder if folder.resolve().is_relative_to(root) else None
    except (OSError, ValueError):
        return None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_rule(raw: object, index: int, api_hosts: Sequence[str], mocks_dir: str,
                wiretrace: str = "") -> Rule | RuleError:
    def fail(field: str, message: str) -> RuleError:
        return RuleError(message, index, field)

    if not isinstance(raw, dict):
        return fail("", "must be an object")
    if set(raw) != RULE_KEYS:
        unknown = sorted(set(raw) - RULE_KEYS)
        return fail(unknown[0] if unknown else sorted(RULE_KEYS - set(raw))[0],
                    "is not a rule field" if unknown else "is missing")
    rule_id, name, enabled = raw["id"], raw["name"], raw["enabled"]
    if not isinstance(rule_id, str) or not RULE_ID.fullmatch(rule_id):
        return fail("id", "must be 6 to 32 lowercase letters or digits")
    if not isinstance(name, str) or not name.strip():
        return fail("name", "must not be empty")
    if len(name) > MAX_NAME:
        return fail("name", f"must be at most {MAX_NAME} characters")
    if any(ord(c) < 32 for c in name):
        return fail("name", "must not contain control characters")
    if not isinstance(enabled, bool):
        return fail("enabled", "must be true or false")

    groups = {"match": MATCH_KEYS, "action": ACTION_KEYS, "apply": APPLY_KEYS}
    for group, keys in groups.items():
        value = raw[group]
        if not isinstance(value, dict):
            return fail(group, "must be an object")
        optional = set(OPTIONAL_ACTION_KEYS) if group == "action" else set()
        if not keys <= set(value) <= keys | optional:
            unknown = sorted(set(value) - keys - optional)
            missing = sorted(keys - set(value))
            return fail(f"{group}.{(unknown or missing)[0]}", "is not a rule field" if unknown else "is missing")
    match, action, apply = raw["match"], raw["action"], raw["apply"]
    action = {**OPTIONAL_ACTION_KEYS, **action}

    method, host, path, contains = match["method"], match["host"], match["path"], match["body_contains"]
    if not isinstance(method, str) or not (method == "ANY" or (len(method) <= MAX_METHOD and METHOD.fullmatch(method))):
        return fail("match.method", "must be ANY or an uppercase HTTP method")
    if not isinstance(host, str):
        return fail("match.host", "must be a string")
    hosts = [h.strip().lower() for h in api_hosts]
    if host and host.lower() not in hosts:
        return fail("match.host", "must be empty (any host) or one of the preset's API hosts")
    if not isinstance(path, str) or not path:
        return fail("match.path", "must not be empty")
    if len(path) > MAX_PATH:
        return fail("match.path", f"must be at most {MAX_PATH} characters")
    if not path.startswith(("/", "*")):
        return fail("match.path", "must start with / or *")
    if not isinstance(contains, str):
        return fail("match.body_contains", "must be a string")
    if len(contains) > MAX_BODY_CONTAINS:
        return fail("match.body_contains", f"must be at most {MAX_BODY_CONTAINS} characters")

    kind, status, body, mock, delay_ms = (action["type"], action["status"], action["body"],
                                          action["mock_file"], action["delay_ms"])
    if kind not in ACTIONS:
        return fail("action.type", "must be mock, status, delay, drop, pause, rewrite or map_remote")
    if not _is_int(status) or (kind in ("mock", "status") and not 100 <= status <= 599):
        return fail("action.status", "must be 100 to 599")
    if not isinstance(body, str):
        return fail("action.body", "must be a string")
    body_bytes = body.encode("utf-8", "surrogatepass")
    if len(body_bytes) > MAX_RULE_BODY:
        return fail("action.body", "must be at most 1 MiB")
    if not isinstance(mock, str):
        return fail("action.mock_file", "must be a string")
    if kind == "mock" and mock and resolve_mock(mocks_dir, mock, wiretrace) is None:
        return fail("action.mock_file", "must be a mock file of this preset")
    if not _is_int(delay_ms) or not 0 <= delay_ms <= MAX_RULE_DELAY_MS:
        return fail("action.delay_ms", f"must be 0 to {MAX_RULE_DELAY_MS:,} ms")
    if kind == "delay" and delay_ms == 0:
        return fail("action.delay_ms", "must be more than 0 for a delay rule")
    pause_at = action["pause_at"]
    if pause_at not in PAUSE_AT:
        return fail("action.pause_at", "must be request, response or both")
    if kind == "pause" and delay_ms:
        return fail("action.delay_ms", "must be 0 for a pause rule")
    ops: tuple = ()
    if kind == "rewrite":
        if delay_ms:
            return fail("action.delay_ms", "must be 0 for a Rewrite rule")
        ops, problem = rewrite.parse_ops(action["ops"])
        if problem:
            return fail(f"action.{problem[0]}", problem[1])
        action = {**action, "ops": [op.raw for op in ops]}
    target = None
    if kind == "map_remote":
        if delay_ms:
            return fail("action.delay_ms", "must be 0 for a Map remote rule")
        target, problem = parse_target(action["target"], host)
        if problem:
            return fail(f"action.{problem[0]}", problem[1])
        action = {**action, "target": target._asdict()}

    mode, n = apply["mode"], apply["n"]
    if mode not in APPLY_MODES:
        return fail("apply.mode", "must be always, once or every_nth")
    if not _is_int(n) or (mode == "every_nth" and not MIN_NTH <= n <= MAX_NTH):
        return fail("apply.n", f"must be {MIN_NTH} to {MAX_NTH:,}")

    kept = {key: action[key] for key in OPTIONAL_ACTION_KEYS if ACTION_OF_KEY[key] == kind}
    data = {"id": rule_id, "name": name, "enabled": enabled,
            "match": {"method": method, "host": host.lower(), "path": path, "body_contains": contains},
            "action": {"type": kind, "status": status, "body": body, "mock_file": mock, "delay_ms": delay_ms,
                       **kept},
            "apply": {"mode": mode, "n": n}}
    content = {k: v for k, v in data.items() if k != "enabled"}
    digest = hashlib.sha256(_canonical(content).encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return Rule(rule_id, name, enabled, method, host.lower(), _path_pattern(path), "?" in path,
                contains.encode("utf-8", "surrogatepass"), kind, status, body_bytes, mock, delay_ms,
                mode, n, f"{rule_id}:{digest}", data, pause_at, ops, target)


def parse_rules(data: object, api_hosts: Sequence[str], mocks_dir: str,
                wiretrace: str = "") -> Rules | RuleError:
    """Validate a rules document (`{version: 1, rules: [...]}`); never raises. Messages carry no values."""
    if not isinstance(data, dict):
        return RuleError("The rules file must be a JSON object")
    if set(data) - {"version", "rules"}:
        return RuleError("The rules file has unknown keys", None, sorted(set(data) - {"version", "rules"})[0])
    if data.get("version") != RULES_VERSION:
        return RuleError(f"version must be {RULES_VERSION}", None, "version")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        return RuleError("rules must be a list", None, "rules")
    if len(raw_rules) > MAX_RULES:
        return RuleError(f"At most {MAX_RULES} rules", None, "rules")
    rules, seen = [], set()
    for index, raw in enumerate(raw_rules):
        rule = _parse_rule(raw, index, api_hosts, mocks_dir, wiretrace)
        if isinstance(rule, RuleError):
            return rule
        if rule.id in seen:
            return RuleError("id is used by another rule", index, "id")
        seen.add(rule.id)
        rules.append(rule)
    revision = hashlib.sha256(_canonical([r.data for r in rules]).encode("utf-8", "surrogatepass")).hexdigest()[:16]
    return Rules(tuple(rules), revision)


def rules_document(rules: Sequence[dict]) -> dict:
    return {"version": RULES_VERSION, "rules": list(rules)}


def request_body_prefix(request: http.Request, limit: int = MAX_RULE_BODY) -> bytes:
    """Up to `limit` bytes of the decoded request body; an undecodable body is used as it travelled."""
    raw = request.raw_content or b""
    encoding = request.headers.get("content-encoding", "").strip().lower()
    try:
        if encoding == "gzip":
            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, limit)
        if encoding == "deflate":
            try:
                return zlib.decompressobj().decompress(raw, limit)
            except zlib.error:
                return zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw, limit)
        if encoding == "br":
            import brotli
            return brotli.Decompressor().process(raw, output_buffer_limit=limit)[:limit]
        if encoding == "zstd":
            import zstandard
            return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read(limit)
    except Exception:
        pass
    return raw[:limit]


def rewrite_message(message: http.Message, ops: tuple) -> list:
    """Apply a rule's changes to one message, in order; JSON changes only to a JSON body of at most 1 MiB."""
    results = rewrite.apply_header_ops(message.headers, ops)
    json_ops = tuple(op for op in ops if op.kind in ("set_json", "remove_json"))
    if json_ops:
        if len(request_body_prefix(message, rewrite.MAX_JSON_BODY + 1)) > rewrite.MAX_JSON_BODY:
            results += rewrite.skipped_all(json_ops, rewrite.TOO_LARGE)
        else:
            try:
                text = message.get_text(strict=True) or ""
            except ValueError:
                text = None
            if text is None or not rewrite.is_json_body(message.headers.get("content-type", ""), text[:64]):
                results += rewrite.skipped_all(json_ops, rewrite.NOT_JSON)
            else:
                new, found = rewrite.apply_json_ops(text, json_ops)
                try:
                    if new is not None:
                        message.text = new
                    results += found
                except ValueError:
                    results += rewrite.skipped_all(json_ops, rewrite.NOT_JSON)
    order = {id(op): i for i, op in enumerate(ops)}
    return sorted(results, key=lambda r: order.get(id(r.op), 0))


def change_results(rule_name: str, results: list) -> list[dict]:
    """What each change did, for the window's Changes tab. The values stay out of comments and logs."""
    out = []
    for r in results:
        op = r.op
        value = op.raw.get("value") if op.kind in ("set_header", "add_header", "set_json") else None
        out.append({"rule": rule_name, "on": op.on, "op": op.kind, "target": op.name or op.path_text,
                    "value": value, "applied": r.applied, "reason": r.reason})
    return out


def mismatch(rule: Rule, request: http.Request) -> str | None:
    """Why `rule` does not match the request, or None when it does. Assumes an API host."""
    if rule.method != "ANY" and request.method.upper() != rule.method:
        return f"method is {request.method.upper()}, the rule wants {rule.method}"
    if rule.host and not is_api_host(request.pretty_host, (rule.host,)):
        return "host differs"
    target = request.path if rule.with_query else request.path.split("?", 1)[0]
    if not rule.path.fullmatch(target):
        return "path does not match"
    if rule.body_contains and rule.body_contains not in request_body_prefix(request):
        return "body does not contain the text"
    return None


def should_apply(mode: str, n: int, matches: int, applied: int) -> bool:
    """`matches` already counts the current request."""
    if mode == "once":
        return applied == 0
    if mode == "every_nth":
        return n > 0 and matches % n == 0
    return True


def describe(rule: Rule) -> str:
    """What the app gets from an applied rule, in one line, without the body."""
    extra = f" after {rule.delay_ms:,} ms" if rule.delay_ms and rule.action != "delay" else ""
    if rule.action == "mock":
        source = f"mock file {rule.mock_file}" if rule.mock_file else "the typed-in body"
        return f"Mock response {rule.status} with {source}{extra}"
    if rule.action == "status":
        return f"Status {rule.status}{' with the typed-in body' if rule.body else ' with the default error body'}{extra}"
    if rule.action == "delay":
        return f"The server's response, {rule.delay_ms:,} ms later"
    if rule.action == "pause":
        return {"request": "Paused before it is sent, until you continue it in the window",
                "response": "The response is paused before the app gets it, until you send it",
                "both": "Paused before it is sent, and its response again before the app gets it"}[rule.pause_at]
    if rule.action == "rewrite":
        sides = sorted({op.on for op in rule.ops}, key=rewrite.SIDES.index)
        count = f"{len(rule.ops)} {'change' if len(rule.ops) == 1 else 'changes'}"
        return f"The server's response, with {count} to the {' and the '.join(sides)}"
    if rule.action == "map_remote" and rule.target is not None:
        return f"The response of {rule.target.url}, with the same path and query"
    return f"The connection is closed without a response{extra}"


def _comment_name(name: str) -> str:
    return name.replace(";", ",")


class QATools:
    def __init__(self) -> None:
        self._snapshot = Snapshot()
        self._summary = ""
        self._rules = Rules()
        self.rules_error = ""
        # Per rule key: [matches, applied, last match (Unix seconds) or None]. In memory only.
        self._stats: dict[str, list] = {}
        self.stats_version = 0
        self._rules_file = ""
        self._rules_stat: tuple | None = None
        self._rules_checked = 0.0
        self._wiretrace = ""

    def load(self, loader) -> None:
        loader.add_option("qa_api_hosts", Sequence[str], [],
                          "Hosts (and subdomains) the Wiretrace QA features apply to. Empty: nothing happens.")
        loader.add_option("qa_mocks_dir", str, "",
                          "Folder of mock files: <folder>/<METHOD>/<path>.json.")
        loader.add_option("qa_wiretrace_dir", str, "",
                          "Wiretrace folder. Mock files are served only from inside it. Empty: this checkout.")
        loader.add_option("qa_request_id_header", str, "X-Request-ID",
                          "Header read to show a request ID as the flow comment.")
        loader.add_option("qa_fault_filter", str, "",
                          "Filter expression selecting the requests to fault, e.g. ~u /api/v1/orders. "
                          "Empty: no faults. Response filters (~c, ~bs) never match.")
        loader.add_option("qa_fault_status", int, 0,
                          "Status to return instead of forwarding a matching request. 0: off.")
        loader.add_option("qa_fault_delay_ms", int, 0,
                          "Delay, in milliseconds, before a matching request continues.")
        loader.add_option("qa_fault_drop", bool, False,
                          "Close the connection of a matching request without a response.")
        loader.add_option("qa_rules_file", str, "",
                          "Rules file (JSON, written by the Wiretrace window). Empty or missing: no rules.")
        loader.add_option("qa_breakpoints", bool, False,
                          "Pause rules hold a request in the Wiretrace window. Off: they pass unpaused.")

    def configure(self, updated) -> None:
        o = ctx.options
        # Built first: a value that fails validation must leave the snapshot in effect untouched.
        snapshot = build_snapshot(list(o.qa_api_hosts), o.qa_mocks_dir, o.qa_request_id_header,
                                  o.qa_fault_filter, o.qa_fault_status, o.qa_fault_delay_ms, o.qa_fault_drop)
        self._snapshot = snapshot
        self._wiretrace = o.qa_wiretrace_dir
        # Rules are validated against the API hosts and the mocks folder, so any change re-reads them.
        if self._rules_file != o.qa_rules_file or updated & {
                "qa_api_hosts", "qa_mocks_dir", "qa_rules_file", "qa_wiretrace_dir"}:
            self._rules_file = o.qa_rules_file
            self.reload_rules()
        summary = (f"Wiretrace QA: {len(snapshot.api_hosts)} API hosts, "
                   f"mocks {'on' if snapshot.mocks_dir else 'off'}, "
                   f"faults {'on' if snapshot.faults.on else 'off'}, "
                   f"{sum(r.enabled for r in self._rules.rules)} rules on")
        if summary != self._summary:
            self._summary = summary
            logger.info(summary)

    # Rules: read here, written by the window (whole file, os.replace)

    @property
    def rules(self) -> Rules:
        return self._rules

    @property
    def rules_file(self) -> str:
        return self._rules_file

    def _stat_rules_file(self) -> tuple | None:
        try:
            st = os.stat(self._rules_file)
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size, st.st_ino

    def reload_rules(self) -> str:
        """Read the rules file now. On an invalid file the rules in effect stay; return the error, or ""."""
        self._rules_checked = time.monotonic()
        self._rules_stat = self._stat_rules_file() if self._rules_file else None
        if not self._rules_file or self._rules_stat is None:
            return self._install(Rules(), "")
        try:
            with open(self._rules_file, "rb") as f:
                raw = f.read(MAX_RULES * (MAX_RULE_BODY + 4096) + 1)
            data = json.loads(raw)
        except OSError:
            return self._reject("The rules file cannot be read")
        except ValueError:
            return self._reject("The rules file is not valid JSON")
        parsed = parse_rules(data, self._snapshot.api_hosts, self._snapshot.mocks_dir, self._wiretrace)
        if isinstance(parsed, RuleError):
            where = f"rule {parsed.index + 1}, " if parsed.index is not None else ""
            return self._reject(f"{where}{parsed.field or 'file'}: {parsed.message}")
        return self._install(parsed, "")

    def _reject(self, message: str) -> str:
        if message != self.rules_error:
            # The message names a field and a limit, never a value from the file.
            logger.warning("Wiretrace QA: rules file not applied (%s); the previous rules stay", message)
        self.rules_error = message
        self.stats_version += 1
        return message

    def _install(self, rules: Rules, error: str) -> str:
        changed = rules.revision != self._rules.revision
        self._rules = rules
        self.rules_error = error
        keys = {r.key for r in rules.rules}
        self._stats = {k: v for k, v in self._stats.items() if k in keys}
        if changed:
            self.stats_version += 1
        return error

    def maybe_reload_rules(self) -> None:
        """Re-read the file when it changed on disk; checked at most once per RELOAD_CHECK_S."""
        if not self._rules_file:
            return
        now = time.monotonic()
        if now - self._rules_checked < RELOAD_CHECK_S:
            return
        self._rules_checked = now
        if self._stat_rules_file() != self._rules_stat:
            self.reload_rules()

    def rule_stats(self) -> dict[str, dict]:
        """Counters of the rules in effect, by rule id."""
        out = {}
        for rule in self._rules.rules:
            matches, applied, last = self._stats.get(rule.key, (0, 0, None))
            out[rule.id] = {"matches": matches, "applied": applied, "last_ts": last}
        return out

    @property
    def api_hosts(self) -> tuple[str, ...]:
        return self._snapshot.api_hosts

    def mock_dir_for_write(self, name: str) -> Path | None:
        return mock_dir_for_write(self._snapshot.mocks_dir, name, self._wiretrace)

    @staticmethod
    def mock_name_problem(name: object) -> str | None:
        return mock_name_problem(name)

    def validate_rules(self, data: object) -> dict:
        """`{"rules": [normalized rule…]}`, or `{"error", "index", "field"}`. Changes nothing."""
        parsed = parse_rules(data, self._snapshot.api_hosts, self._snapshot.mocks_dir, self._wiretrace)
        if isinstance(parsed, RuleError):
            return {"error": parsed.message, "index": parsed.index, "field": parsed.field}
        return {"rules": [r.data for r in parsed.rules]}

    def test_rule(self, raw: object, flow: http.HTTPFlow) -> dict:
        """Whether a draft rule would match `flow`, and what the app would get. Counters stay untouched."""
        parsed = parse_rules(rules_document([raw]), self._snapshot.api_hosts, self._snapshot.mocks_dir,
                             self._wiretrace)
        if isinstance(parsed, RuleError):
            return {"error": parsed.message, "index": None, "field": parsed.field}
        rule = parsed.rules[0]
        if not is_api_host(flow.request.pretty_host, self._snapshot.api_hosts):
            return {"matches": False, "reason": "The request is not to an API host of the preset", "result": None}
        why = mismatch(rule, flow.request)
        if why is not None:
            return {"matches": False, "reason": f"No match: {why}", "result": None}
        notes = []
        if not rule.enabled:
            notes.append("the rule is off")
        if rule.mode == "once":
            notes.append("once: only until it has applied, then re-arm")
        elif rule.mode == "every_nth":
            notes.append(f"every {rule.n}th matching request")
        reason = "Matches" + (f" ({'; '.join(notes)})" if notes else "")
        return {"matches": True, "reason": reason, "result": describe(rule)}

    def rearm(self, rule_id: str) -> bool:
        for rule in self._rules.rules:
            if rule.id == rule_id:
                self._stats.pop(rule.key, None)
                self.stats_version += 1
                return True
        return False

    def pick_rule(self, rules: Rules, flow: http.HTTPFlow) -> Rule | None:
        return self.pick_rules(rules, flow)[1]

    def pick_rules(self, rules: Rules, flow: http.HTTPFlow) -> tuple[list[Rule], Rule | None]:
        """Count every enabled match in order (spec 022, rule order 1-3). Change rules whose apply mode
        says so are collected; the first answer rule that applies ends the walk. A change rule's applied
        counter moves only when `apply_changes` applies it."""
        changes: list[Rule] = []
        for rule in rules.rules:
            if not rule.enabled or mismatch(rule, flow.request) is not None:
                continue
            stats = self._stats.setdefault(rule.key, [0, 0, None])
            stats[0] += 1
            stats[2] = time.time()
            self.stats_version += 1
            if not should_apply(rule.mode, rule.n, stats[0], stats[1]):
                continue
            if rule.action in CHANGE_ACTIONS:
                changes.append(rule)
                continue
            stats[1] += 1
            return changes, rule
        return changes, None

    # Change rules (spec 022, slices E and G): applied only to a request that goes to a server.

    def _applied(self, rule: Rule) -> None:
        stats = self._stats.setdefault(rule.key, [0, 0, None])
        stats[1] += 1
        self.stats_version += 1

    def map_targets(self) -> frozenset[str]:
        """The target hosts of the enabled Map remote rules, which proxy_guard checks strictly."""
        return frozenset(r.target.host for r in self._rules.rules
                         if r.enabled and r.action == "map_remote" and r.target is not None)

    @staticmethod
    async def refused_target(target: Target) -> bool:
        try:
            found = await guard.resolve(target.host)
        except OSError:
            # The connection fails to resolve it too; proxy_guard checks again when it opens.
            return False
        return any(item.map_blocked for item in found)

    async def apply_changes(self, changes: list[Rule], flow: http.HTTPFlow, parts: list[str]) -> bool:
        """The first Map remote, then request changes in rule order; response changes are kept for the
        response hook. False when the Map remote target was refused and Wiretrace answered 502."""
        if not changes or flow.is_replay or not flow.killable:
            return True
        remote = next((r for r in changes if r.action == "map_remote"), None)
        if remote is not None and remote.target is not None and not is_websocket_handshake(flow.request):
            refused = await self.refused_target(remote.target)
            if not flow.killable:
                return False
            if refused:
                parts.append("map remote: refused, local address")
                _set_comment(flow, parts)
                flow.marked = FAULT_MARK
                flow.response = http.Response.make(502, json.dumps({"error": MAP_REFUSED}), JSON)
                return False
            self._applied(remote)
            asked = flow.request.pretty_host
            flow.metadata[MAPPED_KEY] = {"from": asked, "to": remote.target.url, "rule": remote.name,
                                         "from_scheme": flow.request.scheme, "from_port": flow.request.port}
            flow.request.scheme = remote.target.scheme
            flow.request.host = remote.target.host
            flow.request.port = remote.target.port
            parts.append(f"map remote: {_comment_name(asked)} → {remote.target.hostport}")
        results: list[dict] = flow.metadata.setdefault(CHANGES_KEY, [])
        later: list[dict] = []
        for rule in changes:
            if rule.action != "rewrite":
                continue
            self._applied(rule)
            parts.append(f"rewrite: {_comment_name(rule.name)} ({len(rule.ops)} "
                         f"{'change' if len(rule.ops) == 1 else 'changes'})")
            ops = tuple(op for op in rule.ops if op.on == "request")
            results += change_results(rule.name, rewrite_message(flow.request, ops))
            if any(op.on == "response" for op in rule.ops):
                later.append({"rule": rule.name, "ops": [op.raw for op in rule.ops if op.on == "response"]})
        if later:
            flow.metadata[REWRITE_KEY] = later
        if not results:
            flow.metadata.pop(CHANGES_KEY, None)
        _set_comment(flow, parts)
        return True

    def apply_response_changes(self, flow: http.HTTPFlow) -> None:
        later = flow.metadata.pop(REWRITE_KEY, None)
        # A response Wiretrace made is not the server's: it is never rewritten (invariant 2).
        if not later or flow.response is None or flow.marked in (MOCK_MARK, FAULT_MARK):
            return
        results: list[dict] = flow.metadata.setdefault(CHANGES_KEY, [])
        for entry in later:
            ops, problem = rewrite.parse_ops(entry["ops"])
            if problem is None:
                results += change_results(entry["rule"], rewrite_message(flow.response, ops))

    # Breakpoints (spec 022, slice D): mitmproxy holds an intercepted flow until the window resumes or kills it.

    @staticmethod
    def _window() -> Any:
        try:
            return ctx.master.addons.get("wiretraceui")
        except Exception:
            return None

    def pause(self, flow: http.HTTPFlow, phase: str, parts: list[str], original: http.Message | None = None) -> None:
        """Hold the flow at `phase` when the window can take it; else say why in the comment.
        `original` is the message before change rules, when they changed it."""
        window = self._window() if ctx.options.qa_breakpoints else None
        reason = window.pause_refusal() if window is not None else NO_WINDOW
        if reason is None:
            parts.append(f"breakpoint: {phase}")
            _set_comment(flow, parts)
            flow.intercept()
            window.paused(flow, phase, original)
        else:
            parts.append(f"breakpoint: not paused, {reason}")
            _set_comment(flow, parts)

    @staticmethod
    def pausable(flow: http.HTTPFlow) -> bool:
        return not flow.is_replay and not is_websocket_handshake(flow.request)

    async def apply_rule(self, rule: Rule, flow: http.HTTPFlow, parts: list[str], changes: list[Rule] = ()) -> None:
        """The answer rule; `changes` apply when the request still goes to the server (rule order 4)."""
        changes = list(changes)
        parts.append(f"rule: {_comment_name(rule.name)}")
        _set_comment(flow, parts)
        if rule.action == "pause":
            if not self.pausable(flow):
                await self.apply_changes(changes, flow, parts)
                return
            # The breakpoint shows the changed request; its Original, the request before any change.
            original = flow.request.copy()
            if not await self.apply_changes(changes, flow, parts):
                return
            if rule.pause_at in ("response", "both"):
                flow.metadata[PAUSE_KEY] = "response"
            if rule.pause_at in ("request", "both"):
                self.pause(flow, "request", parts, original)
            return
        if rule.delay_ms:
            await asyncio.sleep(rule.delay_ms / 1000)
            if not flow.killable:
                return
            parts.append(f"fault: delay {rule.delay_ms} ms")
            _set_comment(flow, parts)
        if rule.action == "delay":
            await self.apply_changes(changes, flow, parts)
        elif rule.action == "drop":
            parts.append("fault: dropped")
            _set_comment(flow, parts)
            flow.marked = FAULT_MARK
            flow.kill()
        elif rule.action == "status":
            parts.append(f"fault: status {rule.status}")
            _set_comment(flow, parts)
            flow.marked = FAULT_MARK
            flow.response = http.Response.make(rule.status, rule.body or FAULT_BODY, JSON)
        elif rule.action == "mock":
            body = rule.body
            if rule.mock_file:
                file = resolve_mock(self._snapshot.mocks_dir, rule.mock_file, self._wiretrace)
                try:
                    body = file.read_bytes() if file else None
                except OSError:
                    body = None
                if body is None:
                    # The file went away since the rule was saved: forward the request instead.
                    await self.apply_changes(changes, flow, parts)
                    return
            parts.append(f"mock: {rule.mock_file or 'rule body'}")
            _set_comment(flow, parts)
            flow.marked = MOCK_MARK
            flow.response = http.Response.make(rule.status, body, JSON)

    async def request(self, flow: http.HTTPFlow) -> None:
        snapshot = self._snapshot
        if not is_api_host(flow.request.pretty_host, snapshot.api_hosts):
            return
        self.maybe_reload_rules()
        # Invariant 1: this request keeps this snapshot, whatever a reload does during its delay.
        rules = self._rules

        # A replay keeps the "replay: <original id>" part the window gave it; anything else starts empty.
        parts: list[str] = replay_parts(flow.comment) if flow.is_replay == "request" else []
        request_id = header_value(flow.request.headers, snapshot.request_id_header)
        if request_id:
            parts.append(f"request-id: {request_id}")
            _set_comment(flow, parts)

        changes, rule = self.pick_rules(rules, flow) if rules.rules else ([], None)
        if rule is not None:
            await self.apply_rule(rule, flow, parts, changes)
            return

        faults = snapshot.faults
        if faults.on and faults.matcher(flow):
            if faults.delay_ms:
                await asyncio.sleep(faults.delay_ms / 1000)
                # killable is "live and not killed": the client may have left during the delay.
                if not flow.killable:
                    return
                parts.append(f"fault: delay {faults.delay_ms} ms")
                _set_comment(flow, parts)
            if faults.drop:
                parts.append("fault: dropped")
                _set_comment(flow, parts)
                flow.marked = FAULT_MARK
                flow.kill()
                return
            if faults.status:
                parts.append(f"fault: status {faults.status}")
                _set_comment(flow, parts)
                flow.marked = FAULT_MARK
                flow.response = http.Response.make(faults.status, FAULT_BODY, JSON)
                return

        found = mock_file(snapshot.mocks_dir, request_method(flow.request), flow.request.path, self._wiretrace)
        if found:
            file, label = found
            try:
                body = file.read_bytes()
            except OSError:
                body = None
            if body is not None:
                parts.append(f"mock: {label}")
                _set_comment(flow, parts)
                flow.marked = MOCK_MARK
                flow.response = http.Response.make(200, body, JSON)
                return
        await self.apply_changes(changes, flow, parts)

    def error(self, flow: http.HTTPFlow) -> None:
        # Nothing waits for the response any more; the ops would otherwise be saved with the flow.
        flow.metadata.pop(PAUSE_KEY, None)
        flow.metadata.pop(REWRITE_KEY, None)

    async def response(self, flow: http.HTTPFlow) -> None:
        snapshot = self._snapshot
        if not is_api_host(asked_host(flow), snapshot.api_hosts):
            flow.metadata.pop(REWRITE_KEY, None)
            return
        if not header_value(flow.request.headers, snapshot.request_id_header):
            request_id = header_value(flow.response.headers, snapshot.request_id_header)
            if request_id:
                # The request-id part comes first, ahead of any fault or mock part.
                _set_comment(flow, [f"request-id: {request_id}", *([flow.comment] if flow.comment else [])])
        pause = flow.metadata.pop(PAUSE_KEY, None) == "response" and flow.killable
        original = flow.response.copy() if pause and flow.metadata.get(REWRITE_KEY) else None
        self.apply_response_changes(flow)
        if pause:
            self.pause(flow, "response", [part for part in (flow.comment or "").split("; ") if part], original)
            # Wait here rather than after every hook: the flows file is written by a later hook, and
            # must get the response as it was sent to the app.
            await flow.wait_for_resume()


addons = [QATools()]
