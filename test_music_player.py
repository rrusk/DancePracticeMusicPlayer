import unittest
import os
from unittest.mock import patch, MagicMock

# Before we can import the Kivy app, we need to set up the environment
# to prevent it from trying to create a window. This is crucial for running
# tests on a system without a display, like a continuous integration server.
os.environ["KIVY_NO_ARGS"] = "1"
os.environ['KIVY_NO_WINDOW'] = '1'

# Now we can safely import the application components
# pylint: disable=wrong-import-position
from music_player import MusicPlayer

class TestMusicPlayerLogic(unittest.TestCase):
    """
    Unit tests for the business logic of the MusicPlayer class.

    These tests do not require a running Kivy App and focus on pure logic.

    To run these tests:
    1. Make sure you have the necessary Kivy dependencies for testing:
       pip install "kivy[base]"

    2. From your terminal, in the same directory as this file, run:
       python -m unittest test_music_player.py
    """

    def setUp(self):
        """
        Set up a fresh MusicPlayer instance for each test.
        This method runs before every single test function, ensuring test isolation.
        """
        # Bypassing the full __init__ to avoid widget setup, which would require a full Kivy context.
        self.player = MusicPlayer.__new__(MusicPlayer)

        # Manually initializing properties needed for the logic tests.
        self.player.practice_dances = {
            "default": [
                "Waltz", "Tango", "VWSlow", "VienneseWaltz", "Foxtrot",
                "QuickStep", "WCS", "Samba", "ChaCha", "Rumba", "PasoDoble",
                "JSlow", "Jive"
            ],
            "newcomer": [
                "Waltz", "JSlow", "Jive", "Rumba", "Foxtrot", "ChaCha",
                "Tango", "Samba", "QuickStep", "VWSlow", "VienneseWaltz", "WCS"
            ],
        }
        # Mock methods that interact with the file system or Kivy UI to isolate the logic.
        self.player.update_playlist = MagicMock()
        self.player.load_custom_practice_types = MagicMock(return_value={})
        self.player.custom_practice_mapping = {}
        # Manually call merge_custom_practice_types as it's part of the setup logic.
        self.player.merge_custom_practice_types()


    def test_secs_to_time_str(self):
        """Tests the conversion of seconds to a formatted time string (e.g., MM:SS)."""
        self.assertEqual(self.player._secs_to_time_str(59), "00:59")
        self.assertEqual(self.player._secs_to_time_str(60), "01:00")
        self.assertEqual(self.player._secs_to_time_str(150), "02:30")
        self.assertEqual(self.player._secs_to_time_str(3600), "01:00:00")
        self.assertEqual(self.player._secs_to_time_str(3661), "01:01:01")

    def test_get_song_label(self):
        """Tests the generation of song labels from metadata dictionaries."""
        # Test a standard song with complete information.
        song_info = {
            'title': 'Blue Suede Shoes',
            'artist': 'Elvis Presley',
            'album': 'Elvis Presley',
            'genre': 'Rock and Roll'
        }
        expected_label = "Blue Suede Shoes / Rock and Roll / Elvis Presley / Elvis Presley"
        self.assertEqual(self.player._get_song_label(song_info), expected_label)

        # Test a song with missing information to ensure it uses default values.
        song_info_missing = {'title': 'Hound Dog'}
        expected_label_missing = "Hound Dog / Genre Unspecified / Artist Unspecified / Album Unspecified"
        self.assertEqual(self.player._get_song_label(song_info_missing), expected_label_missing)

        # Test an announcement file, which should only display its title.
        announce_info = {'dance': 'announce', 'title': 'Waltz'}
        self.assertEqual(self.player._get_song_label(announce_info), "Waltz")

    def test_get_adjusted_song_count(self):
        """Tests the logic for adjusting song counts based on practice type rules."""
        self.player.adjust_song_counts_for_playlist = True
        self.player.current_dance_adjustments = {
            "Jive": "n-1",
            "VWSlow": "cap_at_1",
            "WCS": "cap_at_2",
            "PasoDoble": {"1": 0, "2": 1, "default": 2}
        }

        # Test each type of rule to ensure it's interpreted correctly.
        self.assertEqual(self.player._get_adjusted_song_count("Jive", 3), 2, "Failed 'n-1' rule")
        self.assertEqual(self.player._get_adjusted_song_count("Jive", 1), 1, "Failed 'n-1' rule at minimum")
        self.assertEqual(self.player._get_adjusted_song_count("VWSlow", 5), 1, "Failed 'cap_at_1' rule")
        self.assertEqual(self.player._get_adjusted_song_count("WCS", 5), 2, "Failed 'cap_at_2' rule")
        self.assertEqual(self.player._get_adjusted_song_count("PasoDoble", 1), 0, "Failed dictionary mapping rule for 1")
        self.assertEqual(self.player._get_adjusted_song_count("PasoDoble", 2), 1, "Failed dictionary mapping rule for 2")
        self.assertEqual(self.player._get_adjusted_song_count("PasoDoble", 3), 2, "Failed dictionary default rule")
        self.assertEqual(self.player._get_adjusted_song_count("Tango", 3), 3, "Failed for a dance with no rules")

    def test_set_practice_type_60min(self):
        """Tests that properties are set correctly for the '60min' practice type."""
        self.player.set_practice_type(None, "60min")

        self.assertEqual(self.player.num_selections, 2)
        self.assertEqual(self.player.randomize_playlist, True)
        self.assertEqual(self.player.adjust_song_counts_for_playlist, True)
        self.assertFalse(self.player.play_all_songs)
        self.assertIn("PasoDoble", self.player.current_dance_adjustments)
        self.assertEqual(self.player.dances, self.player.practice_dances["default"])

    def test_set_practice_type_nc_60min(self):
        """Tests that properties are set correctly for the 'NC 60min' practice type."""
        self.player.set_practice_type(None, "NC 60min")

        self.assertEqual(self.player.num_selections, 2)
        self.assertEqual(self.player.dances, self.player.practice_dances["newcomer"])


    @patch('os.path.isdir')
    @patch('os.walk')
    def test_collect_music_files(self, mock_walk, mock_isdir):
        """
        Tests the file collection logic by mocking the file system.
        This allows us to test the file filtering logic without needing real files or folders.
        """
        mock_isdir.return_value = True
        fake_music_dir = '/fake/music'
        fake_waltz_dir = os.path.join(fake_music_dir, 'Waltz')

        # Define the fake file system structure that os.walk will "find".
        mock_walk.return_value = [
            (fake_waltz_dir, ['subdir'], ['song1.mp3', 'song2.wav', 'info.txt']),
            (os.path.join(fake_waltz_dir, 'subdir'), [], ['song3.m4a', 'album_art.jpg'])
        ]

        result = self.player._collect_music_files(fake_music_dir, 'Waltz')

        # Verify that the function attempted to walk the correct directory.
        mock_walk.assert_called_with(fake_waltz_dir)

        # Check that only valid music file extensions were collected from the fake structure.
        self.assertEqual(len(result), 3)
        self.assertIn(os.path.join(fake_waltz_dir, 'song1.mp3'), result)
        self.assertIn(os.path.join(fake_waltz_dir, 'song2.wav'), result)
        self.assertIn(os.path.join(fake_waltz_dir, 'subdir', 'song3.m4a'), result)
        self.assertNotIn(os.path.join(fake_waltz_dir, 'info.txt'), result)

    @patch('music_player.MusicPlayer._collect_music_files')
    @patch('music_player.MusicPlayer._create_song_info')
    @patch('music_player.MusicPlayer._get_announce_path', return_value=None)
    def test_get_songs_for_dance_with_play_all(self, mock_get_announce, mock_create_info, mock_collect_files):
        """Tests that 'play_all_songs' overrides num_selections and gets all files."""
        # --- Setup ---
        # Set player state to simulate a practice type where all songs should be played.
        self.player.play_all_songs = True
        self.player.randomize_playlist = False # Use non-random for a predictable output order.

        # Mock the list of files that would be found on the file system.
        fake_paths = ['/music/c.mp3', '/music/a.mp3', '/music/b.mp3']
        mock_collect_files.return_value = fake_paths

        # Mock the metadata reader to just return the path for easy verification.
        mock_create_info.side_effect = lambda path, dance: {'path': path, 'dance': dance}

        # --- Action ---
        # Call the method. Note that num_selections is 1, but should be ignored.
        result_playlist = self.player._get_songs_for_dance('/fake/dir', 'TestDance', 1, False)

        # --- Assertions ---
        # 1. Verify that all 3 mocked files were selected, not just 1.
        self.assertEqual(len(result_playlist), 3)

        # 2. Verify the file collection was called as expected.
        mock_collect_files.assert_called_with('/fake/dir', 'TestDance')

        # 3. Since randomize_playlist was False, verify the output is sorted alphabetically.
        self.assertEqual(result_playlist[0]['path'], '/music/a.mp3')
        self.assertEqual(result_playlist[1]['path'], '/music/b.mp3')
        self.assertEqual(result_playlist[2]['path'], '/music/c.mp3')

if __name__ == '__main__':
    # The verbosity argument increases the detail of the test output.
    unittest.main(verbosity=2)
