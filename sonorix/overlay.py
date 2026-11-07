"""Píldora flotante con forma de onda en vivo.

Nunca roba el foco (WS_EX_NOACTIVATE) y los clics la atraviesan
(WS_EX_TRANSPARENT), así el texto se pega donde estaba el cursor.
"""
from __future__ import annotations

import ctypes
import math
import queue
import time
import tkinter as tk
from collections import deque
from ctypes import wintypes
from tkinter import font as tkfont

KEY = "#010203"           # color clave = transparente
BG = "#0b0c18"
BORDER = "#2a2f5c"
FG = "#e9e9f1"
MUTED = "#8b8d9a"
RED = "#ff4d5e"
AMBER = "#ffb547"
GREEN = "#3ddc97"
GRAD3 = [(0, 229, 255), (124, 77, 255), (255, 43, 214)]  # cian → violeta → magenta

H = 46
BARS = 30
FPS = 33


def _lerp(c1, c2, t):
    return "#%02x%02x%02x" % tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _neon(t: float) -> str:
    t = max(0.0, min(1.0, t))
    if t < 0.55:
        return _lerp(GRAD3[0], GRAD3[1], t / 0.55)
    return _lerp(GRAD3[1], GRAD3[2], (t - 0.55) / 0.45)


def _work_area():
    r = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom


