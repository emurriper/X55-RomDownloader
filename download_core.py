"""Catálogo y descargas independientes de la interfaz gráfica."""

import json
import os
from pathlib import Path
import tempfile
import threading
import shutil
import stat
import zipfile
import zlib
import unicodedata
import errno
import http.client
import socket
import ssl
import urllib.parse
import urllib.request
import urllib.error
from local_library import LocalLibrary
from x55_systems import KEEP_ARCHIVES, CARTRIDGE_EXTENSIONS


def component(value):
    if (not isinstance(value, str) or not value.strip() or value in (".", "..")
            or any(c in value for c in '/\\:\x00') or value.endswith((".", " "))):
        raise ValueError(f"Nombre de archivo o carpeta inválido: {value!r}")
    return value


def validate_catalog(catalog):
    if not isinstance(catalog, dict):
        raise ValueError("El catálogo debe ser un objeto de sistemas.")
    for system, entry in catalog.items():
        if not isinstance(system, str) or not system.strip() or not isinstance(entry, dict):
            raise ValueError("Sistema inválido en el catálogo.")
        component(entry.get("folder"))
        if not isinstance(entry.get("games"), list):
            raise ValueError(f"Falta la lista games en {system}.")
        for game in entry["games"]:
            if not isinstance(game, dict) or not isinstance(game.get("name"), str) or not game["name"].strip():
                raise ValueError(f"Juego sin nombre en {system}.")
            component(game.get("filename"))
            if "installed_filename" in game:
                component(game["installed_filename"])
            if game.get('source_provider') == 'romsgames':
                source = urllib.parse.urlsplit(game.get('source_page') or '')
                if source.scheme != 'https' or source.hostname not in ('www.romsgames.net', 'romsgames.net') or '-rom-' not in source.path:
                    raise ValueError(f"Ficha de origen inválida en {system}.")
                continue
            url = game.get("url")
            if not isinstance(url, str):
                raise ValueError(f"URL inválida en {system}.")
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError(f"La URL de {game['name']} debe ser HTTP o HTTPS.")
    return catalog


def read_catalog(path):
    with open(path, encoding="utf-8") as stream:
        return validate_catalog(json.load(stream))


def destination_for(root, folder, filename):
    base = Path(root).resolve()
    destination = base / component(folder) / component(filename)
    if not destination.resolve().is_relative_to(base):
        raise ValueError("La ruta de descarga sale del directorio de ROMs.")
    return destination


def _library_records(directory, filename='.x55-installed.json'):
    try:
        with (directory / filename).open(encoding='utf-8') as stream:
            records = json.load(stream)
        return records if isinstance(records, dict) else {}
    except (OSError, ValueError):
        return {}


def effective_game(root, folder, game):
    if game.get('source_provider') != 'romsgames':
        return game
    directory = destination_for(root, folder, game['filename']).parent
    filename = _library_records(directory, '.x55-sources.json').get(game['source_page'])
    if isinstance(filename, str):
        component(filename)
        return {**game, 'filename': filename}
    return game


