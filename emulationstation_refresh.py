"""Actualiza las listas de la sesión local de EmulationStation al salir de la app."""

from pathlib import Path
import urllib.request
import urllib.error


MARKER = '.x55-refresh-pending'


def mark_pending(root):
    marker = Path(root) / MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)


def is_pending(root):
    return (Path(root) / MARKER).is_file()


def refresh_pending(root, opener=None):
    marker = Path(root) / MARKER
    if not marker.is_file():
        return False, 'No hay cambios pendientes en la lista de juegos.'
    try:
        # El servicio nativo usa loopback. No depende de la IP Wi-Fi ni de proxies.
        if opener is None:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:1234/reloadgames', timeout=3) as response:
            if response.status not in (200, 202):
                raise OSError(f'EmulationStation respondió HTTP {response.status}.')
        marker.unlink(missing_ok=True)
        return True, 'Actualización de la lista solicitada a EmulationStation.'
    except (OSError, ValueError) as error:
        if isinstance(error, urllib.error.HTTPError):
            error.close()
        # No se pierden las ROMs ni se reinicia la sesión si el servicio no responde.
        return False, f'La actualización queda pendiente: {error}'
