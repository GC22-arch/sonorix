"""Captura de micrófono a 16 kHz mono (lo que Whisper quiere de verdad)."""
from __future__ import annotations

import io
import threading
import time
import wave

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
BLOCK = 800  # 50 ms


class Recorder:
    def __init__(self, device=None):
        self.device = device
        self.level = 0.0          # RMS suavizado 0..1, lo lee la superposición
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self.started_at = 0.0

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                return
            self._frames = []
            self.level = 0.0
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=BLOCK,
                device=self.device,
                callback=self._callback,
            )
            stream.start()
            self._stream = stream
            self.started_at = time.time()

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        self._frames.append(indata.copy())
        x = indata.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x)))
        # ataque rápido, caída suave
        self.level = rms if rms > self.level else self.level * 0.6 + rms * 0.4

    def stop(self) -> np.ndarray | None:
        with self._lock:
            stream, self._stream = self._stream, None
        if stream is None:
            return None
        try:
            stream.stop()
        finally:
            stream.close()
        self.level = 0.0
        if not self._frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(self._frames).reshape(-1)


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    x = audio.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(x * x)))


def _block_energy(audio: np.ndarray, ms: int = 30) -> np.ndarray:
    win = int(SAMPLE_RATE * ms / 1000)
    n = audio.size // win
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    blocks = audio[: n * win].astype(np.float32).reshape(n, win) / 32768.0
    return np.sqrt(np.mean(blocks * blocks, axis=1))


def speech_ratio(audio: np.ndarray) -> float:
    """Fracción de bloques de 30 ms con voz. El umbral se adapta al ruido de
    fondo de cada micrófono (los de laptop suelen captar muy bajo)."""
    e = _block_energy(audio)
    if e.size == 0:
        return 0.0
    floor = float(np.percentile(e, 20))
    threshold = max(0.0015, floor * 3.0)
    return float(np.mean(e > threshold))


def normalize(audio: np.ndarray, target_peak: float = 0.85, max_gain: float = 12.0) -> np.ndarray:
    """Sube el volumen de grabaciones bajas (sin saturar) para que Whisper entienda mejor."""
    if audio.size == 0:
        return audio
    peak = float(np.percentile(np.abs(audio.astype(np.float32)), 99.9)) / 32768.0
    if peak <= 0 or peak >= target_peak:
        return audio
    gain = min(max_gain, target_peak / peak)
    if gain <= 1.05:
        return audio
    return np.clip(audio.astype(np.float32) * gain, -32767, 32767).astype(np.int16)


def encode(audio: np.ndarray) -> tuple[bytes, str, str]:
    """FLAC si hay soundfile (≈40% del tamaño), si no WAV."""
    try:
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="FLAC", subtype="PCM_16")
        return buf.getvalue(), "audio.flac", "audio/flac"
    except Exception:  # noqa: BLE001
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(audio.tobytes())
        return buf.getvalue(), "audio.wav", "audio/wav"


def list_input_devices() -> list[dict]:
    out = []
    try:
        default_in = sd.default.device[0]
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                api = sd.query_hostapis(d["hostapi"])["name"]
                # MME remuestrea a 16 kHz sin quejarse; WASAPI compartido no.
                if api != "MME" or "mapper" in d["name"].lower() or "asignador" in d["name"].lower():
                    continue
                out.append({"index": i, "name": d["name"], "api": api, "default": i == default_in})
    except Exception:  # noqa: BLE001
        pass
    return out


def tone(freq: float, ms: int = 70, volume: float = 0.18, sr: int = 44_100) -> np.ndarray:
    t = np.linspace(0, ms / 1000, int(sr * ms / 1000), endpoint=False)
    env = np.minimum(1, np.minimum(t, t[::-1]) / 0.012)  # fade in/out
    return (np.sin(2 * np.pi * freq * t) * env * volume).astype(np.float32)
