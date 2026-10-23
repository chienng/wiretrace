"""Rewrite rules: header and JSON field changes (spec 022, slice E).

Pure functions on values; no mitmproxy state. addons/qa_tools.py parses a rule's changes with
`parse_ops` and applies them with `apply_header_ops` and `apply_json_ops`. Error messages and
results name a field, a header name or a path, never a value.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, NamedTuple

MAX_OPS = 20
MAX_HEADER_VALUE = 4096
MAX_PATH_PARTS = 20
MAX_PATH_CHARS = 256
MAX_JSON_VALUE = 64 << 10
MAX_JSON_BODY = 1 << 20
SIDES = ("request", "response")
OPS = ("set_header", "add_header", "remove_header", "set_json", "remove_json")
OP_KEYS = {
    "set_header": {"on", "op", "name", "value"},
    "add_header": {"on", "op", "name", "value"},
    "remove_header": {"on", "op", "name"},
    "set_json": {"on", "op", "path", "value"},
    "remove_json": {"on", "op", "path"},
}
REFUSED_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "keep-alive", "te",
                             "trailer", "upgrade"})
MASKED_HEADERS = frozenset({"authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key"})
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}")
KEY = re.compile(r'[^.\[\]"]+')
INDEX = re.compile(r"\[(0|[1-9][0-9]{0,8})\]")
NOT_FOUND = "not found"
NOT_JSON = "body is not JSON"
TOO_LARGE = "body is over 1 MiB"


class Op(NamedTuple):
    """One change. `path` is parsed from `path_text`; `value` is a header value or a parsed JSON value."""
    on: str
    kind: str
    name: str = ""
    path_text: str = ""
    path: tuple = ()
    value: Any = None
    raw: dict = {}


class ChangeResult(NamedTuple):
    op: Op
    applied: bool
    reason: str = ""


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def loads(text: str | bytes) -> Any:
    """Strict JSON: NaN and Infinity, which json.dumps would write back, are refused."""
    return json.loads(text, parse_constant=_reject_constant)


def parse_path(text: object) -> tuple | None:
    """`data.items[0]["a.b"]` -> ("data", "items", 0, "a.b"); None when it does not parse."""
    if not isinstance(text, str) or not text or len(text) > MAX_PATH_CHARS:
        return None
    parts: list = []
    i = 0
    while i < len(text):
        if text.startswith('["', i):
            try:
                key, end = json.JSONDecoder().raw_decode(text, i + 1)
            except ValueError:
                return None
            if not isinstance(key, str) or not text.startswith("]", end):
                return None
            parts.append(key)
            i = end + 1
            continue
        index = INDEX.match(text, i)
        if index:
            parts.append(int(index.group(1)))
            i = index.end()
            continue
        if parts:
            if text[i] != ".":
                return None
            i += 1
        key = KEY.match(text, i)
        if not key:
            return None
        parts.append(key.group())
        i = key.end()
    return tuple(parts) if len(parts) <= MAX_PATH_PARTS else None


def header_problem(name: object) -> str | None:
    if not isinstance(name, str) or not TOKEN.fullmatch(name):
        return "must be a header name (letters, digits and - _ . ! # $ % & ' * + ^ ` | ~)"
    lowered = name.lower()
    if lowered in REFUSED_HEADERS or lowered.startswith("proxy-"):
        return "is set by Wiretrace or the connection and cannot be changed"
    return None


def parse_ops(raw: object) -> tuple[tuple[Op, ...], tuple[str, str] | None]:
    """The changes of a Rewrite rule, or the field (`ops.2.name`) and message of the first problem."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_OPS:
        return (), ("ops", f"must be 1 to {MAX_OPS} changes")
    ops = []
    for i, item in enumerate(raw):
        def fail(key: str, message: str) -> tuple[tuple, tuple[str, str]]:
            return (), (f"ops.{i}.{key}" if key else f"ops.{i}", message)

        if not isinstance(item, dict):
            return fail("", "must be an object")
        kind = item.get("op")
        if kind not in OPS:
            return fail("op", "must be set_header, add_header, remove_header, set_json or remove_json")
        if set(item) != OP_KEYS[kind]:
            extra = sorted(set(item) - OP_KEYS[kind])
            return fail((extra or sorted(OP_KEYS[kind] - set(item)))[0], "is not a field of this change" if extra else "is missing")
        if item["on"] not in SIDES:
            return fail("on", "must be request or response")
        if kind.endswith("_header"):
            problem = header_problem(item["name"])
            if problem:
                return fail("name", problem)
            value = item.get("value", "")
            if not isinstance(value, str) or len(value) > MAX_HEADER_VALUE or any(c in value for c in "\r\n\0"):
                return fail("value", f"must be text of at most {MAX_HEADER_VALUE:,} characters, without a line break")
            ops.append(Op(item["on"], kind, name=item["name"], value=value, raw=dict(item)))
            continue
        path = parse_path(item["path"])
        if path is None:
            return fail("path", f"must be keys joined by . with [n] for items, at most {MAX_PATH_PARTS} parts "
                                f"and {MAX_PATH_CHARS} characters")
        value = None
        if kind == "set_json":
            text = item["value"]
            if not isinstance(text, str) or len(text.encode("utf-8", "surrogatepass")) > MAX_JSON_VALUE:
                return fail("value", "must be JSON text of at most 64 KiB")
            try:
                value = loads(text)
            except ValueError:
                return fail("value", 'must be JSON: true, 12, "text", null or {"a": 1}')
        ops.append(Op(item["on"], kind, path_text=item["path"], path=path, value=value, raw=dict(item)))
    return tuple(ops), None