def remember_source(root, folder, game):
    directory = destination_for(root, folder, game['filename']).parent
    directory.mkdir(parents=True, exist_ok=True)
    records = _library_records(directory, '.x55-sources.json')
    records[game['source_page']] = component(game['filename'])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='.x55-source-', suffix='.part', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(records, stream, ensure_ascii=False)
        os.replace(temporary, directory / '.x55-sources.json')
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _remember_installation(archive, output):
    records = _library_records(archive.parent)
    records[archive.name] = {'rom': output.name, 'size': output.stat().st_size}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=archive.parent,
                                         prefix='.x55-library-', suffix='.part', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(records, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, archive.parent / '.x55-installed.json')
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def local_game_status(root, folder, game, library=None):
    """Consulta archivos locales; no lee el contenido de ROMs ni conecta a la red."""
    game = effective_game(root, folder, game)
    destination = destination_for(root, folder, game['filename'])

    def present(path, expected_size=None):
        try:
            return (not path.is_symlink() and path.is_file() and path.stat().st_size > 0
                    and (expected_size is None or path.stat().st_size == expected_size))
        except OSError:
            return False

    is_zip = destination.suffix.lower() in ('.zip', '.7z')
    zip_path = destination if is_zip and destination.is_file() else None

    def result(status, path):
        return {'status': status, 'path': path, 'zip_path': zip_path}

    def detected():
        found = (library or LocalLibrary(root)).find(folder, game)
        return {**result('installed', found['path']), **found} if found else None

    if folder in KEEP_ARCHIVES and zip_path is not None and present(zip_path):
        return {'status': 'installed', 'path': zip_path, 'zip_path': None}

    if game.get('installed_filename'):
        target = destination_for(root, folder, game['installed_filename'])
        if present(target):
            return result('installed', target)
    if not is_zip:
        if present(destination):
            return result('installed', destination)
        return detected() or result('available', destination)
    record = _library_records(destination.parent).get(destination.name)
    if isinstance(record, dict):
        try:
            target = destination_for(root, folder, record.get('rom'))
            if present(target, record.get('size')):
                return result('installed', target)
        except (OSError, ValueError):
            pass
    found = detected()
    if found:
        return found
    if zip_path is not None and destination.suffix.lower() == '.zip':
        try:
            with zipfile.ZipFile(zip_path) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if len(files) == 1:
                    item = files[0]
                    parts = item.orig_filename.split('/')
                    for part in parts:
                        component(part)
                    target = destination_for(root, folder, parts[-1])
                    if target.suffix.lower() in ExtractZip.EXTENSIONS and present(target, item.file_size):
                        return result('installed', target)
        except (OSError, ValueError, zipfile.BadZipFile):
            pass
        return result('zip', destination)

    # Compatibilidad con ROMs extraídas antes de registrar instalaciones.
    # Tolera puntuación distinta, pero exige un único nombre equivalente.
    def normalized(name):
        return ''.join(c for c in unicodedata.normalize('NFKD', name.casefold()) if c.isalnum())

    expected = normalized(destination.stem)
    try:
        matches = [path for path in destination.parent.iterdir()
                   if path.suffix.lower() in ExtractZip.EXTENSIONS
                   and normalized(path.stem) == expected and present(path)]
        if len(matches) == 1:
            return result('installed', matches[0])
    except OSError:
        pass
    return result('archive' if zip_path is not None else 'available', destination)


class BackgroundTask:
    def __init__(self, status):
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.state = {"status": status, "downloaded": 0, "total": None, "error": ""}
        self.thread = threading.Thread(target=self._run, daemon=True)

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self):
        self.thread.start()
        return self


class InvalidDownload(ValueError):
    pass


class ResolveGame(BackgroundTask):
    def __init__(self, game, root, folder):
        self.game = dict(game)
        self.root, self.folder = root, folder
        super().__init__('resolving')

    def _run(self):
        try:
            from romsgames_source import resolve_game
            resolved = resolve_game(self.game['source_page'], self.game.get('media_id'))
            if self.cancel.is_set():
                self.update(status='cancelled')
                return
            self.game.update(resolved)
            remember_source(self.root, self.folder, self.game)
            self.update(status='done')
        except Exception as error:
            self.update(status='cancelled' if self.cancel.is_set() else 'error', **download_error(error))
            if isinstance(error, urllib.error.HTTPError):
                error.close()


def download_error(error):
    """Mensajes para la consola, sin exponer URLs firmadas ni respuestas HTML."""
    kind, title = 'download', 'No se pudo descargar'
    if isinstance(error, urllib.error.HTTPError):
        code = error.code
        if code in (401, 403):
            kind, title = 'access', 'Enlace no disponible'
            message = (f'Acceso rechazado (HTTP {code}). El enlace puede haber caducado '
                       'o requerir una sesión. Renueva la URL de este juego en catalog.json.')
        elif code in (404, 410):
            kind, title = 'missing', 'Archivo no disponible'
            message = f'El servidor ya no ofrece ese archivo (HTTP {code}). Actualiza la URL del juego en catalog.json.'
        elif code == 429:
            kind, title = 'rate_limit', 'Demasiadas solicitudes'
            message = 'El servidor limita las descargas (HTTP 429). Espera un rato antes de volver a intentarlo.'
        elif 500 <= code <= 599:
            kind, title = 'server', 'Servidor no disponible'
            message = f'El servidor falló (HTTP {code}). Vuelve a intentarlo más tarde.'
        else:
            message = f'El servidor rechazó la descarga (HTTP {code}). Comprueba el enlace del juego.'
    elif isinstance(error, InvalidDownload):
        kind, title, message = 'invalid_file', 'Respuesta no válida', str(error)
    elif isinstance(error, http.client.IncompleteRead):
        kind, title, message = 'incomplete', 'Descarga incompleta', 'La conexión terminó antes de recibir todo el archivo. Vuelve a intentarlo.'
    else:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(reason, ssl.SSLError):
            kind, title = 'tls', 'No se pudo verificar la conexión'
            message = 'Falló la conexión segura. Comprueba la fecha y hora de la consola y el certificado del servidor.'
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            kind, title, message = 'timeout', 'Conexión agotada', 'El servidor tardó demasiado en responder. Comprueba el Wi-Fi y vuelve a intentarlo.'
        elif isinstance(reason, OSError) and reason.errno == errno.ENOSPC:
            kind, title, message = 'space', 'Sin espacio disponible', 'Libera espacio en la tarjeta antes de volver a descargar.'
        elif isinstance(error, urllib.error.URLError) or isinstance(reason, ConnectionError):
            kind, title, message = 'network', 'Sin conexión con el servidor', 'Comprueba el Wi-Fi y la dirección del enlace. El servidor podría no estar disponible.'
        elif isinstance(error, OSError):
            kind, title, message = 'storage', 'No se pudo guardar el archivo', 'Comprueba el espacio disponible y que la carpeta de ROMs sea accesible.'
        else:
            message = 'La descarga no pudo completarse. Comprueba el enlace y vuelve a intentarlo.'
    return {'error_kind': kind, 'error_title': title,
            'error': message + ' No se reemplazó ningún archivo existente.'}


