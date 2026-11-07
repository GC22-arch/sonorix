"""Atajo global con dos modos:

- Mantener pulsado  → graba mientras la tecla esté abajo (push-to-talk).
- Doble toque       → manos libres; un toque más (o Esc) lo termina.

Si mientras mantienes la tecla pulsas otra (p.ej. Ctrl+C), se entiende como
atajo normal y la grabación se cancela sin hacer nada.
"""
from __future__ import annotations

import threading
import time

import keyboard

IDLE, HOLD, HANDSFREE = "idle", "hold", "handsfree"


def canonical(name: str) -> str:
    """Windows entrega nombres traducidos ("ctrl derecha", "mayús derecha"...).
    Los llevamos a una forma estable en inglés: "right ctrl", "shift", etc."""
    n = (name or "").strip().lower()
    if not n:
        return ""
    right = n.startswith("right") or "derech" in n or "dcha" in n
    if "ctrl" in n or "control" in n:
        base = "ctrl"
    elif "alt gr" in n or "altgr" in n:
        return "alt gr"
    elif "alt" in n:
        base = "alt"
    elif "shift" in n or "mayús" in n or "mayus" in n:
        base = "shift"
    elif "win" in n:
        base = "windows"
    else:
        return n
    return f"right {base}" if right else base


class HotkeyController:
    def __init__(self, settings, *, on_start, on_stop, on_cancel):
        self.settings = settings
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cancel = on_cancel
        self.state = IDLE
        self.enabled = True
        self._key = ""
        self._down = False
        self._press_t = 0.0
        self._last_tap_t = 0.0
        self._ignore_up = False
        self._hook = None
        self._capture: tuple[threading.Event, list] | None = None
        self._lock = threading.Lock()

    @property
    def key(self) -> str:
        return self._key

    def start(self) -> None:
        self._key = self._normalize(self.settings.hotkey)
        self._hook = keyboard.hook(self._on_event)

    def stop(self) -> None:
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None

    def rebind(self, key: str) -> None:
        with self._lock:
            self._key = self._normalize(key)
            self.state, self._down, self._ignore_up = IDLE, False, False

    def force_idle(self) -> None:
        with self._lock:
            self.state = IDLE

    def capture_next_key(self, timeout: float = 8.0) -> str | None:
        ev = threading.Event()
        box: list = []
        self._capture = (ev, box)
        ev.wait(timeout)
        self._capture = None
        return box[0] if box else None

    @staticmethod
    def _normalize(name: str) -> str:
        return canonical(name)

    # -- núcleo -------------------------------------------------------
    def _on_event(self, e: keyboard.KeyboardEvent) -> None:
        name = self._normalize(e.name)
        if self._capture and e.event_type == keyboard.KEY_DOWN and name:
            ev, box = self._capture
            box.append(name)
            ev.set()
            return
        if not self.enabled or not name:
            return
        now = time.time()
        with self._lock:
            if name != self._key:
                if e.event_type != keyboard.KEY_DOWN:
                    return
                if self.state == HOLD:
                    self.state = IDLE            # era un atajo tipo Ctrl+C
                    self._last_tap_t = 0.0
                    self.on_cancel("combo")
                elif self.state == HANDSFREE and name in ("esc", "escape"):
                    self.state = IDLE
                    self.on_cancel("esc")
                return

            if e.event_type == keyboard.KEY_DOWN:
                if self._down:                   # autorepetición
                    return
                self._down = True
                self._press_t = now
                if self.state == HANDSFREE:      # toque para terminar
                    self.state = IDLE
                    self._ignore_up = True
                    self.on_stop()
                    return
                if now - self._last_tap_t <= float(self.settings.double_tap_window):
                    self.state = HANDSFREE       # doble toque
                    self._last_tap_t = 0.0
                    self._ignore_up = True
                    self.on_start(True)
                    return
                self.state = HOLD
                self.on_start(False)
            else:                                # KEY_UP
                self._down = False
                if self._ignore_up:
                    self._ignore_up = False
                    return
                if self.state == HOLD:
                    self.state = IDLE
                    if now - self._press_t < float(self.settings.tap_max):
                        self._last_tap_t = now   # posible primer toque
                        self.on_cancel("tap")
                    else:
                        self.on_stop()
