"""Instalador local y por SSH para X55 con ROCKNIX. Sin paquetes externos."""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

RUNTIME_FILES = ('rom_downloader.py', 'download_core.py', 'graphical_app.py',
                 'sdl_backend.py', 'launch_rocknix.py', 'archive_support.py',
                 'romsgames_source.py', 'import_site.py', 'emulationstation_refresh.py',
                 'local_library.py', 'x55_systems.py', 'catalog.json')
MENU_FILES = ('es_systems_x55_downloader.cfg', 'gamelist.xml', 'logo.svg', 'canvas-metadata.xml')


def payload_from_directory(source, update_catalog=False):
    source = Path(source)
    def read(path):
        return path.read_text(encoding='utf-8-sig')
    return {'files': {name: read(source / name) for name in RUNTIME_FILES},
            'menu': {name: read(source / 'menu' / name) for name in MENU_FILES},
            'port': read(source / 'X55 ROM Downloader.sh'),
            'update_catalog': update_catalog}


def preflight():
    import ctypes
    import platform
    if sys.platform != 'linux' or platform.machine().lower() not in ('aarch64', 'arm64'):
        raise RuntimeError('Este instalador requiere ROCKNIX ARM64 en una X55.')
    for path in ('/storage/roms', '/usr/config/emulationstation/es_systems.cfg',
                 '/storage/.config/emulationstation'):
        if not Path(path).exists():
            raise RuntimeError('Falta una ruta de ROCKNIX: ' + path)
    for library in ('libSDL2-2.0.so.0', 'libSDL2_ttf-2.0.so.0'):
        ctypes.CDLL(library)
    if not shutil.which('bash'):
        raise RuntimeError('No se encuentra bash.')
    print('Entorno ROCKNIX ARM64 y SDL2/SDL_ttf comprobados.')
    if not shutil.which('7za'):
        print('Aviso: sin 7za, los archivos 7z requieren extraccion manual.')


def install(payload):
    import fcntl
    files = payload['files']
    expected = set(RUNTIME_FILES)
    if set(files) != expected:
        raise ValueError('La lista de archivos no coincide con la aplicación.')
    for name, text in files.items():
        if name.endswith('.py'):
            compile(text, name, 'exec')
    json.loads(files['catalog.json'])
    subprocess.run(['/bin/bash', '-n'], input=payload['port'], text=True, check=True)
    for name, text in payload['menu'].items():
        ET.fromstring(text)
    storage = Path('/storage').resolve()
    app = Path('/storage/.local/share/x55-rom-downloader')
    port = Path('/storage/roms/ports/X55 ROM Downloader.sh')
    menu = app / 'menu'
    entry = menu / 'X55 ROM Downloader.sh'
    config = Path('/storage/.config/emulationstation/es_systems_x55_downloader.cfg')
    for target in (app, port, menu, entry, config):
        if target.is_symlink() or not target.resolve().is_relative_to(storage):
            raise ValueError('Destino de instalación inesperado: ' + str(target))
    marker = app / 'installation.json'
    if app.exists() and any(app.iterdir()) and not marker.is_file():
        raise ValueError('La carpeta ya contiene archivos ajenos a esta instalación.')
    if port.exists() and '# X55-ROM-DOWNLOADER-PORT' not in port.read_text():
        raise ValueError('El script de Ports ya existe y no pertenece a esta aplicación.')
    if config.exists() and 'X55-ROM-DOWNLOADER-MENU' not in config.read_text():
        raise ValueError('La configuración de menú ya existe y no pertenece a la app.')
    app.mkdir(parents=True, exist_ok=True)
    menu.mkdir(parents=True, exist_ok=True)
    with (app / '.running.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Cierra X55 ROM Downloader antes de actualizar.')
        if (app / 'catalog.json').is_file() and not payload['update_catalog']:
            files['catalog.json'] = (app / 'catalog.json').read_text(encoding='utf-8')
        backup = app / 'backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        def write_file(target, text, mode=0o644):
            data = text.encode('utf-8')
            if target.is_file() and target.read_bytes() == data:
                return
            if target.exists():
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup / target.name)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.x55-install-', delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(mode)
                os.replace(temporary, target)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        for name, text in files.items():
            write_file(app / name, text)
        write_file(entry, payload['port'], 0o755)
        for name in ('logo.svg',):
            write_file(menu / name, payload['menu'][name])
        # Usar siempre el skin activo; retirar solo el antiguo tema añadido por esta app.
        own_theme = menu / 'theme.xml'
        if own_theme.is_file() and not own_theme.is_symlink():
            content = own_theme.read_text()
            if '/storage/.config/emulationstation/themes/system-theme/theme.xml' in content and '<path>./logo.svg</path>' in content:
                backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(own_theme, backup / 'menu-theme.xml')
                own_theme.unlink()
        # Conservar los metadatos de uso que EmulationStation guarde posteriormente.
        gamelist = menu / 'gamelist.xml'
        if not gamelist.exists():
            write_file(gamelist, payload['menu']['gamelist.xml'])
        # Canvas ya dibuja secciones desconocidas con su estilo y nombre originales.
        # Solo necesita metadatos del nuevo sistema; no se modifica ningún archivo nativo.
        canvas_metadata = Path('/storage/roms/themes/canvas-es/_inc/systems/metadata/x55downloader.xml')
        if canvas_metadata.parent.is_dir():
            if canvas_metadata.exists() and 'X55-ROM-DOWNLOADER-MENU' not in canvas_metadata.read_text():
                raise ValueError('Los metadatos de Canvas ya existen y no pertenecen a la app.')
            if canvas_metadata.is_symlink() or not canvas_metadata.resolve().is_relative_to(storage):
                raise ValueError('Ruta de metadatos de Canvas inesperada.')
            write_file(canvas_metadata, payload['menu']['canvas-metadata.xml'])
        write_file(config, payload['menu']['es_systems_x55_downloader.cfg'])
        manifest = {'version':'0.4', 'files':{name:hashlib.sha256(text.encode('utf-8')).hexdigest() for name,text in files.items()}}
        write_file(marker, json.dumps(manifest, indent=2) + '\n')
        for name, expected_hash in manifest['files'].items():
            if hashlib.sha256((app / name).read_bytes()).hexdigest() != expected_hash:
                raise RuntimeError('Falló la verificación de ' + name)
        # Retirar únicamente el antiguo acceso conocido, con copia recuperable.
        if port.exists():
            if port.is_symlink() or port.parent.resolve() != Path('/storage/roms/ports').resolve():
                raise ValueError('Ruta de Ports inesperada; no se retiró el acceso antiguo.')
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(port, backup / 'X55 ROM Downloader.port.sh')
            port.unlink()
    print('Instalación verificada:', app)
    print('Acceso principal: Descargas -> X55 ROM Downloader')
    print('Configuración adicional:', config)
    print('Catálogo:', 'actualizado desde el portátil' if payload['update_catalog'] else 'conservado si ya existía')
    import sys
    sys.path.insert(0, str(app))
    from emulationstation_refresh import mark_pending, refresh_pending
    mark_pending('/storage/roms')
    _, message = refresh_pending('/storage/roms')
    print(message)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--update-catalog', action='store_true', help='Reemplazar el catalogo instalado')
    parser.add_argument('--check', action='store_true', help='Solo comprobar el entorno, sin instalar')
    parser.add_argument('--payload-stdin', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    preflight()
    if args.check:
        return
    if args.payload_stdin:
        payload = json.loads(base64.b64decode(sys.stdin.read(), validate=True))
    else:
        payload = payload_from_directory(args.source, args.update_catalog)
    install(payload)


if __name__ == '__main__':
    main()
