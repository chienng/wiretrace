"""The data folder (docs/specs/023-user-data-outside-the-install-folder.md)."""

import errno
import io as std_io
import os
import stat
import zipfile
from pathlib import Path

import pytest
from mitmproxy import io
from mitmproxy.test import tflow

from addons import qa_tools
from cli import __main__ as cli_main
from cli import datadir, doctor, preset, redact, report, session, start

PRESET = "name: {name}\napi_hosts:\n  - api.example.com\n"
SESSION = "2026-10-14_091500_staging_android"


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def old_install(root: Path) -> Path:
    """An install folder as 0.9.1 and older left it."""
    (root / "presets").mkdir(parents=True)
    (root / "presets" / "staging.yaml").write_text(PRESET.format(name="staging"))
    (root / "presets" / "default.yaml").write_text(PRESET.format(name="default"))
    (root / "rules").mkdir()
    (root / "rules" / "staging.json").write_text('{"version": 1, "rules": []}\n')
    mock = root / "mocks" / "staging" / "GET" / "api" / "v1" / "profile.json"
    mock.parent.mkdir(parents=True)
    mock.write_text('{"name": "Ada"}\n')
    os.chmod(mock, 0o644)
    (root / "sessions" / SESSION).mkdir(parents=True)
    (root / "sessions" / SESSION / session.META).write_text("{}\n")
    (root / ".proxy-port").write_text("8890\n")
    return root


@pytest.fixture
def data(tmp_path) -> Path:
    return datadir.ensure(tmp_path / "data")


# Where the data folder is

def test_the_default_is_application_support_under_the_home_folder(tmp_path):
    assert datadir.resolve({}, home=tmp_path) == tmp_path / "Library" / "Application Support" / "Wiretrace"


def test_wiretrace_data_overrides_it(tmp_path):
    assert datadir.resolve({datadir.ENV: str(tmp_path / "x")}, home=tmp_path / "home") == tmp_path / "x"
    assert datadir.resolve({datadir.ENV: ""}, home=tmp_path) == tmp_path.joinpath(*datadir.DEFAULT_PARTS)


def test_a_relative_override_is_refused():
    with pytest.raises(datadir.DataDirError) as info:
        datadir.resolve({datadir.ENV: "wt-data"})
    assert str(info.value) == ("Wiretrace data folder wt-data: not an absolute path. Set WIRETRACE_DATA to a "
                               "folder you can write, or unset it.")


def test_data_dir_refuses_a_relative_folder_before_anything_uses_it(monkeypatch):
    monkeypatch.setattr(datadir, "DATA_DIR", Path("wt-data"))
    with pytest.raises(datadir.DataDirError, match="not an absolute path"):
        datadir.data_dir()
    with pytest.raises(datadir.DataDirError):
        datadir.prepare()


def test_the_tests_never_resolve_the_real_data_folder():
    real = datadir.resolve({}, home=Path.home())
    assert not datadir.same(datadir.DATA_DIR, real)
    assert not datadir.same(datadir.data_dir(), real)
    assert os.environ[datadir.ENV] == str(datadir.DATA_DIR)


def test_presets_rules_sessions_and_the_port_resolve_under_the_data_folder():
    data = datadir.DATA_DIR
    assert preset.PRESETS_DIR == data / "presets"
    assert session.SESSIONS_DIR == data / "sessions"
    assert start.rules_file(preset.Preset("staging", ("a.example.com",))) == data / "rules" / "staging.json"
    assert start.DATA_DIR == data
    (data / ".proxy-port").write_text("8899\n")
    try:
        assert doctor.saved_proxy_port() == 8899 and start.resolve_proxy_port(data) == 8899
    finally:
        (data / ".proxy-port").unlink()


