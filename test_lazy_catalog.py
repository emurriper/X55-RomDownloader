from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from download_core import ResolveGame, effective_game, validate_catalog, local_game_status
from graphical_app import Application
from build_catalog import build
from import_site import SYSTEMS


class LazyCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = {'name': 'Demo', 'filename': 'rg-demo.download', 'source_provider': 'romsgames',
                     'source_page': 'https://www.romsgames.net/playstation-portable-rom-demo/'}
        self.catalog = {'PSP': {'folder': 'psp', 'games': [self.game]}}

    def test_source_catalog_does_not_require_expired_direct_url(self):
        validate_catalog(self.catalog)
        with patch('romsgames_source.resolve_game') as resolver:
            app = Application(self.catalog, self.root, read_only=True)
            app.act('select')
            app.act('select')
            self.assertEqual(app.page, 'notice')
            resolver.assert_not_called()

    def test_resolution_before_confirmation_and_persistent_filename(self):
        resolved = {**self.game, 'filename': 'Real Name.7z', 'url': 'https://static.romsgames.net/test/output.bin'}
        with patch('romsgames_source.resolve_game', return_value=resolved), patch('graphical_app.Download') as download:
            app = Application(self.catalog, self.root)
            app.act('select')
            app.act('select')
            self.assertEqual(app.page, 'resolve')
            app.job.thread.join(5)
            app.advance()
            self.assertEqual(app.page, 'confirm')
            self.assertEqual(app.destination.name, 'Real Name.7z')
            download.assert_not_called()
        restored = effective_game(self.root, 'psp', self.game)
        self.assertEqual(restored['filename'], 'Real Name.7z')
        (self.root / 'psp' / 'Real Name.7z').write_bytes(b'7z fixture')
        self.assertEqual(local_game_status(self.root, 'psp', self.game)['status'], 'archive')

    def test_cancelled_resolution_does_not_record_filename(self):
        job = ResolveGame(self.game, self.root, 'psp')
        job.cancel.set()
        with patch('romsgames_source.resolve_game', return_value={**self.game, 'filename': 'real.zip'}):
            job.start()
            job.thread.join(5)
        self.assertEqual(job.snapshot()['status'], 'cancelled')
        self.assertFalse((self.root / 'psp' / '.x55-sources.json').exists())

    def test_catalog_build_preserves_existing_local_filename(self):
        slugs = ('gameboy', 'gameboy-color', 'gameboy-advance', 'nintendo',
                 'super-nintendo', 'sega-genesis', 'playstation', 'playstation-portable')
        index = {'systems': {slug: {'name': SYSTEMS[slug][0], 'folder': SYSTEMS[slug][1],
                                  'catalogue_complete': True, 'games': [
                                      {'name': 'Demo', 'page_url': f'https://www.romsgames.net/{slug}-rom-demo/'}]}
                             for slug in slugs}}
        previous = {'PSP': {'folder': 'psp', 'games': [
            {'name': 'Demo (Europe)', 'filename': 'Already Downloaded.zip', 'url': 'https://example.com/old.zip'}]}}
        entry = build(index, previous, selected=slugs)['PSP']['games'][0]
        self.assertEqual(entry['filename'], 'Already Downloaded.zip')
        self.assertEqual(entry['source_provider'], 'romsgames')
        self.assertNotIn('url', entry)


if __name__ == '__main__':
    unittest.main()
