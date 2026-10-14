"""The built Wiretrace window ships in git: releases are packed with `git archive`, and QA Macs
have no Node to build it."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "ui" / "dist"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def test_the_built_window_is_present():
    index = (DIST / "index.html").read_text(encoding="utf-8")
    for asset in re.findall(r'(?:src|href)="/(assets/[^"]+)"', index):
        assert (DIST / asset).is_file(), f"ui/dist/index.html refers to a missing {asset}"


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="not a git checkout (release folder)")
def test_the_built_window_is_not_ignored_and_is_tracked():
    # --no-index also reports rules that match files already tracked; a rebuild writes new
    # hashed file names, which an ignore rule would silently leave out of the next commit.
    ignored = git("check-ignore", "--no-index", "-v", "ui/dist/index.html", "ui/dist/assets/x.js")
    assert ignored.returncode == 1, f"ui/dist/ is ignored:\n{ignored.stdout}"

    tracked = set(git("ls-files", "--", "ui/dist").stdout.splitlines())
    on_disk = {p.relative_to(ROOT).as_posix() for p in DIST.rglob("*")
               if p.is_file() and p.name != ".DS_Store"}
    assert on_disk <= tracked, f"not in git: {sorted(on_disk - tracked)}"