class Download(BackgroundTask):
    """Un trabajador escribe el temporal; la interfaz consulta una instantánea."""

    def __init__(self, url, destination, headers=None):
        self.url = url
        self.destination = Path(destination)
        self.headers = headers or {}
        super().__init__("connecting")

    def _run(self):
        temporary = None
        try:
            self.destination.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(self.url, headers={"User-Agent": "X55-ROM-Downloader/0.3", **self.headers})
            with urllib.request.urlopen(request, timeout=10) as response:
                content_type = response.headers.get_content_type()
                if content_type in ('text/html', 'application/xhtml+xml'):
                    raise InvalidDownload('El servidor devolvió una página web en vez del archivo. Obtén un enlace directo nuevo y actualiza catalog.json.')
                length = response.headers.get("Content-Length")
                total = int(length) if length and length.isdigit() else None
                self.update(status="downloading", total=total)
                downloaded = 0
                with tempfile.NamedTemporaryFile(dir=self.destination.parent,
                                                 prefix=".x55-", suffix=".part", delete=False) as output:
                    temporary = output.name
                    while not self.cancel.is_set():
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        if downloaded == 0:
                            prefix = chunk.lstrip(b'\xef\xbb\xbf \t\r\n').lower()
                            if prefix.startswith((b'<!doctype html', b'<html', b'<head', b'<body')):
                                raise InvalidDownload('El enlace devuelve una página web, no una ROM. Actualiza la URL directa en catalog.json.')
                            if self.destination.suffix.lower() == '.zip' and not chunk.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
                                raise InvalidDownload('El servidor no devolvió un archivo ZIP. El enlace puede haber caducado; actualiza catalog.json.')
                            if self.destination.suffix.lower() == '.7z' and not chunk.startswith(b'7z\xbc\xaf\x27\x1c'):
                                raise InvalidDownload('El servidor no devolvió un archivo 7z válido. Vuelve a seleccionar el juego para renovar el enlace.')
                        output.write(chunk)
                        downloaded += len(chunk)
                        self.update(downloaded=downloaded)
                if self.cancel.is_set():
                    self.update(status="cancelled")
                    return
                if total is not None and downloaded != total:
                    raise InvalidDownload("La descarga terminó con un tamaño incompleto. Vuelve a intentarlo.")
                if downloaded == 0:
                    raise InvalidDownload('El servidor devolvió un archivo vacío. Comprueba el enlace de descarga.')
            os.replace(temporary, self.destination)
            temporary = None
            self.update(status="done")
        except Exception as error:
            self.update(status="cancelled" if self.cancel.is_set() else "error", **download_error(error))
            if isinstance(error, urllib.error.HTTPError):
                error.close()
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


