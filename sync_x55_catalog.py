"""Descarga solo índices de las consolas del perfil X55, sin descargar ROMs."""

import argparse
import json
import os
from pathlib import Path
import tempfile

from build_catalog import build
from download_core import read_catalog
from import_site import crawl_system, import_pages
from x55_systems import SYSTEMS, SELECTED, REFERENCE


def save_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.catalogue-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=Path('site_index.json'))
    parser.add_argument('--previous', type=Path, default=Path('catalog.json'))
    parser.add_argument('--output', type=Path, default=Path('catalog.x55.json'))
    parser.add_argument('--cache-dir', type=Path, default=Path('site_cache'))
    parser.add_argument('--delay', type=float, default=1.5)
    parser.add_argument('--paths', type=Path, help='Mapa de carpetas obtenido de la consola')
    args = parser.parse_args()
    index = json.loads(args.index.read_text(encoding='utf-8'))
    if args.paths:
        native = json.loads(args.paths.read_text(encoding='utf-8'))
        native_paths = set(native.values())
        missing = [entry['folder'] for entry in SYSTEMS.values()
                   if '/storage/roms/' + entry['folder'] not in native_paths]
        if missing:
            raise ValueError('Carpetas no confirmadas en la consola: ' + ', '.join(missing))
    for number, slug in enumerate(SELECTED, 1):
        previous = index['systems'].get(slug, {})
        if previous.get('catalogue_complete'):
            print(f"[{number}/{len(SELECTED)}] {slug}: completo, se conserva ({len(previous['games'])} fichas)", flush=True)
            continue
        print(f'[{number}/{len(SELECTED)}] IMPORTANDO {slug}', flush=True)
        paths = crawl_system(slug, delay=args.delay, cache_dir=args.cache_dir, resume=True)
        imported = import_pages(paths)['systems'][slug]
        # Los listados de una sola pagina omiten el contador: contrastar
        # con el total publicado en el indice de consolas guardado.
        if imported['total_games_hint'] is None:
            imported['total_games_hint'] = previous.get('total_games_hint')
            imported['catalogue_complete'] = (imported['total_games_hint'] is not None
                                             and len(imported['games']) == imported['total_games_hint'])
        if not imported['catalogue_complete']:
            raise ValueError('El recuento no coincide con el anunciado: ' + slug)
        index['systems'][slug] = {**previous, **imported}
        save_json(args.index, index)
    catalog = build(index, read_catalog(args.previous))
    save_json(args.output, catalog)
    report = {'reference': REFERENCE, 'metadata_only': True,
              'systems': [{**SYSTEMS[slug], 'slug': slug, 'games': len(index['systems'][slug]['games'])}
                          for slug in SELECTED],
              'excluded_from_console_profile': sorted(set(index['systems']) - set(SELECTED)),
              'total_games': sum(len(entry['games']) for entry in catalog.values())}
    save_json('x55_catalogue_profile.json', report)
    print('LISTO:', len(catalog), 'consolas,', report['total_games'], 'fichas.', flush=True)
    print('Catálogo:', args.output, '| No se descargaron ROMs.', flush=True)


if __name__ == '__main__':
    main()
