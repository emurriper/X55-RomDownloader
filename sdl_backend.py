"""Adaptador pequeño de SDL2/SDL_ttf con ctypes, sin paquetes Python externos."""

import ctypes as C
from collections import OrderedDict
import os
import time


class Rect(C.Structure):
    _fields_ = [(name, C.c_int) for name in ("x", "y", "w", "h")]


class Color(C.Structure):
    _fields_ = [(name, C.c_uint8) for name in ("r", "g", "b", "a")]


class Event(C.Union):
    _fields_ = [("type", C.c_uint32), ("raw", C.c_uint8 * 56), ("alignment", C.c_uint64)]


class Screen:
    def __init__(self):
        self.window = self.renderer = None
        self.fonts = {}
        self.textures = OrderedDict()
        self.controllers = {}
        self.held = {}
        self.next_repeat = {}
        self.ttf_ready = False
        self.s = C.CDLL("libSDL2-2.0.so.0")
        self.t = C.CDLL("libSDL2_ttf-2.0.so.0")
        p, i, u, b = C.c_void_p, C.c_int, C.c_uint32, C.c_uint8
        signatures = {
            "SDL_Init": (i, u), "SDL_Quit": (None,), "SDL_GetError": (C.c_char_p,),
            "SDL_CreateWindow": (p, C.c_char_p, i, i, i, i, u),
            "SDL_DestroyWindow": (None, p), "SDL_CreateRenderer": (p, p, i, u),
            "SDL_DestroyRenderer": (None, p), "SDL_RenderSetLogicalSize": (i, p, i, i),
            "SDL_SetRenderDrawColor": (i, p, b, b, b, b), "SDL_RenderClear": (i, p),
            "SDL_RenderFillRect": (i, p, C.POINTER(Rect)), "SDL_RenderPresent": (None, p),
            "SDL_PollEvent": (i, C.POINTER(Event)), "SDL_NumJoysticks": (i,),
            "SDL_IsGameController": (i, i), "SDL_GameControllerOpen": (p, i),
            "SDL_GameControllerClose": (None, p), "SDL_GameControllerGetJoystick": (p, p),
            "SDL_JoystickInstanceID": (i, p), "SDL_CreateTextureFromSurface": (p, p, p),
            "SDL_FreeSurface": (None, p), "SDL_DestroyTexture": (None, p),
            "SDL_QueryTexture": (i, p, p, p, C.POINTER(i), C.POINTER(i)),
            "SDL_RenderCopy": (i, p, p, p, C.POINTER(Rect)),
        }
        for name, signature in signatures.items():
            self._bind(self.s, name, signature)
        for name, signature in {
            "TTF_Init": (i,), "TTF_Quit": (None,), "TTF_OpenFont": (p, C.c_char_p, i),
            "TTF_CloseFont": (None, p), "TTF_RenderUTF8_Blended": (p, p, C.c_char_p, Color),
        }.items():
            self._bind(self.t, name, signature)
        try:
            self._check(self.SDL_Init(0x20 | 0x2000 | 0x4000))
            self.window = self.SDL_CreateWindow(b"X55 ROM Downloader v0.3", 0x2FFF0000,
                                                0x2FFF0000, 1280, 720, 0x1001)
            if not self.window:
                raise RuntimeError(self.error())
            self.renderer = self.SDL_CreateRenderer(self.window, -1, 6)
            if not self.renderer:
                self.renderer = self.SDL_CreateRenderer(self.window, -1, 1)
            if not self.renderer:
                raise RuntimeError(self.error())
            self._check(self.SDL_RenderSetLogicalSize(self.renderer, 1280, 720))
            self._check(self.TTF_Init())
            self.ttf_ready = True
            self.font_path = next((path for path in (
                "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
            ) if os.path.isfile(path)), None)
            if not self.font_path:
                raise RuntimeError("No se encuentra una fuente TrueType.")
            for index in range(self.SDL_NumJoysticks()):
                self._open_controller(index)
        except Exception:
            self.close()
            raise

    def _bind(self, library, name, signature):
        fn = getattr(library, name)
        fn.restype, fn.argtypes = signature[0], list(signature[1:])
        setattr(self, name, fn)

    def error(self):
        return self.SDL_GetError().decode("utf-8", "replace")

    def _check(self, result):
        if result < 0:
            raise RuntimeError(self.error())

    def _open_controller(self, index):
        if self.SDL_IsGameController(index):
            handle = self.SDL_GameControllerOpen(index)
            if handle:
                identity = self.SDL_JoystickInstanceID(self.SDL_GameControllerGetJoystick(handle))
                old = self.controllers.get(identity)
                if old:
                    self.SDL_GameControllerClose(old)
                self.controllers[identity] = handle

    def fill(self, x, y, w, h, color):
        self.SDL_SetRenderDrawColor(self.renderer, *color, 255)
        self.SDL_RenderFillRect(self.renderer, C.byref(Rect(x, y, w, h)))

    def clear(self):
        self.SDL_SetRenderDrawColor(self.renderer, 14, 20, 32, 255)
        self.SDL_RenderClear(self.renderer)

    def text(self, text, x, y, size=28, color=(225, 233, 245), max_width=1190):
        # No se renderizan cadenas ilimitadas procedentes del catálogo o de errores.
        text = str(text).replace("\n", " ").replace("\r", " ")[:180] or " "
        key = (text, size, color)
        if key not in self.textures:
            if size not in self.fonts:
                font = self.TTF_OpenFont(self.font_path.encode(), size)
                if not font:
                    raise RuntimeError(self.error())
                self.fonts[size] = font
            surface = self.TTF_RenderUTF8_Blended(self.fonts[size], text.encode(), Color(*color, 255))
            if not surface:
                raise RuntimeError(self.error())
            texture = self.SDL_CreateTextureFromSurface(self.renderer, surface)
            self.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError(self.error())
            width, height = C.c_int(), C.c_int()
            self.SDL_QueryTexture(texture, None, None, C.byref(width), C.byref(height))
            self.textures[key] = texture, width.value, height.value
            if len(self.textures) > 160:
                _, (old, _, _) = self.textures.popitem(last=False)
                self.SDL_DestroyTexture(old)
        self.textures.move_to_end(key)
        texture, width, height = self.textures[key]
        width = min(width, max_width)
        self.SDL_RenderCopy(self.renderer, texture, C.byref(Rect(0, 0, width, height)),
                            C.byref(Rect(x, y, width, height)))

    def actions(self):
        actions = []
        event = Event()
        # X55: A físico=East, B=South, X=North. SDL usa letras Xbox.
        buttons = {1: "select", 0: "back", 3: "search", 6: "start",
                   11: "up", 12: "down", 13: "left", 14: "right"}
        keys = {13: "select", 27: "back", 120: "search", 8: "erase",
                1073741906: "up", 1073741905: "down",
                1073741904: "left", 1073741903: "right"}
        while self.SDL_PollEvent(C.byref(event)):
            raw = bytes(event.raw)
            identity = int.from_bytes(raw[8:12], "little", signed=True)
            if event.type == 0x100:
                actions.append("quit")
            elif event.type == 0x200 and raw[12] == 13:  # SDL_WINDOWEVENT_FOCUS_LOST
                self.held.clear()
                self.next_repeat.clear()
            elif event.type == 0x653:
                self._open_controller(identity)
            elif event.type == 0x654:
                controller = self.controllers.pop(identity, None)
                if controller:
                    self.SDL_GameControllerClose(controller)
                self.held = {k: v for k, v in self.held.items() if k[1] != identity}
            elif event.type in (0x651, 0x652):
                action = buttons.get(raw[12])
                source = ("button", identity, raw[12])
                self._held_action(source, action if event.type == 0x651 else None, actions)
            elif event.type == 0x650 and raw[12] in (0, 1):
                axis = raw[12]
                value = int.from_bytes(raw[16:18], "little", signed=True)
                action = None
                if abs(value) > 14000:
                    action = ("left" if value < 0 else "right") if axis == 0 else ("up" if value < 0 else "down")
                self._held_action(("axis", identity, axis), action, actions)
            elif event.type in (0x300, 0x301):
                symbol = int.from_bytes(raw[20:24], "little", signed=True)
                if not raw[13]:
                    self._held_action(("key", 0, symbol), keys.get(symbol) if event.type == 0x300 else None, actions)
        now = time.monotonic()
        active = set(self.held.values()) & {"up", "down", "left", "right"}
        for action in list(self.next_repeat):
            if action not in active:
                del self.next_repeat[action]
        for action in active:
            if action not in self.next_repeat:
                self.next_repeat[action] = now + 0.32
            elif now >= self.next_repeat[action]:
                actions.append(action)
                self.next_repeat[action] = now + 0.12
        return actions

    def _held_action(self, source, action, actions):
        old = self.held.pop(source, None)
        if action:
            self.held[source] = action
            if action != old:
                actions.append(action)

    def present(self):
        self.SDL_RenderPresent(self.renderer)

    def close(self):
        for handle in self.controllers.values():
            self.SDL_GameControllerClose(handle)
        self.controllers.clear()
        for texture, _, _ in self.textures.values():
            self.SDL_DestroyTexture(texture)
        self.textures.clear()
        for font in self.fonts.values():
            self.TTF_CloseFont(font)
        self.fonts.clear()
        if self.ttf_ready:
            self.TTF_Quit()
        if self.renderer:
            self.SDL_DestroyRenderer(self.renderer)
        if self.window:
            self.SDL_DestroyWindow(self.window)
        self.SDL_Quit()
