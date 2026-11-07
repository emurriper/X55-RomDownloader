from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from download_core import ExtractZip, local_game_status
from graphical_app import Application


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / 'psp'
        self.folder.mkdir()
        self.game = {'name': 'Demo', 'filename': 'archive.zip', 'url': 'https://example.com/archive.zip'}
        self.archive = self.folder / self.game['filename']

    def make_zip(self, name='Different Game Title.iso'):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr(name, b'ISO fixture')

    def state(self):
        return local_game_status(self.root, 'psp', self.game)

    def app(self, read_only=False):
        app = Application({'PSP': {'folder': 'psp', 'games': [self.game]}}, self.root, read_only)
        app.act('select')
        return app

    def test_available_then_downloaded_zip(self):
        self.assertEqual(self.state()['status'], 'available')
        self.make_zip()
        state = self.state()
        self.assertEqual(state['status'], 'zip')
        self.assertEqual(state['zip_path'], self.archive)

    def test_extracted_installation_survives_restart_and_zip_deletion(self):
        self.make_zip()
        job = ExtractZip(self.archive).start()
        job.thread.join(5)
        self.assertEqual(job.snapshot()['status'], 'done')
        self.assertEqual(self.state()['status'], 'installed')
        job.delete_archive()
        self.assertEqual(self.state()['status'], 'installed')
        self.assertEqual(self.state()['path'], self.folder / 'Different Game Title.iso')
        # Si el usuario borra la ROM, el registro no debe marcarla como instalada.
        job.output.unlink()
        self.assertEqual(self.state()['status'], 'available')

    def test_legacy_punctuation_without_zip_or_record(self):
        self.game['filename'] = 'God of War - Ghost of Sparta (Europe Australia) (EnFrDeEsIt).zip'
        target = self.folder / 'God of War - Ghost of Sparta (Europe, Australia) (En,Fr,De,Es,It).iso'
        target.write_bytes(b'existing ISO')
        self.assertEqual(self.state()['status'], 'installed')
        self.assertEqual(self.state()['path'], target)

    def test_zip_metadata_detects_existing_rom(self):
        self.make_zip()
        (self.folder / 'Different Game Title.iso').write_bytes(b'ISO fixture')
        self.assertEqual(self.state()['status'], 'installed')
        self.assertIsNotNone(self.state()['zip_path'])

    def test_zero_size_and_partial_files_are_not_installed(self):
        self.game['filename'] = 'game.iso'
        (self.folder / 'game.iso').touch()
        (self.folder / '.x55-download.part').write_bytes(b'partial')
        self.assertEqual(self.state()['status'], 'available')
        (self.folder / 'game.iso').write_bytes(b'ISO')
        self.assertEqual(self.state()['status'], 'installed')

    def test_invalid_record_cannot_escape_roms(self):
        (self.folder / '.x55-installed.json').write_text('{"archive.zip":{"rom":"../outside.iso","size":1}}')
        (self.root / 'outside.iso').write_bytes(b'x')
        self.assertEqual(self.state()['status'], 'available')

    def test_available_game_asks_before_downloading(self):
        app = self.app()
        with patch('graphical_app.Download') as download:
            app.act('select')
            self.assertEqual(app.page, 'confirm')
            download.assert_not_called()

    def test_existing_zip_is_processed_without_network_and_status_refreshes(self):
        self.make_zip()
        app = self.app()
        with patch('graphical_app.Download') as download:
            app.act('select')
            self.assertEqual(app.page, 'local')
            app.act('select')
            self.assertEqual(app.page, 'extract')
            app.job.thread.join(5)
            app.advance()
            self.assertEqual(app.page, 'zip_choice')
            app.act('select')
            app.act('back')
            self.assertEqual(app.game_status(self.game)['status'], 'installed')
            app.act('select')
            self.assertEqual(app.page, 'local')
            self.assertFalse(self.archive.exists())
            download.assert_not_called()

    def test_read_only_local_actions_do_not_extract_or_download(self):
        self.make_zip()
        app = self.app(read_only=True)
        with patch('graphical_app.Download') as download, patch('graphical_app.ExtractZip') as extract:
            app.act('select')
            self.assertEqual(app.page, 'local')
            app.act('select')
            self.assertEqual(app.page, 'notice')
            app.act('back')
            app.act('select')
            app.act('search')
            self.assertEqual(app.page, 'notice')
            download.assert_not_called()
            extract.assert_not_called()

    def test_installed_game_requires_explicit_redownload(self):
        self.game['installed_filename'] = 'installed.iso'
        (self.folder / 'installed.iso').write_bytes(b'ISO fixture')
        app = self.app()
        with patch('graphical_app.Download') as download:
            app.act('select')
            self.assertEqual(app.page, 'local')
            app.act('select')
            self.assertEqual(app.page, 'local')
            app.act('search')
            self.assertEqual(app.page, 'confirm')
            download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
