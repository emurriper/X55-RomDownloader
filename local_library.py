"""Índice de ROMs existentes: solo nombres, metadatos y tamaño, sin modificar archivos."""

import os
from pathlib import Path
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from x55_systems import FORMATS as X55_FORMATS


FORMATS = {
    'gb': {'.gb'}, 'gbc': {'.gbc', '.gb'}, 'gba': {'.gba'},
    'nes': {'.nes', '.fds'}, 'snes': {'.sfc', '.smc'},
    'megadrive': {'.md', '.gen', '.bin', '.smd'}, 'genesis': {'.md', '.gen', '.bin', '.smd'},
    'psx': {'.chd', '.pbp', '.cue', '.iso', '.img', '.bin', '.m3u'},
    'psp': {'.iso', '.cso', '.pbp', '.chd'},
    'n64': {'.n64', '.z64', '.v64'}, 'nds': {'.nds'},
}
for folder, extensions in X55_FORMATS.items():
    FORMATS.setdefault(folder, set()).update(extensions)
ALIASES = {'megadrive': ('megadrive', 'genesis'), 'genesis': ('genesis', 'megadrive')}
REGIONS = {'usa', 'us', 'europe', 'eu', 'japan', 'jp', 'world', 'australia', 'france',
           'germany', 'spain', 'italy', 'uk', 'united kingdom', 'canada', 'korea',
           'china', 'taiwan', 'brazil', 'sweden', 'netherlands', 'russia', 'asia',
           'hong kong', 'finland', 'denmark', 'norway', 'portugal'}
LANGUAGES = {'en', 'fr', 'de', 'es', 'it', 'ja', 'ko', 'zh', 'nl', 'pt', 'ru', 'sv',
             'fi', 'da', 'no', 'pl', 'cs', 'hu', 'tr'}


def title_key(title):
    def parenthesis(match):
        value = match[1].strip().casefold()
        pieces = [p.strip() for p in re.split(r'[,/;+]', value)]
        if (pieces and all(p in REGIONS or p in LANGUAGES for p in pieces)
                or re.fullmatch(r'(?:rev(?:ision)?\s*[a-z0-9.]+|v(?:er(?:sion)?)?\s*\d[\w. -]*|multi\d+)', value)):
            return ' '
        return match[0]
    title = re.sub(r'\(([^()]*)\)', parenthesis, str(title))
    # Etiquetas de traducción y verificación, sin eliminar hacks o demos por defecto.
    title = re.sub(r'\[(?:T[-+][^\]]*|Add by[^\]]*|[!nbaofp](?:\d+)?|[!])\]', ' ', title, flags=re.I)
    title = title.strip()
    article = re.fullmatch(r'(.+),\s*(The|A|An)', title, flags=re.I)
    if article:
        title = article[2] + ' ' + article[1]
    title = unicodedata.normalize('NFKD', title.casefold().replace('&', ' and '))
    return ''.join(c for c in title if c.isalnum())


class LocalLibrary:
    def __init__(self, root, ttl=10):
        self.root = Path(root).resolve()
        self.ttl = ttl
        self.cache = {}

    def invalidate(self, folder=None):
        if folder is None:
            self.cache.clear()
        else:
            self.cache.pop(folder, None)

    def _scan(self, folder):
        index = {}
        formats = FORMATS.get(folder, set())
        if not formats:
            return index
        for alias in ALIASES.get(folder, (folder,)):
            directory = self.root / alias
            try:
                if not directory.resolve().is_relative_to(self.root):
                    continue
            except OSError:
                continue
            metadata = []
            valid_files = set()
            for current, folders, files in os.walk(directory, followlinks=False):
                folders[:] = [name for name in folders if not name.startswith('.')
                              and name.casefold() not in ('images', 'videos', 'manuals', 'media', 'saves', 'states')]
                for name in files:
                    path = Path(current) / name
                    if name == 'gamelist.xml':
                        if not path.is_symlink():
                            metadata.append(path)
                        continue
                    if name.startswith('.') or path.suffix.lower() not in formats or path.is_symlink():
                        continue
                    try:
                        if not path.is_file() or path.stat().st_size <= 0:
                            continue
                    except OSError:
                        continue
                    valid_files.add(path)
                    key = title_key(path.stem)
                    if key:
                        index.setdefault(key, {})[path] = 'name'
            for source in metadata:
                try:
                    tree = ET.parse(source)
                except (OSError, ET.ParseError):
                    continue
                for game in tree.getroot().findall('game'):
                    raw_path, name = game.findtext('path'), game.findtext('name')
                    if not raw_path or not name:
                        continue
                    try:
                        path = (source.parent / raw_path).resolve()
                        if not path.is_relative_to(directory.resolve()) or path not in valid_files:
                            continue
                    except OSError:
                        continue
                    key = title_key(name)
                    if key:
                        index.setdefault(key, {}).setdefault(path, 'gamelist')
        return index

    def find(self, folder, game):
        now = time.monotonic()
        cached = self.cache.get(folder)
        if cached is None or now - cached[0] >= self.ttl:
            cached = now, self._scan(folder)
            self.cache[folder] = cached
        keys = [title_key(game.get('name', ''))]
        filename = game.get('filename', '')
        if Path(filename).suffix.lower() != '.download':
            keys.append(title_key(Path(filename).stem))
        for key in keys:
            matches = cached[1].get(key, {})
            # Revalidar los archivos detectados para no conservar instalados borrados.
            live = []
            for path, method in matches.items():
                try:
                    if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                        live.append((path, method))
                except OSError:
                    pass
            if live:
                live.sort(key=lambda entry: str(entry[0]).casefold())
                return {'path': live[0][0], 'matched_by': live[0][1], 'matches': len(live)}
        return None
