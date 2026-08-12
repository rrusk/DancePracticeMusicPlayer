# app_paths.py
"""Decides where the player keeps the files it writes.

The player writes four things: `music.ini`, `play_history.json`,
`song_metadata_cache.json`, and `custom_practice_types.json` from the practice
type editor. They have always lived beside `music_player.py`, which is right for
a git checkout and for a portable extracted PyInstaller directory, and wrong for
an installed build under `Program Files`, where Windows refuses the writes. The
failures are handled rather than fatal, but history, the cache and custom
practice types would all silently stop persisting.

So the application directory is used unless it is somewhere applications get
installed -- Program Files, /usr, /Applications -- or the permissions say no.
That keeps every existing source deployment exactly as it is, and sends an
installed copy to the per-user data directory instead. When it does fall back,
any file already shipped in the application directory is copied across once, so
a packaged build starts from what it shipped with.

Note that nothing is written in order to decide this. Creating a probe file in
the application directory on every launch is wasted work at best, and where the
directory is protected it is the very operation antivirus software intercepts.

Read-only assets -- `announce/`, `cues/`, `icons/`, `builtin_practice_types.json`
-- always stay with the application and are reached with `app_path`.
"""
import os
import shutil
import stat
import sys

APP_NAME = "DancePracticeMusicPlayer"

# The directory the application was installed or checked out into. Under
# PyInstaller this is the bundle directory, which is where `datas` are placed.
APP_DIR = os.path.dirname(os.path.abspath(__file__))

_state_dir = None  # Resolved once, on first use.


def default_user_data_dir() -> str:
    """Returns the per-user data directory for this platform.

    Mirrors where Kivy would put application data, without needing a running App
    so that the practice type editor and the utility scripts can use it too.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def is_install_location(directory: str) -> bool:
    """Returns True if `directory` is somewhere applications are installed.

    A copy of the player living under Program Files (or /usr, or /Applications)
    was put there by an installer and must be treated as read-only, whatever the
    permissions happen to say.

    This is decided from the path rather than by trying to write a file. An
    attempted write into Program Files is exactly what Defender's Controlled
    Folder Access and real-time scanning watch for, and it can block rather than
    fail: probing it once stalled the whole test suite. There is no reason to
    ask the question experimentally when the answer follows from the location.
    """
    resolved = os.path.normcase(os.path.abspath(directory))

    roots = []
    if sys.platform == "win32":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
                         "SystemRoot"):
            if value := os.environ.get(variable):
                roots.append(value)
    else:
        roots = ["/usr", "/opt", "/Applications", "/Library", "/snap"]

    for root in roots:
        root = os.path.normcase(os.path.abspath(root))
        if resolved == root or resolved.startswith(root + os.sep):
            return True
    return False


def directory_is_writable(directory: str) -> bool:
    """Returns True if `directory` looks writable, without writing anything.

    `os.access` can be optimistic on Windows, where it reports the read-only
    attribute rather than the effective ACL. That is acceptable here: an install
    location is already excluded by `is_install_location`, and any remaining
    false positive means a write fails and is reported, which every caller
    already handles.
    """
    return os.path.isdir(directory) and os.access(directory, os.W_OK)


def state_dir(app_dir: str = None, user_dir: str = None) -> str:
    """Returns the directory for files the player writes, creating it if needed.

    Resolved once and remembered, so the writability probe runs a single time per
    session.

    Args:
        app_dir: Application directory to test. Defaults to `APP_DIR`.
        user_dir: Fallback directory. Defaults to the per-user data directory.

    Returns:
        The application directory when it is writable, otherwise the fallback.
    """
    global _state_dir  # pylint: disable=global-statement
    if _state_dir is not None and app_dir is None and user_dir is None:
        return _state_dir

    application = app_dir or APP_DIR
    if not is_install_location(application) and directory_is_writable(application):
        resolved = application
    else:
        resolved = user_dir or default_user_data_dir()
        try:
            os.makedirs(resolved, exist_ok=True)
        except OSError as error:
            # Nothing left to try; the caller's write will fail and be reported.
            print(f"Could not create {resolved}: {error}")
            resolved = application
        else:
            reason = ("is an installed location" if is_install_location(application)
                      else "is not writable")
            print(f"{application} {reason}; "
                  f"keeping settings and history in {resolved}")

    if app_dir is None and user_dir is None:
        _state_dir = resolved
    return resolved


def user_path(filename: str, seed_from_app_dir: bool = True) -> str:
    """Returns the full path of a file the player writes.

    Args:
        filename: Bare file name, e.g. "play_history.json".
        seed_from_app_dir: If the resolved directory is not the application
            directory and the file does not exist there yet, copy the shipped
            copy across so a packaged build starts from what it shipped with.

    Returns:
        The full path to use for reading and writing that file.
    """
    directory = state_dir()
    path = os.path.join(directory, filename)

    if seed_from_app_dir and directory != APP_DIR and not os.path.exists(path):
        shipped = os.path.join(APP_DIR, filename)
        if os.path.isfile(shipped):
            try:
                # copyfile, not copy2: the shipped file is typically read-only in
                # an installed build, and copying its permissions across would
                # leave the user with a copy they still cannot save to.
                shutil.copyfile(shipped, path)
                os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
                print(f"Copied {filename} into {directory}")
            except OSError as error:
                print(f"Could not copy {filename} into {directory}: {error}")

    return path


def app_path(*parts: str) -> str:
    """Returns the path of a read-only asset shipped with the application."""
    return os.path.join(APP_DIR, *parts)


def reset() -> None:
    """Forgets the resolved directory. For tests."""
    global _state_dir  # pylint: disable=global-statement
    _state_dir = None
