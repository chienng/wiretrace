import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cli import session

NOW = datetime(2026, 10, 14, 12, 0, 0)


def make(sessions: Path, started: datetime, preset: str = "staging", target: str = "android",
         meta: bool = True) -> Path:
    folder = sessions / f"{started:%Y-%m-%d_%H%M%S}_{preset}_{target}"
    folder.mkdir(parents=True)
    (folder / "flows.mitm").write_bytes(b"flows")
    if meta:
        (folder / session.META).write_text("{}")
    return folder


@pytest.mark.parametrize("name, expected", [
    ("2026-10-14_091500_staging_android", datetime(2026, 10, 14, 9, 15)),
    ("2026-10-14_091500_my-app_v2_ios-sim", datetime(2026, 10, 14, 9, 15)),
    ("2026-10-14_091500_staging_android-emu", datetime(2026, 10, 14, 9, 15)),
    ("2026-10-14_091500_staging_device", datetime(2026, 10, 14, 9, 15)),
    ("2026-10-14_091500_staging_ios", datetime(2026, 10, 14, 9, 15)),
    ("2026-13-14_091500_staging_android", None),
    ("2026-10-14_091500_staging_windows", None),
    ("2026-10-14_091500__android", None),
    ("2026-10-14_091500_staging_android.bak", None),
    ("x2026-10-14_091500_staging_android", None),
    ("old-session", None),
    ("", None),
])
def test_started_reads_the_name(name, expected):
    assert session.started(name) == expected


def test_old_session_is_deleted_and_counted(tmp_path):
    old = make(tmp_path, NOW - timedelta(days=14, minutes=1))
    assert session.remove_old(tmp_path, NOW) == 1
    assert not old.exists()


def test_session_inside_the_keep_window_is_kept(tmp_path):
    kept = [make(tmp_path, NOW - timedelta(days=13)), make(tmp_path, NOW - timedelta(days=14), preset="exact"),
            make(tmp_path, NOW + timedelta(days=1), preset="future")]
    assert session.remove_old(tmp_path, NOW) == 0
    assert all(folder.is_dir() for folder in kept)


def test_keep_days_is_a_parameter(tmp_path):
    folder = make(tmp_path, NOW - timedelta(days=3))
    assert session.remove_old(tmp_path, NOW, keep_days=7) == 0 and folder.exists()
    assert session.remove_old(tmp_path, NOW, keep_days=2) == 1 and not folder.exists()


def test_keep_days_is_fourteen():
    assert session.KEEP_DAYS == 14


def test_keep_sessions_is_five():
    assert session.KEEP_SESSIONS == 5


def test_only_the_five_newest_sessions_are_kept(tmp_path):
    folders = [make(tmp_path, NOW - timedelta(hours=hours)) for hours in range(7, 0, -1)]
    assert session.remove_old(tmp_path, NOW) == 2
    assert not any(folder.exists() for folder in folders[:2])
    assert all(folder.is_dir() for folder in folders[2:])


def test_the_age_limit_still_applies_within_the_five_newest(tmp_path):
    old = make(tmp_path, NOW - timedelta(days=20))
    recent = make(tmp_path, NOW - timedelta(hours=1))
    assert session.remove_old(tmp_path, NOW) == 1
    assert not old.exists() and recent.is_dir()


def test_folders_without_meta_json_are_not_counted_toward_the_five(tmp_path):
    loose = [make(tmp_path, NOW - timedelta(minutes=minutes), preset=f"loose{minutes}", meta=False)
             for minutes in (1, 2, 3)]
    sessions = [make(tmp_path, NOW - timedelta(hours=hours)) for hours in range(5, 0, -1)]
    assert session.remove_old(tmp_path, NOW) == 0
    assert all(folder.is_dir() for folder in loose + sessions)


