"""The product's old name appears nowhere in the repo."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "sessions",
}

SKIP_UNDER = {"docs/images", "ui/dist", "ui/node_modules"}

# Split so this file does not contain the name it looks for.
OLD = ("dv", "lens")

PATTERNS = [
    re.compile(OLD[0] + OLD[1], re.I),
    re.compile(r"\b" + OLD[0] + r"[\s\\#/*>_-]*" + OLD[1], re.I),
]


def is_text_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def files() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in SKIP_DIRS and rel(here / d) not in SKIP_UNDER
        )
        found.extend(here / f for f in sorted(filenames))
    return found


def scan() -> tuple[list[str], set[str]]:
    hits: list[str] = []
    scanned: set[str] = set()
    for path in files():
        r = rel(path)
        if not is_text_file(path):
            continue
        scanned.add(r)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        found = {text.count("\n", 0, m.start()) + 1 for p in PATTERNS for m in p.finditer(text)}
        hits.extend(f"{r}:{no}:{lines[no - 1]}" for no in sorted(found))
    return hits, scanned


def test_old_product_name_is_gone():
    hits, scanned = scan()
    assert {"wiretrace", "cli/__init__.py", "addons/wiretrace_ui.py", "ui/src/App.tsx",
            "docs/user-guide.md", "tests/test_names.py"} <= scanned
    assert not hits, "Old product name found:\n" + "\n".join(hits)
