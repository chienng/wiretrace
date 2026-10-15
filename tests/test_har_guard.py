"""The stop-time HAR is built from trimmed flows.

A real `mitmdump -n -r` is required: `-s` hooks run before mitmproxy's savehar
(incident 2026-10-14). A unit call of the hook does not prove that order.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mitmproxy import io
from mitmproxy.test import tflow

from cli.bodies import HAR_LIMIT, PLACEHOLDER

ROOT = Path(__file__).resolve().parent.parent
VENV_BIN = Path(sys.prefix) / "bin"
needs_mitmdump = pytest.mark.skipif(not (VENV_BIN / "mitmdump").exists(), reason="mitmdump is not in the venv")


def _write_bomb(path: Path) -> None:
    flow = tflow.tflow(resp=True)
    flow.request.host = "api.example.com"
    flow.request.path = "/bomb"
    flow.response.headers["Content-Type"] = "text/plain"
    flow.response.headers["Content-Encoding"] = "gzip"
    flow.response.raw_content = gzip.compress(b"X" * (HAR_LIMIT + 1))
    with open(path, "wb") as out:
        io.FlowWriter(out).add(flow)


@needs_mitmdump
def test_real_mitmdump_har_contains_the_placeholder(tmp_path):
    flows = tmp_path / "flows.mitm"
    har = tmp_path / "flows.har"
    _write_bomb(flows)
    result = subprocess.run(
        [str(VENV_BIN / "mitmdump"), "-n", "-s", str(ROOT / "addons" / "har_guard.py"),
         "-r", str(flows), "--set", f"hardump={har}", "--set", f"confdir={tmp_path / 'confdir'}"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    text = har.read_text(encoding="utf-8")
    assert PLACEHOLDER in text
    assert len(text) < 1_000_000
    document = json.loads(text)
    content = document["log"]["entries"][0]["response"]["content"]
    assert content["text"] == PLACEHOLDER
    names = [header["name"].lower() for header in document["log"]["entries"][0]["response"]["headers"]]
    assert "content-encoding" not in names
