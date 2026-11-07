import unittest
from urllib.parse import parse_qs, urlsplit

from import_site import Page
from romsgames_source import resolved_entry


class SourceTests(unittest.TestCase):
    PAGE = 'https://www.romsgames.net/playstation-portable-rom-demo/'

    def test_form_query_and_decoded_filename(self):
        entry = resolved_entry({'downloadUrl': 'https://static.romsgames.net/test/output.bin',
                                'downloadName': 'Demo%20Game.7z', 'asset': {'title': 'Demo Game'}}, self.PAGE, 123)
        self.assertEqual(entry['filename'], 'Demo Game.7z')
        query = parse_qs(urlsplit(entry['url']).query)
        self.assertEqual(query['mediaId'], ['123'])
        self.assertEqual(query['attach'], ['Demo%20Game.7z'])
        self.assertEqual(entry['source_page'], self.PAGE)

    def test_invalid_download_response_is_rejected(self):
        for response in ({}, {'downloadUrl': 'https://ads.example/file', 'downloadName': 'a.zip'},
                         {'downloadUrl': 'https://static.romsgames.net/file', 'downloadName': '..%2Ffile.zip'}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                resolved_entry(response, self.PAGE, 123)

    def test_live_button_id_survives_empty_hidden_input(self):
        page = Page('<button data-media-id="123">Download</button><input id="media-id" value="">')
        self.assertEqual(page.media_id, '123')


if __name__ == '__main__':
    unittest.main()