def apply_header_ops(headers: Any, ops: tuple[Op, ...]) -> list[ChangeResult]:
    """Header changes on mitmproxy `Headers` (names case-insensitive), in order. JSON ops are ignored."""
    results = []
    for op in ops:
        if op.kind == "set_header":
            headers[op.name] = op.value
        elif op.kind == "add_header":
            headers.add(op.name, op.value)
        elif op.kind == "remove_header":
            if op.name not in headers:
                results.append(ChangeResult(op, False, NOT_FOUND))
                continue
            del headers[op.name]
        else:
            continue
        results.append(ChangeResult(op, True))
    return results


def _container(doc: Any, path: tuple) -> Any:
    """The object or array holding the last part of `path`, or None when a parent is missing."""
    node = doc
    for part in path[:-1]:
        if isinstance(part, int):
            if not isinstance(node, list) or part >= len(node):
                return None
        elif not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, (dict, list)) else None


def _apply_json(doc: Any, op: Op) -> bool:
    node = _container(doc, op.path)
    last = op.path[-1]
    if node is None or isinstance(last, int) != isinstance(node, list):
        return False
    if isinstance(node, list) and last >= len(node):
        return False
    if op.kind == "set_json":
        # The rule's parsed value is shared by every request it changes.
        node[last] = copy.deepcopy(op.value)
        return True
    if isinstance(node, list):
        del node[last]
        return True
    if last not in node:
        return False
    del node[last]
    return True


def apply_json_ops(text: str, ops: tuple[Op, ...]) -> tuple[str | None, list[ChangeResult]]:
    """JSON field changes on a body's text, in order: the new compact text, or None when nothing changed.

    A missing parent or item skips that change; a body that does not parse skips them all.
    """
    json_ops = [op for op in ops if op.kind in ("set_json", "remove_json")]
    if not json_ops:
        return None, []
    try:
        doc = loads(text)
    except (ValueError, RecursionError):
        return None, [ChangeResult(op, False, NOT_JSON) for op in json_ops]
    results = []
    for op in json_ops:
        applied = _apply_json(doc, op)
        results.append(ChangeResult(op, applied, "" if applied else NOT_FOUND))
    if not any(r.applied for r in results):
        return None, results
    try:
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")), results
    except (ValueError, RecursionError):
        return None, [ChangeResult(r.op, False, NOT_JSON) for r in results]


def skipped_all(ops: tuple[Op, ...], reason: str) -> list[ChangeResult]:
    return [ChangeResult(op, False, reason) for op in ops if op.kind in ("set_json", "remove_json")]


def is_json_body(content_type: str, text_start: str) -> bool:
    return "json" in content_type.lower() or text_start.lstrip()[:1] in ("{", "[")
