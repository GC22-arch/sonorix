"""Configuración persistente de Sonorix.

Los datos (settings, base de datos, logs) viven en %LOCALAPPDATA%\\Sonorix para
no pelearse con la sincronización de OneDrive.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

APP_NAME = "Sonorix"
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "sonorix.db"
LOG_PATH = DATA_DIR / "sonorix.log"

DEFAULTS: dict = {
    # Motor
    "engine": "auto",                      # auto (Groq gratis → local si falla) | groq | local
    "groq_api_key": "",
    "groq_model": "whisper-large-v3-turbo",
    "local_model": "small",                # tiny | base | small | medium | large-v3
    "language": "es",                      # "" = autodetectar
    # Atajo
    "hotkey": "right ctrl",
    "tap_max": 0.25,                       # s: pulsación más corta que esto = toque
    "double_tap_window": 0.40,             # s: ventana para el doble toque
    "min_duration": 0.35,                  # s: grabaciones más cortas se descartan
    # Salida
    "paste_method": "clipboard",           # clipboard | type
    "restore_clipboard": True,
    "trailing_space": True,
    # Inteligencia
    "ai_cleanup": False,
    "cleanup_model": "llama-3.1-8b-instant",
    "cleanup_style": "natural",            # natural | formal | casual
    "vocabulary": "",                      # palabras/nombres para guiar a Whisper
    "replacements": {},                    # {"dicho": "escrito"}
    "voice_commands": True,
    # Interfaz
    "sounds": True,
    "overlay_position": "bottom",          # bottom | top
    "mic_device": None,                    # índice de dispositivo o None = predeterminado
    "web_port": 5000,
    # Celular (PWA por wifi, HTTPS autofirmado + token de emparejado)
    "mobile_enabled": False,
    "mobile_port": 5443,
    "mobile_token": "",
    "mobile_paste_pc": False,              # además de devolver el texto, pegarlo en el PC
}

SECRET_KEYS = {"groq_api_key", "mobile_token"}


def _load_dotenv() -> None:
    """Carga un .env junto al proyecto (sin dependencias)."""
    env = APP_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH):
        _load_dotenv()
        self.path = path
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self._listeners: list = []
        self.load()

    # -- persistencia -------------------------------------------------
    def load(self) -> None:
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                with self._lock:
                    for k, v in stored.items():
                        if k in DEFAULTS:
                            self._data[k] = v
            except (OSError, json.JSONDecodeError):
                pass

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    # -- acceso -------------------------------------------------------
    def __getattr__(self, key):
        if key.startswith("_") or key not in DEFAULTS:
            raise AttributeError(key)
        with self._lock:
            return self._data[key]

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    @property
    def api_key(self) -> str:
        return (self.get("groq_api_key") or os.environ.get("GROQ_API_KEY", "")).strip()

    def public(self) -> dict:
        """Copia apta para el panel web (sin secretos)."""
        with self._lock:
            data = copy.deepcopy(self._data)
        for k in SECRET_KEYS:
            data.pop(k, None)
        key = self.api_key
        data["has_api_key"] = bool(key)
        data["api_key_hint"] = f"{key[:4]}…{key[-4:]}" if len(key) > 12 else ""
        data["api_key_from_env"] = bool(os.environ.get("GROQ_API_KEY")) and not self.get("groq_api_key")
        return data

    def update(self, changes: dict) -> dict:
        clean = {}
        for k, v in changes.items():
            if k not in DEFAULTS:
                continue
            default = DEFAULTS[k]
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, float):
                v = float(v)
            elif isinstance(default, int) and not isinstance(default, bool):
                v = int(v)
            elif isinstance(default, dict) and not isinstance(v, dict):
                continue
            elif k == "mic_device":
                v = None if v in (None, "", "default") else int(v)
            clean[k] = v
        with self._lock:
            old = copy.deepcopy(self._data)
            self._data.update(clean)
            self.save()
        changed = {k for k in clean if old.get(k) != clean[k]}
        for cb in list(self._listeners):
            try:
                cb(changed)
            except Exception:  # noqa: BLE001 - un listener roto no debe tumbar la app
                pass
        return self.public()

    def on_change(self, callback) -> None:
        self._listeners.append(callback)
