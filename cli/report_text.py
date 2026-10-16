"""The bug report form's description: Markdown (YouTrack, Jira Cloud) or Jira wiki (Jira Data Center).

Spec: docs/specs/012-bug-report-form.md. Every value given here is already masked; this module only
lays it out. Captured text cannot leave its code block: a Markdown fence is longer than any run of
backticks inside it, and `{code}` and `{noformat}` inside Jira wiki content are escaped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

FORMATS = ("markdown", "jira")
LOG_NOTE = "Log lines are masked by pattern only; check them before sharing."
CUT_NOTE = "… (cut, full body in the HAR)"
COLUMNS = ("Time", "Method", "Host", "Path", "Status", "Duration", "Request ID", "Wiretrace note")
MAX_ROWS = 100

_BACKTICKS = re.compile(r"`+")
_MACRO = re.compile(r"\{(code|noformat)", re.IGNORECASE)
# Jira wiki text effects, links, tables and macros. A backslash is left as is: `\\` is a line break.
_JIRA_SPECIAL = re.compile(r"([{}\[\]|*_+^~!#?-])")


@dataclass(frozen=True)
class Environment:
    preset: str
    target: str
    mode: str
    model: str
    os: str
    version: str


@dataclass(frozen=True)
class Request:
    method: str
    host: str
    path: str
    status: str
    duration: str
    request_id: str
    failed: bool


@dataclass(frozen=True)
class Body:
    """`text` is None for a binary body, which only the HAR carries."""

    text: str | None
    json: bool
    cut: bool
    size: int


@dataclass(frozen=True)
class Facts:
    session: str
    environment: Environment
    request: Request | None = None
    body: Body | None = None
    log_lines: tuple[str, ...] = ()
    # Shown under Log lines when there is none to show.
    no_log_lines: str = ""
    failed: tuple[Sequence[str], ...] = ()


def one_line(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", text)


def _longest_backticks(text: str) -> int:
    return max((len(run) for run in _BACKTICKS.findall(text)), default=0)


def md_code(text: str) -> str:
    """Inline code that no backtick in `text` can close."""
    text = one_line(text)
    fence = "`" * (_longest_backticks(text) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def md_block(text: str, info: str = "") -> list[str]:
    fence = "`" * max(3, _longest_backticks(text) + 1)
    return [f"{fence}{info}", text, fence]


def jira_text(text: str) -> str:
    return _JIRA_SPECIAL.sub(r"\\\1", one_line(text))


def jira_code(text: str) -> str:
    return "{{" + jira_text(text) + "}}"


def jira_block(text: str, macro: str, language: str = "") -> list[str]:
    opening = f"{{{macro}:{language}}}" if language else f"{{{macro}}}"
    return [opening, _MACRO.sub(lambda m: "\\{" + m.group(1), text), f"{{{macro}}}"]


class _Layout:
    def __init__(self, fmt: str) -> None:
        self.md = fmt == "markdown"

    def heading(self, text: str) -> str:
        return f"## {text}" if self.md else f"h2. {text}"

    def item(self, text: str) -> str:
        return f"- {text}" if self.md else f"* {text}"

    def code(self, text: str) -> str:
        return md_code(text) if self.md else jira_code(text)

    def text(self, text: str) -> str:
        return one_line(text) if self.md else jira_text(text)

    def body_block(self, text: str, is_json: bool) -> list[str]:
        if self.md:
            return md_block(text, "json" if is_json else "")
        return jira_block(text, "code", "json") if is_json else jira_block(text, "noformat")

    def log_block(self, text: str) -> list[str]:
        return md_block(text) if self.md else jira_block(text, "noformat")

    def table(self, rows: Sequence[Sequence[str]]) -> list[str]:
        if not rows:
            return ["No failed requests."]
        if self.md:
            def cell(value: str) -> str:
                return one_line(value).replace("|", "\\|")
            lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
            lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows[:MAX_ROWS]]
        else:
            lines = ["||" + "||".join(COLUMNS) + "||"]
            lines += ["|" + "|".join(jira_text(v) or " " for v in row) + "|" for row in rows[:MAX_ROWS]]
        if len(rows) > MAX_ROWS:
            lines += ["", f"and {len(rows) - MAX_ROWS} more"]
        return lines


def _environment(layout: _Layout, env: Environment) -> list[str]:
    def shown(value: str) -> str:
        return layout.text(value) if value else "not recorded"

    device = [layout.text(v) for v in (env.model, env.os) if v]
    last = " · ".join([*device, f"Wiretrace {layout.text(env.version)}"])
    return [layout.item(f"Preset: {shown(env.preset)} · Target: {shown(env.target)} · Mode: {shown(env.mode)}"),
            layout.item(f"Device: {last}" if device else last)]


def _request(layout: _Layout, request: Request) -> list[str]:
    parts = [f"{layout.code(f'{request.method} {request.host}{request.path}')} → {layout.text(request.status)}"]
    if request.duration != "-":
        parts.append(layout.text(request.duration))
    if request.request_id != "-":
        parts.append(f"request ID {layout.code(request.request_id)}")
    return [layout.item(" · ".join(parts))]


def _body(layout: _Layout, body: Body) -> list[str]:
    if body.text is None:
        return [f"Binary body ({body.size} bytes); see the HAR."]
    if not body.text:
        return ["Empty body."]
    lines = layout.body_block(body.text, body.json)
    return [*lines, CUT_NOTE] if body.cut else lines


def render(facts: Facts, fmt: str) -> str:
    """The description in `fmt` (one of FORMATS)."""
    layout = _Layout(fmt)
    lines = [
        layout.heading("Steps to reproduce"), "", "1. " if layout.md else "# ", "",
        layout.heading("Expected"), "", "",
        layout.heading("Actual"), "", "",
        layout.heading("Environment"), "", *_environment(layout, facts.environment), "",
    ]
    request = facts.request
    if request is None:
        lines += [layout.heading("Failed requests"), "", *layout.table(facts.failed), ""]
    else:
        lines += [layout.heading("Failed request" if request.failed else "Request"), "", *_request(layout, request), ""]
        if facts.body is not None:
            lines += [layout.heading("Response body"), "", *_body(layout, facts.body), ""]
        lines += [layout.heading("Log lines"), ""]
        lines += layout.log_block("\n".join(facts.log_lines)) if facts.log_lines else [facts.no_log_lines]
        lines += [""]
    lines.append(LOG_NOTE)
    return "\n".join(lines) + "\n"
