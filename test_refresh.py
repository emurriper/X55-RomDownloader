from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import io
import urllib.error
from unittest.mock import MagicMock, patch

from emulationstation_refresh import MARKER, is_pending, mark_pending, refresh_pending
from graphical_app import Application


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def response(self, status=200):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = status
        return opener

    def test_browsing_does_not_request_refresh(self):
        opener = self.response()
        self.assertFalse(refresh_pending(self.root, opener)[0])
        opener.open.assert_not_called()

    def test_successful_request_consumes_marker_once(self):
        mark_pending(self.root)
        mark_pending(self.root)
        opener = self.response()
        self.assertTrue(refresh_pending(self.root, opener)[0])
        self.assertFalse(is_pending(self.root))
        refresh_pending(self.root, opener)
        opener.open.assert_called_once_with('http://127.0.0.1:1234/reloadgames', timeout=3)

    def test_failure_is_retried_next_session(self):
        mark_pending(self.root)
        opener = self.response()
        opener.open.side_effect = OSError('service unavailable')
        self.assertFalse(refresh_pending(self.root, opener)[0])
        self.assertTrue(is_pending(self.root))
        self.assertTrue(refresh_pending(self.root, self.response())[0])

    def test_unexpected_http_status_keeps_marker(self):
        mark_pending(self.root)
        self.assertFalse(refresh_pending(self.root, self.response(503))[0])
        self.assertTrue(is_pending(self.root))

    def test_rejected_request_closes_response_and_keeps_marker(self):
        mark_pending(self.root)
        stream = io.BytesIO(b'forbidden')
        opener = self.response()
        opener.open.side_effect = urllib.error.HTTPError('http://127.0.0.1:1234/reloadgames', 403, 'Forbidden', {}, stream)
        self.assertFalse(refresh_pending(self.root, opener)[0])
        self.assertTrue(stream.closed)
        self.assertTrue(is_pending(self.root))

    def test_failed_extraction_does_not_schedule_refresh(self):
        app = Application({}, self.root)
        app.page = 'extract'
        app.job = SimpleNamespace(snapshot=lambda: {'status': 'error'})
        app.advance()
        self.assertFalse(is_pending(self.root))

    def test_verified_rom_schedules_refresh_before_archive_choice(self):
        app = Application({}, self.root)
        app.page = 'extract'
        app.job = SimpleNamespace(snapshot=lambda: {'status': 'done'})
        app.advance()
        self.assertEqual(app.page, 'zip_choice')
        self.assertTrue(is_pending(self.root))

    def test_raw_rom_is_scheduled_even_when_user_leaves_immediately(self):
        app = Application({}, self.root)
        app.page = 'download'
        app.destination = self.root / 'demo.gba'
        app.job = SimpleNamespace(snapshot=lambda: {'status': 'done'})
        app.act('back')
        self.assertEqual(app.page, 'list')
        self.assertTrue(is_pending(self.root))

    def test_refresh_happens_after_window_closes_and_read_only_skips_it(self):
        for read_only in (False, True):
            with self.subTest(read_only=read_only):
                app = Application({}, self.root, read_only=read_only)
                app.running = False
                screen = MagicMock()
                calls = []
                screen.close.side_effect = lambda: calls.append('close')
                def refresh(root):
                    calls.append('refresh')
                    return True, 'requested'
                with patch('graphical_app.Screen', return_value=screen), patch('graphical_app.refresh_pending', side_effect=refresh):
                    app.run()
                self.assertEqual(calls, ['close'] if read_only else ['close', 'refresh'])


if __name__ == '__main__':
    unittest.main()
