"""Entrada del menú Descargas: sesión Wayland, bloqueo y registro de errores."""

import contextlib
import os
from pathlib import Path
import sys
import traceback


def graphical_environment(environ=None, proc=Path('/proc')):
    """Prioriza el entorno heredado y consulta solo variables gráficas de ES."""
    current = dict(os.environ if environ is None else environ)
    candidates = [current]
    keys = {'XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY'}
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if not (entry / 'comm').read_text().strip().startswith('emulationstatio'):
                continue
            env = {}
            for raw in (entry / 'environ').read_bytes().split(b'\0'):
                name, separator, value = raw.partition(b'=')
                if separator and name.decode(errors='replace') in keys:
                    env[name.decode()] = value.decode()
            candidates.append(env)
        except (OSError, UnicodeError):
            continue
    for candidate in candidates:
        runtime = candidate.get('XDG_RUNTIME_DIR')
        display = candidate.get('WAYLAND_DISPLAY')
        if runtime and display and (Path(runtime) / display).is_socket():
            return {'XDG_RUNTIME_DIR': runtime, 'WAYLAND_DISPLAY': display}
    for runtime in ('/var/run/0-runtime-dir', '/run/user/0'):
        for socket in sorted(Path(runtime).glob('wayland-*')):
            if socket.is_socket():
                return {'XDG_RUNTIME_DIR': runtime, 'WAYLAND_DISPLAY': socket.name}
    raise RuntimeError('No se encuentra la sesión Wayland de ROCKNIX. Abre la app desde Descargas.')


def main():
    import fcntl  # Solo se necesita en ROCKNIX, no al usar el proyecto en Windows.

    app_dir = Path(__file__).resolve().parent
    with (app_dir / '.running.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('X55 ROM Downloader ya está abierto.')
            return 0
        log = app_dir / 'launcher.log'
        if log.exists():
            log.replace(app_dir / 'launcher.previous.log')
        with log.open('w', encoding='utf-8', buffering=1) as stream:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                try:
                    os.environ.update(graphical_environment())
                    os.environ['SDL_VIDEODRIVER'] = 'wayland'
                    os.environ['SDL_GAMECONTROLLERCONFIG_FILE'] = '/storage/.config/SDL-GameControllerDB/gamecontrollerdb.txt'
                    print('Inicio desde Descargas · X55 ROM Downloader V0.5', flush=True)
                    print('Wayland:', os.environ['WAYLAND_DISPLAY'], flush=True)
                    from rom_downloader import main as app_main
                    sys.argv = [str(app_dir / 'rom_downloader.py'), '--gui', '--roms-dir', '/storage/roms', *sys.argv[1:]]
                    app_main()
                    return 0
                except SystemExit as error:
                    return error.code if isinstance(error.code, int) else 1
                except Exception:
                    traceback.print_exc()
                    return 1


if __name__ == '__main__':
    raise SystemExit(main())