def test_the_launcher_passes_the_data_folder_to_the_addons(tmp_path):
    p = preset.Preset("staging", ("a.example.com",))
    cmd = start.build_command(p, "proxy", "wiretrace", tmp_path / "s" / "flows.mitm", tmp_path, data_dir=tmp_path)
    assert f"qa_data_dir={tmp_path.resolve()}" in cmd
    assert f"qa_mocks_dir={tmp_path / 'mocks' / 'staging'}" in cmd
    assert f"qa_rules_file={tmp_path / 'rules' / 'staging.json'}" in cmd
    assert not any("qa_wiretrace_dir" in part for part in cmd)


# Creating it

def test_ensure_creates_application_support_and_the_folders_0700(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    data = datadir.resolve({}, home=home)
    assert datadir.ensure(data) == data
    assert (home / "Library" / "Application Support").is_dir()
    assert mode(data) == 0o700
    for name in datadir.SUBFOLDERS:
        assert mode(data / name) == 0o700


def test_an_unwritable_parent_names_the_folder(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir()
    os.chmod(parent, 0o500)
    try:
        with pytest.raises(datadir.DataDirError) as info:
            datadir.ensure(parent / "Wiretrace")
    finally:
        os.chmod(parent, 0o700)
    assert str(info.value) == (f"Wiretrace data folder {parent / 'Wiretrace'}: not writable. Set WIRETRACE_DATA "
                               "to a folder you can write, or unset it.")


def test_a_file_in_the_way_is_refused(tmp_path):
    (tmp_path / "data").write_text("")
    with pytest.raises(datadir.DataDirError, match="a file, not a folder"):
        datadir.ensure(tmp_path / "data")
    (tmp_path / "d2").mkdir()
    (tmp_path / "d2" / "sessions").write_text("")
    with pytest.raises(datadir.DataDirError, match=r"a file, not a folder \(sessions/\)"):
        datadir.ensure(tmp_path / "d2")


def test_a_home_path_is_shown_with_a_tilde(tmp_path):
    assert datadir.shown(tmp_path / "Library" / "x", home=tmp_path) == "~/Library/x"
    assert datadir.shown(Path("/elsewhere/x"), home=tmp_path) == "/elsewhere/x"


# Shipped examples

def examples(root: Path) -> Path:
    (root / "presets").mkdir(parents=True)
    (root / "presets" / "default.yaml").write_text(PRESET.format(name="default"))
    (root / "presets" / "example.yaml").write_text(PRESET.format(name="example"))
    (root / "rules").mkdir()
    (root / "rules" / "example.json").write_text('{"version": 1, "rules": []}\n')
    (root / "mocks" / "example" / "GET").mkdir(parents=True)
    (root / "mocks" / "example" / "GET" / "index.json").write_text("{}\n")
    return root


def test_a_missing_example_is_copied_and_a_changed_one_is_kept(tmp_path, data):
    shipped = examples(tmp_path / "examples")
    (data / "presets" / "default.yaml").write_text("# mine\n")
    datadir.seed_examples(shipped, data)
    assert (data / "presets" / "default.yaml").read_text() == "# mine\n"
    assert (data / "presets" / "example.yaml").read_text() == PRESET.format(name="example")
    assert (data / "rules" / "example.json").is_file()
    assert (data / "mocks" / "example" / "GET" / "index.json").is_file()
    assert mode(data / "presets" / "example.yaml") == 0o600
    (data / "presets" / "example.yaml").unlink()
    datadir.seed_examples(shipped, data)
    assert (data / "presets" / "example.yaml").is_file()


def test_the_release_ships_its_examples_under_examples():
    root = datadir.INSTALL_DIR
    for name in ("presets/default.yaml", "presets/example.yaml", "rules/example.json",
                 "mocks/example/GET/api/v1/profile.json"):
        assert (root / "examples" / name).is_file()
    preset.load_preset("default", root / "examples" / "presets")
    preset.load_preset("example", root / "examples" / "presets")


# Migration from the install folder

def test_migration_copies_presets_rules_mocks_and_the_port_and_moves_sessions(tmp_path, data):
    old = old_install(tmp_path / "wiretrace")
    moved = datadir.migrate(old, data)
    assert dict(moved.counts) == {"presets": 2, "rules": 1, "mocks": 1, ".proxy-port": 1, "sessions": 1}
    assert (data / "presets" / "staging.yaml").read_text() == PRESET.format(name="staging")
    assert (data / "rules" / "staging.json").is_file()
    copied = data / "mocks" / "staging" / "GET" / "api" / "v1" / "profile.json"
    assert copied.read_text() == '{"name": "Ada"}\n' and mode(copied) == 0o600
    assert mode(data / "mocks" / "staging" / "GET") == 0o700
    assert (data / ".proxy-port").read_text() == "8890\n" and mode(data / ".proxy-port") == 0o600
    assert (data / "sessions" / SESSION / session.META).is_file()
    # Copied, so 0.9.1 still finds them; the session was moved.
    assert (old / "presets" / "staging.yaml").is_file() and (old / ".proxy-port").is_file()
    assert not (old / "sessions" / SESSION).exists()
    assert not [p for p in data.rglob("*.tmp")]


def test_the_summary_line(tmp_path, data):
    old = old_install(tmp_path / "wiretrace")
    (data / "presets" / "default.yaml").write_text("# mine\n")
    text = datadir.summary(datadir.migrate(old, data), data)
    assert text == (f"Moved your data to {datadir.shown(data)}: 1 preset, 1 rule file, 1 mock file, 1 session, "
                    "the proxy port. Kept 1 existing file: presets/default.yaml.")
    assert (data / "presets" / "default.yaml").read_text() == "# mine\n"
    assert str(tmp_path) not in text.replace(datadir.shown(data), "")


def test_the_summary_counts_in_the_plural_and_shortens_long_lists(data):
    moved = datadir.Moved()
    moved.counts.update({"presets": 3, "rules": 2, "mocks": 5, "sessions": 12})
    moved.kept = [f"presets/p{i}.yaml" for i in range(7)]
    text = datadir.summary(moved, data)
    assert ": 3 presets, 2 rule files, 5 mock files, 12 sessions." in text
    assert "Kept 7 existing files: presets/p0.yaml, presets/p1.yaml, presets/p2.yaml, presets/p3.yaml, " \
           "presets/p4.yaml and 2 more." in text


def test_symlinks_are_skipped_and_never_followed(tmp_path, data):
    outside = tmp_path / "outside"
    (outside / "GET").mkdir(parents=True)
    (outside / "GET" / "secret.json").write_text("{}")
    (outside / "x.yaml").write_text(PRESET.format(name="x"))
    old = tmp_path / "wiretrace"
    (old / "presets").mkdir(parents=True)
    (old / "presets" / "x.yaml").symlink_to(outside / "x.yaml")
    old.joinpath("mocks").symlink_to(outside)
    (old / "rules").mkdir()
    (old / "rules" / "linked").symlink_to(outside)
    moved = datadir.migrate(old, data)
    assert not +moved.counts
    assert sorted(moved.skipped) == ["mocks/", "presets/x.yaml"]
    assert list((data / "presets").iterdir()) == [] and list((data / "mocks").iterdir()) == []


def test_a_symlink_inside_mocks_and_a_symlinked_session_are_skipped(tmp_path, data):
    old = tmp_path / "wiretrace"
    (old / "mocks" / "staging").mkdir(parents=True)
    (old / "mocks" / "staging" / "a.json").write_text("{}")
    (old / "mocks" / "staging" / "b.json").symlink_to("/etc/hosts")
    (old / "mocks" / "staging" / "dir").symlink_to("/etc")
    (tmp_path / "real-session").mkdir()
    (old / "sessions").mkdir()
    (old / "sessions" / SESSION).symlink_to(tmp_path / "real-session")
    moved = datadir.migrate(old, data)
    assert moved.counts["mocks"] == 1
    assert sorted(moved.skipped) == ["mocks/staging/b.json", "mocks/staging/dir", f"sessions/{SESSION}"]
    assert not (data / "sessions" / SESSION).exists()


def test_a_destination_symlink_is_never_written_through(tmp_path, data):
    old = old_install(tmp_path / "wiretrace")
    target = tmp_path / "elsewhere"
    target.mkdir()
    os.rmdir(data / "mocks")
    (data / "mocks").symlink_to(target)
    moved = datadir.migrate(old, data)
    assert [path for path, _ in moved.failed] == ["mocks/staging/GET/api/v1/profile.json"]
    assert list(target.iterdir()) == []


def test_invalid_preset_names_other_files_and_non_session_folders_are_left(tmp_path, data):
    old = tmp_path / "wiretrace"
    (old / "presets").mkdir(parents=True)
    for name in (".hidden.yaml", "has space.yaml", "notes.txt", "-dash.yaml"):
        (old / "presets" / name).write_text("x")
    (old / "rules").mkdir()
    (old / "rules" / "bad name.json").write_text("{}")
    (old / "sessions" / "my-notes").mkdir(parents=True)
    (old / "sessions" / "2026-10-14_091500_staging_phone").mkdir()
    (old / ".proxy-port").write_text("80\n")
    moved = datadir.migrate(old, data)
    assert not moved.found()
    assert (old / "sessions" / "my-notes").is_dir()
    assert not (data / ".proxy-port").exists()


def test_prepare_migrates_once_and_writes_the_marker(tmp_path, data):
    old = old_install(tmp_path / "wiretrace")
    text = datadir.prepare(data, old, tmp_path / "no-examples")
    assert text.startswith(f"Moved your data to {datadir.shown(data)}: 2 presets")
    marker = data / datadir.MARKER
    assert marker.read_text() == f"{datadir.__version__}\n" and mode(marker) == 0o600
    (old / "presets" / "later.yaml").write_text(PRESET.format(name="later"))
    assert datadir.prepare(data, old, tmp_path / "no-examples") is None
    assert not (data / "presets" / "later.yaml").exists()


def test_the_marker_is_written_when_nothing_was_found(tmp_path, data):
    (tmp_path / "empty").mkdir()
    assert datadir.prepare(data, tmp_path / "empty", tmp_path / "no-examples") is None
    assert (data / datadir.MARKER).is_file()


def test_a_data_folder_that_is_the_install_folder_migrates_nothing(tmp_path):
    old = old_install(tmp_path / "wiretrace")
    assert datadir.prepare(old, old, tmp_path / "no-examples") is None
    assert (old / "sessions" / SESSION).is_dir()


def test_a_crash_halfway_is_retried_and_the_retry_keeps_what_was_copied(tmp_path, data, monkeypatch):
    old = old_install(tmp_path / "wiretrace")
    real = datadir._sessions

    def crash(*args):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(datadir, "_sessions", crash)
    with pytest.raises(datadir.DataDirError):
        datadir.prepare(data, old, tmp_path / "no-examples")
    assert not (data / datadir.MARKER).exists()
    assert (data / "presets" / "staging.yaml").is_file()
    monkeypatch.setattr(datadir, "_sessions", real)
    text = datadir.prepare(data, old, tmp_path / "no-examples")
    assert ": 1 session." in text and "Kept 5 existing files" in text
    assert (data / datadir.MARKER).is_file() and (data / "sessions" / SESSION).is_dir()


def test_one_unreadable_file_is_named_and_the_rest_goes_on(tmp_path, data):
    old = old_install(tmp_path / "wiretrace")
    os.chmod(old / "presets" / "default.yaml", 0)
    try:
        moved = datadir.migrate(old, data)
    finally:
        os.chmod(old / "presets" / "default.yaml", 0o600)
    assert moved.failed == [("presets/default.yaml", "Permission denied")]
    assert moved.counts["presets"] == 1 and moved.counts["sessions"] == 1
    assert "Could not move 1 file: presets/default.yaml (" in datadir.summary(moved, data)


def test_a_session_on_another_volume_is_copied_and_the_original_stays(tmp_path, data, monkeypatch):
    old = old_install(tmp_path / "wiretrace")
    (old / "sessions" / SESSION / session.FLOWS).write_bytes(b"flows")
    (old / "sessions" / SESSION / "screenshots").mkdir()
    (old / "sessions" / SESSION / "screenshots" / "a.png").write_bytes(b"png")
    rename = os.rename

    def across_volumes(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        if src_dir_fd != dst_dir_fd:
            raise OSError(errno.EXDEV, "Cross-device link")
        return rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(datadir.os, "rename", across_volumes)
    moved = datadir.migrate(old, data)
    assert moved.counts["sessions"] == 1 and not moved.failed
    copied = data / "sessions" / SESSION
    assert (copied / session.FLOWS).read_bytes() == b"flows"
    assert (copied / "screenshots" / "a.png").read_bytes() == b"png"
    assert mode(copied) == 0o700 and mode(copied / "screenshots") == 0o700
    assert (old / "sessions" / SESSION / session.FLOWS).is_file()
    assert [p.name for p in (data / "sessions").iterdir()] == [SESSION]


# import-data

def test_import_data_takes_the_same_and_a_second_run_copies_nothing_new(tmp_path, data):
    old = old_install(tmp_path / "wiretrace-old")
    code, text = datadir.import_data(old, data)
    assert code == 0 and text.startswith(f"Moved your data to {datadir.shown(data)}: 2 presets, 1 rule file")
    code, text = datadir.import_data(old, data)
    assert code == 0
    assert text == (f"Moved your data to {datadir.shown(data)}: nothing new. Kept 5 existing files: "
                    "presets/default.yaml, presets/staging.yaml, rules/staging.json, "
                    "mocks/staging/GET/api/v1/profile.json, .proxy-port.")


def test_import_data_refuses_a_missing_folder_a_file_and_the_data_folder(tmp_path, data):
    assert datadir.import_data(tmp_path / "nope", data) == (1, f"No folder {tmp_path / 'nope'}.")
    (tmp_path / "file").write_text("")
    assert datadir.import_data(tmp_path / "file", data)[0] == 1
    assert datadir.import_data(data, data)[0] == 1
    (tmp_path / "empty").mkdir()
    assert datadir.import_data(tmp_path / "empty", data) == (
        0, f"No Wiretrace data in {tmp_path / 'empty'}: nothing imported.")


def test_the_import_data_and_data_commands(tmp_path, capsys):
    old = tmp_path / "wiretrace-old"
    (old / "rules").mkdir(parents=True)
    (old / "rules" / "imported.json").write_text("{}\n")
    try:
        assert cli_main.main(["import-data", str(old)]) == 0
        assert ": 1 rule file." in capsys.readouterr().out
        assert (datadir.DATA_DIR / "rules" / "imported.json").is_file()
        assert cli_main.main(["data"]) == 0
        assert capsys.readouterr().out == f"{datadir.DATA_DIR}\n"
        assert cli_main.main(["app", "data-dir"]) == 0
        assert capsys.readouterr().out == f"{datadir.DATA_DIR}\n"
    finally:
        (datadir.DATA_DIR / "rules" / "imported.json").unlink(missing_ok=True)


def test_a_relative_wiretrace_data_stops_every_command(monkeypatch, capsys):
    monkeypatch.setattr(datadir, "DATA_DIR", Path("wt-data"))
    assert cli_main.main(["data"]) == 1
    assert "Wiretrace data folder wt-data: not an absolute path." in capsys.readouterr().err


# doctor

def test_doctor_names_the_data_folder_and_warns_about_old_folders(tmp_path, data):
    old = old_install(tmp_path / "wiretrace")
    printed = []
    results = doctor.check_data(data, old, out=printed.append)
    assert printed and printed[0].startswith("Moved your data to")
    assert results[0] == doctor.Result(doctor.OK, "Data folder", datadir.shown(data))
    warnings = [r.detail for r in results[1:]]
    assert warnings[0] == (f"The install folder still has presets/ from an older version; Wiretrace now reads "
                           f"{datadir.shown(data)}. Delete presets/ there once you have checked your presets.")
    assert [w.split(" still has ")[1].split("/")[0] for w in warnings] == ["presets", "rules", "mocks", "sessions"]


def test_doctor_fails_with_the_folder_when_it_is_not_writable(tmp_path):
    parent = tmp_path / "locked"
    parent.mkdir()
    os.chmod(parent, 0o500)
    try:
        results = doctor.check_data(parent / "Wiretrace", tmp_path, out=lambda _: None)
    finally:
        os.chmod(parent, 0o700)
    assert results == [doctor.Result(doctor.FAIL, "Data folder", datadir.problem_text(parent / "Wiretrace",
                                                                                      "not writable"))]


# Containment

def test_a_preset_mocks_dir_outside_the_data_folder_is_refused(data):
    assert preset.mocks_dir_problem("mocks/staging", data) is None
    assert preset.mocks_dir_problem("/etc", data) == "must be relative to the Wiretrace data folder, not an absolute path"
    (data / "mocks" / "out").symlink_to("/")
    assert preset.mocks_dir_problem("mocks/out", data) == "must be a folder inside the Wiretrace data folder"


def test_a_mock_file_symlinked_out_of_the_data_folder_is_refused(tmp_path, data):
    (tmp_path / "secret.json").write_text("{}")
    mocks = data / "mocks" / "staging"
    (mocks / "GET").mkdir(parents=True)
    (mocks / "GET" / "ok.json").write_text("{}")
    (mocks / "GET" / "leak.json").symlink_to(tmp_path / "secret.json")
    assert qa_tools.mock_file(str(mocks), "GET", "/ok", str(data)) is not None
    assert qa_tools.mock_file(str(mocks), "GET", "/leak", str(data)) is None
    assert qa_tools.resolve_mock(str(mocks), "GET/leak.json", str(data)) is None
    # A mocks folder outside the data folder is not served, whatever the launcher says.
    assert qa_tools.mock_file(str(mocks), "GET", "/ok", str(tmp_path / "other")) is None
    assert qa_tools.mock_dir_for_write(str(tmp_path / "x"), "GET/a.json", str(data)) is None


def test_without_a_data_folder_option_the_addon_uses_the_resolved_one(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_tools, "default_data_dir", lambda: tmp_path)
    (tmp_path / "mocks" / "GET").mkdir(parents=True)
    (tmp_path / "mocks" / "GET" / "a.json").write_text("{}")
    assert qa_tools.mock_file(str(tmp_path / "mocks"), "GET", "/a") is not None
    monkeypatch.setattr(qa_tools, "default_data_dir", lambda: None)
    assert qa_tools.mock_file(str(tmp_path / "mocks"), "GET", "/a") is None


# Privacy: nothing a report holds names the data folder

def test_report_exports_hold_no_absolute_data_folder_path(data):
    p = preset.Preset("staging", ("api.example.com",))
    (data / "presets" / "staging.yaml").write_text(PRESET.format(name="staging"))
    meta = start.session_meta(p, "android", "proxy", "wiretrace", redact.rules_for(p))
    folder = session.create("staging", "android", meta, data / "sessions")
    f = tflow.tflow(resp=True)
    f.request.host = "api.example.com"
    with open(folder / session.FLOWS, "wb") as out:
        io.FlowWriter(out).add(f)
    (folder / session.APP_LOG).write_text('{"message": "hello"}\n')
    forbidden = {str(data), str(data.resolve()), str(Path.home())}

    with zipfile.ZipFile(report.create(folder, data / "presets").zip) as zf:
        blobs = [zf.read(name) for name in zf.namelist()]
    blobs.append((folder / session.META).read_bytes())
    blobs.append(repr(report.draft(folder, data / "presets", report.Include())).encode())
    exported = report.export(folder, data / "presets", "zip", report.Include())
    with zipfile.ZipFile(std_io.BytesIO(exported[1])) as zf:
        blobs += [zf.read(name) for name in zf.namelist()]
    for blob in blobs:
        for path in forbidden:
            assert path.encode() not in blob
