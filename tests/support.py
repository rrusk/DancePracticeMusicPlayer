"""Helpers shared by the tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile


def preview_practice(**changes):
    """A small validated practice used by preview and export tests."""
    from utils import simulate_practice
    return simulate_practice.load_practice("Example", {"Example": {
        "dances": ["Waltz", "Jive"], "num_selections": 2,
        "randomize_playlist": False, "dance_intros": {"default": "none"},
        **changes,
    }})


class PracticePreviewFixture:
    """Reusable temporary CLI inputs for unittest.TestCase subclasses."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.builtin = self.root / "builtin.json"
        self.custom = self.root / "custom.json"
        self.cache = self.root / "cache.json"
        self.config = self.root / "music.ini"
        self.remote_library = self.root / "unavailable"
        self.builtin.write_text(json.dumps({"Example": {
            "dances": ["Waltz", "Jive"], "num_selections": 1,
            "dance_intros": {"default": "none"}, "randomize_playlist": False,
        }}))
        self.custom.write_text("{}")
        self.config.write_text(f"[user]\nmusic_dir = {self.remote_library}\n")
        self.cache.write_text(json.dumps({"songs": {
            str(self.remote_library / dance / f"{i}.mp3"): {"duration": 300}
            for dance in ("Waltz", "Jive") for i in range(3)
        }}))
        self.args = [str(self.cache), "--builtin-types", str(self.builtin),
                     "--custom-types", str(self.custom), "--config", str(self.config),
                     "--practice-type", "Example", "--runs", "2"]

    def run_script(self, *extra):
        from utils import simulate_practice
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = simulate_practice.main(self.args + list(extra))
        self.assertEqual(result, 0)
        return output.getvalue()


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
