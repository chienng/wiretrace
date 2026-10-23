"""The data folder: what the tester creates, kept outside the install folder (docs/specs/023).

presets/, rules/, mocks/, sessions/ and .proxy-port live in ~/Library/Application Support/Wiretrace,
or in WIRETRACE_DATA. Installing a new version replaces the install folder and never touches them.
Code, .venv, ui/dist, examples/, app-start.log and .app-last stay in the install folder.

Standard library only: doctor imports this, and so do the add-ons when mitmweb runs them directly.

Migration and import (invariants): only preset and rules files with a valid name, regular files
under mocks/, session folders and a valid .proxy-port are taken. Nothing is read through a symlink
in the source and nothing is written through one in the data folder; every folder is opened
relative to its parent with O_NOFOLLOW. A destination that exists is kept, never overwritten.
Files are written 0600 and folders created 0700. A file that fails is named in the summary and the
pass goes on. The summary holds counts and paths relative to the folders, never an absolute path.
"""

from __future__ import annotations

import errno
import os
import secrets
import shutil
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

ENV = "WIRETRACE_DATA"
INSTALL_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = INSTALL_DIR / "examples"
PRESETS, RULES, MOCKS, SESSIONS = "presets", "rules", "mocks", "sessions"
SUBFOLDERS = (PRESETS, RULES, MOCKS, SESSIONS)
PROXY_PORT_FILE = ".proxy-port"
# Written once the install folder was migrated: the version, 0600.
MARKER = ".migrated"
DEFAULT_PARTS = ("Library", "Application Support", "Wiretrace")
# Finder's folder settings, not a mock file.
IGNORED_NAMES = frozenset({".DS_Store"})
# Paths named in one part of the summary before "and N more".
LISTED = 5

_DIR = os.O_RDONLY | os.O_DIRECTORY
_KINDS = ((PRESETS, "preset", "presets"), (RULES, "rule file", "rule files"),
          (MOCKS, "mock file", "mock files"), (SESSIONS, "session", "sessions"))


class DataDirError(Exception):
    """The data folder cannot be used. The message is shown to the user as is."""


def problem_text(path: object, reason: str) -> str:
    return f"Wiretrace data folder {path}: {reason}. Set {ENV} to a folder you can write, or unset it."


