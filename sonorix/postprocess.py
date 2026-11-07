"""Post-procesado: alucinaciones de Whisper, comandos de voz y diccionario."""
from __future__ import annotations

import re

# Frases que Whisper inventa sobre silencio/ruido.
HALLUCINATIONS = {
    "subtítulos realizados por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "gracias por ver",
    "¡gracias por ver el video!",
    "suscríbete al canal",
    "thank you for watching",
    "thanks for watching",
    "thanks for watching!",
    "you",
    "...",
}


def strip_hallucinations(text: str) -> str:
    norm = text.strip().lower().strip(" .!¡¿?")
    if norm in {h.strip(" .!¡¿?") for h in HALLUCINATIONS}:
        return ""
    text = re.sub(r"\s*Subtítulos (realizados )?por la comunidad de Amara\.org\.?", "", text, flags=re.I)
    return text.strip()


_P = r"[\s,.;:]*"
COMMANDS: list[tuple[re.Pattern, str]] = [
    (re.compile(_P + r"\b(nuevo p[aá]rrafo|new paragraph)\b" + _P, re.I), "\n\n"),
    (re.compile(_P + r"\b(punto y aparte)\b" + _P, re.I), ".\n"),
    (re.compile(_P + r"\b(nueva l[ií]nea|salto de l[ií]nea|new line)\b" + _P, re.I), "\n"),
    (re.compile(r"\s*\b(abre(?:r)? interrogaci[oó]n)\b\s*", re.I), " ¿"),
    (re.compile(r"\s*\b(cierra(?:r)? interrogaci[oó]n)\b[\s.,]*", re.I), "? "),
    (re.compile(r"\s*\b(dos puntos)\b[\s.,]*", re.I), ": "),
    (re.compile(r"\s*\b(punto y coma)\b[\s.,]*", re.I), "; "),
    (re.compile(r"\s*\b(signo de exclamaci[oó]n)\b[\s.,]*", re.I), "! "),
]


def _capitalize_after_breaks(text: str) -> str:
    return re.sub(r"(^|\n|[.!?¿¡]\s+)([a-záéíóúñ])", lambda m: m.group(1) + m.group(2).upper(), text)


def apply_voice_commands(text: str) -> str:
    out = text
    for pat, rep in COMMANDS:
        out = pat.sub(rep, out)
    if out != text:
        out = re.sub(r"[ \t]+\n", "\n", out)
        out = re.sub(r"\n[ \t]+", "\n", out)
        out = re.sub(r" {2,}", " ", out)
        out = _capitalize_after_breaks(out.strip(" "))
    return out


def apply_replacements(text: str, replacements: dict) -> str:
    for said, written in (replacements or {}).items():
        said = (said or "").strip()
        if not said:
            continue
        text = re.sub(rf"(?<!\w){re.escape(said)}(?!\w)", written.replace("\\", "\\\\"), text, flags=re.I)
    return text


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
