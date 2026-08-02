"""
Eve v7 — people/profile layer.

Har IG user ka seekha hua profile: kitne msg, kaisa tone, gaali karta hai ya
nahi, last kab dikha. Panel memory (manual) + ye auto-learning dono milkar
bot ko banda pehchanwate hain.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from storage.database import get_connection

DDL = """
CREATE TABLE IF NOT EXISTS PEOPLE (
    ig_username  TEXT PRIMARY KEY,
    ig_user_id   TEXT,
    display_name TEXT,
    gender       TEXT,
    note         TEXT,
    msg_count    INTEGER NOT NULL DEFAULT 0,
    abuse_count  INTEGER NOT NULL DEFAULT 0,
    avg_words    REAL NOT NULL DEFAULT 0,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_ABUSE = re.compile(
    r"\b(bsdk|mc|bc|chutiy\w*|randi|lund|gandu|loda|jhaat|madarch\w*|"
    r"behenc\w*|gaand|harami|kutt[ae])\b", re.I)


def init() -> None:
    with get_connection() as conn:
        conn.executescript(DDL)


def _norm(u: str) -> str:
    return (u or "").strip().lstrip("@").lower()


def touch(username: str, text: str = "", ig_user_id: str = "") -> None:
    """Har message pe call — profile update ho jaata hai."""
    u = _norm(username)
    if not u:
        return
    words = len((text or "").split())
    abusive = 1 if _ABUSE.search(text or "") else 0
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO PEOPLE (ig_username, ig_user_id, msg_count,"
            " abuse_count, avg_words) VALUES (?, ?, 1, ?, ?)"
            " ON CONFLICT(ig_username) DO UPDATE SET"
            "  ig_user_id  = COALESCE(NULLIF(excluded.ig_user_id, ''), PEOPLE.ig_user_id),"
            "  msg_count   = PEOPLE.msg_count + 1,"
            "  abuse_count = PEOPLE.abuse_count + ?,"
            "  avg_words   = (PEOPLE.avg_words * PEOPLE.msg_count + ?)"
            "                / (PEOPLE.msg_count + 1),"
            "  last_seen   = datetime('now')",
            (u, str(ig_user_id or ""), abusive, float(words), abusive, float(words)),
        )


def set_profile(username: str, *, display_name: str = "", gender: str = "",
                note: str = "") -> None:
    u = _norm(username)
    if not u:
        return
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO PEOPLE (ig_username, display_name, gender, note)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(ig_username) DO UPDATE SET"
            "  display_name = COALESCE(NULLIF(excluded.display_name,''), PEOPLE.display_name),"
            "  gender       = COALESCE(NULLIF(excluded.gender,''), PEOPLE.gender),"
            "  note         = COALESCE(NULLIF(excluded.note,''), PEOPLE.note)",
            (u, display_name, gender, note),
        )


def get(username: str) -> Dict[str, Any]:
    u = _norm(username)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM PEOPLE WHERE ig_username = ?", (u,)
        ).fetchone()
    return dict(row) if row else {}


def msg_count(username: str) -> int:
    try:
        return int(get(username).get("msg_count") or 0)
    except Exception:
        return 0


def all_people(limit: int = 200) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM PEOPLE ORDER BY msg_count DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]


def profile_block(username: str) -> str:
    """System prompt me chipkane wala chhota profile."""
    p = get(username)
    if not p:
        return ""
    bits = [f"@{p['ig_username']}"]
    if p.get("display_name"):
        bits.append(f"naam {p['display_name']}")
    if p.get("gender"):
        bits.append(str(p["gender"]))
    if p.get("note"):
        bits.append(str(p["note"]))
    style = "gaali-baaz" if p.get("abuse_count", 0) >= 3 else "normal"
    bits.append(f"style: {style}, msgs: {p.get('msg_count', 0)}")
    return "USER PROFILE: " + ", ".join(bits)
