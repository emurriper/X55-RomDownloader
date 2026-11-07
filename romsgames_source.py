"""Acceso a páginas públicas y resolución normal del botón Download de RomsGames."""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit, urlunsplit
import urllib.request

from download_core import component


def headers(page_url, json_response=False):
    result = {'User-Agent': 'X55-ROM-Downloader/0.3', 'Origin': 'https://www.romsgames.net',
              'Referer': page_url}
    if json_response:
        result.update({'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                       'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
    return result


def fetch_page(url):
    from import_site import site_url
    url = site_url(url)
    if not url:
        raise ValueError('Se esperaba una página de romsgames.net.')
    request = urllib.request.Request(url, headers=headers(url))
    with urllib.request.urlopen(request, timeout=20) as response:
        if not site_url(response.url) or response.headers.get_content_type() != 'text/html':
            raise ValueError('Respuesta inesperada al consultar la página.')
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError('Página demasiado grande; se detuvo la importación.')
        return body.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


def resolved_entry(response, page_url, media_id):
    from import_site import site_url
    if not site_url(page_url):
        raise ValueError('Página de origen inválida.')
    if not str(media_id).isdecimal() or int(media_id) <= 0:
        raise ValueError('Identificador de archivo inválido.')
    if not isinstance(response, dict):
        raise ValueError('La respuesta de descarga no es un objeto JSON.')
    raw_name = response.get('downloadName')
    if not isinstance(raw_name, str):
        raise ValueError('La respuesta no indica el nombre del archivo.')
    filename = component(unquote(raw_name))
    parsed = urlsplit(response.get('downloadUrl') or '')
    if parsed.scheme != 'https' or parsed.hostname != 'static.romsgames.net' or parsed.username or parsed.password:
        raise ValueError('El servidor no devolvió un enlace de archivo reconocido.')
    # Reproduce el envío GET del formulario: attach conserva el valor recibido.
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(mediaId=str(media_id), attach=raw_name)
    direct = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))
    return {'name': response.get('asset', {}).get('title') or Path(filename).stem,
            'url': direct, 'filename': filename, 'source_page': site_url(page_url),
            'source_provider': 'romsgames', 'media_id': str(media_id)}


def resolve_game(page_url, media_id=None):
    from import_site import Page, site_url
    page_url = site_url(page_url)
    if not page_url or '-rom-' not in urlsplit(page_url).path:
        raise ValueError('Se esperaba una ficha de juego de RomsGames.')
    if media_id is None:
        media_id = Page(fetch_page(page_url)).media_id
    if not str(media_id).isdecimal() or int(media_id) <= 0:
        raise ValueError('La página no contiene un identificador de descarga válido.')
    parsed = urlsplit(page_url)
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, 'download', ''))
    request = urllib.request.Request(endpoint, data=urlencode({'mediaId': media_id}).encode(),
                                     headers=headers(page_url, json_response=True))
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.headers.get_content_type() != 'application/json':
            raise ValueError('El sitio solicita una interacción adicional; no devolvió el enlace en JSON.')
        raw = response.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            raise ValueError('Respuesta de descarga demasiado grande.')
        data = json.loads(raw)
    return resolved_entry(data, page_url, media_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page', required=True)
    parser.add_argument('--media-id')
    parser.add_argument('--output', type=Path, default=Path('resolved_game.json'))
    args = parser.parse_args()
    entry = resolve_game(args.page, args.media_id)
    request = urllib.request.Request(entry['url'], method='HEAD', headers=headers(args.page))
    with urllib.request.urlopen(request, timeout=20) as response:
        print('HTTP:', response.status, '| Tipo:', response.headers.get_content_type(),
              '| Bytes:', response.headers.get('Content-Length'))
    args.output.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Entrada resuelta:', entry['filename'])
    print('Salida:', args.output, '(no se descargó el juego)')


if __name__ == '__main__':
    main()
