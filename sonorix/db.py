"""Historial de transcripciones en SQLite."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    raw_text    TEXT,
    duration    REAL    NOT NULL DEFAULT 0,
    words       INTEGER NOT NULL DEFAULT 0,
    language    TEXT,
    engine      TEXT,
    model       TEXT,
    app         TEXT,
    mode        TEXT,
    cleaned     INTEGER NOT NULL DEFAULT 0,
    latency_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tr_created ON transcriptions(created_at);
"""

TYPING_WPM = 40          # velocidad media tecleando
GROQ_USD_PER_HOUR = 0.04  # whisper-large-v3-turbo (mínimo facturable 10 s por petición)


class Database:
    def __init__(self, path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def add(self, **row) -> int:
        row.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        with self._lock:
            cur = self._conn.execute(f"INSERT INTO transcriptions ({cols}) VALUES ({qs})", tuple(row.values()))
            self._conn.commit()
            return cur.lastrowid

    def list(self, q: str = "", limit: int = 50, offset: int = 0) -> dict:
        where, args = "", []
        if q:
            where = "WHERE text LIKE ? OR app LIKE ?"
            args = [f"%{q}%", f"%{q}%"]
        with self._lock:
            total = self._conn.execute(f"SELECT COUNT(*) FROM transcriptions {where}", args).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM transcriptions {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM transcriptions ORDER BY id")]

    def last(self) -> dict | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM transcriptions ORDER BY id DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def delete(self, item_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM transcriptions WHERE id = ?", (item_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def clear(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM transcriptions")
            self._conn.commit()
            return cur.rowcount

    def stats(self) -> dict:
        with self._lock:
            c = self._conn
            agg = c.execute(
                """SELECT COUNT(*) n, COALESCE(SUM(words),0) w, COALESCE(SUM(duration),0) d,
                          COALESCE(AVG(latency_ms),0) lat,
                          COALESCE(SUM(CASE WHEN engine='groq' THEN MAX(duration,10) ELSE 0 END),0) billed
                   FROM transcriptions"""
            ).fetchone()
            today = datetime.now().date()
            start = (today - timedelta(days=13)).isoformat()
            daily_rows = c.execute(
                """SELECT substr(created_at,1,10) day, SUM(words) w, COUNT(*) n FROM transcriptions
                   WHERE created_at >= ? GROUP BY day""",
                (start,),
            ).fetchall()
            apps = c.execute(
                """SELECT CASE WHEN instr(app,' · ')>0 THEN substr(app,1,instr(app,' · ')-1) ELSE app END a,
                          COUNT(*) n, SUM(words) w
                   FROM transcriptions WHERE app IS NOT NULL AND app != ''
                   GROUP BY a ORDER BY w DESC LIMIT 6"""
            ).fetchall()
            days_used = {r[0] for r in c.execute("SELECT DISTINCT substr(created_at,1,10) FROM transcriptions")}
            today_words = c.execute(
                "SELECT COALESCE(SUM(words),0) FROM transcriptions WHERE substr(created_at,1,10)=?",
                (today.isoformat(),),
            ).fetchone()[0]

        by_day = {r["day"]: (r["w"], r["n"]) for r in daily_rows}
        daily = []
        for i in range(13, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            w, n = by_day.get(d, (0, 0))
            daily.append({"day": d, "words": w or 0, "count": n or 0})

        streak, d = 0, today
        if d.isoformat() not in days_used:
            d -= timedelta(days=1)
        while d.isoformat() in days_used:
            streak += 1
            d -= timedelta(days=1)

        words, seconds = agg["w"], agg["d"]
        typing_s = words / TYPING_WPM * 60
        return {
            "count": agg["n"],
            "words": words,
            "today_words": today_words,
            "audio_seconds": round(seconds, 1),
            "wpm": round(words / (seconds / 60), 0) if seconds > 5 else 0,
            "saved_seconds": round(max(0.0, typing_s - seconds), 0),
            "avg_latency_ms": round(agg["lat"] or 0),
            "est_cost_usd": round(agg["billed"] / 3600 * GROQ_USD_PER_HOUR, 4),
            "streak": streak,
            "daily": daily,
            "apps": [{"app": r["a"], "count": r["n"], "words": r["w"]} for r in apps],
        }
