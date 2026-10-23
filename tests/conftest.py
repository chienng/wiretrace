"""Every test runs against a temporary data folder, never ~/Library/Application Support/Wiretrace.

Set before any test module imports cli/: the data folder's constants are built at import time.
The folder is marked migrated, so no test moves the sessions of this checkout into it.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_DATA = Path(tempfile.mkdtemp(prefix="wiretrace-test-data-"))
os.environ["WIRETRACE_DATA"] = str(TEST_DATA)

from cli import datadir  # noqa: E402

datadir.ensure(TEST_DATA)
(TEST_DATA / datadir.MARKER).write_text("test\n")


@pytest.fixture(autouse=True)
def _test_data_folder(monkeypatch):
    """Subprocesses started by a test inherit the same folder."""
    monkeypatch.setenv(datadir.ENV, str(TEST_DATA))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_DATA, ignore_errors=True)
