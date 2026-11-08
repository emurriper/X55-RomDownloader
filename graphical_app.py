"""Interfaz de X55 ROM Downloader para pantalla y mando de la consola."""

import time
import unicodedata

from download_core import Download, ExtractZip, ResolveGame, destination_for, local_game_status, effective_game
from sdl_backend import Screen
from emulationstation_refresh import is_pending, mark_pending, refresh_pending
from local_library import LocalLibrary


def folded(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def size_text(size):
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class Application:
    KEYBOARD = list("ABCDEFGHIJ" "KLMNOPQRST" "UVWXYZ0123" "456789") + ["Espacio", "Borrar", "Limpiar", "Listo"]

    def __init__(self, catalog, root, read_only=False):
        self.catalog = catalog
        self.root = root
        self.read_only = read_only
        self.screen = None
        self.system = None
        self.query = ""
        self.index = 0
        self.system_index = 0
        self.page = "list"
        self.keyboard_index = 0
        self.draft = ""
        self.game = None
        self.destination = None
        self.notice = ""
        self.job = None
        self.running = True
        self.cancel_confirm = False
        self.status_cache = {}
        self.filter_key = None
        self.filtered_items = []
        self.refresh_needed = is_pending(root)
        self.refresh_notice = ''
        self.last_library_job = None
        self.local_library = LocalLibrary(root)

    def library_updated(self):
        if self.read_only or self.last_library_job is self.job:
            return
        self.last_library_job = self.job
        self.local_library.invalidate()
        try:
            mark_pending(self.root)
            self.refresh_needed = True
            self.refresh_notice = 'La lista de juegos se actualizará al salir.'
        except OSError:
            self.refresh_notice = 'ROM guardada; actualiza la lista desde EmulationStation.'
            print(self.refresh_notice, flush=True)

    def game_status(self, game, refresh=False):
        key = (self.system, game['filename'])
        now = time.monotonic()
        cached = self.status_cache.get(key)
        if refresh or cached is None or now - cached[0] >= 2:
            try:
                state = local_game_status(self.root, self.catalog[self.system]['folder'], game, library=self.local_library)
            except (OSError, ValueError) as error:
                state = {'status': 'error', 'path': None, 'zip_path': None, 'error': str(error)}
            self.status_cache[key] = now, state
        return self.status_cache[key][1]

    def items(self):
        if self.system is None:
            return list(self.catalog)
        key = (self.system, self.query)
        if key != self.filter_key:
            query = folded(self.query)
            self.filtered_items = [game for game in self.catalog[self.system]['games']
                                   if not query or query in folded(game['name'])]
            self.filter_key = key
        return self.filtered_items

    def prepare_download(self):
        if self.game.get('source_provider') == 'romsgames':
            self.job = ResolveGame(self.game, self.root, self.catalog[self.system]['folder']).start()
            self.page = 'resolve'
            self.cancel_confirm = False
        else:
            self.page = 'confirm'

    def back(self):
        if self.page in ("confirm", "notice", "local"):
            self.page = "list"
        elif self.page == "keyboard":
            self.page = "list"
        elif self.system is not None:
            self.system = None
            self.query = ""
            self.index = self.system_index
        else:
            self.page = "exit"

    def act(self, action):
        if action == "quit":
            self.running = False
            return
        if self.page == "zip_choice":
            if action == "select":
                try:
                    self.job.delete_archive()
                    self.status_cache.clear()
                    self.notice = "Comprimido eliminado. La ROM extraída se conserva."
                except (OSError, ValueError) as error:
                    self.notice = str(error)
                self.page = "notice"
            elif action in ("back", "start"):
                self.page = "list"
            return
        if self.page in ("download", "extract", "resolve"):
            state = self.job.snapshot()["status"]
            if state == 'done':
                previous_page = self.page
                self.advance()
                if self.page != previous_page:
                    return
            if state in ("done", "cancelled", "error"):
                if action in ("select", "back", "start"):
                    self.status_cache.clear()
                    self.page = "list"
            elif action == "back":
                self.cancel_confirm = not self.cancel_confirm
            elif action == "select" and self.cancel_confirm:
                self.job.cancel.set()
                self.cancel_confirm = False
            return
        if self.page == "exit":
            if action in ("select", "start"):
                self.running = False
            elif action == "back":
                self.page = "list"
            return
        if action == "start":
            self.page = "exit"
            return
        if action == "back":
            self.back()
            return
        if self.page == "notice":
            if action == "select":
                self.page = "list"
            return
        if self.page == "local":
            state = self.game_status(self.game, refresh=True)
            if action == 'select' and state['zip_path'] is not None:
                if self.read_only:
                    self.notice = 'Vista previa: la extracción y el borrado están desactivados.'
                    self.page = 'notice'
                else:
                    self.begin_extraction()
            elif action == 'search':
                if self.read_only:
                    self.notice = 'Vista previa: las descargas están desactivadas.'
                    self.page = 'notice'
                else:
                    self.prepare_download()
            return
        if self.page == "confirm":
            if action == "search" and self.destination.suffix.lower() in ('.zip', '.7z') and self.destination.is_file():
                self.begin_extraction()
                return
            if action == "select":
                # Revalidar justo antes de descargar, por si cambió la ruta.
                try:
                    self.destination = destination_for(self.root, self.catalog[self.system]["folder"], self.game["filename"])
                    headers = {}
                    if self.game.get('source_provider') == 'romsgames':
                        headers['Referer'] = self.game['source_page']
                    self.job = Download(self.game["url"], self.destination, headers=headers).start()
                    self.cancel_confirm = False
                    self.page = "download"
                except Exception as error:
                    self.notice = str(error)
                    self.page = "notice"
            return
        if self.page == "keyboard":
            if action == "left":
                self.keyboard_index = (self.keyboard_index // 10) * 10 + (self.keyboard_index % 10 - 1) % 10
            elif action == "right":
                self.keyboard_index = (self.keyboard_index // 10) * 10 + (self.keyboard_index % 10 + 1) % 10
            elif action in ("up", "down"):
                self.keyboard_index = (self.keyboard_index + (-10 if action == "up" else 10)) % 40
            elif action == "erase":
                self.draft = self.draft[:-1]
            elif action == "search":
                self.apply_query()
            elif action == "select":
                key = self.KEYBOARD[self.keyboard_index]
                if key == "Listo":
                    self.apply_query()
                elif key == "Borrar":
                    self.draft = self.draft[:-1]
                elif key == "Limpiar":
                    self.draft = ""
                elif len(self.draft) < 50:
                    self.draft += " " if key == "Espacio" else key
            return
        items = self.items()
        if action in ("up", "down") and items:
            self.index = (self.index + (-1 if action == "up" else 1)) % len(items)
        elif action in ("left", "right") and items:
            self.index = max(0, min(len(items) - 1, self.index + (-8 if action == "left" else 8)))
        elif action == "search" and self.system is not None:
            self.draft = self.query
            self.keyboard_index = 0
            self.page = "keyboard"
        elif action == "select" and items:
            if self.system is None:
                self.system_index = self.index
                self.system = items[self.index]
                self.local_library.invalidate(self.catalog[self.system]['folder'])
                self.status_cache.clear()
                self.index = 0
                self.query = ""
            else:
                self.game = effective_game(self.root, self.catalog[self.system]['folder'], items[self.index])
                state = self.game_status(self.game, refresh=True)
                if state['status'] == 'error':
                    self.notice = state['error']
                    self.page = 'notice'
                    return
                if state['status'] in ('installed', 'zip', 'archive'):
                    self.destination = destination_for(self.root, self.catalog[self.system]['folder'], self.game['filename'])
                    self.page = 'local'
                    return
                if self.read_only:
                    self.notice = "Vista previa: las descargas están desactivadas."
                    self.page = "notice"
                    return
                try:
                    self.destination = destination_for(self.root, self.catalog[self.system]["folder"], self.game["filename"])
                    self.prepare_download()
                except Exception as error:
                    self.notice = str(error)
                    self.page = "notice"

    def apply_query(self):
        self.query = self.draft.strip()
        self.index = 0
        self.page = "list"

    def begin_extraction(self):
        if self.catalog.get(self.system, {}).get('archive_mode') == 'keep':
            return
        if self.destination.suffix.lower() == '.7z':
            from archive_support import Extract7z
            self.job = Extract7z(self.destination).start()
        else:
            self.job = ExtractZip(self.destination).start()
        self.cancel_confirm = False
        self.page = "extract"

    def advance(self):
        if self.page == 'resolve' and self.job.snapshot()['status'] == 'done':
            self.game = self.job.game
            self.destination = destination_for(self.root, self.catalog[self.system]['folder'], self.game['filename'])
            self.status_cache.clear()
            self.page = 'confirm'
        elif self.page == "download" and self.job.snapshot()["status"] == "done":
            if self.catalog.get(self.system, {}).get('archive_mode') == 'keep':
                self.library_updated()
            elif self.destination.suffix.lower() in ('.zip', '.7z'):
                self.begin_extraction()
            elif self.destination.suffix.lower() in ExtractZip.EXTENSIONS | {'.bin', '.cue', '.m3u', '.pbp', '.img'}:
                self.library_updated()
        elif self.page == "extract" and self.job.snapshot()["status"] == "done":
            self.library_updated()
            self.status_cache.clear()
            self.page = "zip_choice"

    def draw(self):
        s = self.screen
        s.clear()
        s.fill(0, 0, 1280, 112, (23, 33, 51))
        s.fill(40, 28, 6, 56, (64, 214, 170))
        s.text("X55 ROM Downloader", 64, 24, 36)
        s.text("V0.4" + ("  ·  Vista previa" if self.read_only else ""), 65, 72, 21, (126, 211, 188))
        s.fill(0, 650, 1280, 70, (23, 33, 51))
        if self.page == "list":
            self.draw_list()
        elif self.page == "keyboard":
            self.draw_keyboard()
        elif self.page in ("download", "extract", "resolve"):
            self.draw_download()
        elif self.page == "zip_choice":
            s.text("ROM verificada", 48, 145, 34)
            s.text(self.job.output.name, 48, 225, 28)
            message = ("La ROM instalada coincide con el tamaño y CRC del comprimido."
                       if self.job.snapshot().get("existing") else "La extracción y comprobación CRC terminaron correctamente.")
            s.text(message, 48, 310, 27)
            s.text("¿Quieres borrar el comprimido para liberar espacio?", 48, 385, 30)
            s.text("B conserva el archivo y vuelve a los juegos.", 48, 450, 25, (147, 166, 192))
            if self.refresh_notice:
                s.text(self.refresh_notice, 48, 520, 24, (126, 211, 188))
            s.text("A Borrar comprimido     B Conservar", 48, 673, 25)
        elif self.page == 'local':
            state = self.game_status(self.game)
            installed = state['status'] == 'installed'
            s.text('Juego instalado' if installed else 'Comprimido descargado', 48, 145, 34)
            s.text(self.game['name'], 48, 225, 30)
            s.text(str(state['path']), 48, 285, 23)
            if installed:
                s.text('El archivo de la ROM ya está en la consola.', 48, 365, 28, (126, 211, 188))
                s.text('Abre el juego desde su sistema en EmulationStation.', 48, 410, 25)
                if state.get('matched_by'):
                    s.text('Detectado por nombre; la región o versión puede ser diferente.', 48, 540, 23, (147, 166, 192))
            else:
                s.text('Puedes extraerlo sin volver a descargar.', 48, 365, 28)
            if state['zip_path'] is not None:
                s.text('El comprimido también está guardado.' if installed else 'Se verificará la ROM antes de ofrecer borrar el archivo.', 48, 470, 25)
                footer = 'A Verificar' if installed else 'A Extraer'
                footer += '   X Descargar de nuevo   B Volver'
            else:
                footer = 'X Descargar de nuevo   B Volver'
            s.text(footer, 48, 673, 25)
        elif self.page == "confirm":
            s.text("Confirmar descarga", 48, 145, 34)
            s.text(self.game["name"], 48, 225, 32)
            s.text(str(self.destination), 48, 285, 24)
            if self.destination.exists():
                s.text("El archivo ya existe y será reemplazado al terminar.", 48, 365, 28, (255, 199, 111))
            else:
                s.text("El juego se guardará en la carpeta de su sistema.", 48, 365)
            if self.catalog[self.system].get('archive_mode') != 'keep' and self.destination.suffix.lower() in ('.zip', '.7z') and self.destination.is_file():
                s.text("A Descargar de nuevo     X Extraer archivo existente     B Volver", 48, 673, 25)
            else:
                s.text("A Descargar     B Volver", 48, 673, 25)
        elif self.page == "notice":
            s.text("Aviso", 48, 145, 34)
            self.message(self.notice, 240)
            s.text("A / B Volver", 48, 673, 25)
        elif self.page == "exit":
            s.text("¿Salir de X55 ROM Downloader?", 48, 230, 36)
            if self.refresh_needed and not self.read_only:
                s.text('Al salir se actualizará la lista de juegos.', 48, 320, 27, (126, 211, 188))
            s.text("A Salir     B Continuar", 48, 673, 25)
        s.present()

    def message(self, message, y):
        message = str(message)
        for row in range(4):
            line, message = message[:82], message[82:]
            self.screen.text(line, 48, y + row * 38, 26)
            if not message:
                break

    def draw_list(self):
        s = self.screen
        items = self.items()
        title = self.system if self.system is not None else "Sistemas"
        s.text(title, 48, 132, 32)
        count = f"{len(items)} {'juegos' if self.system else 'sistemas'}"
        if self.system and self.catalog[self.system].get('performance') == 'variable':
            count += '  ·  Rendimiento variable'
        if self.system and self.catalog[self.system].get('archive_mode') == 'keep':
            count += '  ·  Requiere romset y BIOS compatibles'
        if self.query:
            count += f"  ·  Buscar: {self.query}"
        s.text(count, 48, 177, 23, (147, 166, 192))
        if not items:
            s.text("No hay coincidencias." if self.query else "No hay juegos disponibles.", 64, 280, 30)
        first = self.index // 8 * 8
        for row, item in enumerate(items[first:first + 8]):
            selected = first + row == self.index
            y = 222 + row * 50
            if selected:
                s.fill(40, y - 2, 1200, 47, (38, 91, 87))
                s.fill(40, y - 2, 5, 47, (64, 214, 170))
            if self.system is None:
                label = f"{item}"
                s.text(f"{len(self.catalog[item]['games'])} juegos", 1060, y + 5, 24, (147, 186, 188), 165)
            else:
                label = item["name"]
                state = self.game_status(item)['status']
                labels = {'installed': ('Instalado', (126, 211, 188)),
                          'zip': ('ZIP descargado', (255, 199, 111)),
                          'archive': ('7z descargado', (255, 199, 111)),
                          'available': ('Disponible', (147, 166, 192)),
                          'error': ('Revisar ruta', (255, 150, 150))}
                badge, color = labels[state]
                s.text(badge, 1010, y + 6, 23, color, 215)
            s.text(label, 64, y + 3, 28, max_width=910)
        if items:
            s.text(f"{self.index + 1}/{len(items)}", 1100, 143, 23)
        footer = "A Seleccionar   B Volver   X Buscar   Start Salir" if self.system else "Cruceta / analógico Navegar   A Abrir   B / Start Salir"
        s.text(footer, 48, 673, 25)

    def draw_keyboard(self):
        s = self.screen
        s.text(f"Buscar en {self.system}", 48, 133, 32)
        s.fill(40, 193, 1200, 65, (28, 42, 61))
        s.text(self.draft + "_", 58, 206, 30)
        for i, key in enumerate(self.KEYBOARD):
            x, y = 40 + (i % 10) * 120, 292 + (i // 10) * 75
            selected = i == self.keyboard_index
            s.fill(x, y, 112, 62, (38, 112, 96) if selected else (28, 42, 61))
            s.text(key, x + 9, y + 17, 21 if len(key) > 1 else 28, max_width=98)
        s.text("A Escribir   B Cancelar   X Aplicar búsqueda", 48, 673, 25)

    def draw_download(self):
        s = self.screen
        state = self.job.snapshot()
        status = state["status"]
        headings = {"connecting": "Conectando…", "downloading": "Descargando…",
                    "done": "Descarga terminada", "cancelled": "Descarga cancelada", "error": "Error de descarga"}
        headings['resolving'] = 'Obteniendo enlace actualizado…'
        if self.page in ('download', 'resolve') and status == 'error':
            headings['error'] = state.get('error_title', 'Error de descarga')
        if self.page == "extract":
            headings.update(extracting="Extrayendo y verificando ROM…", verifying="Verificando ROM ya instalada…", done="ROM verificada",
                            cancelled="Extracción cancelada · Archivo conservado", error="No se pudo extraer · Archivo conservado")
        s.text(headings[status], 48, 143, 34)
        s.text(self.game["name"], 48, 215, 30)
        s.text(str(self.destination), 48, 268, 23, (147, 166, 192))
        downloaded, total = state["downloaded"], state["total"]
        s.fill(48, 340, 1184, 30, (34, 48, 66))
        if total:
            ratio = min(downloaded / total, 1)
            s.fill(48, 340, int(1184 * ratio), 30, (64, 214, 170))
            text = f"{ratio * 100:.1f}%   ·   {size_text(downloaded)} / {size_text(total)}"
        else:
            if status in ("connecting", "downloading", "extracting", "verifying", 'resolving'):
                s.fill(48 + int(time.monotonic() * 180) % 960, 340, 224, 30, (64, 214, 170))
            text = size_text(downloaded) + ("  ·  Tamaño total desconocido" if status == "downloading" else "")
        s.text(text, 48, 390)
        if status == 'downloading':
            speed = state.get('speed', 0)
            eta = state.get('eta')
            remaining = f'  ·  Restan {int(eta)//60} min {int(eta)%60:02d} s' if eta is not None else ''
            s.text(f"{size_text(speed)}/s  ·  {state.get('connections', 1)} conexiones{remaining}", 48, 450, 25)
        if status == "error":
            self.message(state["error"], 450)
        if status in ("done", "cancelled", "error"):
            footer = "A / B Volver a los juegos"
        elif self.job.cancel.is_set():
            footer = "Cancelando…"
        elif self.cancel_confirm:
            footer = "¿Cancelar?   A Sí   B Continuar"
        else:
            footer = "B Cancelar extracción" if self.page == "extract" else "B Cancelar descarga"
        s.text(footer, 48, 673, 25)

    def run(self, max_seconds=None):
        self.screen = Screen()
        started = time.monotonic()
        print("V0.4 LISTA: interfaz 1280x720 y controles activos", flush=True)
        try:
            while self.running:
                if max_seconds is not None and time.monotonic() - started >= max_seconds:
                    break
                for action in self.screen.actions():
                    self.act(action)
                self.advance()
                self.draw()
                time.sleep(0.016)
        finally:
            if self.job and self.job.thread.is_alive():
                self.job.cancel.set()
                self.job.thread.join(timeout=12)
            self.screen.close()
            if not self.read_only:
                _, message = refresh_pending(self.root)
                print(message, flush=True)
            print("V0.4 CERRADA", flush=True)
