from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cover_art import CoverCache, CoverPage, cache_key, image_url, prune_cache
from x55_systems import SYSTEMS, SELECTED


class CoverTests(unittest.TestCase):
    def test_only_image_matching_selected_game_is_used(self):
        page = 'https://www.romsgames.net/nintendo-rom-demo/'
        parser = CoverPage(page, 'Demo (USA)')
        parser.feed('<img alt="RomsGames" src="/image/logo.png">'
                    '<img alt="Other Game" src="https://cache.downloadroms.io/other.jpg">'
                    '<img alt="Demo" src="https://cache.downloadroms.io/demo.jpg">')
        self.assertEqual(parser.image, 'https://cache.downloadroms.io/demo.jpg')

    def test_unrelated_hosts_and_non_https_are_rejected(self):
        page = 'https://www.romsgames.net/nintendo-rom-demo/'
        for url in ['file:///tmp/a.png', 'https://ads.example/a.jpg',
                    'http://cache.downloadroms.io/a.jpg', 'https://user:pass@cache.downloadroms.io/a.jpg']:
            self.assertIsNone(image_url(url, page))

    def test_local_image_is_reduced_and_cache_hit_needs_no_network(self):
        with tempfile.TemporaryDirectory() as root:
            images = Path(root)/'nes/images'
            images.mkdir(parents=True)
            source = images/'Demo (USA)-image.png'
            source.write_bytes(b'local image')
            cache = CoverCache(root)
            self.addCleanup(cache.close)
            game = {'name': 'Demo', 'source_page': 'https://www.romsgames.net/nintendo-rom-demo/'}
            def convert(input_path, output):
                self.assertEqual(input_path.resolve(), source.resolve())
                output.write_bytes(b'\xff\xd8\xffthumbnail')
            with patch.object(cache, '_convert', side_effect=convert) as converter, patch('cover_art.urlopen') as network:
                result = cache._load(cache_key(game), game)
                self.assertEqual(result.read_bytes(), b'\xff\xd8\xffthumbnail')
                self.assertEqual(cache._load(cache_key(game), game), result)
                self.assertEqual(converter.call_count, 1)
                network.assert_not_called()

    def test_cache_evicts_only_owned_oldest_images(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old, recent = root/('a'*64+'.jpg'), root/('b'*64+'.jpg')
            old.write_bytes(b'x'*20)
            recent.write_bytes(b'x'*20)
            unrelated = root/'personal.jpg'
            unrelated.write_bytes(b'keep')
            prune_cache(root, limit=20, keep=recent)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())

    def test_same_title_in_different_systems_gets_different_cache_key(self):
        game = {'name': 'Demo'}
        self.assertNotEqual(cache_key(game, 'nes'), cache_key(game, 'psp'))

    def test_local_image_lookup_isolated_for_all_supported_systems(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CoverCache(root)
            self.addCleanup(cache.close)
            for slug in SELECTED:
                folder = SYSTEMS[slug]['folder']
                images = Path(root)/folder/'images'
                images.mkdir(parents=True, exist_ok=True)
                source = images/'Demo-image.png'
                source.write_bytes(b'local image')
                with self.subTest(folder=folder):
                    self.assertEqual(cache._local_image('Demo', folder).resolve(), source.resolve())
                    self.assertLessEqual(len(cache.local_indexes), 3)

    def test_disk_budget_is_shared_across_systems(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old, recent = root/'nes'/('a'*64+'.jpg'), root/'psp'/('b'*64+'.jpg')
            old.parent.mkdir()
            recent.parent.mkdir()
            old.write_bytes(b'a'*20)
            recent.write_bytes(b'b'*20)
            prune_cache(root, limit=20, keep=recent)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())

    def test_invalid_system_cannot_escape_cache_directory(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CoverCache(root)
            self.addCleanup(cache.close)
            for folder in ['../outside', '/tmp', 'psp/../../outside', '']:
                with self.subTest(folder=folder), self.assertRaises(ValueError):
                    cache.select({'name': 'Demo'}, folder)

    def test_fast_navigation_loads_only_latest_selection(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CoverCache(root)
            self.addCleanup(cache.close)
            ready = threading.Event()
            loaded = []
            def load(key, game):
                loaded.append(game['name'])
                ready.set()
                return Path(root)/'latest.jpg'
            with patch.object(cache, '_load', side_effect=load):
                cache.select({'name': 'First'})
                cache.select({'name': 'Last'})
                self.assertTrue(ready.wait(2))
            self.assertEqual(loaded, ['Last'])

    def test_stale_worker_cannot_replace_new_selection(self):
        with tempfile.TemporaryDirectory() as root:
            cache = CoverCache(root)
            self.addCleanup(cache.close)
            started, release, done = threading.Event(), threading.Event(), threading.Event()
            def load(key, game):
                if game['name'] == 'First':
                    started.set()
                    release.wait(2)
                else:
                    done.set()
                return Path(root)/(game['name']+'.jpg')
            with patch.object(cache, '_load', side_effect=load):
                cache.select({'name': 'First'})
                self.assertTrue(started.wait(2))
                cache.select({'name': 'Last'})
                release.set()
                self.assertTrue(done.wait(2))
                deadline = time.monotonic()+1
                while cache.select({'name': 'Last'})[0] is None and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertEqual(cache.select({'name': 'Last'})[0].name, 'Last.jpg')


if __name__ == '__main__':
    unittest.main()
