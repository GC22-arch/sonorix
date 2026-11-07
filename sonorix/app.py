"""Orquestador: atajo → grabación → transcripción → limpieza → pegado → historial."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import sounddevice as sd

from . import postprocess, recorder, transcriber, winutil
from .config import DB_PATH, Settings
from .db import Database
from .hotkey import HotkeyController

log = logging.getLogger("sonorix")


class Core:
    def __init__(self, overlay_show=lambda *a, **k: None):
        self.settings = Settings()
        self.db = Database(DB_PATH)
        self.show = overlay_show
        self.recorder = recorder.Recorder(device=self.settings.mic_device)
        self.paused = False
        self.busy = False
        self.web_server = None
        self.mobile = None
        self._jobs: "queue.Queue[tuple]" = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sonorix-tx")
        self._target_app = ""
        self._handsfree = False
        self._session = 0
        self._privacy_opened = False
        self.hotkeys = HotkeyController(
            self.settings,
            on_start=lambda hf: self._jobs.put(("start", hf)),
            on_stop=lambda: self._jobs.put(("stop", None)),
            on_cancel=lambda why: self._jobs.put(("cancel", why)),
        )
        self.settings.on_change(self._on_settings_changed)
        self._tones = {
            "start": recorder.tone(880, 60),
            "stop": recorder.tone(620, 60),
            "error": recorder.tone(240, 160),
        }

    # -- ciclo de vida ------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._worker, name="sonorix-core", daemon=True).start()
        self.hotkeys.start()
        log.info("Sonorix listo. Atajo: %s", self.settings.hotkey)

    def shutdown(self) -> None:
        self.hotkeys.stop()
        self.recorder.stop()
        if self.web_server:
            self.web_server.shutdown()
        if self.mobile:
            self.mobile.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def status(self) -> dict:
        return {
            "paused": self.paused,
            "recording": self.recorder.recording,
            "busy": self.busy,
            "hotkey": self.settings.hotkey,
            "engine": self.settings.engine,
            "has_api_key": bool(self.settings.api_key),
            "local_available": transcriber.local_available(),
            "mobile": self.mobile.info() if self.mobile else None,
        }

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.hotkeys.enabled = not paused
        if paused:
            self._jobs.put(("cancel", "pause"))
        self.show("info", "Sonorix en pausa" if paused else "Sonorix activo")

    def _on_settings_changed(self, changed: set) -> None:
        if "hotkey" in changed:
            self.hotkeys.rebind(self.settings.hotkey)
        if "mic_device" in changed:
            self.recorder.device = self.settings.mic_device
        if changed & {"mobile_enabled", "mobile_port"} and self.mobile:
            self.mobile.sync()

    def _beep(self, name: str) -> None:
        if self.settings.sounds:
            try:
                sd.play(self._tones[name], 44_100)
            except Exception:  # noqa: BLE001
                pass

    # -- hilo de control ---------------------------------------------
    def _worker(self) -> None:
        while True:
            kind, arg = self._jobs.get()
            try:
                if kind == "start":
                    self._start_recording(arg)
                elif kind == "stop":
                    self._stop_recording()
                elif kind == "cancel":
                    if arg != "tap":
                        log.info("Grabación cancelada (%s)", arg)
                    self._session += 1
                    self.recorder.stop()
                    self.show("hidden")
            except Exception as exc:  # noqa: BLE001
                log.exception("Error en %s", kind)
                self.hotkeys.force_idle()
                self.recorder.stop()
                self._error(str(exc) or type(exc).__name__)

    def _start_recording(self, handsfree: bool) -> None:
        if self.paused:
            return
        self._handsfree = handsfree
        self._target_app = winutil.foreground_app()
        if not self.recorder.recording:
            try:
                self.recorder.start()
            except Exception as exc:  # noqa: BLE001
                self.hotkeys.force_idle()
                if winutil.microphone_blocked():
                    if not self._privacy_opened:
                        self._privacy_opened = True
                        os.startfile("ms-settings:privacy-microphone")
                    raise RuntimeError("Windows bloquea el micrófono: actívalo en Privacidad → Micrófono") from exc
                raise RuntimeError(f"No pude abrir el micrófono: {exc}") from exc
        self._session += 1
        session = self._session
        if handsfree:
            self.show("recording", handsfree=True)
            self._beep("start")
        else:
            # Esperamos un poco antes de mostrar la píldora: un toque suelto no debe parpadear.
            def _reveal():
                if self._session == session and self.recorder.recording:
                    self.show("recording", handsfree=False)
            threading.Timer(float(self.settings.tap_max), _reveal).start()

    def _stop_recording(self) -> None:
        self._session += 1
        audio = self.recorder.stop()
        if audio is None:
            return
        duration = audio.size / recorder.SAMPLE_RATE
        if duration < float(self.settings.min_duration):
            self.show("hidden")
            return
        if self._handsfree:
            self._beep("stop")
        ratio = recorder.speech_ratio(audio)
        log.info("Grabación %.1f s · nivel %.4f · voz %.0f%%", duration, recorder.rms(audio), ratio * 100)
        if ratio < 0.03:
            self.show("info", "No se escuchó voz · acércate al micrófono")
            return
        audio = recorder.normalize(audio)
        self.show("processing", "Transcribiendo…")
        mode = "manos libres" if self._handsfree else "mantener"
        self._pool.submit(self._process_safe, audio, duration, self._target_app, mode)

    # -- pipeline -----------------------------------------------------
    def _error(self, msg: str) -> None:
        log.error(msg)
        self._beep("error")
        self.show("error", msg[:90])

    def _process_safe(self, audio, duration, app, mode) -> None:
        self.busy = True
        try:
            result = self.transcribe(audio, duration=duration)
            if not result["text"]:
                log.info("Transcripción vacía (motor %s)", result["engine"])
                self.show("info", "No se escuchó voz")
                return
            text = result["text"]
            if self.settings.trailing_space and not text.endswith(("\n", " ")):
                text += " "
            winutil.paste_text(text, self.settings.paste_method, self.settings.restore_clipboard)
            self._save(result, duration=duration, app=app, mode=mode)
            self.show("done", f"{result['words']} palabras · {result['latency_ms'] / 1000:.1f} s")
        except transcriber.TranscriptionError as exc:
            self._error(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo transcribiendo")
            self._error(f"Error: {exc}")
        finally:
            self.busy = False

    def transcribe(self, audio, *, duration: float, filename: str = "", mime: str = "") -> dict:
        """audio: np.ndarray int16 16 kHz, o bytes ya codificados (celular)."""
        s = self.settings
        t0 = time.perf_counter()
        key = s.api_key
        engine = s.engine
        has_local = transcriber.local_available()
        if engine in ("groq", "auto") and not key:
            if has_local:
                engine = "local"
            else:
                raise transcriber.TranscriptionError("Falta tu API key gratis de Groq → abre localhost:5000")
        raw = None
        if engine in ("groq", "auto"):
            if isinstance(audio, (bytes, bytearray)):
                data, fname, ftype = bytes(audio), filename or "audio.webm", mime or "audio/webm"
            else:
                data, fname, ftype = recorder.encode(audio)
            try:
                raw = transcriber.transcribe_groq(data, fname, ftype, api_key=key, model=s.groq_model,
                                                  language=s.language, prompt=s.vocabulary)
                engine, model = "groq", s.groq_model
            except transcriber.TranscriptionError as exc:
                if not (engine == "auto" and exc.retryable and has_local):
                    raise
                log.info("Groq no disponible (%s) → motor local", exc)
                self.show("processing", "Local (sin cupo/red)…")
                engine = "local"
        if raw is None:
            raw = transcriber.transcribe_local(audio, model_size=s.local_model,
                                               language=s.language, prompt=s.vocabulary)
            engine, model = "local", f"faster-whisper/{s.local_model}"

        text = postprocess.strip_hallucinations(raw)
        cleaned = False
        if text and s.ai_cleanup and key and postprocess.word_count(text) >= 4:
            try:
                new = transcriber.cleanup_text(text, api_key=key, model=s.cleanup_model,
                                               style=s.cleanup_style, vocabulary=s.vocabulary)
                cleaned = new != text
                text = new
            except Exception as exc:  # noqa: BLE001 - la limpieza es opcional
                log.warning("Limpieza IA falló: %s", exc)
        if text and s.voice_commands:
            text = postprocess.apply_voice_commands(text)
        if text:
            text = postprocess.apply_replacements(text, s.replacements)
        return {
            "text": text.strip(" "),
            "raw": raw,
            "engine": engine,
            "model": model,
            "cleaned": cleaned,
            "words": postprocess.word_count(text),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    def _save(self, result: dict, *, duration: float, app: str, mode: str) -> int:
        return self.db.add(
            text=result["text"], raw_text=result["raw"], duration=round(duration, 2),
            words=result["words"], language=self.settings.language or "auto",
            engine=result["engine"], model=result["model"], app=app, mode=mode,
            cleaned=int(result["cleaned"]), latency_ms=result["latency_ms"],
        )

    # -- celular ------------------------------------------------------
    def transcribe_upload(self, data: bytes, filename: str, mime: str, duration: float) -> dict:
        self.busy = True
        try:
            result = self.transcribe(data, duration=duration, filename=filename, mime=mime)
            if result["text"]:
                pasted = False
                if self.settings.mobile_paste_pc:
                    t = result["text"] + (" " if self.settings.trailing_space else "")
                    winutil.paste_text(t, self.settings.paste_method, self.settings.restore_clipboard)
                    pasted = True
                    self.show("done", f"📱 {result['words']} palabras")
                result["id"] = self._save(result, duration=duration, app="celular", mode="celular")
                result["pasted_pc"] = pasted
            return result
        finally:
            self.busy = False
