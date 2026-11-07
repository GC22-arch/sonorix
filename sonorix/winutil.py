"""Utilidades Win32 vía ctypes: pegar, ventana activa, instancia única, inicio con Windows."""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

import keyboard
import pyperclip

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def foreground_app() -> str:
    """Nombre del proceso + título de la ventana activa, p.ej. 'chrome · Gmail'."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        size = wintypes.DWORD(1024)
        pbuf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
            exe = Path(pbuf.value).stem
        kernel32.CloseHandle(h)
    if exe and title:
        return f"{exe} · {title}"[:120]
    return (exe or title)[:120]


def _wait_modifiers_released(timeout: float = 1.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if not any(keyboard.is_pressed(k) for k in ("ctrl", "alt", "shift")):
                return
        except ValueError:
            return
        time.sleep(0.02)


def paste_text(text: str, method: str = "clipboard", restore: bool = True) -> None:
    _wait_modifiers_released()
    if method == "type":
        keyboard.write(text, delay=0)
        return
    previous = None
    if restore:
        try:
            previous = pyperclip.paste()
        except Exception:  # noqa: BLE001
            previous = None
    pyperclip.copy(text)
    time.sleep(0.03)
    keyboard.send("ctrl+v")
    if restore and previous is not None:
        def _restore():
            time.sleep(0.6)
            try:
                if pyperclip.paste() == text:
                    pyperclip.copy(previous)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=_restore, daemon=True).start()


def microphone_blocked() -> bool:
    """True si la privacidad de Windows niega el micrófono a apps de escritorio."""
    import winreg

    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    checks = [(winreg.HKEY_LOCAL_MACHINE, base), (winreg.HKEY_CURRENT_USER, base),
              (winreg.HKEY_CURRENT_USER, base + r"\NonPackaged")]
    for hive, path in checks:
        try:
            with winreg.OpenKey(hive, path) as k:
                if str(winreg.QueryValueEx(k, "Value")[0]).lower() == "deny":
                    return True
        except OSError:
            continue
    return False


_mutex = None


def acquire_single_instance(name: str = "Local\\SonorixSingleInstance") -> bool:
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, name)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
STARTUP_FILE = STARTUP_DIR / "Sonorix.vbs"


def startup_enabled() -> bool:
    return STARTUP_FILE.exists()


def set_startup(enabled: bool, pythonw: str, workdir: str) -> None:
    if enabled:
        STARTUP_DIR.mkdir(parents=True, exist_ok=True)
        script = (
            'Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.CurrentDirectory = "{workdir}"\r\n'
            f'sh.Run """{pythonw}"" -m sonorix", 0, False\r\n'
        )
        STARTUP_FILE.write_text(script, encoding="utf-16")
    elif STARTUP_FILE.exists():
        STARTUP_FILE.unlink()
