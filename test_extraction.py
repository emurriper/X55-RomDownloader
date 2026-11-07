from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from download_core import ExtractZip
from graphical_app import Application


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "game.zip"

    def make_zip(self, entries=None):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in entries or [("game.iso", b"sample ISO" * 100)]:
                info = zipfile.ZipInfo(name)
                info.filename = name
                archive.writestr(info, data)

    def run_job(self, job=None):
        job = (job or ExtractZip(self.archive)).start()
        job.thread.join(5)
        self.assertFalse(job.thread.is_alive())
        self.assertFalse(list(self.root.glob("*.part")))
        return job

    def test_verified_extraction_and_explicit_delete(self):
        self.make_zip()
        job = self.run_job()
        self.assertEqual(job.snapshot()["status"], "done")
        self.assertEqual(job.output.read_bytes(), b"sample ISO" * 100)
        self.assertTrue(self.archive.exists())
        job.delete_archive()
        self.assertFalse(self.archive.exists())
        self.assertTrue(job.output.exists())

    def test_existing_rom_is_never_replaced(self):
        self.make_zip()
        target = self.root / "game.iso"
        target.write_bytes(b"existing game")
        job = self.run_job()
        self.assertEqual(job.snapshot()["status"], "error")
        self.assertEqual(target.read_bytes(), b"existing game")
        self.assertTrue(self.archive.exists())
        with self.assertRaises(ValueError):
            job.delete_archive()

    def test_matching_existing_rom_offers_zip_deletion_without_rewriting(self):
        self.make_zip()
        target = self.root / "game.iso"
        target.write_bytes(b"sample ISO" * 100)
        original = ExtractZip.identity(target)
        app = Application({}, self.root)
        app.destination = self.archive
        app.page = "download"
        app.job = SimpleNamespace(snapshot=lambda: {"status": "done"})
        with patch('download_core.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            app.advance()
            app.job.thread.join(5)
        self.assertEqual(app.job.snapshot()["status"], "done")
        self.assertTrue(app.job.snapshot()["existing"])
        app.advance()
        self.assertEqual(app.page, "zip_choice")
        app.act("select")
        self.assertFalse(self.archive.exists())
        self.assertEqual(ExtractZip.identity(target), original)

    def test_existing_rom_with_same_size_but_wrong_crc_keeps_both(self):
        self.make_zip()
        target = self.root / "game.iso"
        target.write_bytes(b"wrong data" * 100)
        original = target.read_bytes()
        job = self.run_job()
        self.assertEqual(job.snapshot()["status"], "error")
        self.assertIn("CRC", job.snapshot()["error"])
        self.assertEqual(target.read_bytes(), original)
        self.assertTrue(self.archive.exists())
        with self.assertRaises(ValueError):
            job.delete_archive()

    def test_cancel_existing_rom_verification_keeps_both(self):
        self.make_zip()
        target = self.root / "game.iso"
        target.write_bytes(b"sample ISO" * 100)
        original = ExtractZip.identity(target)
        job = ExtractZip(self.archive)
        job.cancel.set()
        self.run_job(job)
        self.assertEqual(job.snapshot()["status"], "cancelled")
        self.assertTrue(self.archive.exists())
        self.assertEqual(ExtractZip.identity(target), original)

    def test_unsafe_names_multiple_files_and_unsupported_formats(self):
        for entries in ([('../escape.iso', b'x')], [('/escape.iso', b'x')],
                        [('a\\escape.iso', b'x')], [('game.exe', b'x')],
                        [('game.iso', b'x'), ('other.iso', b'y')]):
            with self.subTest(entries=entries):
                self.make_zip(entries)
                job = self.run_job()
                self.assertEqual(job.snapshot()["status"], "error")
                self.assertTrue(self.archive.exists())
                self.assertEqual(list(self.root.iterdir()), [self.archive])

    def test_corrupt_crc_keeps_zip_and_removes_partial(self):
        self.make_zip()
        with zipfile.ZipFile(self.archive) as archive:
            item = archive.infolist()[0]
            offset = item.header_offset + 30 + len(item.filename.encode()) + len(item.extra)
        with self.archive.open("r+b") as stream:
            stream.seek(offset)
            value = stream.read(1)
            stream.seek(offset)
            stream.write(bytes([value[0] ^ 255]))
        job = self.run_job()
        self.assertEqual(job.snapshot()["status"], "error")
        self.assertFalse((self.root / "game.iso").exists())
        self.assertTrue(self.archive.exists())

    def test_cancel_during_extraction(self):
        self.make_zip([('game.iso', b'x' * 3 * 1024 * 1024)])
        job = ExtractZip(self.archive)
        original_update = job.update
        def cancel_after_first_chunk(**values):
            original_update(**values)
            if values.get('downloaded', 0):
                job.cancel.set()
        job.update = cancel_after_first_chunk
        self.run_job(job)
        self.assertEqual(job.snapshot()["status"], "cancelled")
        self.assertTrue(self.archive.exists())
        self.assertFalse((self.root / "game.iso").exists())

    def test_insufficient_space(self):
        self.make_zip()
        with patch('download_core.shutil.disk_usage', return_value=SimpleNamespace(free=0)):
            job = self.run_job()
        self.assertEqual(job.snapshot()["status"], "error")
        self.assertFalse((self.root / "game.iso").exists())

    def test_changed_rom_or_zip_cannot_delete_archive(self):
        for changed in ("rom", "zip"):
            with self.subTest(changed=changed):
                (self.root / "game.iso").unlink(missing_ok=True)
                self.make_zip()
                job = self.run_job()
                path = job.output if changed == "rom" else self.archive
                with path.open("ab") as stream:
                    stream.write(b"changed")
                with self.assertRaises(ValueError):
                    job.delete_archive()
                self.assertTrue(self.archive.exists())

    def test_application_automatically_extracts_then_offers_keep_or_delete(self):
        for action in ("back", "select"):
            with self.subTest(action=action):
                (self.root / "game.iso").unlink(missing_ok=True)
                self.make_zip()
                app = Application({}, self.root)
                app.destination = self.archive
                app.page = "download"
                app.job = SimpleNamespace(snapshot=lambda: {"status": "done"})
                app.advance()
                self.assertEqual(app.page, "extract")
                app.job.thread.join(5)
                app.advance()
                self.assertEqual(app.page, "zip_choice")
                app.act(action)
                self.assertEqual(self.archive.exists(), action == "back")
                self.assertTrue((self.root / "game.iso").is_file())


if __name__ == "__main__":
    unittest.main()