class ExtractZip(BackgroundTask):
    """Extrae una sola ROM, verifica CRC y nunca reemplaza un archivo existente."""

    EXTENSIONS = {".iso", ".cso", ".chd", ".gb", ".gbc", ".gba", ".nes", ".sfc",
                  ".smc", ".n64", ".z64", ".v64", ".nds", ".md", ".gen", ".sms", ".gg", ".pce"}
    EXTENSIONS |= CARTRIDGE_EXTENSIONS | {'.cdi'}

    def __init__(self, archive):
        self.archive = Path(archive)
        self.output = None
        self.verified_archive = None
        self.verified_output = None
        super().__init__("extracting")

    @staticmethod
    def identity(path):
        info = path.stat()
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def delete_archive(self):
        if self.snapshot()["status"] != "done" or self.verified_archive is None:
            raise ValueError("El comprimido solo se puede borrar después de verificar la ROM.")
        if not self.output or not self.output.is_file():
            raise ValueError("No se encuentra la ROM extraída; se conserva el ZIP.")
        if self.identity(self.output) != self.verified_output:
            raise ValueError("La ROM extraída ha cambiado; se conserva el ZIP.")
        if self.identity(self.archive) != self.verified_archive:
            raise ValueError("El ZIP ha cambiado; se conserva.")
        self.archive.unlink()
        self.verified_archive = None

    def _verify_existing(self, target, item, original_archive):
        if target.is_symlink() or not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("El destino no es una ROM regular. Se conservan los archivos.")
        original_output = self.identity(target)
        if original_output[2] != item.file_size:
            raise ValueError("La ROM existente tiene un tamaño diferente. Se conservan la ROM y el ZIP.")
        self.update(status="verifying", total=item.file_size, existing=True)
        copied, crc = 0, 0
        with target.open("rb") as source:
            while not self.cancel.is_set():
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                crc = zlib.crc32(chunk, crc)
                self.update(downloaded=copied)
        if self.cancel.is_set():
            self.update(status="cancelled")
            return
        if copied != item.file_size or crc != item.CRC:
            raise ValueError("El CRC de la ROM existente no coincide. Se conservan la ROM y el ZIP.")
        if self.identity(target) != original_output or self.identity(self.archive) != original_archive:
            raise ValueError("Los archivos cambiaron durante la verificación. Se conserva el ZIP.")
        self.output = target
        self.verified_output = original_output
        self.verified_archive = original_archive
        _remember_installation(self.archive, target)
        self.update(status="done")

    def _run(self):
        temporary = None
        reserved = None
        try:
            original = self.identity(self.archive)
            root = self.archive.parent.resolve()
            with zipfile.ZipFile(self.archive) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if len(files) != 1:
                    raise ValueError("Extracción automática: el ZIP debe contener una sola ROM. Se conserva el ZIP.")
                item = files[0]
                parts = item.orig_filename.split("/")
                for part in parts:
                    component(part)
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError("No se admiten enlaces simbólicos ni ZIP cifrados.")
                name = parts[-1]
                if Path(name).suffix.lower() not in self.EXTENSIONS:
                    raise ValueError("Formato no compatible con extracción automática. Se conserva el ZIP.")
                target = root / name
                if os.path.lexists(target):
                    self._verify_existing(target, item, original)
                    return
                if shutil.disk_usage(root).free < item.file_size + 64 * 1024 * 1024:
                    raise OSError("Espacio insuficiente para extraer la ROM. Se conserva el ZIP.")
                self.update(total=item.file_size)
                copied = 0
                with archive.open(item) as source, tempfile.NamedTemporaryFile(
                        dir=root, prefix=".x55-extract-", suffix=".part", delete=False) as output:
                    temporary = Path(output.name)
                    while not self.cancel.is_set():
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        copied += len(chunk)
                        self.update(downloaded=copied)
                    if self.cancel.is_set():
                        self.update(status="cancelled")
                        return
                    output.flush()
                    os.fsync(output.fileno())
                if copied != item.file_size:
                    raise OSError("El tamaño extraído no coincide con el ZIP.")
            if self.identity(self.archive) != original:
                raise ValueError("El ZIP cambió durante la extracción; se conserva.")
            if self.cancel.is_set():
                self.update(status="cancelled")
                return
            # Reservar el nombre de forma exclusiva evita reemplazar una ROM existente.
            with target.open("xb"):
                reserved = target
            os.replace(temporary, target)
            reserved = temporary = None
            self.output = target
            self.verified_archive = original
            self.verified_output = self.identity(target)
            _remember_installation(self.archive, target)
            self.update(status="done")
        except Exception as error:
            self.update(status="cancelled" if self.cancel.is_set() else "error", error=str(error))
        finally:
            for path in (temporary, reserved):
                if path is not None:
                    path.unlink(missing_ok=True)
