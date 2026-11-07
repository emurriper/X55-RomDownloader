import json
from pathlib import Path
import tempfile
import unittest

from import_site import import_pages, site_url


class ImportTests(unittest.TestCase):
    def test_listing_card_with_legacy_slug_excludes_footer(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'atari.html'
            path.write_text('''<link rel="canonical" href="https://www.romsgames.net/roms/atari-2600/">
                <a class="shadow-lg" href="/atari-2006-rom-adventure/">Adventure</a>
                <a href="/atari-2600-rom-footer/">Footer</a>
                <div>Showing 1 to 1 of 1</div>''', encoding='utf-8')
            entry = import_pages([path])['systems']['atari-2600']
            self.assertTrue(entry['catalogue_complete'])
            self.assertEqual([game['name'] for game in entry['games']], ['Adventure'])

    def test_listing_pagination_deduplication_and_download_form(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            listing = root / 'listing.html'
            listing.write_text('''<link rel="canonical" href="https://www.romsgames.net/roms/playstation-portable/?letter=all&amp;sort=alphabetical">
                <a href="/playstation-portable-rom-demo/">Demo &amp; Test</a>
                <a href="/playstation-portable-rom-demo/">Duplicate</a>
                <a href="https://ads.example/playstation-portable-rom-ad/">Ad</a>
                <a href="?letter=all&amp;page=62&amp;sort=alphabetical">62</a>
                <a href="?letter=a&amp;page=999&amp;sort=alphabetical">A</a>
                <div>Showing 1 to 36 of 2207</div>''', encoding='utf-8')
            game = root / 'game.html'
            game.write_text('''<link rel="canonical" href="https://www.romsgames.net/playstation-portable-rom-demo/">
                <form id="download-form" action="https://static.romsgames.net/sample/output.bin"></form>
                <input id="media-id" value="123"><input id="media-attach" value="Demo%20Game.7z">
                <a href="/playstation-portable-rom-recommendation/">Recommendation</a>''', encoding='utf-8')
            entry = import_pages([listing, game])['systems']['playstation-portable']
            self.assertEqual(entry['folder'], 'psp')
            self.assertEqual(entry['page_count_hint'], 62)
            self.assertEqual(entry['total_games_hint'], 2207)
            self.assertEqual(len(entry['games']), 1)
            item = entry['games'][0]
            self.assertEqual(item['name'], 'Demo & Test')
            self.assertEqual(item['download_status'], 'needs_resolution')
            self.assertNotIn('url', item)
            self.assertEqual(item['download_page']['declared_filename'], 'Demo Game.7z')
            self.assertFalse(item['download_page']['automatic_extraction_supported'])
            json.dumps(entry)

    def test_consoles_and_unsupported_folder_are_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            page = Path(root) / 'consoles.html'
            page.write_text('''<link rel="canonical" href="https://www.romsgames.net/roms/">
                <a href="/roms/playstation-portable/">Playstation Portable 2207 Games</a><a href="/roms/unknown-console/">Other</a>''')
            result = import_pages([page])
            self.assertIn('playstation-portable', result['systems'])
            self.assertEqual(result['systems']['playstation-portable']['total_games_hint'], 2207)
            self.assertEqual(result['systems']['playstation-portable']['source_name'], 'Playstation Portable')
            self.assertIsNone(result['systems']['unknown-console']['folder'])
            self.assertFalse(any('muestra' in warning for warning in result['warnings']))

    def test_external_and_javascript_urls_are_rejected(self):
        self.assertIsNone(site_url('javascript:alert(1)'))
        self.assertIsNone(site_url('https://romsgames.net.evil.example/roms/'))
        self.assertIsNone(site_url('https://romsfun.com/roms/'))

    def test_footer_games_do_not_pollute_listing_cards(self):
        with tempfile.TemporaryDirectory() as root:
            page = Path(root) / 'listing.html'
            page.write_text('''<link rel="canonical" href="https://www.romsgames.net/roms/gameboy-advance/">
                <a class="relative shadow-lg" href="/gameboy-advance-rom-listed/">Listed game</a>
                <footer><a href="/gameboy-advance-rom-footer-only/">Footer recommendation</a></footer>''')
            games = import_pages([page])['systems']['gameboy-advance']['games']
            self.assertEqual([game['name'] for game in games], ['Listed game'])


if __name__ == '__main__':
    unittest.main()
