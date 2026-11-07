"""Modo celular: PWA servida por HTTPS en la red local.

El navegador del celular solo permite usar el micrófono en contexto seguro,
así que generamos un certificado autofirmado (el celular avisará una vez).
El acceso exige un token de emparejado que viaja en el QR del panel.
"""
from __future__ import annotations

import datetime as dt
import hmac
import ipaddress
import logging
import secrets
import socket
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, make_response, redirect, request, send_from_directory

from .config import DATA_DIR

log = logging.getLogger("sonorix.mobile")
STATIC = Path(__file__).parent / "static" / "mobile"
CERT = DATA_DIR / "mobile-cert.pem"
KEY = DATA_DIR / "mobile-key.pem"
COOKIE = "sonorix_t"
MAX_UPLOAD = 25 * 1024 * 1024


def lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def ensure_cert(ips: list[str]) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    if CERT.exists() and KEY.exists():
        try:
            cert = x509.load_pem_x509_certificate(CERT.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
            valid = cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
            if set(ips) <= have and valid:
                return
        except Exception:  # noqa: BLE001
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sonorix")])
    now = dt.datetime.now(dt.timezone.utc)
    alt = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    alt += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .sign(key, hashes.SHA256())
    )
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def create_mobile_app(core) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD

    def token() -> str:
        return core.settings.mobile_token

    def authed() -> bool:
        t = request.cookies.get(COOKIE) or request.headers.get("X-Sonorix-Token") or ""
        return bool(token()) and hmac.compare_digest(t, token())

    @app.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.get("/")
    def index():
        t = request.args.get("t")
        if t:
            if not hmac.compare_digest(t, token()):
                abort(403)
            resp = make_response(redirect("/", code=302))  # saca el token de la URL
            resp.set_cookie(COOKIE, t, max_age=60 * 60 * 24 * 400, secure=True, httponly=True, samesite="Strict")
            return resp
        if not authed():
            return send_from_directory(STATIC, "pair.html"), 401
        return send_from_directory(STATIC, "index.html")

    # Recursos públicos (no revelan nada): manifest, sw, icono.
    @app.get("/manifest.webmanifest")
    def manifest():
        r = send_from_directory(STATIC, "manifest.webmanifest")
        r.headers["Content-Type"] = "application/manifest+json"
        return r

    @app.get("/sw.js")
    def sw():
        r = send_from_directory(STATIC, "sw.js")
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.get("/icon.svg")
    def icon():
        return send_from_directory(STATIC.parent, "icon.svg")

    @app.get("/api/me")
    def me():
        if not authed():
            abort(401)
        s = core.settings
        return jsonify({"paste_pc": s.mobile_paste_pc, "language": s.language, "ai_cleanup": s.ai_cleanup,
                        "engine": s.engine, "has_api_key": bool(s.api_key)})

    @app.post("/api/prefs")
    def prefs():
        if not authed():
            abort(401)
        body = request.get_json(silent=True) or {}
        allowed = {k: body[k] for k in ("mobile_paste_pc", "ai_cleanup") if k in body}
        core.settings.update(allowed)
        return jsonify({"ok": True})

    @app.post("/api/transcribe")
    def transcribe():
        if not authed():
            abort(401)
        f = request.files.get("audio")
        if not f:
            abort(400)
        data = f.read()
        if len(data) < 1000:
            return jsonify({"text": "", "words": 0})
        duration = float(request.form.get("duration", 0) or 0)
        mime = (f.mimetype or "audio/webm").split(";")[0]
        ext = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/mpeg": "mp3",
               "audio/x-m4a": "m4a", "audio/wav": "wav"}.get(mime, "webm")
        try:
            result = core.transcribe_upload(data, f"audio.{ext}", mime, duration)
        except Exception as exc:  # noqa: BLE001
            log.warning("Transcripción móvil falló: %s", exc)
            return jsonify({"error": str(exc)[:160]}), 502
        return jsonify({k: result.get(k) for k in ("text", "words", "latency_ms", "cleaned", "pasted_pc", "id")})

    @app.get("/api/history")
    def history():
        if not authed():
            abort(401)
        return jsonify(core.db.list("", 20, 0))

    return app


class MobileServer:
    def __init__(self, core):
        self.core = core
        self._server = None
        self._thread = None
        self.error = ""
        self.ips: list[str] = []
        self._lock = threading.Lock()

    def ensure_token(self) -> str:
        if not self.core.settings.mobile_token:
            self.core.settings.update({"mobile_token": secrets.token_urlsafe(24)})
        return self.core.settings.mobile_token

    def regenerate_token(self) -> str:
        self.core.settings.update({"mobile_token": secrets.token_urlsafe(24)})
        return self.core.settings.mobile_token

    def sync(self) -> None:
        with self._lock:
            want = bool(self.core.settings.mobile_enabled)
            if self._server and (not want or self._server.port != int(self.core.settings.mobile_port)):
                self._stop_locked()
            if want and not self._server:
                self._start_locked()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    def _start_locked(self) -> None:
        from werkzeug.serving import make_server

        self.error = ""
        try:
            self.ensure_token()
            self.ips = lan_ips()
            ensure_cert(self.ips)
            port = int(self.core.settings.mobile_port)
            srv = make_server("0.0.0.0", port, create_mobile_app(self.core), threaded=True,
                              ssl_context=(str(CERT), str(KEY)))
            self._server = srv
            self._thread = threading.Thread(target=srv.serve_forever, name="sonorix-mobile", daemon=True)
            self._thread.start()
            log.info("Modo celular en https://%s:%s", self.ips[0] if self.ips else "?", port)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            log.exception("No pude iniciar el modo celular")

    def info(self) -> dict:
        running = self._server is not None
        port = int(self.core.settings.mobile_port)
        ip = self.ips[0] if self.ips else None
        url = f"https://{ip}:{port}/?t={self.core.settings.mobile_token}" if running and ip else None
        return {"enabled": bool(self.core.settings.mobile_enabled), "running": running, "ips": self.ips,
                "port": port, "error": self.error, "pair_url": url}

    def qr_svg(self) -> str:
        info = self.info()
        if not info["pair_url"]:
            return ""
        import qrcode
        import qrcode.image.svg

        img = qrcode.make(info["pair_url"], image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        return img.to_string(encoding="unicode")
