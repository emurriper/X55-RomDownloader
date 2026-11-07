"""Importa un índice de RomsGames desde páginas HTML guardadas, sin descargar ROMs.

El resultado es un índice de fichas, NO un catalog.json de enlaces directos.
"""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit


SYSTEMS = {
    'playstation-portable': ('PSP', 'psp'), 'playstation': ('PlayStation', 'psx'),
    'gameboy': ('Game Boy', 'gb'), 'gameboy-color': ('Game Boy Color', 'gbc'),
    'gameboy-advance': ('Game Boy Advance', 'gba'), 'nintendo': ('NES', 'nes'),
    'super-nintendo': ('Super Nintendo', 'snes'), 'nintendo-64': ('Nintendo 64', 'n64'),
    'nintendo-ds': ('Nintendo DS', 'nds'), 'sega-genesis': ('Mega Drive', 'megadrive'),
    'sega-master-system': ('Master System', 'mastersystem'), 'sega-game-gear': ('Game Gear', 'gamegear'),
    'neo-geo': ('Neo Geo', 'neogeo'),
    'snk-neo-geo': ('Neo Geo', 'neogeo'), 'game-gear': ('Game Gear', 'gamegear'),
}
from x55_systems import SYSTEMS as X55_SYSTEMS
SYSTEMS.update({slug: (entry['name'], entry['folder']) for slug, entry in X55_SYSTEMS.items()})


def site_url(value, base='https://www.romsgames.net/'):
    parsed = urlsplit(urljoin(base, value))
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('romsgames.net', 'www.romsgames.net'):
        return None
    return urlunsplit(('https', 'www.romsgames.net', parsed.path, parsed.query, ''))


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.canonical = None
        self.og_url = None
        self.links = []
        self.anchor = None
        self.visible = []
        self.hidden = 0
        self.download_action = None
        self.media_id = None
        self.filename = None
        self.captcha = False
        self.feed(html)
        self.canonical = site_url(self.canonical or self.og_url or '') if (self.canonical or self.og_url) else None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'link' and 'canonical' in attrs.get('rel', '').split():
            self.canonical = attrs.get('href')
        if tag == 'meta' and attrs.get('property') == 'og:url':
            self.og_url = attrs.get('content')
        if tag == 'a':
            self.anchor = {'href': attrs.get('href', ''), 'text': [], 'rel': attrs.get('rel', ''),
                           'class': attrs.get('class', '')}
        if tag == 'form' and attrs.get('id') == 'download-form':
            self.download_action = attrs.get('action')
        if tag == 'input' and attrs.get('id') == 'media-id':
            self.media_id = attrs.get('value') or self.media_id
        if tag == 'button' and attrs.get('data-media-id') and not self.media_id:
            self.media_id = attrs['data-media-id']
        if tag == 'input' and attrs.get('id') == 'media-attach':
            self.filename = unquote(attrs.get('value', ''))
        if 'recaptcha' in attrs.get('class', '') or attrs.get('id') == 'recaptcha':
            self.captcha = True

    def handle_data(self, data):
        if not self.hidden:
            self.visible.append(data)
            if self.anchor is not None:
                self.anchor['text'].append(data)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a' and self.anchor is not None:
            self.anchor['text'] = ' '.join(' '.join(self.anchor['text']).split())
            self.links.append(self.anchor)
            self.anchor = None


