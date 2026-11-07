"""Punto de entrada: python -m sonorix"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
import webbrowser
from logging.handlers import RotatingFileHandler

from . import winutil
from .config import LOG_PATH


def _setup_logging() -> None:
    handlers = [RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stdout and sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


def main() -> int:
    _setup_logging()
    log = logging.getLogger("sonorix")

    from .config import Settings

    port = Settings().web_port
    if not winutil.acquire_single_instance():
        webbrowser.open(f"http://localhost:{port}")  # ya corre: abre el panel
        return 0

    winutil.enable_dpi_awareness()

    from .app import Core
    from .mobile import MobileServer
    from .overlay import Overlay
    from .tray import Tray
    from .web import serve

    root = tk.Tk()
    root.title("Sonorix")
    core = Core()
    overlay = Overlay(root, level_source=lambda: core.recorder.level, position=core.settings.overlay_position)
    core.show = overlay.show

    try:
        serve(core, core.settings.web_port)
        log.info("Panel en http://localhost:%s", core.settings.web_port)
    except OSError as exc:
        log.error("No pude abrir el panel en el puerto %s: %s", core.settings.web_port, exc)

    core.mobile = MobileServer(core)
    core.mobile.sync()
    core.start()

    def quit_app():
        root.after(0, root.destroy)

    tray = Tray(core, on_quit=quit_app)
    tray.start()

    first_run = not core.settings.api_key and core.db.last() is None
    if first_run or "--panel" in sys.argv:
        webbrowser.open(f"http://localhost:{core.settings.web_port}")
    hk = core.settings.hotkey.upper()
    overlay.show("info", f"Sonorix listo · mantén {hk} o toca 2 veces")

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        tray.stop()
        core.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
