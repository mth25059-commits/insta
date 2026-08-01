"""
Eve v7 — SQLite layer. Poora brain isi ek file me rehta hai (Drive pe yahi
file gzip hokar jaati hai).

    from storage.database import get_connection, init_db
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import config

logger = logging.getLogger("eve.db")

_lock = threading.RLock()
_local = threading.local()

BASE_DDL = """
PRAGMA journal_mode=WAL;

-- Global key/value state (mode, tone, nicknames, admins, usage counters).
CREATE TABLE IF NOT EXISTS BOT_STATE (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Har Instagram message ka raw log — GC style learning yahi se hoti hai.
CREATE TABLE IF NOT EXISTS MESSAGES (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ig_message_id TEXT UNIQUE,
    thread_id     TEXT,
    thread_title  TEXT,
    ig_username   TEXT,
    ig_user_id    TEXT,
    text          TEXT,
    is_bot        INTEGER NOT NULL DEFAULT 0,
    replied       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON MESSAGES(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON MESSAGES(ig_username);

-- Thread ke members — naya banda aaye to intro poochhne ke liye.
CREATE TABLE IF NOT EXISTS THREAD_MEMBERS (
    thread_id   TEXT NOT NULL,
    ig_username TEXT NOT NULL,
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (thread_id, ig_username)
);
"""


def db_path() -> Path:
    p = Path(config.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """
    Thread-local connection + ek global write lock. SQLite multi-thread me
    'database is locked' na de isliye.
    """
    conn: Optional[sqlite3.Connection] = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn

    with _lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    """Idempotent — har boot pe call karo."""
    with get_connection() as conn:
        conn.executescript(BASE_DDL)
    logger.info("[DB] ready: %s", db_path())


def reset_thread_connection() -> None:
    """Drive se restore ke baad purani file handle band karni padti hai."""
    conn: Optional[sqlite3.Connection] = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


# --------------------------------------------------------------- helpers


def log_message(
    *,
    ig_message_id: str,
    thread_id: str,
    ig_username: str,
    text: str,
    thread_title: str = "",
    ig_user_id: str = "",
    is_bot: bool = False,
) -> bool:
    """Naya message save karo. False = duplicate (pehle se hai)."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO MESSAGES"
            " (ig_message_id, thread_id, thread_title, ig_username, ig_user_id,"
            "  text, is_bot) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(ig_message_id), str(thread_id), thread_title or None,
             (ig_username or "").lstrip("@").lower(), str(ig_user_id or ""),
             text or "", 1 if is_bot else 0),
        )
        return cur.rowcount > 0


def recent_messages(thread_id: str, limit: int = 12) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT ig_username, text, is_bot FROM MESSAGES WHERE thread_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (str(thread_id), int(limit)),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def is_new_member(thread_id: str, ig_username: str) -> bool:
    """Pehli baar dikha is thread me? True sirf ek hi baar aayega."""
    u = (ig_username or "").lstrip("@").lower()
    if not u or not thread_id:
        return False
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO THREAD_MEMBERS (thread_id, ig_username)"
            " VALUES (?, ?)",
            (str(thread_id), u),
        )
        return cur.rowcount > 0
