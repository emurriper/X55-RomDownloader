from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from archive_support import Extract7z
from download_core import local_game_status


EXE = shutil.which('7za')


@unittest.skipUnless(EXE, 'Pruebas nativas 7za: ejecutar en ROCKNIX')
class SevenZipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.archive = self.root / 'demo.7z'

    def make(self, data=b'ISO fixture' * 100):
        (self.source / 'demo.iso').write_bytes(data)
        subprocess.run([EXE, 'a', '-t7z', '-bd', str(self.archive), '.'], cwd=self.source,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        return data

    def run_job(self, job=None):
        job = (job or Extract7z(self.archive)).start()
        job.thread.join(15)
        self.assertFalse(job.thread.is_alive())
        self.assertFalse(list(self.root.glob('*.part')))
        return job

    def test_extract_verify_keep_and_delete(self):
        data = self.make()
        job = self.run_job()
        self.assertEqual(job.snapshot()['status'], 'done', job.snapshot())
        self.assertEqual(job.output.read_bytes(), data)
        self.assertTrue(self.archive.exists())
        job.delete_archive()
        self.assertFalse(self.archive.exists())
        self.assertTrue(job.output.exists())

    def test_matching_existing_rom_is_not_rewritten(self):
        data = self.make()
        target = self.root / 'demo.iso'
        target.write_bytes(data)
        before = Extract7z.identity(target)
        job = self.run_job()
        self.assertEqual(job.snapshot()['status'], 'done', job.snapshot())
        self.assertEqual(Extract7z.identity(target), before)

    def test_wrong_existing_rom_keeps_both(self):
        self.make()
        target = self.root / 'demo.iso'
        target.write_bytes(b'original')
        job = self.run_job()
        self.assertEqual(job.snapshot()['status'], 'error')
        self.assertEqual(target.read_bytes(), b'original')
        self.assertTrue(self.archive.exists())

    def test_cancel_keeps_archive_and_no_final_rom(self):
        self.make()
        job = Extract7z(self.archive)
        job.cancel.set()
        job = self.run_job(job)
        self.assertEqual(job.snapshot()['status'], 'cancelled')
        self.assertFalse((self.root / 'demo.iso').exists())
        self.assertTrue(self.archive.exists())

    def test_multiple_files_require_manual_extraction(self):
        self.make()
        (self.source / 'second.iso').write_bytes(b'other')
        subprocess.run([EXE, 'a', '-t7z', str(self.archive), 'second.iso'], cwd=self.source,
                       stdout=subprocess.DEVNULL, check=True)
        job = self.run_job()
        self.assertEqual(job.snapshot()['status'], 'error')
        self.assertTrue(self.archive.exists())
        self.assertFalse((self.root / 'demo.iso').exists())


if __name__ == '__main__':
    unittest.main()
