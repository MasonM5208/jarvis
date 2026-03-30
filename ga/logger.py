"""
ga/logger.py — Persistent inference logging for GA fitness signals.
"""
import sqlite3
import time
import uuid
from pathlib import Path
from logger import get_logger

log = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "ga_logs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS inference_logs (
    id                   TEXT PRIMARY KEY,
    genome_id            TEXT NOT NULL DEFAULT 'default',
    session_id           TEXT,
    query_class          TEXT NOT NULL DEFAULT 'general',
    message              TEXT,
    response             TEXT,
    tool_calls_made      INTEGER DEFAULT 0,
    tool_calls_succeeded INTEGER DEFAULT 0,
    latency_ms           INTEGER,
    tokens_used          INTEGER,
    thumbs_up            INTEGER,   -- NULL=no feedback, 1=positive, 0=negative
    task_completed       INTEGER,   -- NULL=unknown, 1=yes, 0=no
    timestamp            REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_genome_id  ON inference_logs(genome_id);
CREATE INDEX IF NOT EXISTS idx_query_class ON inference_logs(query_class);
CREATE INDEX IF NOT EXISTS idx_timestamp  ON inference_logs(timestamp);
"""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


class GALogger:
    """Records inference events and explicit feedback for GA fitness scoring."""

    def log_inference(
        self,
        *,
        session_id: str,
        message: str,
        response: str,
        latency_ms: int,
        tool_calls_made: int = 0,
        tool_calls_succeeded: int = 0,
        tokens_used: int = 0,
        genome_id: str = "default",
        query_class: str = "general",
    ) -> str:
        """Insert one inference record. Returns the log entry ID."""
        entry_id = str(uuid.uuid4())[:12]
        with _conn() as c:
            c.execute(
                """INSERT INTO inference_logs
                   (id, genome_id, session_id, query_class, message, response,
                    tool_calls_made, tool_calls_succeeded, latency_ms, tokens_used, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id, genome_id, session_id, query_class,
                    message[:500], response[:500],
                    tool_calls_made, tool_calls_succeeded,
                    latency_ms, tokens_used,
                    time.time(),
                ),
            )
        log.debug("ga_log", entry_id=entry_id, genome_id=genome_id, latency_ms=latency_ms)
        return entry_id

    def record_feedback(self, session_id: str, positive: bool) -> bool:
        """Tag the most recent inference for a session with thumbs up/down."""
        with _conn() as c:
            cur = c.execute(
                """UPDATE inference_logs SET thumbs_up = ?
                   WHERE session_id = ?
                   AND id = (
                       SELECT id FROM inference_logs
                       WHERE session_id = ?
                       ORDER BY timestamp DESC LIMIT 1
                   )""",
                (1 if positive else 0, session_id, session_id),
            )
            updated = cur.rowcount > 0
        log.info("ga_feedback", session_id=session_id, positive=positive, updated=updated)
        return updated

    def get_logs_for_genome(self, genome_id: str, limit: int = 100) -> list[dict]:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM inference_logs WHERE genome_id = ? ORDER BY timestamp DESC LIMIT ?",
                (genome_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent(self, limit: int = 50) -> list[dict]:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM inference_logs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# Module-level singleton
ga_logger = GALogger()
