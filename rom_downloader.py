import os
import argparse
import time

from download_core import Download, ResolveGame, read_catalog, destination_for

APP_NAME = "X55 ROM Downloader"
VERSION = "0.4"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(BASE_DIR, "catalog.json")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads") if os.name == "nt" else "/storage/roms"


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def load_catalog():
    return read_catalog(CATALOG_FILE)


def download_file(url, destination, headers=None):
    print("\nDescargando...")
    print(f"Destino: {destination}\n")
    job = Download(url, destination, headers=headers).start()
    try:
        while job.thread.is_alive():
            state = job.snapshot()
            total, downloaded = state["total"], state["downloaded"]
            prefix = f"{min(downloaded * 100 / total, 100):5.1f}% " if total else ""
            print(f"\rProgreso: {prefix}({downloaded / 1024:.1f} KB)", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        job.cancel.set()
        job.thread.join(timeout=12)
        raise
    state = job.snapshot()
    if state["status"] != "done":
        raise OSError(state["error"] or "Descarga cancelada")
    print("\n\nDescarga terminada.")


def choose_system(catalog):
    systems = list(catalog.keys())

    clear()

    print("=" * 42)
    print(f" {APP_NAME} v{VERSION}")
    print("=" * 42)
    print()

    for index, system in enumerate(systems, start=1):
        count = len(catalog[system]["games"])
        print(f"{index}. {system} ({count})")

    print("\n0. Salir")

    selection = input("\nSelecciona sistema: ")

    if selection == "0":
        return None

    try:
        number = int(selection)
        return systems[number - 1] if 1 <= number <= len(systems) else ""
    except (ValueError, IndexError):
        return ""


def choose_game(system, catalog):
    games = catalog[system]["games"]

    clear()
    print(f"=== {system} ===\n")

    if not games:
        print("No hay juegos disponibles.")
        input("\nPulsa ENTER para volver...")
        return None

    for index, game in enumerate(games, start=1):
        print(f"{index}. {game['name']}")

    print("\n0. Volver")

    selection = input("\nSelecciona juego: ")

    if selection == "0":
        return None

    try:
        number = int(selection)
        return games[number - 1] if 1 <= number <= len(games) else {}
    except (ValueError, IndexError):
        return {}


def cli_main():
    try:
        catalog = load_catalog()
    except Exception as error:
        print(f"ERROR cargando catalog.json: {error}")
        return

    while True:
        system = choose_system(catalog)

        if system is None:
            break

        if not system:
            continue

        game = choose_game(system, catalog)

        if not game:
            continue

        system_folder = catalog[system]["folder"]

        try:
            headers = {}
            if game.get('source_provider') == 'romsgames':
                print('Obteniendo enlace actualizado...')
                resolver = ResolveGame(game, DOWNLOAD_DIR, system_folder).start()
                while resolver.thread.is_alive():
                    resolver.thread.join(0.1)
                if resolver.snapshot()['status'] != 'done':
                    raise OSError(resolver.snapshot()['error'])
                game = resolver.game
                headers['Referer'] = game['source_page']
            destination = destination_for(DOWNLOAD_DIR, system_folder, game["filename"])
            download_file(game["url"], destination, headers=headers)
            input("\nPulsa ENTER para continuar...")

        except Exception as error:
            print(f"\nERROR: {error}")
            input("\nPulsa ENTER para continuar...")


def main():
    global CATALOG_FILE, DOWNLOAD_DIR
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{VERSION}")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--cli", action="store_true", help="Interfaz de terminal")
    modes.add_argument("--gui", action="store_true", help="Interfaz SDL2 para ROCKNIX")
    parser.add_argument("--catalog", default=CATALOG_FILE, help="Ruta del catálogo JSON")
    parser.add_argument("--roms-dir", default=DOWNLOAD_DIR, help="Directorio raíz de destino")
    parser.add_argument("--read-only", action="store_true", help="Vista previa gráfica sin descargas")
    parser.add_argument("--max-seconds", type=float, help="Cerrar la interfaz gráfica tras estos segundos (diagnóstico)")
    args = parser.parse_args()
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error("--max-seconds debe ser mayor que cero.")
    CATALOG_FILE, DOWNLOAD_DIR = args.catalog, args.roms_dir
    if args.cli or (os.name == "nt" and not args.gui):
        if args.read_only:
            parser.error("--read-only requiere la interfaz gráfica (--gui).")
        cli_main()
        return
    try:
        from graphical_app import Application
        Application(load_catalog(), DOWNLOAD_DIR, args.read_only).run(max_seconds=args.max_seconds)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
