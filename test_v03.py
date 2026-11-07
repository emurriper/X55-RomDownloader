import http.server
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import io
import ssl
import zipfile

from download_core import Download, destination_for, read_catalog, validate_catalog
from graphical_app import Application


PAYLOAD = b"x55-download-test" * 8192


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/status/'):
            self.send_error(int(self.path.rsplit('/', 1)[1]))
            return
        if self.path == "/missing":
            self.send_error(404)
            return
        body = PAYLOAD
        content_type = 'application/octet-stream'
        if self.path in ('/html', '/hidden-html'):
            body = b'<!doctype html><html>Session expired</html>'
            if self.path == '/html':
                content_type = 'text/html'
        elif self.path == '/empty':
            body = b''
        elif self.path == '/zip':
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('test.iso', b'ISO fixture')
            body = stream.getvalue()
            content_type = 'application/zip'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        if self.path != "/unknown":
            self.send_header("Content-Length", str(len(body) + (10 if self.path == "/short" else 0)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()

    def test_success_with_and_without_length(self):
        for route in ("/ok", "/unknown"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as root:
                target = destination_for(root, "gb", "test.gb")
                job = self.download(route, target)
                self.assertEqual(job.snapshot()["status"], "done")
                self.assertEqual(target.read_bytes(), PAYLOAD)
                self.assertFalse(list(target.parent.glob("*.part")))

    def test_failure_preserves_existing_file(self):
        for route in ("/missing", "/short"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "existing.gb"
                target.write_bytes(b"original")
                job = self.download(route, target)
                self.assertEqual(job.snapshot()["status"], "error")
                self.assertEqual(target.read_bytes(), b"original")
                self.assertFalse(list(Path(root).glob("*.part")))

    def test_cancel_preserves_file(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "existing.gb"
            target.write_bytes(b"original")
            job = Download(self.url("/ok"), target)
            job.cancel.set()
            job.start()
            job.thread.join(5)
            self.assertEqual(job.snapshot()["status"], "cancelled")
            self.assertEqual(target.read_bytes(), b"original")
            self.assertFalse(list(Path(root).glob("*.part")))

    def test_http_errors_explain_next_step_and_preserve_existing_file(self):
        for code, kind in ((401, 'access'), (403, 'access'), (404, 'missing'),
                           (410, 'missing'), (429, 'rate_limit'), (503, 'server')):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                target = Path(root) / 'game.zip'
                target.write_bytes(b'existing ZIP')
                job = self.download(f'/status/{code}', target)
                state = job.snapshot()
                self.assertEqual(state['status'], 'error')
                self.assertEqual(state['error_kind'], kind)
                self.assertIn(str(code), state['error'])
                self.assertEqual(target.read_bytes(), b'existing ZIP')
                self.assertFalse(list(Path(root).glob('*.part')))

    def test_html_empty_and_invalid_zip_are_not_saved_as_roms(self):
        for route, filename in (('/html', 'test.gb'), ('/hidden-html', 'test.gb'),
                                ('/empty', 'game.zip'), ('/ok', 'game.zip'), ('/ok', 'game.7z')):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as root:
                target = Path(root) / filename
                target.write_bytes(b'original')
                state = self.download(route, target).snapshot()
                self.assertEqual(state['status'], 'error')
                self.assertEqual(state['error_kind'], 'invalid_file')
                self.assertEqual(target.read_bytes(), b'original')
                self.assertFalse(list(Path(root).glob('*.part')))

    def test_valid_zip_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'game.zip'
            self.assertEqual(self.download('/zip', target).snapshot()['status'], 'done')
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.read('test.iso'), b'ISO fixture')

    def test_network_and_tls_failures_have_specific_messages(self):
        for reason, kind in ((TimeoutError(), 'timeout'),
                             (ssl.SSLCertVerificationError('bad certificate'), 'tls'),
                             (OSError('DNS failure'), 'network')):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as root:
                target = Path(root) / 'game.zip'
                with patch('download_core.urllib.request.urlopen', side_effect=urllib.error.URLError(reason)):
                    job = self.download('/unused', target)
                self.assertEqual(job.snapshot()['error_kind'], kind)
                self.assertFalse(target.exists())

    def url(self, route):
        return f"http://127.0.0.1:{self.server.server_port}{route}"

    def download(self, route, target):
        job = Download(self.url(route), target).start()
        job.thread.join(5)
        self.assertFalse(job.thread.is_alive())
        return job


class CatalogAndNavigationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            'Game Boy': {'folder': 'gb', 'games': [{'name': 'Test Download', 'filename': 'test.gb', 'url': 'https://example.com/test.gb'}]},
            'NES': {'folder': 'nes', 'games': []},
            'Neo Geo': {'folder': 'neogeo', 'games': []},
        }

    def test_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as root:
            for folder, filename in (("../escape", "a.gb"), ("gb", "../a.gb"),
                                     ("/tmp", "a.gb"), ("gb", "C:\\a.gb")):
                with self.subTest(folder=folder, filename=filename), self.assertRaises(ValueError):
                    destination_for(root, folder, filename)
            self.assertEqual(destination_for(root, "gb", "test.gb"), Path(root).resolve() / "gb" / "test.gb")

    def test_catalog_rejects_non_http_urls(self):
        with self.assertRaises(ValueError):
            validate_catalog({"GB": {"folder": "gb", "games": [
                {"name": "Test", "filename": "a.gb", "url": "file:///etc/passwd"}]}})

    def test_navigation_search_and_read_only(self):
        app = Application(self.catalog, "unused", read_only=True)
        app.act("select")
        self.assertEqual(app.system, "Game Boy")
        app.act("search")
        self.assertEqual(app.page, "keyboard")
        app.draft = "download"
        app.act("search")
        self.assertEqual(len(app.items()), 1)
        app.act("select")
        self.assertEqual(app.page, "notice")
        self.assertIsNone(app.job)
        app.act("back")
        app.act("back")
        self.assertIsNone(app.system)

    def test_empty_system_and_keyboard_wrap(self):
        app = Application(self.catalog, "unused")
        app.index = 2
        app.act("select")
        self.assertEqual(app.items(), [])
        app.act("select")
        self.assertEqual(app.page, "list")
        app.act("search")
        app.act("up")
        app.act("left")
        self.assertEqual(app.KEYBOARD[app.keyboard_index], "Listo")
        app.act("select")
        self.assertEqual(app.page, "list")


if __name__ == "__main__":
    unittest.main()