def test_keep_count_is_a_parameter(tmp_path):
    folders = [make(tmp_path, NOW - timedelta(hours=hours)) for hours in (3, 2, 1)]
    assert session.remove_old(tmp_path, NOW, keep_count=1) == 2
    assert [folder.exists() for folder in folders] == [False, False, True]
    assert session.remove_old(tmp_path, NOW, keep_count=0) == 1


def test_folder_with_another_name_is_kept(tmp_path):
    for name in ("notes", "2020-01-01_000000_staging_android.bak", "2020-01-01_000000_staging_linux",
                 "backup-2020-01-01_000000_staging_android"):
        (tmp_path / name).mkdir()
        (tmp_path / name / session.META).write_text("{}")
    assert session.remove_old(tmp_path, NOW) == 0
    assert len(list(tmp_path.iterdir())) == 4


def test_folder_without_meta_json_is_kept(tmp_path):
    folder = make(tmp_path, NOW - timedelta(days=30), meta=False)
    assert session.remove_old(tmp_path, NOW) == 0
    assert (folder / "flows.mitm").is_file()


def test_symlink_to_an_old_looking_folder_is_kept_and_its_target_untouched(tmp_path):
    outside = tmp_path / "outside"
    target = make(outside, NOW - timedelta(days=30))
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    link = sessions / "2020-01-01_000000_staging_android"
    link.symlink_to(target, target_is_directory=True)

    assert session.remove_old(sessions, NOW) == 0
    assert link.is_symlink() and (target / "flows.mitm").read_bytes() == b"flows"


def test_a_file_with_a_session_name_is_kept(tmp_path):
    file = tmp_path / "2020-01-01_000000_staging_android"
    file.write_text("not a folder")
    assert session.remove_old(tmp_path, NOW) == 0
    assert file.read_text() == "not a folder"


def test_symlink_inside_an_old_session_is_removed_without_touching_its_target(tmp_path):
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "file.txt").write_text("keep")
    sessions = tmp_path / "sessions"
    old = make(sessions, NOW - timedelta(days=30))
    (old / "link").symlink_to(precious, target_is_directory=True)

    assert session.remove_old(sessions, NOW) == 1
    assert (precious / "file.txt").read_text() == "keep"


def test_missing_sessions_folder_gives_zero(tmp_path):
    assert session.remove_old(tmp_path / "missing", NOW) == 0
    assert session.list_sessions(tmp_path / "missing") == []


def test_aware_now_is_compared_in_local_time(tmp_path):
    old = make(tmp_path, datetime.now() - timedelta(days=20))
    fresh = make(tmp_path, datetime.now() - timedelta(days=1), preset="fresh")
    assert session.remove_old(tmp_path, datetime.now(timezone.utc)) == 1
    assert not old.exists() and fresh.exists()


def test_only_old_ones_go_among_several(tmp_path):
    folders = [make(tmp_path, NOW - timedelta(days=d), preset=f"p{d}") for d in (1, 20, 40, 5)]
    assert session.remove_old(tmp_path, NOW) == 2
    assert [f.exists() for f in folders] == [True, False, False, True]


def test_list_sessions_is_oldest_first_and_skips_other_entries(tmp_path):
    newest = make(tmp_path, NOW)
    oldest = make(tmp_path, NOW - timedelta(days=3))
    (tmp_path / "notes").mkdir()
    (tmp_path / "2026-10-14_000000_x_android").write_text("file")
    assert session.list_sessions(tmp_path) == [oldest, newest]


def test_create_names_match_the_pattern(tmp_path):
    folder = session.create("my_preset-2", "ios-sim", {}, tmp_path, now=NOW.astimezone())
    assert session.started(folder.name) == NOW


def test_create_is_private_even_when_the_umask_is_permissive(tmp_path):
    previous = os.umask(0o022)
    try:
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        sessions.chmod(0o755)
        folder = session.create("staging", "android", {}, sessions, now=NOW.astimezone())
        assert sessions.stat().st_mode & 0o777 == 0o700
        assert folder.stat().st_mode & 0o777 == 0o700
        assert (folder / session.META).stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(previous)
