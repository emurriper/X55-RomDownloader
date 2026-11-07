"""Convierte el índice de fichas en catálogo con resolución al seleccionar."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from download_core import read_catalog, validate_catalog
from x55_systems import SYSTEMS, SELECTED


def title_key(name):
    name = re.sub(r'\([^)]*\)', '', name)
    return ''.join(c for c in unicodedata.normalize('NFKD', name.casefold()) if c.isalnum())


def build(index, previous, selected=None):
    selected = SELECTED if selected is None else selected
    if not set(selected).issubset(SYSTEMS):
        raise ValueError('La selección contiene sistemas fuera del perfil de X55.')
    catalog = {}
    for slug in selected:
        system = index['systems'][slug]
        policy = SYSTEMS[slug]
        if not system.get('catalogue_complete'):
            raise ValueError('Índice incompleto o sin carpeta: ' + slug)
        old = next((entry for entry in previous.values() if entry['folder'] == policy['folder']), {'games': []})
        known = {title_key(game['name']): game for game in old['games']}
        games = []
        for item in system['games']:
            page = item['page_url']
            entry = {'name': item['name'], 'filename': 'rg-' + hashlib.sha256(page.encode()).hexdigest()[:20] + '.download',
                     'source_provider': 'romsgames', 'source_page': page}
            existing = known.get(title_key(item['name']))
            if existing:
                entry['filename'] = existing['filename']
                if existing.get('installed_filename'):
                    entry['installed_filename'] = existing['installed_filename']
            games.append(entry)
        catalog[policy['name']] = {'folder': policy['folder'], 'games': games,
                                   'performance': policy['performance'], 'notice': policy.get('notice', ''),
                                   'archive_mode': policy['archive_mode']}
    return validate_catalog(catalog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=Path('site_index.json'))
    parser.add_argument('--previous', type=Path, default=Path('catalog.json'))
    parser.add_argument('--output', type=Path, default=Path('catalog.expanded.json'))
    args = parser.parse_args()
    index = json.loads(args.index.read_text(encoding='utf-8'))
    previous = read_catalog(args.previous)
    catalog = build(index, previous)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Catálogo generado:', sum(len(system['games']) for system in catalog.values()), 'juegos')
    print('Salida:', args.output)


if __name__ == '__main__':
    main()