def import_pages(paths):
    index = {'schema_version': 1, 'site': 'romsgames.net', 'kind': 'page_index',
             'systems': {}, 'samples': [], 'warnings': []}
    details = {}
    console_sample = False

    def system(slug):
        name, folder = SYSTEMS.get(slug, (slug.replace('-', ' ').title(), None))
        return index['systems'].setdefault(slug, {'name': name, 'folder': folder,
            'catalogue_url': f'https://www.romsgames.net/roms/{slug}/',
            'pages_seen': [], 'page_count_hint': None, 'total_games_hint': None, 'games': []})

    for path in paths:
        page = Page(Path(path).read_text(encoding='utf-8-sig', errors='replace'))
        if not page.canonical:
            index['warnings'].append(f'Sin URL canónica reconocida: {Path(path).name}')
            continue
        parsed = urlsplit(page.canonical)
        index['samples'].append({'file': Path(path).name, 'url': page.canonical})
        if parsed.path.rstrip('/') == '/roms':
            console_sample = True
            for link in page.links:
                url = site_url(link['href'], page.canonical)
                match = re.fullmatch(r'/roms/([^/]+)/?', urlsplit(url).path) if url else None
                if match:
                    entry = system(match[1])
                    count = re.fullmatch(r'(.+?)\s+([\d,]+)\s+Games?', link['text'], re.I)
                    label = count[1] if count else link['text']
                    if label:
                        entry['source_name'] = label
                        if match[1] not in SYSTEMS:
                            entry['name'] = label
                    if count and entry['total_games_hint'] is None:
                        entry['total_games_hint'] = int(count[2].replace(',', ''))
            continue
        match = re.fullmatch(r'/roms/([^/]+)/?', parsed.path)
        if match:
            slug = match[1]
            entry = system(slug)
            if page.canonical not in entry['pages_seen']:
                entry['pages_seen'].append(page.canonical)
            known = {game['page_url'] for game in entry['games']}
            pages = [1]
            filters = parse_qs(parsed.query)
            # Los pies de página también enlazan juegos del mismo sistema.
            # Si hay tarjetas reconocibles, importar solo esas tarjetas.
            card_urls = {site_url(link['href'], page.canonical) for link in page.links
                         if 'shadow-lg' in link['class'].split()
                         and '-rom-' in urlsplit(link['href']).path}
            for link in page.links:
                url = site_url(link['href'], page.canonical)
                if not url:
                    continue
                target = urlsplit(url)
                if (url in card_urls or target.path.startswith(f'/{slug}-rom-')) and link['text']:
                    if card_urls and url not in card_urls:
                        continue
                    game_url = urlunsplit((target.scheme, target.netloc, target.path, '', ''))
                    if game_url not in known:
                        known.add(game_url)
                        entry['games'].append({'name': link['text'], 'page_url': game_url,
                                               'download_status': 'needs_resolution'})
                elif target.path.rstrip('/') == parsed.path.rstrip('/'):
                    query = parse_qs(target.query)
                    if all(query.get(key, default) == filters.get(key, default)
                           for key, default in (('letter', ['all']), ('sort', ['alphabetical']))):
                        number = query.get('page', ['1'])[0]
                        if number.isdecimal():
                            pages.append(int(number))
            entry['page_count_hint'] = max(entry['page_count_hint'] or 1, *pages)
            showing = re.search(r'Showing\s+[\d,]+\s+to\s+[\d,]+\s+of\s+([\d,]+)', ' '.join(page.visible), re.I)
            if showing:
                entry['total_games_hint'] = int(showing[1].replace(',', ''))
        elif page.download_action:
            details[page.canonical.split('?')[0]] = {
                'declared_filename': page.filename, 'media_id': page.media_id,
                'download_action_host': urlsplit(page.download_action).hostname,
                'requires_javascript': True, 'captcha_present_in_sample': page.captcha,
                'automatic_extraction_supported': bool(page.filename and Path(page.filename).suffix.lower() == '.zip'),
            }
    for entry in index['systems'].values():
        for game in entry['games']:
            if game['page_url'] in details:
                game['download_page'] = details[game['page_url']]
        entry['catalogue_complete'] = (entry['total_games_hint'] is not None
                                       and len(entry['games']) == entry['total_games_hint'])
    if not console_sample:
        index['warnings'].append('No se encontró la muestra de la página de consolas; el índice de sistemas está incompleto.')
    index['warnings'].append('Las fichas no son enlaces directos. No importar este índice como catalog.json.')
    return index


def crawl_system(slug, max_pages=500, delay=1.5, cache_dir=Path('site_cache'), resume=False):
    from romsgames_source import fetch_page
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        raise ValueError('Slug de sistema inválido.')
    if not 1 <= max_pages <= 500 or delay < 1:
        raise ValueError('Usa entre 1 y 500 páginas y una pausa de al menos 1 segundo.')
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths, previous_games = [], None
    total_pages = max_pages
    for number in range(1, max_pages + 1):
        if number > total_pages:
            break
        path = cache_dir / f'romsgames-{slug}-{number:03}.html'
        cached = resume and path.is_file()
        if not cached:
            time.sleep(delay)
            url = f'https://www.romsgames.net/roms/{slug}/?letter=all&page={number}&sort=alphabetical'
            path.write_text(fetch_page(url), encoding='utf-8')
        entry = import_pages([path])['systems'].get(slug)
        if not entry or not entry['games']:
            raise ValueError(f'{slug}, página {number}: no contiene juegos reconocidos.')
        fingerprint = tuple(game['page_url'] for game in entry['games'])
        if fingerprint == previous_games:
            raise ValueError('El sitio repitió una página; se detuvo la importación.')
        previous_games = fingerprint
        total_pages = min(max_pages, entry['page_count_hint'] or max_pages)
        paths.append(path)
        print(f"{slug} {number}/{total_pages}: {len(entry['games'])} fichas" + (' (cache)' if cached else ''), flush=True)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, default=Path('site_index.json'))
    parser.add_argument('--crawl-system', help='Slug del sistema a consultar en la web, por ejemplo playstation-portable')
    parser.add_argument('--max-pages', type=int, default=2, help='Límite de páginas web; por defecto 2')
    parser.add_argument('--delay', type=float, default=1.5, help='Pausa entre peticiones, mínimo 1 segundo')
    parser.add_argument('--cache-dir', type=Path, default=Path('site_cache'))
    parser.add_argument('--resume', action='store_true', help='Reutilizar las páginas ya guardadas')
    args = parser.parse_args()
    paths = sorted(path for path in args.input_dir.iterdir() if path.is_file() and path.suffix.lower() in ('.html', '.htm'))
    if args.crawl_system:
        paths.extend(crawl_system(args.crawl_system, args.max_pages, args.delay, args.cache_dir, args.resume))
    # Reutiliza las páginas consultadas previamente al reconstruir el índice.
    paths.extend(sorted(args.cache_dir.glob('romsgames-*.html')))
    paths = list(dict.fromkeys(paths))
    if not paths:
        parser.error('No se encontraron páginas HTML guardadas.')
    index = import_pages(paths)
    if not index['systems']:
        parser.error('No se reconoció ningún catálogo de RomsGames. No se escribió el índice.')
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Sistemas encontrados:', len(index['systems']))
    for slug, entry in index['systems'].items():
        if entry['pages_seen']:
            print(f"{slug}: {len(entry['games'])} fichas importadas; total anunciado: {entry['total_games_hint']}; páginas: {entry['page_count_hint']}")
    print('Índice escrito:', args.output)
    for warning in index['warnings']:
        print('AVISO:', warning)


if __name__ == '__main__':
    main()
