"""Helpers shared by the tests."""
import os


def filesystem_is_case_sensitive(directory: str) -> bool:
    """Returns True if `directory` can hold two names differing only in case.

    Probed rather than inferred from the platform. Windows is normally
    case-insensitive but supports per-directory case sensitivity, and macOS can
    be formatted either way, so `os.name` is not the question being asked.

    Tests that need two case-variant folders to exist at once are physically
    impossible where this returns False, and should skip rather than fail.
    """
    probe = os.path.join(directory, "CaseSensitivityProbe")
    os.makedirs(probe, exist_ok=True)
    try:
        return not os.path.isdir(os.path.join(directory, "casesensitivityprobe"))
    finally:
        os.rmdir(probe)
