import tempfile
import unittest
from pathlib import Path

from build_catalog import build
from download_core import local_game_status
from graphical_app import Application
from x55_systems import SYSTEMS, SELECTED, VARIABLE


class ProfileTests(unittest.TestCase):
    def test_profile_excludes_heavy_systems_and_marks_variable(self):
        self.assertEqual(len(SELECTED), 38)
        for slug in ('playstation-2', 'gamecube', 'nintendo-wii', 'xbox', 'nintendo-3ds'):
            self.assertNotIn(slug, SYSTEMS)
        self.assertEqual(len(VARIABLE), 5)
        for slug in VARIABLE:
            self.assertEqual(SYSTEMS[slug]['performance'], 'variable')

    def test_build_does_not_restore_excluded_previous_system(self):
        index = {'systems': {'gameboy': {'catalogue_complete': True, 'games': []}}}
        old = {'PS2': {'folder': 'ps2', 'games': []}}
        self.assertEqual(set(build(index, old, selected=['gameboy'])), {'Game Boy'})
        with self.assertRaises(ValueError):
            build(index, old, selected=['playstation-2'])

    def test_neogeo_archive_is_playable_and_cannot_be_extracted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'neogeo').mkdir()
            target = root / 'neogeo' / 'example.zip'
            target.write_bytes(b'romset fixture')
            game = {'name': 'Example', 'filename': target.name, 'url': 'https://example.com/game.zip'}
            state = local_game_status(root, 'neogeo', game)
            self.assertEqual(state['status'], 'installed')
            self.assertIsNone(state['zip_path'])
            app = Application({'Neo Geo': {'folder': 'neogeo', 'archive_mode': 'keep', 'games': [game]}}, root)
            app.act('select')
            app.destination = target
            app.begin_extraction()
            self.assertIsNone(app.job)


if __name__ == '__main__':
    unittest.main()