def resolve(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """WIRETRACE_DATA when set, else ~/Library/Application Support/Wiretrace. Raises DataDirError."""
    value = (os.environ if environ is None else environ).get(ENV, "")
    if value:
        path = Path(value)
        if not path.is_absolute():
            raise DataDirError(problem_text(value, "not an absolute path"))
        return path
    return (Path.home() if home is None else home).joinpath(*DEFAULT_PARTS)


def _configured() -> Path:
    try:
        return resolve()
    except DataDirError:
        # Kept as given: data_dir() refuses it before anything is read or written there.
        return Path(os.environ[ENV])


# Resolved once per process: the constants of preset.py, session.py and start.py are built from it.
DATA_DIR = _configured()


def data_dir() -> Path:
    """DATA_DIR, or DataDirError when WIRETRACE_DATA is not an absolute path."""
    if not DATA_DIR.is_absolute():
        raise DataDirError(problem_text(DATA_DIR, "not an absolute path"))
    return DATA_DIR


def shown(path: Path, home: Path | None = None) -> str:
    """`path` with the home folder written as ~, for the Terminal and the window only."""
    try:
        rel = path.relative_to(Path.home() if home is None else home)
    except ValueError:
        return str(path)
    return "~" if rel == Path() else f"~/{rel.as_posix()}"


def inside(path: str | Path, data: Path | None = None) -> str:
    """`path` relative to the data folder when it is inside it, else as given."""
    try:
        base = (DATA_DIR if data is None else data).resolve()
        return Path(path).resolve().relative_to(base).as_posix()
    except (ValueError, OSError):
        return str(path)


def same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _reason(e: OSError) -> str:
    return e.strerror or type(e).__name__


def ensure(data: Path | None = None) -> Path:
    """Create the data folder and its four subfolders (0700) where missing. Raises DataDirError."""
    data = data_dir() if data is None else data
    for name in ("", *SUBFOLDERS):
        folder = data / name if name else data
        where = f" ({name}/)" if name else ""
        try:
            os.makedirs(folder, mode=0o700, exist_ok=True)
        except FileExistsError:
            raise DataDirError(problem_text(shown(data), f"a file, not a folder{where}")) from None
        except NotADirectoryError:
            raise DataDirError(problem_text(shown(data), "a part of the path is a file, not a folder")) from None
        except PermissionError:
            raise DataDirError(problem_text(shown(data), f"not writable{where}")) from None
        except OSError as e:
            raise DataDirError(problem_text(shown(data), f"{_reason(e)}{where}")) from None
        if not os.access(folder, os.W_OK | os.X_OK):
            raise DataDirError(problem_text(shown(data), f"not writable{where}"))
    return data


@dataclass
class Moved:
    """What one migration or import did. Paths are relative to the source and data folders."""

    counts: Counter = field(default_factory=Counter)
    kept: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def found(self) -> bool:
        return bool(+self.counts or self.kept or self.skipped or self.failed)


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _listing(items: list[str]) -> str:
    text = ", ".join(items[:LISTED])
    return f"{text} and {len(items) - LISTED} more" if len(items) > LISTED else text


def summary(moved: Moved, data: Path) -> str:
    parts = [_plural(moved.counts[kind], one, many) for kind, one, many in _KINDS if moved.counts[kind]]
    if moved.counts[PROXY_PORT_FILE]:
        parts.append("the proxy port")
    text = f"Moved your data to {shown(data)}: {', '.join(parts) if parts else 'nothing new'}."
    if moved.kept:
        text += f" Kept {_plural(len(moved.kept), 'existing file', 'existing files')}: {_listing(moved.kept)}."
    if moved.skipped:
        text += f" Skipped {_plural(len(moved.skipped), 'symlink', 'symlinks')}: {_listing(moved.skipped)}."
    if moved.failed:
        failed = [f"{path} ({reason})" for path, reason in moved.failed]
        text += f" Could not move {_plural(len(failed), 'file', 'files')}: {_listing(failed)}."
    return text


# Copying, relative to open folders

def _is_link(name: str, dir_fd: int) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _exists(name: str, dir_fd: int) -> bool:
    try:
        os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _entries(dir_fd: int) -> list[os.DirEntry]:
    with os.scandir(dir_fd) as found:
        return sorted(found, key=lambda entry: entry.name)


def _open_sub(name: str, dir_fd: int) -> int:
    return os.open(name, _DIR | os.O_NOFOLLOW, dir_fd=dir_fd)


def _dest_dir(root: int, parts: tuple[str, ...]) -> int:
    """The folder `parts` under the open folder `root`, created 0700 where missing; never through a symlink."""
    fd = os.dup(root)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = _open_sub(part, fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


class _Symlink(Exception):
    pass


def _copy_file(src_dir: int, name: str, dst_dir: int) -> bool:
    """Copy the regular file `name` from one open folder to the other, 0600.

    False when the destination exists. The copy appears whole or not at all: it is written under a
    temporary name and linked into place, which fails rather than replace a file of that name.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src_dir)
    except OSError as e:
        if e.errno == errno.ELOOP or _is_link(name, src_dir):
            raise _Symlink from None
        raise
    with os.fdopen(fd, "rb") as src:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
        if _exists(name, dst_dir):
            return False
        tmp = f".{name}.{secrets.token_hex(4)}.tmp"
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dst_dir)
        try:
            with os.fdopen(out, "wb") as dst:
                os.fchmod(out, 0o600)
                shutil.copyfileobj(src, dst)
            try:
                os.link(tmp, name, src_dir_fd=dst_dir, dst_dir_fd=dst_dir)
            except FileExistsError:
                return False
        finally:
            try:
                os.unlink(tmp, dir_fd=dst_dir)
            except OSError:
                pass
    return True


def _take(src_dir: int, name: str, dst_dir: int, rel: str, moved: Moved, kind: str) -> None:
    try:
        copied = _copy_file(src_dir, name, dst_dir)
    except _Symlink:
        moved.skipped.append(rel)
        return
    except OSError as e:
        moved.failed.append((rel, _reason(e)))
        return
    if copied:
        moved.counts[kind] += 1
    else:
        moved.kept.append(rel)


def _open_source(name: str, src: int, moved: Moved) -> int | None:
    """The source's subfolder `name`, or None when it is missing, not a folder, or a symlink (skipped)."""
    try:
        return _open_sub(name, src)
    except FileNotFoundError:
        return None
    except OSError as e:
        if _is_link(name, src):
            moved.skipped.append(f"{name}/")
        elif e.errno != errno.ENOTDIR:
            moved.failed.append((f"{name}/", _reason(e)))
        return None


def _named_files(src: int, dst: int, folder: str, suffix: str, moved: Moved) -> None:
    """`<folder>/<name><suffix>` where the name is a valid preset name."""
    from .preset import _NAME

    folder_fd = _open_source(folder, src, moved)
    if folder_fd is None:
        return
    try:
        out = None
        for entry in _entries(folder_fd):
            stem = entry.name[:-len(suffix)] if entry.name.endswith(suffix) else ""
            if not _NAME.fullmatch(stem):
                continue
            rel = f"{folder}/{entry.name}"
            if entry.is_symlink():
                moved.skipped.append(rel)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if out is None:
                try:
                    out = _dest_dir(dst, (folder,))
                except OSError as e:
                    moved.failed.append((rel, _reason(e)))
                    continue
            _take(folder_fd, entry.name, out, rel, moved, folder)
        if out is not None:
            os.close(out)
    finally:
        os.close(folder_fd)


def _tree(src_dir: int, dst: int, parts: tuple[str, ...], shown_as: str, moved: Moved, kind: str) -> None:
    """Every regular file under the open folder `src_dir`, into `parts` under the open folder `dst`."""
    for entry in _entries(src_dir):
        if entry.name in IGNORED_NAMES:
            continue
        rel = f"{shown_as}/{entry.name}"
        if entry.is_symlink():
            moved.skipped.append(rel)
        elif entry.is_dir(follow_symlinks=False):
            try:
                child = _open_sub(entry.name, src_dir)
            except OSError as e:
                moved.failed.append((f"{rel}/", _reason(e)))
                continue
            try:
                _tree(child, dst, (*parts, entry.name), rel, moved, kind)
            finally:
                os.close(child)
        elif entry.is_file(follow_symlinks=False):
            try:
                out = _dest_dir(dst, parts)
            except OSError as e:
                moved.failed.append((rel, _reason(e)))
                continue
            try:
                _take(src_dir, entry.name, out, rel, moved, kind)
            finally:
                os.close(out)


def _mocks(src: int, dst: int, moved: Moved) -> None:
    folder_fd = _open_source(MOCKS, src, moved)
    if folder_fd is None:
        return
    try:
        _tree(folder_fd, dst, (MOCKS,), MOCKS, moved, MOCKS)
    finally:
        os.close(folder_fd)


def _port(src: int, dst: int, moved: Moved) -> None:
    from .doctor import MAX_PORT_FILE_BYTES, port_from_bytes

    try:
        fd = os.open(PROXY_PORT_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src)
    except FileNotFoundError:
        return
    except OSError:
        if _is_link(PROXY_PORT_FILE, src):
            moved.skipped.append(PROXY_PORT_FILE)
        return
    with os.fdopen(fd, "rb") as f:
        raw = f.read(MAX_PORT_FILE_BYTES + 1) if stat.S_ISREG(os.fstat(fd).st_mode) else b""
    if port_from_bytes(raw) is not None:
        _take(src, PROXY_PORT_FILE, dst, PROXY_PORT_FILE, moved, PROXY_PORT_FILE)


def _copy_session(src_dir: int, name: str, sessions: int, data: Path, moved: Moved) -> None:
    """A session on another volume: copied into a temporary folder, renamed into place; the original stays."""
    rel = f"{SESSIONS}/{name}"
    tmp = f".{name}.{secrets.token_hex(4)}.tmp"
    os.mkdir(tmp, 0o700, dir_fd=sessions)
    scratch = Moved()
    try:
        source = _open_sub(name, src_dir)
        try:
            out = _open_sub(tmp, sessions)
            try:
                _tree(source, out, (), rel, scratch, SESSIONS)
            finally:
                os.close(out)
        finally:
            os.close(source)
        if scratch.failed:
            moved.failed.extend(scratch.failed)
        elif _exists(name, sessions):
            moved.kept.append(rel)
        else:
            os.rename(tmp, name, src_dir_fd=sessions, dst_dir_fd=sessions)
            moved.counts[SESSIONS] += 1
            moved.skipped.extend(scratch.skipped)
    finally:
        shutil.rmtree(data / SESSIONS / tmp, ignore_errors=True)


def _sessions(src: int, dst: int, data: Path, moved: Moved) -> None:
    """Session folders are moved: renamed, the same volume as the home folder; copied across volumes."""
    from .session import started

    folder_fd = _open_source(SESSIONS, src, moved)
    if folder_fd is None:
        return
    try:
        out = None
        for entry in _entries(folder_fd):
            # The rule of session.list_sessions(): a real folder with a session name.
            if started(entry.name) is None:
                continue
            rel = f"{SESSIONS}/{entry.name}"
            if entry.is_symlink():
                moved.skipped.append(rel)
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                if out is None:
                    out = _dest_dir(dst, (SESSIONS,))
                if _exists(entry.name, out):
                    moved.kept.append(rel)
                    continue
                try:
                    os.rename(entry.name, entry.name, src_dir_fd=folder_fd, dst_dir_fd=out)
                    moved.counts[SESSIONS] += 1
                except OSError as e:
                    if e.errno != errno.EXDEV:
                        raise
                    _copy_session(folder_fd, entry.name, out, data, moved)
            except OSError as e:
                moved.failed.append((rel, _reason(e)))
        if out is not None:
            os.close(out)
    finally:
        os.close(folder_fd)


def migrate(source: Path, data: Path) -> Moved:
    """Take an older Wiretrace folder's presets, rules, mock files and port (copied) and sessions (moved).

    Raises OSError only when `source` or `data` cannot be opened; anything else is in the result.
    """
    moved = Moved()
    src = os.open(source, _DIR)
    try:
        dst = os.open(data, _DIR)
        try:
            _named_files(src, dst, PRESETS, ".yaml", moved)
            _named_files(src, dst, RULES, ".json", moved)
            _mocks(src, dst, moved)
            _port(src, dst, moved)
            _sessions(src, dst, data, moved)
        finally:
            os.close(dst)
    finally:
        os.close(src)
    return moved


def seed_examples(examples: Path, data: Path) -> None:
    """Copy each shipped example that is missing from the data folder; one that exists is never touched."""
    try:
        src = os.open(examples, _DIR)
    except OSError:
        return
    try:
        dst = os.open(data, _DIR)
        try:
            scratch = Moved()
            _named_files(src, dst, PRESETS, ".yaml", scratch)
            _named_files(src, dst, RULES, ".json", scratch)
            _mocks(src, dst, scratch)
        finally:
            os.close(dst)
    finally:
        os.close(src)


def _write_marker(data: Path) -> None:
    try:
        fd = os.open(data / MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(f"{__version__}\n")


def prepare(data: Path | None = None, install: Path = INSTALL_DIR, examples: Path = EXAMPLES_DIR) -> str | None:
    """Create the data folder, take an older version's data from the install folder once, add the
    missing examples. The migration summary, or None when there was nothing to take. Raises DataDirError.

    Safe to run twice at once: every copy creates its destination exclusively or skips it.
    """
    data = ensure(data)
    text = None
    try:
        if not os.path.lexists(data / MARKER):
            if not same(data, install):
                moved = migrate(install, data)
                if moved.found():
                    text = summary(moved, data)
            # Only after the whole pass: a crash halfway retries, and the retry keeps what was copied.
            _write_marker(data)
        seed_examples(examples, data)
    except OSError as e:
        raise DataDirError(problem_text(shown(data), _reason(e))) from None
    return text


def import_data(folder: Path, data: Path) -> tuple[int, str]:
    """`./wiretrace import-data <folder>`: the exit code and the line to print. Never overwrites."""
    try:
        source = folder.expanduser().resolve(strict=True)
    except OSError:
        return 1, f"No folder {folder}."
    if not source.is_dir():
        return 1, f"{folder} is not a folder."
    if same(source, data):
        return 1, f"{folder} is the Wiretrace data folder itself."
    try:
        moved = migrate(source, data)
    except OSError as e:
        return 1, f"Could not read {folder}: {e.strerror or e}."
    if not moved.found():
        return 0, f"No Wiretrace data in {folder}: nothing imported."
    return 0, summary(moved, data)
