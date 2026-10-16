"""scripts/make-app.sh, run against a temporary HOME (docs/specs/014-mac-app-install-and-launcher.md)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cli import __version__

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "make-app.sh"

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("osacompile"),
                                reason="osacompile is macOS only")

FOREIGN_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleIdentifier</key><string>com.example.other</string></dict></plist>
"""


def make_app(home: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT)], env={**os.environ, "HOME": str(home)},
                          capture_output=True, text=True, timeout=120)


def plist_value(app: Path, key: str) -> str:
    return subprocess.run(["plutil", "-extract", key, "raw", "-o", "-", str(app / "Contents" / "Info.plist")],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_the_app_is_built_signed_and_points_at_this_folder(tmp_path):
    result = make_app(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "created: ~/Applications/Wiretrace.app\n"
    app = tmp_path / "Applications" / "Wiretrace.app"
    assert plist_value(app, "CFBundleIdentifier") == "com.safemeet.wiretrace"
    assert plist_value(app, "CFBundleName") == "Wiretrace"
    assert plist_value(app, "CFBundleShortVersionString") == __version__
    assert (app / "Contents" / "Resources" / "wiretrace-root").read_text() == f"{ROOT}\n"
    verify = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True)
    assert verify.returncode == 0, verify.stderr
    attributes = subprocess.run(["xattr", "-lr", str(app)], capture_output=True, text=True).stdout
    assert "com.apple.quarantine" not in attributes
    # Nothing else in ~/Applications: the temporary folder is gone.
    assert [p.name for p in (tmp_path / "Applications").iterdir()] == ["Wiretrace.app"]


def test_the_app_shows_the_wiretrace_icon(tmp_path):
    assert make_app(tmp_path).returncode == 0
    app = tmp_path / "Applications" / "Wiretrace.app"
    icon = app / "Contents" / "Resources" / "applet.icns"
    assert icon.read_bytes() == (ROOT / "app" / "Wiretrace.icns").read_bytes()
    assert plist_value(app, "CFBundleIconFile") == "applet"
    # With CFBundleIconName, macOS would show the default script icon from Assets.car.
    missing = subprocess.run(["plutil", "-extract", "CFBundleIconName", "raw", "-o", "-",
                              str(app / "Contents" / "Info.plist")], capture_output=True)
    assert missing.returncode != 0


def test_a_quarantined_download_does_not_pass_its_flag_to_the_app(tmp_path):
    # A copy of the folder, as if it came out of a downloaded .dmg.
    root = tmp_path / "wiretrace"
    for part in ("scripts/make-app.sh", "app/Wiretrace.applescript", "app/Wiretrace.icns", "cli/__init__.py"):
        (root / part).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / part, root / part)
    flag = "0083;00000000;Safari;"
    for part in ("app/Wiretrace.applescript", "app/Wiretrace.icns"):
        subprocess.run(["xattr", "-w", "com.apple.quarantine", flag, str(root / part)], check=True)
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run([str(root / "scripts" / "make-app.sh")], env={**os.environ, "HOME": str(home)},
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    app = home / "Applications" / "Wiretrace.app"
    assert "com.apple.quarantine" not in subprocess.run(["xattr", "-lr", str(app)], capture_output=True,
                                                        text=True).stdout


def test_our_app_made_from_another_folder_is_replaced(tmp_path):
    assert make_app(tmp_path).returncode == 0
    app = tmp_path / "Applications" / "Wiretrace.app"
    (app / "Contents" / "Resources" / "wiretrace-root").write_text("/old/place/wiretrace\n")
    (app / "Contents" / "Resources" / "left-over").write_text("x")
    result = make_app(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Wiretrace.app now opens {ROOT} (it opened /old/place/wiretrace)\n"
    assert (app / "Contents" / "Resources" / "wiretrace-root").read_text() == f"{ROOT}\n"
    assert not (app / "Contents" / "Resources" / "left-over").exists()


@pytest.mark.parametrize("plist", [FOREIGN_PLIST, None])
def test_an_app_with_another_identifier_is_left_as_it_is(tmp_path, plist):
    contents = tmp_path / "Applications" / "Wiretrace.app" / "Contents"
    contents.mkdir(parents=True)
    if plist is not None:
        (contents / "Info.plist").write_text(plist)
    (contents / "marker").write_text("theirs")
    result = make_app(tmp_path)
    assert result.returncode == 1
    shown = "com.example.other" if plist else "none"
    assert result.stderr == (f"WARN: ~/Applications/Wiretrace.app is not Wiretrace's "
                             f"(bundle identifier: {shown}); left as it is.\n")
    assert (contents / "marker").read_text() == "theirs"
    if plist is not None:
        assert (contents / "Info.plist").read_text() == plist
    assert [p.name for p in (tmp_path / "Applications").iterdir()] == ["Wiretrace.app"]


def test_the_applet_source_compiles(tmp_path):
    result = subprocess.run(["osacompile", "-o", str(tmp_path / "check.scpt"), str(ROOT / "app" / "Wiretrace.applescript")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (ROOT / "app" / "Wiretrace.applescript").read_bytes().isascii()
