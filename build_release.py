"""Prepara un repositorio y ZIP distribuibles usando una lista explicita de archivos."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from build_catalog import build
from install_x55 import RUNTIME_FILES, MENU_FILES
from x55_systems import SELECTED

VERSION = '0.4'
EXTRA_FILES = ('install_x55.py', 'install.sh', 'Install-X55.ps1', 'Start-X55.ps1',
               'X55 ROM Downloader.sh', 'build_catalog.py', 'sync_x55_catalog.py',
               'build_release.py', '.gitignore', '.gitattributes',
               '.github/workflows/checks.yml', '.github/workflows/release.yml')


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('El destino ya existe. Usa otra carpeta de salida.')
    index = json.loads((source / 'site_index.json').read_text(encoding='utf-8'))
    catalog = build(index, {})  # No publicar nombres o registros de la coleccion personal.
    public_index = {**index, 'systems': {slug: index['systems'][slug] for slug in SELECTED},
                    'samples': []}
    files = {}
    names = [name for name in RUNTIME_FILES if name != 'catalog.json'] + list(EXTRA_FILES)
    names += ['menu/' + name for name in MENU_FILES]
    names += sorted(path.name for path in source.glob('test_*.py'))
    for name in names:
        text = (source / name).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
        if name in ('Install-X55.ps1', 'Start-X55.ps1'):
            text = re.sub(r"\[string\]\$X55Address = '[^']+'",
                          '[Parameter(Mandatory=$true)][string]$X55Address', text, count=1)
        files[name] = text.encode('utf-8')
    readme = source / 'README.github.md'
    files['README.md'] = (readme if readme.exists() else source / 'README.md').read_text(
        encoding='utf-8-sig').replace('\r\n', '\n').encode('utf-8')
    # Permite reconstruir el paquete desde el propio ZIP publicado.
    files['README.github.md'] = files['README.md']
    for name, value in (('catalog.json', catalog), ('site_index.json', public_index)):
        files[name] = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    for name, data in files.items():
        text = data.decode('utf-8')
        if re.search(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}', text):
            raise ValueError('Posible credencial en: ' + name)
        if re.search(r'\b192[.]168[.]\d+[.]\d+\b|[A-Z]:\\Users\\', text):
            raise ValueError('Dato local inesperado en: ' + name)
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    files['SHA256SUMS.txt'] = ''.join(f'{digest}  {name}\n' for name, digest in manifest.items()).encode()
    repo = output / 'github' / 'X55-RomDownloader'
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    archive = output / f'X55-RomDownloader-v{VERSION}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo('X55-RomDownloader/' + name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    print(f'Paquete: {archive} ({archive.stat().st_size:,} bytes)')
    print(f'Repositorio preparado: {repo}')
    print(f'Archivos: {len(files)}; consolas: {len(catalog)}; fichas: {sum(len(s["games"]) for s in catalog.values())}')
    return repo, archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, default=Path('dist/release-v' + VERSION))
    args = parser.parse_args()
    prepare(args.source, args.output)


if __name__ == '__main__':
    main()
