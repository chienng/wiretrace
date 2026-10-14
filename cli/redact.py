"""Masking of secrets in `flows.har` and in the bug report zip.

Spec: docs/specs/005-redaction-bug-report-and-session-cleanup.md. HAR entries, JSON bodies,
URL-encoded forms, URLs and WebSocket text are masked by name, structurally. Bodies in any other
format are left as they are. Log lines are free text, so they are masked by pattern. A value is
only rewritten when something in it was masked, so a body without a secret keeps its exact bytes.

This module must not import mitmproxy.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache, cached_property
from typing import TYPE_CHECKING
from urllib.parse import unquote_plus

if TYPE_CHECKING:
    from .preset import Preset

MASK = "***"
DEFAULT_HEADERS = ("Authorization", "Proxy-Authorization", "Cookie", "Set-Cookie")
DEFAULT_FIELDS = ("password", "access_token", "refresh_token", "id_token", "client_secret",
                  "token", "api_key", "secret")
_FORM = "application/x-www-form-urlencoded"
_OPCODE_TEXT = 1


def normalize(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "")


@dataclass(frozen=True)
class Rules:
    headers: tuple[str, ...]
    fields: tuple[str, ...]

    @cached_property
    def header_set(self) -> frozenset[str]:
        return frozenset(name.lower() for name in self.headers)

    @cached_property
    def field_set(self) -> frozenset[str]:
        return frozenset(normalize(name) for name in self.fields)


def _unique(names: tuple[str, ...], key) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for name in names:
        seen.setdefault(key(name), name)
    return tuple(seen.values())


def rules_for(preset: Preset | None) -> Rules:
    """The defaults plus what the preset adds; a preset can never remove a default."""
    headers = DEFAULT_HEADERS + (tuple(preset.redact_headers) if preset else ())
    fields = DEFAULT_FIELDS + (tuple(preset.redact_fields) if preset else ())
    return Rules(_unique(headers, str.lower), _unique(fields, normalize))


def with_names(rules: Rules, headers: object, fields: object) -> Rules:
    """`rules` plus the string names in two lists (from meta.json); anything else is ignored."""
    def names(value: object) -> tuple[str, ...]:
        return tuple(n for n in value if isinstance(n, str) and n) if isinstance(value, list) else ()
    return Rules(_unique(rules.headers + names(headers), str.lower),
                 _unique(rules.fields + names(fields), normalize))


# Structured masking

def _mask_json(node: object, fields: frozenset[str]) -> tuple[object, int]:
    if isinstance(node, dict):
        out: dict = {}
        count = 0
        for key, value in node.items():
            if isinstance(key, str) and normalize(key) in fields:
                count += value != MASK
                out[key] = MASK
            else:
                out[key], inner = _mask_json(value, fields)
                count += inner
        return out, count
    if isinstance(node, list):
        items = [_mask_json(item, fields) for item in node]
        return [item for item, _ in items], sum(count for _, count in items)
    return node, 0


def redact_json_text(text: str, rules: Rules) -> tuple[str, int]:
    """Mask matching keys at any depth. Text that is not JSON, or has nothing to mask, is returned as is.

    Text that looks like JSON but does not parse (cut off, too deep, one object per line) is masked
    by pattern instead, so a malformed body cannot carry a secret through.
    """
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        if not text.lstrip().startswith(("{", "[")):
            return text, 0
        masked = mask_text(text, rules)
        return (masked, 1) if masked != text else (text, 0)
    masked, count = _mask_json(data, rules.field_set)
    if not count:
        return text, 0
    return json.dumps(masked, ensure_ascii=False), count


def _mask_pairs(query: str, rules: Rules) -> tuple[str, int]:
    """Mask the value of matching `name=value` pairs in a query string, keeping every other byte."""
    # Some servers also accept ';' between pairs; the separators are kept as they were.
    parts = re.split(r"([&;])", query)
    count = 0
    for i in range(0, len(parts), 2):
        name, equals, value = parts[i].partition("=")
        if equals and value != MASK and normalize(unquote_plus(name)) in rules.field_set:
            parts[i] = f"{name}={MASK}"
            count += 1
    return ("".join(parts), count) if count else (query, 0)


def redact_body(text: str, mime: str | None, rules: Rules) -> tuple[str, int]:
    """JSON first, then a URL-encoded form; any other format is left as it is."""
    masked, count = redact_json_text(text, rules)
    if count:
        return masked, count
    if (mime or "").split(";")[0].strip().lower() == _FORM:
        return _mask_pairs(text, rules)
    return text, 0


def redact_url(url: str, rules: Rules) -> tuple[str, int]:
    """Mask matching parameters in the query and in a `#a=b&…` fragment."""
    base, hash_sign, fragment = url.partition("#")
    path, question, query = base.partition("?")
    query, in_query = _mask_pairs(query, rules)
    in_fragment = 0
    if "=" in fragment:
        # A client-side route can come first: `#/callback?access_token=…`.
        route, route_question, params = fragment.rpartition("?") if "?" in fragment else ("", "", fragment)
        params, in_fragment = _mask_pairs(params, rules)
        fragment = f"{route}{route_question}{params}"
    if not (in_query or in_fragment):
        return url, 0
    return f"{path}{question}{query}{hash_sign}{fragment}", in_query + in_fragment


# HAR

def _entries(items: object) -> list[dict]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _mask_headers(headers: object, rules: Rules) -> int:
    count = 0
    for header in _entries(headers):
        name, value = header.get("name"), header.get("value")
        if not isinstance(name, str):
            continue
        if name.lower() in rules.header_set:
            count += value != MASK
            header["value"] = MASK
        elif name.lower() == "location" and isinstance(value, str):
            header["value"], inner = redact_url(value, rules)
            count += inner
    return count


def _mask_cookies(cookies: object) -> int:
    count = 0
    for cookie in _entries(cookies):
        if "value" in cookie:
            count += cookie["value"] != MASK
            cookie["value"] = MASK
    return count


def _mask_named(items: object, rules: Rules) -> int:
    """Query-string and form parameters: {"name": ..., "value": ...}."""
    count = 0
    for item in _entries(items):
        name = item.get("name")
        if isinstance(name, str) and normalize(name) in rules.field_set and "value" in item:
            count += item["value"] != MASK
            item["value"] = MASK
    return count


def _mask_key(holder: dict, key: str, count_fn) -> int:
    value = holder.get(key)
    if not isinstance(value, str):
        return 0
    holder[key], count = count_fn(value)
    return count


def _redact_request(request: dict, rules: Rules) -> int:
    count = _mask_headers(request.get("headers"), rules) + _mask_cookies(request.get("cookies"))
    count += _mask_key(request, "url", lambda v: redact_url(v, rules))
    count += _mask_named(request.get("queryString"), rules)
    post = request.get("postData")
    if isinstance(post, dict):
        count += _mask_named(post.get("params"), rules)
        count += _mask_key(post, "text", lambda v: redact_body(v, post.get("mimeType"), rules))
    return count


def _redact_response(response: dict, rules: Rules) -> int:
    count = _mask_headers(response.get("headers"), rules) + _mask_cookies(response.get("cookies"))
    count += _mask_key(response, "redirectURL", lambda v: redact_url(v, rules))
    content = response.get("content")
    if isinstance(content, dict) and content.get("encoding") != "base64":
        count += _mask_key(content, "text", lambda v: redact_body(v, content.get("mimeType"), rules))
    return count


def redact_har(har: dict, rules: Rules) -> tuple[dict, int]:
    """A masked copy of the HAR and the number of values masked. Tolerates any missing key."""
    masked = copy.deepcopy(har)
    log = masked.get("log") if isinstance(masked, dict) else None
    count = 0
    for entry in _entries(log.get("entries") if isinstance(log, dict) else None):
        request, response = entry.get("request"), entry.get("response")
        if isinstance(request, dict):
            count += _redact_request(request, rules)
        if isinstance(response, dict):
            count += _redact_response(response, rules)
        for message in _entries(entry.get("_webSocketMessages")):
            if message.get("opcode") == _OPCODE_TEXT:
                count += _mask_key(message, "data", lambda v: redact_json_text(v, rules))
    return masked, count


# Log text

def _spelling(name: str) -> str:
    """The name as a pattern that also accepts an optional `_` or `-` between its letters."""
    return "[_-]?".join(re.escape(char) for char in normalize(name))


def _boundary(name: str) -> str:
    return r"\b" if re.match(r"\w", name) else ""


_Replacement = str | Callable[[re.Match[str]], str]


@cache
def _text_patterns(rules: Rules) -> tuple[tuple[re.Pattern[str], _Replacement], ...]:
    flags = re.IGNORECASE
    headers = [re.escape(name) for name in rules.headers if name]
    fields = [_spelling(name) for name in rules.fields if normalize(name)]
    names = headers + fields
    patterns: list[tuple[str, str]] = []
    if headers:
        alternatives = "|".join(f"{_boundary(h)}{h}" for h in headers)
        patterns.append((rf"({alternatives})\s*:\s*[^\r\n]*", r"\1: ***"))
    patterns.append((r"\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***"))
    if names:
        quoted = rf'(?P<k>"(?:{"|".join(names)})"\s*:\s*)'
        patterns.append((quoted + r'"(?:[^"\\]|\\.)*"', r'\g<k>"***"'))
        patterns.append((quoted + r'(?!")[^\s,}\]]+', r'\g<k>"***"'))
    compiled: list[tuple[re.Pattern[str], _Replacement]] = [
        (re.compile(pattern, flags), repl) for pattern, repl in patterns]
    if fields:
        # A quoted value is masked up to its closing quote, so a value with spaces does not leak.
        pair = (rf"""(?P<k>\b(?:{"|".join(fields)})\s*[=:]\s*)"""
                rf"""(?:(?P<q>["'])(?:(?!(?P=q))[^\\]|\\.)*(?P=q)|["']?[^\s&,;"'}}\]]+)""")
        compiled.append((re.compile(pair, flags), _mask_pair_value))
    return tuple(compiled)


def _mask_pair_value(match: re.Match[str]) -> str:
    quote = match.group("q") or ""
    return f"{match.group('k')}{quote}{MASK}{quote}"


def mask_text(text: str, rules: Rules) -> str:
    """Mask header lines, bearer tokens and `field=value` / `"field": value` pairs in free text."""
    for pattern, repl in _text_patterns(rules):
        text = pattern.sub(repl, text)
    return text


def _mask_strings(node: object, rules: Rules) -> object:
    if isinstance(node, str):
        return mask_text(node, rules)
    if isinstance(node, dict):
        return {key: _mask_strings(value, rules) for key, value in node.items()}
    if isinstance(node, list):
        return [_mask_strings(value, rules) for value in node]
    return node


def mask_log_line(line: str, rules: Rules) -> str:
    """A JSON object line has matching keys and every text value masked; any other line is masked as a whole."""
    try:
        record = json.loads(line)
    except (ValueError, RecursionError):
        return mask_text(line, rules)
    if not isinstance(record, dict):
        return mask_text(line, rules)
    keyed, _ = _mask_json(record, rules.field_set)
    masked = _mask_strings(keyed, rules)
    if masked == record:
        return line
    return json.dumps(masked, ensure_ascii=False)
