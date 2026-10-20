"""SQLite: görülen ilanlar, skorlar ve durumlar."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.config import path
from app.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    fingerprint TEXT,
    source      TEXT,
    title       TEXT,
    company     TEXT,
    location    TEXT,
    url         TEXT,
    description TEXT,
    extra       TEXT,
    status      TEXT DEFAULT 'new',   -- new | scored | notified | skipped | below
    score       INTEGER,
    match_json  TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_fp ON jobs(fingerprint);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(path("database"))
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def is_seen(job: Job) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM jobs WHERE id = ? OR fingerprint = ? LIMIT 1", (job.id, job.fingerprint)
        ).fetchone()
        return row is not None


def add(job: Job) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO jobs (id, fingerprint, source, title, company, location, url,"
            " description, extra, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                job.id, job.fingerprint, job.source, job.title, job.company, job.location,
                job.url, job.description, json.dumps(job.extra, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def set_status(job_id: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))


def set_match(job_id: str, score: int, match: dict, status: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE jobs SET score = ?, match_json = ?, status = ? WHERE id = ?",
            (score, json.dumps(match, ensure_ascii=False), status, job_id),
        )


def get(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def by_status(status: str) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs WHERE status = ?", (status,))]


def stats() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}


def reevaluate_threshold(threshold: int) -> int:
    """Eşik değiştiğinde 'below' kalmış ama yeni eşiği geçen staj ilanlarını 'scored' (bildirilecek) yapar."""
    promoted = 0
    with _conn() as c:
        rows = c.execute(
            "SELECT id, match_json FROM jobs WHERE status = 'below' AND score >= ? AND match_json IS NOT NULL",
            (threshold,),
        ).fetchall()
        for r in rows:
            m = json.loads(r["match_json"])
            if m.get("is_internship"):
                c.execute("UPDATE jobs SET status = 'scored' WHERE id = ?", (r["id"],))
                promoted += 1
    return promoted


def top_jobs(min_sc: int, limit: int = 10) -> list[dict]:
    """Son taranan ilanlar arasından eşik üstü en yüksek puanlı staj ilanlarını döner."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM jobs WHERE score >= ? AND match_json IS NOT NULL AND status != 'skipped' "
            "ORDER BY score DESC LIMIT ?",
            (min_sc, limit * 2),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if json.loads(d["match_json"]).get("is_internship"):
            out.append(d)
            if len(out) >= limit:
                break
    return out

