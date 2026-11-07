"""Icono en la bandeja del sistema (logo Sonorix: anillo ecualizador)."""
from __future__ import annotations

import math
import webbrowser

import pystray
from PIL import Image, ImageDraw

BARS = [20, 14, 18, 12, 21, 12, 22, 14, 17, 16, 12.5, 16]
NEON = [(0, 229, 255), (124, 77, 255), (255, 43, 214)]
GREY = [(150, 150, 165), (110, 110, 125), (80, 80, 95)]


def _grad(stops, t):
    t = max(0.0, min(1.0, t))
    if t < 0.55:
        a, b, u = stops[0], stops[1], t / 0.55
    else:
        a, b, u = stops[1], stops[2], (t - 0.55) / 0.45
    return tuple(int(x + (y - x) * u) for x, y in zip(a, b))


def make_icon(size: int = 64, paused: bool = False) -> Image.Image:
    ss = 4  # supersampling para bordes suaves
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = S / 120
    c = S / 2
    stops = GREY if paused else NEON
    d.ellipse((1 * k, 1 * k, S - 1 * k, S - 1 * k), fill=(8, 9, 18, 255))
    w = int(6.5 * k)
    for i, ln in enumerate(BARS):
        a = math.radians(i * 30 - 90)
        x1, y1 = c + 22 * k * math.cos(a), c + 22 * k * math.sin(a)
        x2, y2 = c + (22 + ln * 1.25) * k * math.cos(a), c + (22 + ln * 1.25) * k * math.sin(a)
        col = _grad(stops, ((x2 + y2) / 2 / S - 0.18) / 0.64)
        d.line((x1, y1, x2, y2), fill=col, width=w)
        for x, y in ((x1, y1), (x2, y2)):
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=col)
    d.ellipse((c - 15 * k, c - 15 * k, c + 15 * k, c + 15 * k), fill=_grad(stops, 0.5))
    d.ellipse((c - 6 * k, c - 6 * k, c + 6 * k, c + 6 * k), fill=(8, 9, 18, 255))
    return img.resize((size, size), Image.LANCZOS)


class Tray:
    def __init__(self, core, on_quit):
        self.core = core
        url = f"http://localhost:{core.settings.web_port}"
        self.icon = pystray.Icon(
            "Sonorix",
            make_icon(),
            "Sonorix — dictado por voz",
            menu=pystray.Menu(
                pystray.MenuItem("Abrir panel", lambda: webbrowser.open(url), default=True),
                pystray.MenuItem("Copiar último dictado", self._copy_last),
                pystray.MenuItem("Pausar", self._toggle, checked=lambda _: core.paused),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", lambda: on_quit()),
            ),
        )

    def _copy_last(self) -> None:
        import pyperclip

        last = self.core.db.last()
        if last:
            pyperclip.copy(last["text"])
            self.core.show("done", "Último dictado copiado")
        else:
            self.core.show("info", "Aún no hay dictados")

    def _toggle(self) -> None:
        self.core.set_paused(not self.core.paused)
        self.icon.icon = make_icon(paused=self.core.paused)

    def start(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass
