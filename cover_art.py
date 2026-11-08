"""Miniaturas por sistema: un trabajador y caché global de disco limitada."""
from collections import OrderedDict
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from local_library import title_key, ALIASES
from x55_systems import SYSTEMS

MAX_IMAGE_BYTES = 2 * 1024 * 1024
CACHE_BYTES = 100 * 1024 * 1024
IMAGE_HOSTS = {'www.romsgames.net', 'romsgames.net', 'cache.downloadroms.io', 'cache.lategames.net'}


def image_url(value, page):
    url = urljoin(page, value)
    p = urlsplit(url)
    if p.scheme == 'https' and p.hostname in IMAGE_HOSTS and not p.username and not p.password:
        return url
    return None


class CoverPage(HTMLParser):
    def __init__(self, page, name):
        super().__init__(convert_charrefs=True)
        self.page, self.name = page, title_key(name)
        self.image = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'img' and title_key(a.get('alt', '')) == self.name:
            self.image = self.image or image_url(a.get('data-src') or a.get('src', ''), self.page)


def cache_key(game, folder='nes'):
    return hashlib.sha256((folder + '\n' + game.get('source_page', '') + '\n' + game['name']).encode()).hexdigest()


def valid_folder(folder):
    if not isinstance(folder, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', folder):
        raise ValueError('Sistema de miniaturas no valido')
    return folder


def prune_cache(directory, limit=CACHE_BYTES, keep=None):
    files = []
    directory = Path(directory)
    parents = [directory] + [p for p in directory.iterdir()
                             if p.is_dir() and not p.is_symlink()
                             and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', p.name)]
    for parent in parents:
        for p in parent.iterdir():
            if p.is_file() and not p.is_symlink() and re.fullmatch(r'[a-f0-9]{64}\.jpg', p.name):
                info = p.stat()
                files.append((info.st_mtime, info.st_size, p))
    total = sum(size for _, size, _ in files)
    for _, size, p in sorted(files):
        if total <= limit:
            break
        if p != keep:
            p.unlink(missing_ok=True)
            total -= size


class CoverCache:
    def __init__(self, roms_root):
        self.root = Path(roms_root).resolve()
        self.directory = self.root / '.x55-cover-cache'
        self.condition = threading.Condition()
        self.pending = None
        self.selected = None
        self.result = (None, None, 'Selecciona un juego')
        self.stopped = False
        self.local_indexes = OrderedDict()
        self.thread = threading.Thread(target=self._run, daemon=True, name='game-cover')
        self.thread.start()

    def select(self, game, folder='nes'):
        folder = valid_folder(folder)
        key = cache_key(game, folder)
        with self.condition:
            if self.selected != key:
                self.selected = key
                self.pending = (key, {**game, '_cover_folder': folder}, time.monotonic() + .3)
                self.result = (key, None, 'Cargando imagen...')
                self.condition.notify_all()
            return self.result[1:]

    def pause(self):
        with self.condition:
            self.pending = None
            self.selected = None

    def close(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

    def _local_image(self, name, folder):
        if folder not in self.local_indexes:
            index = {}
            for alias in ALIASES.get(folder, (folder,)):
                images = self.root / alias / 'images'
                if not images.is_dir() or not images.resolve().is_relative_to(self.root):
                    continue
                for p in sorted(images.iterdir()):
                    if p.is_symlink() or p.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                        continue
                    stem = re.sub(r'-(?:thumb|image)$', '', p.stem)
                    if stem == p.stem:
                        continue
                    key = title_key(stem)
                    # Preferir imagen principal; las revisiones regionales comparten miniatura.
                    if key not in index or p.stem.endswith('-image'):
                        index[key] = p
            self.local_indexes[folder] = index
            if len(self.local_indexes) > 3:
                self.local_indexes.popitem(last=False)
        self.local_indexes.move_to_end(folder)
        return self.local_indexes[folder].get(title_key(name))

    def _convert(self, source, output):
        tool = shutil.which('magick') or shutil.which('convert')
        if not tool:
            raise RuntimeError('No hay conversor de miniaturas')
        with Path(source).open('rb') as f:
            prefix = f.read(8)
        if not prefix.startswith((b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n')):
            raise ValueError('Imagen no compatible')
        subprocess.run([tool, '-limit', 'memory', '32MiB', '-limit', 'map', '64MiB',
                        '-limit', 'width', '4096', '-limit', 'height', '4096',
                        str(source), '-auto-orient', '-thumbnail', '320x340>', '-strip',
                        '-quality', '80', str(output)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8, check=True)

    def _load(self, key, game):
        folder = valid_folder(game.get('_cover_folder', 'nes'))
        directory = self.directory / folder
        if self.directory.is_symlink() or directory.is_symlink():
            raise ValueError('Ruta de cache no valida')
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.resolve().is_relative_to(self.root):
            raise ValueError('Ruta de cache no valida')
        directory.mkdir(exist_ok=True)
        target = directory / (key + '.jpg')
        if target.is_file() and not target.is_symlink() and target.stat().st_size:
            if time.time() - target.stat().st_mtime > 60:
                os.utime(target, None)
            return target
        source = self._local_image(game['name'], folder)
        with tempfile.TemporaryDirectory(prefix='.cover-', dir=directory) as temporary:
            temporary = Path(temporary)
            if source is None:
                page = game.get('source_page', '')
                from import_site import site_url
                prefixes = tuple('/' + slug + '-rom-' for slug, entry in SYSTEMS.items() if entry['folder'] == folder)
                if not page or site_url(page) != page or not prefixes or not urlsplit(page).path.startswith(prefixes):
                    return None
                with urlopen(Request(page, headers={'User-Agent': 'X55-ROM-Downloader/0.5'}), timeout=6) as response:
                    if not site_url(response.url):
                        raise ValueError('Respuesta de ficha inesperada')
                    body = response.read(2*1024*1024 + 1)
                if len(body) > 2*1024*1024:
                    raise ValueError('Ficha demasiado grande')
                parser = CoverPage(page, game['name'])
                parser.feed(body.decode('utf-8', errors='replace'))
                if not parser.image:
                    return None
                with self.condition:
                    if self.selected != key or self.stopped:
                        return None
                request = Request(parser.image, headers={'User-Agent': 'X55-ROM-Downloader/0.5', 'Referer': page})
                with urlopen(request, timeout=6) as response:
                    if not image_url(response.url, page) or not response.headers.get_content_type().startswith('image/'):
                        raise ValueError('Respuesta de imagen inesperada')
                    data = response.read(MAX_IMAGE_BYTES + 1)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError('Imagen demasiado grande')
                source = temporary / 'source.image'
                source.write_bytes(data)
            output = temporary / 'thumb.jpg'
            self._convert(source, output)
            if not output.is_file() or not 0 < output.stat().st_size <= MAX_IMAGE_BYTES:
                raise ValueError('Miniatura no valida')
            os.replace(output, target)
        prune_cache(self.directory, keep=target)
        return target

    def _run(self):
        while True:
            with self.condition:
                while not self.stopped and self.pending is None:
                    self.condition.wait()
                if self.stopped:
                    return
                key, game, ready = self.pending
                delay = ready-time.monotonic()
                if delay > 0:
                    self.condition.wait(delay)
                    continue
                self.pending = None
            try:
                path = self._load(key, game)
                result = (key, path, '' if path else 'Sin imagen disponible')
            except Exception:
                result = (key, None, 'Imagen no disponible')
            with self.condition:
                if self.selected == key:
                    self.result = result
