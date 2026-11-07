"""Panel web local en http://localhost:5000 (solo escucha en 127.0.0.1)."""
from __future__ import annotations

import csv
import io
import logging
import sys
import threading
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from . import recorder, transcriber, winutil
from .config import APP_DIR

STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


def create_app(core) -> Flask:
    app = Flask(__name__, static_folder=None)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.before_request
    def _guard():
        # Anti DNS-rebinding: solo aceptamos Host local.
        host = (request.host or "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            abort(403)
        # Anti CSRF: las mutaciones exigen una cabecera propia (fuerza preflight CORS).
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Sonorix") != "1":
            abort(403)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC, name)

    @app.get("/api/status")
    def status():
        return jsonify(core.status())

    @app.post("/api/pause")
    def pause():
        core.set_paused(bool((request.get_json(silent=True) or {}).get("paused", not core.paused)))
        return jsonify(core.status())

    @app.get("/api/stats")
    def stats():
        return jsonify(core.db.stats())

    @app.get("/api/history")
    def history():
        q = request.args.get("q", "").strip()
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
        return jsonify(core.db.list(q, limit, offset))

    @app.delete("/api/history/<int:item_id>")
    def delete_item(item_id):
        return jsonify({"ok": core.db.delete(item_id)})

    @app.delete("/api/history")
    def clear_history():
        if request.args.get("confirm") != "1":
            abort(400)
        return jsonify({"deleted": core.db.clear()})

    @app.post("/api/history/<int:item_id>/paste")
    def repaste(item_id):
        rows = [r for r in core.db.list(limit=1000)["items"] if r["id"] == item_id]
        if not rows:
            abort(404)
        winutil.paste_text(rows[0]["text"], "clipboard", restore=False)  # queda en el portapapeles
        return jsonify({"ok": True})

    @app.get("/api/export.csv")
    def export_csv():
        buf = io.StringIO()
        rows = core.db.all()
        fields = ["id", "created_at", "text", "raw_text", "duration", "words", "language",
                  "engine", "model", "app", "mode", "cleaned", "latency_ms"]
        w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=sonorix-historial.csv"})

    @app.get("/api/settings")
    def get_settings():
        data = core.settings.public()
        data["startup"] = winutil.startup_enabled()
        data["local_available"] = transcriber.local_available()
        return jsonify(data)

    @app.post("/api/settings")
    def post_settings():
        body = request.get_json(silent=True) or {}
        if "startup" in body:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            winutil.set_startup(bool(body.pop("startup")), str(pyw if pyw.exists() else sys.executable), str(APP_DIR))
        if body.get("groq_api_key") == "":
            body.pop("groq_api_key")  # vacío = no tocar
        data = core.settings.update(body)
        data["startup"] = winutil.startup_enabled()
        data["local_available"] = transcriber.local_available()
        return jsonify(data)

    @app.post("/api/settings/clear-key")
    def clear_key():
        core.settings.update({"groq_api_key": ""})
        return jsonify(core.settings.public())

    @app.post("/api/test-key")
    def test_key():
        key = ((request.get_json(silent=True) or {}).get("key") or core.settings.api_key).strip()
        if not key:
            return jsonify({"ok": False, "message": "No hay API key"})
        ok, msg = transcriber.test_key(key)
        return jsonify({"ok": ok, "message": msg})

    @app.post("/api/hotkey/capture")
    def capture_hotkey():
        name = core.hotkeys.capture_next_key(timeout=8)
        return jsonify({"key": name})

    @app.get("/api/mobile")
    def mobile_info():
        return jsonify(core.mobile.info())

    @app.get("/api/mobile/qr.svg")
    def mobile_qr():
        svg = core.mobile.qr_svg()
        if not svg:
            abort(404)
        return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})

    @app.post("/api/mobile/regenerate")
    def mobile_regen():
        core.mobile.regenerate_token()  # desempareja todos los celulares
        return jsonify(core.mobile.info())

    @app.get("/api/devices")
    def devices():
        return jsonify(recorder.list_input_devices())

    return app


def serve(core, port: int) -> threading.Thread:
    from werkzeug.serving import make_server

    app = create_app(core)
    server = make_server("127.0.0.1", port, app, threaded=True)
    t = threading.Thread(target=server.serve_forever, name="sonorix-web", daemon=True)
    t.start()
    core.web_server = server
    return t