class Overlay:
    def __init__(self, root: tk.Tk, level_source, position: str = "bottom"):
        self.root = root
        self.level_source = level_source          # callable → float RMS
        self.position = position
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.state = "hidden"
        self.message = ""
        self.handsfree = False
        self.started = 0.0
        self.hide_at = 0.0
        self.alpha = 0.0
        self.target_alpha = 0.0
        self.levels: deque[float] = deque([0.0] * BARS, maxlen=BARS)
        self.width = 0

        scale = root.winfo_fpixels("1i") / 96
        self.s = max(1.0, scale)
        self.h = int(H * self.s)
        self.font = tkfont.Font(family="Segoe UI Semibold", size=10)
        self.tiny = tkfont.Font(family="Segoe UI", size=7)

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.0)
        root.configure(bg=KEY)
        root.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._resize(int(240 * self.s))
        root.update_idletasks()
        self._apply_ex_style()
        root.after(int(1000 / FPS), self._tick)

    # -- API thread-safe ---------------------------------------------
    def show(self, state: str, message: str = "", **kw) -> None:
        self.events.put((state, message, kw))

    # -- Win32 --------------------------------------------------------
    def _apply_ex_style(self) -> None:
        u = ctypes.windll.user32
        hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        GWL_EXSTYLE = -20
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= 0x08000000 | 0x00000080 | 0x00000020 | 0x00080000 | 0x00000008
        #        NOACTIVATE    TOOLWINDOW   TRANSPARENT  LAYERED      TOPMOST
        u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

    def _resize(self, width: int) -> None:
        if width == self.width:
            return
        self.width = width
        left, top, right, bottom = _work_area()
        x = left + (right - left - width) // 2
        margin = int(28 * self.s)
        y = top + margin if self.position == "top" else bottom - self.h - margin
        self.root.geometry(f"{width}x{self.h}+{x}+{y}")
        self.canvas.config(width=width, height=self.h)

    # -- bucle --------------------------------------------------------
    def _drain(self) -> None:
        while True:
            try:
                state, message, kw = self.events.get_nowait()
            except queue.Empty:
                return
            now = time.time()
            self.state, self.message = state, message
            self.hide_at = 0.0
            if state == "recording":
                self.handsfree = kw.get("handsfree", False)
                self.started = now
                self.levels.extend([0.0] * BARS)
                self.target_alpha = 0.96
            elif state == "processing":
                self.started = now
                self.target_alpha = 0.96
            elif state in ("done", "info"):
                self.target_alpha = 0.96
                self.hide_at = now + 1.4
            elif state == "error":
                self.target_alpha = 0.98
                self.hide_at = now + 4.0
            else:  # hidden
                self.target_alpha = 0.0

    def _tick(self) -> None:
        try:
            self._drain()
            now = time.time()
            if self.hide_at and now >= self.hide_at:
                self.hide_at = 0.0
                self.target_alpha = 0.0
            if abs(self.alpha - self.target_alpha) > 0.01:
                step = 0.22 if self.target_alpha > self.alpha else 0.12
                self.alpha += max(-step, min(step, self.target_alpha - self.alpha))
                self.root.attributes("-alpha", max(0.0, self.alpha))
            elif self.alpha != self.target_alpha:
                self.alpha = self.target_alpha
                self.root.attributes("-alpha", self.alpha)
            if self.alpha > 0.0 or self.target_alpha > 0.0:
                self._draw(now)
        finally:
            self.root.after(int(1000 / FPS), self._tick)

    # -- dibujo -------------------------------------------------------
    def _pill(self, w: int, h: int, color: str, outline: str) -> None:
        c, r = self.canvas, h // 2
        c.create_oval(0, 0, h - 1, h - 1, fill=outline, outline="")
        c.create_oval(w - h, 0, w - 1, h - 1, fill=outline, outline="")
        c.create_rectangle(r, 0, w - r, h - 1, fill=outline, outline="")
        b = max(1, int(self.s))
        c.create_oval(b, b, h - 1 - b, h - 1 - b, fill=color, outline="")
        c.create_oval(w - h + b, b, w - 1 - b, h - 1 - b, fill=color, outline="")
        c.create_rectangle(r, b, w - r, h - 1 - b, fill=color, outline="")

    def _draw(self, now: float) -> None:
        c, s, h = self.canvas, self.s, self.h
        c.delete("all")
        st = self.state
        if st == "recording":
            self._draw_recording(now)
        elif st == "processing":
            self._resize(int(200 * s))
            self._pill(self.width, h, BG, BORDER)
            self._draw_processing(now)
        elif st in ("done", "info", "error"):
            color = {"done": GREEN, "info": MUTED, "error": RED}[st]
            icon = {"done": "✓", "info": "•", "error": "!"}[st]
            tw = self.font.measure(self.message)
            self._resize(int(min(560 * s, tw + 72 * s)))
            self._pill(self.width, h, BG, BORDER)
            cx = int(24 * s)
            c.create_oval(cx - 9 * s, h / 2 - 9 * s, cx + 9 * s, h / 2 + 9 * s, fill=color, outline="")
            c.create_text(cx, h / 2, text=icon, fill=BG, font=self.font)
            c.create_text(int(42 * s), h / 2, text=self.message, fill=FG, font=self.font, anchor="w")

    def _draw_recording(self, now: float) -> None:
        c, s, h = self.canvas, self.s, self.h
        self._resize(int(260 * s))
        w = self.width
        self._pill(w, h, BG, BORDER)

        # punto pulsante
        color = AMBER if self.handsfree else RED
        pulse = 0.5 + 0.5 * math.sin(now * 6)
        cx, cy = int(22 * s), h / 2
        rr = (5 + 2.5 * pulse) * s
        c.create_oval(cx - rr - 3 * s, cy - rr - 3 * s, cx + rr + 3 * s, cy + rr + 3 * s,
                      fill=_lerp((16, 17, 22), (90, 30, 36) if not self.handsfree else (90, 66, 28), 0.6 * pulse),
                      outline="")
        c.create_oval(cx - 5 * s, cy - 5 * s, cx + 5 * s, cy + 5 * s, fill=color, outline="")

        # onda
        raw = float(self.level_source() or 0.0)
        db = 20 * math.log10(raw + 1e-6)
        norm = max(0.0, min(1.0, (db + 52) / 40))
        self.levels.append(norm)
        x0, x1 = int(42 * s), w - int(66 * s)
        span = x1 - x0
        bw = span / BARS
        maxh = h - 18 * s
        for i, v in enumerate(self.levels):
            t = i / (BARS - 1)
            shape = 0.55 + 0.45 * math.sin(math.pi * t)  # centro más alto
            bh = max(2.5 * s, v * maxh * shape)
            bx = x0 + i * bw + bw * 0.18
            c.create_rectangle(bx, cy - bh / 2, bx + bw * 0.64, cy + bh / 2,
                               fill=_neon(t), outline="")

        # tiempo + modo
        el = int(now - self.started)
        c.create_text(w - int(20 * s), cy - (6 * s if self.handsfree else 0), text=f"{el // 60}:{el % 60:02d}",
                      fill=FG, font=self.font, anchor="e")
        if self.handsfree:
            c.create_text(w - int(20 * s), cy + 9 * s, text="manos libres", fill=MUTED,
                          font=self.tiny, anchor="e")

    def _draw_processing(self, now: float) -> None:
        c, s, h = self.canvas, self.s, self.h
        cy = h / 2
        for i in range(3):
            ph = (now * 3.2 - i * 0.35) % 1.0
            k = 0.5 + 0.5 * math.sin(ph * 2 * math.pi)
            r = (3 + 2 * k) * s
            cx = int((22 + i * 13) * s)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=_neon(i / 2 * 0.6 + 0.4 * k), outline="")
        c.create_text(int(68 * s), cy, text=self.message or "Transcribiendo…", fill=FG, font=self.font, anchor="w")
