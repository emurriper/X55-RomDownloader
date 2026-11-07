from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from download_core import local_game_status
from graphical_app import Application
from local_library import LocalLibrary, title_key


class ExistingCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.game = {'name': 'Super Mario Bros. 3', 'filename': 'rg-placeholder.download',
                     'source_provider': 'romsgames',
                     'source_page': 'https://www.romsgames.net/nintendo-rom-super-mario-bros-3/'}

    def rom(self, name, folder='nes'):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'ROM fixture')
        return path

    def test_existing_rom_detected_without_resolving_url(self):
        target = self.rom('Super Mario Bros. 3 (USA) (Rev A).nes')
        app = Application({'NES': {'folder': 'nes', 'games': [self.game]}}, self.root)
        app.act('select')
        with patch('romsgames_source.resolve_game') as resolve, patch('graphical_app.Download') as download:
            state = app.game_status(self.game)
            self.assertEqual(state['status'], 'installed')
            self.assertEqual(state['path'], target)
            app.act('select')
            self.assertEqual(app.page, 'local')
            self.assertIsNone(app.job)
            resolve.assert_not_called()
            download.assert_not_called()

    def test_nested_rom_and_translation_tags(self):
        target = self.rom('Traducciones/Super Mario Bros. 3 (Japan) [T-En by Someone v1.0] [n].nes')
        state = local_game_status(self.root, 'nes', self.game)
        self.assertEqual(state['status'], 'installed')
        self.assertEqual(state['path'], target)

    def test_gamelist_name_resolves_differently_named_file(self):
        target = self.rom('ABCD1234.nes')
        (self.root / 'nes' / 'gamelist.xml').write_text('''<gameList><game>
            <path>./ABCD1234.nes</path><name>Super Mario Bros. 3</name>
            </game></gameList>''')
        state = local_game_status(self.root, 'nes', self.game)
        self.assertEqual(state['status'], 'installed')
        self.assertEqual(state['path'], target)
        self.assertEqual(state['matched_by'], 'gamelist')

    def test_sequels_demos_hacks_and_other_system_do_not_match(self):
        for name in ('Super Mario Bros. 2 (USA).nes', 'Super Mario Bros. 3 (Demo).nes',
                     'Super Mario Bros. 3 [Hack Test].nes'):
            self.rom(name)
        self.rom('Super Mario Bros. 3 (USA).sfc', folder='snes')
        self.assertEqual(local_game_status(self.root, 'nes', self.game)['status'], 'available')

    def test_compressed_save_and_zero_size_are_not_installed_roms(self):
        for ext in ('.zip', '.7z', '.sav', '.part'):
            self.rom('Super Mario Bros. 3 (USA)' + ext)
        empty = self.rom('Super Mario Bros. 3 (USA).nes')
        empty.write_bytes(b'')
        self.assertEqual(local_game_status(self.root, 'nes', self.game)['status'], 'available')

    def test_multiple_regions_are_detected_and_deletion_is_revalidated(self):
        paths = [self.rom(f'Super Mario Bros. 3 ({region}).nes') for region in ('USA', 'Europe')]
        library = LocalLibrary(self.root)
        self.assertEqual(library.find('nes', self.game)['matches'], 2)
        paths[0].unlink()
        self.assertEqual(library.find('nes', self.game)['matches'], 1)
        paths[1].unlink()
        self.assertIsNone(library.find('nes', self.game))

    def test_gamelist_cannot_point_outside_system(self):
        self.rom('Outside.nes', folder='other')
        directory = self.root / 'nes'
        directory.mkdir()
        (directory / 'gamelist.xml').write_text('''<gameList><game>
            <path>../other/Outside.nes</path><name>Super Mario Bros. 3</name>
            </game></gameList>''')
        self.assertEqual(local_game_status(self.root, 'nes', self.game)['status'], 'available')

    def test_mega_drive_uses_genesis_folder_too(self):
        target = self.rom('Sonic The Hedgehog (USA, Europe).md', folder='genesis')
        game = {'name': 'Sonic The Hedgehog', 'filename': 'rg-sonic.download'}
        state = local_game_status(self.root, 'megadrive', game)
        self.assertEqual(state['status'], 'installed')
        self.assertEqual(state['path'], target)

    def test_article_punctuation_accents_and_versions(self):
        self.assertEqual(title_key('Legend of Zelda, The'), title_key('The Legend of Zelda (USA)'))
        self.assertEqual(title_key('Pok\u00e9mon'), title_key('Pokemon (En,Fr,De)'))
        self.assertEqual(title_key("Mike Tyson's Punch-Out!!"), title_key("Mike Tyson's Punch-Out!! (Japan, USA) (Rev 1)"))
        self.assertNotEqual(title_key('Pac-Man (Namco)'), title_key('Pac-Man (Tengen)'))
        self.assertNotEqual(title_key('Game (Disc 1)'), title_key('Game (Disc 2)'))


if __name__ == '__main__':
    unittest.main()
