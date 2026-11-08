"""Pruebas HTTP reales de rangos, reconstrucción, retroceso y cancelación."""
import http.server
from pathlib import Path
import random
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from download_core import Download

PAYLOAD = random.Random(55).randbytes(1024 * 1024 + 137)


class Handler(http.server.BaseHTTPRequestHandler):
    requests = []
    lock = threading.Lock()
    range_started = threading.Event()

    def log_message(self, *args):
        pass

    def do_GET(self):
        requested = self.headers.get('Range')
        with self.lock:
            self.requests.append((self.path, requested, self.headers.get('If-Range')))
            full_count = sum(p == self.path and r is None for p, r, _ in self.requests)
        if self.path == '/fallback-error' and not requested and full_count > 1:
            self.send_error(503)
            return
        body = PAYLOAD
        if self.path == '/small':
            body = body[:512]
        start, end = 0, len(body)-1
        status = 200
        if requested and self.path != '/ignore':
            start, end = map(int, requested.removeprefix('bytes=').split('-'))
            status = 206
            body = PAYLOAD[start:end+1]
        self.send_response(status)
        self.send_header('Content-Type', 'application/octet-stream')
        if self.path != '/no-ranges':
            self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('ETag', '"changed"' if requested and self.path == '/changed' else '"fixture"')
        if status == 206:
            offset = 1 if self.path in ('/bad-offset', '/fallback-error') else 0
            total = len(PAYLOAD)+1 if self.path == '/bad-total' else len(PAYLOAD)
            self.send_header('Content-Range', f'bytes {start+offset}-{end}/{total}')
        self.end_headers()
        if requested:
            self.range_started.set()
        if requested and self.path == '/short':
            body = body[:-15]
        try:
            for i in range(0, len(body), 8192):
                self.wfile.write(body[i:i+8192])
                self.wfile.flush()
                if requested and self.path == '/slow':
                    time.sleep(.015)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        self.close_connection = True


class ParallelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        Handler.requests.clear()
        Handler.range_started.clear()
        self.threshold = patch.object(Download, 'PARALLEL_THRESHOLD', 1024)
        self.threshold.start()
        self.addCleanup(self.threshold.stop)

    def job(self, route, target):
        return Download(f'http://127.0.0.1:{self.server.server_port}{route}', target).start()

    def test_four_disjoint_ranges_reconstruct_exact_file(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'test.iso'
            job = self.job('/ranges', target)
            job.thread.join(6)
            self.assertFalse(job.thread.is_alive())
            self.assertEqual(job.snapshot()['status'], 'done')
            self.assertEqual(job.snapshot()['connections'], 4)
            self.assertEqual(job.snapshot()['downloaded'], len(PAYLOAD))
            self.assertEqual(target.read_bytes(), PAYLOAD)
            ranges = [r for r in Handler.requests if r[1]]
            self.assertEqual(len(ranges), 4)
            self.assertTrue(all(r[2] == '"fixture"' for r in ranges))
            self.assertFalse(list(Path(root).glob('*.part')))

    def test_unsupported_bad_and_truncated_ranges_restart_cleanly(self):
        for route in ['/ignore', '/bad-offset', '/bad-total', '/short', '/changed']:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as root:
                Handler.requests.clear()
                target = Path(root)/'test.iso'
                target.write_bytes(b'original')
                job = self.job(route, target)
                job.thread.join(6)
                self.assertFalse(job.thread.is_alive())
                self.assertEqual(job.snapshot()['status'], 'done', job.snapshot())
                self.assertEqual(job.snapshot()['connections'], 1)
                self.assertEqual(target.read_bytes(), PAYLOAD)
                self.assertEqual(sum(r[1] is None for r in Handler.requests), 2)
                self.assertFalse(list(Path(root).glob('*.part')))

    def test_small_file_uses_one_request(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'small.gb'
            job = self.job('/small', target)
            job.thread.join(6)
            self.assertEqual(job.snapshot()['status'], 'done')
            self.assertEqual(len(Handler.requests), 1)
            self.assertEqual(target.read_bytes(), PAYLOAD[:512])

    def test_server_without_range_support_uses_one_request(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'test.iso'
            job = self.job('/no-ranges', target)
            job.thread.join(6)
            self.assertEqual(job.snapshot()['status'], 'done')
            self.assertEqual(len(Handler.requests), 1)
            self.assertEqual(target.read_bytes(), PAYLOAD)

    def test_failed_fallback_preserves_existing_file_and_cleans_sparse_temporary(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'test.iso'
            target.write_bytes(b'original')
            job = self.job('/fallback-error', target)
            job.thread.join(6)
            self.assertFalse(job.thread.is_alive())
            self.assertEqual(job.snapshot()['status'], 'error')
            self.assertEqual(job.snapshot()['error_kind'], 'server')
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(list(Path(root).glob('*.part')))

    def test_cancel_waits_for_workers_and_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)/'test.iso'
            target.write_bytes(b'original')
            job = self.job('/slow', target)
            self.assertTrue(Handler.range_started.wait(3))
            job.cancel.set()
            job.thread.join(6)
            self.assertFalse(job.thread.is_alive())
            self.assertEqual(job.snapshot()['status'], 'cancelled')
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(list(Path(root).glob('*.part')))


if __name__ == '__main__':
    unittest.main()
