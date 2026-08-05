"""
Eve v7 — LONG TERM MEMORY (per user).

Bot ko yaad rehna chahiye ki kisne kya bataya — naam, ex, kaam, pasand, dukh.
Do tarike se yaad rakhta hai:

  1) regex se turant (naam, ex, padhai, city, pasand)
  2) reply ke baad ek sasta LLM call jo exchange se 1-2 fact nikaal ke rakh de

    user_facts.learn(username, text)          -> regex facts
    user_facts.learn_async(username, convo)   -> LLM facts (background)
    user_facts.block(username)                -> prompt me daalne wala text
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Dict, List, Optional

from storage import database

logger = logging.getLogger("eve.facts")

MAX_FACTS = 25          # per user
_LOCK = threading.Lock()

DDL = """
CREATE TABLE IF NOT EXISTS USER_FACTS (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ig_username TEXT NOT NULL,
    fact_key    TEXT NOT NULL,
    fact_value  TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (ig_username, fact_key)
);
CREATE INDEX IF NOT EXISTS idx_user_facts_u ON USER_FACTS(ig_username);
"""


def init() -> None:
    with database.get_connection() as c:
        c.executescript(DDL)


def _u(username: str) -> str:
    return (username or "").lstrip("@").lower().strip()


def remember(username: str, key: str, value: str) -> None:
    u, key = _u(username), (key or "").strip().lower()
    value = (value or "").strip()
    if not u or not key or not value or len(value) > 200:
        return
    try:
        with database.get_connection() as c:
            c.execute(
                "INSERT INTO USER_FACTS (ig_username, fact_key, fact_value,"
                " updated_at) VALUES (?, ?, ?, datetime('now'))"
                " ON CONFLICT(ig_username, fact_key) DO UPDATE SET"
                " fact_value = excluded.fact_value, updated_at = datetime('now')",
                (u, key, value))
            # purane extra facts hata do (naye 25 hi rakho)
            c.execute(
                "DELETE FROM USER_FACTS WHERE ig_username = ? AND id NOT IN ("
                " SELECT id FROM USER_FACTS WHERE ig_username = ?"
                " ORDER BY updated_at DESC, id DESC LIMIT ?)", (u, u, MAX_FACTS))
    except Exception:
        logger.debug("[FACTS] save fail", exc_info=True)


def facts(username: str) -> Dict[str, str]:
    u = _u(username)
    if not u:
        return {}
    try:
        with database.get_connection() as c:
            rows = c.execute(
                "SELECT fact_key, fact_value FROM USER_FACTS WHERE ig_username = ?"
                " ORDER BY updated_at DESC LIMIT ?", (u, MAX_FACTS)).fetchall()
        return {r["fact_key"]: r["fact_value"] for r in rows}
    except Exception:
        return {}


def block(username: str) -> str:
    f = facts(username)
    if not f:
        return ""
    lines = [f"- {k}: {v}" for k, v in f.items()]
    return (f"@{_u(username)} KE BAARE ME JO PEHLE PATA CHALA (ye yaad hai "
            "tujhe, isko dhyan me rakh ke baat kar, ulta mat poochh):\n"
            + "\n".join(lines))


def forget(username: str, key: str = "") -> int:
    u = _u(username)
    with database.get_connection() as c:
        if key:
            cur = c.execute("DELETE FROM USER_FACTS WHERE ig_username = ?"
                            " AND fact_key = ?", (u, key.lower()))
        else:
            cur = c.execute("DELETE FROM USER_FACTS WHERE ig_username = ?", (u,))
        return cur.rowcount


# ------------------------------------------------------- regex learning

_NAME = [
    re.compile(r"\b(?:mera|mere)\s+naam\s+([A-Za-z][A-Za-z ]{1,20}?)\s*(?:hai|h|he)?\b", re.I),
    re.compile(r"\bnaam\s+(?:to\s+)?([A-Za-z][A-Za-z]{1,18})\s+(?:hai|h|he)\b", re.I),
    re.compile(r"\b(?:my name is|i am|i'm|myself)\s+([A-Za-z][A-Za-z]{1,18})\b", re.I),
    re.compile(r"^([A-Za-z][a-z]{2,15})\s+naam\s+(?:hai|h)\b", re.I),
]
_STOPNAMES = {"kya", "nahi", "hai", "bhai", "yaar", "sorry", "good", "bad",
              "eve", "babu", "the", "a", "an", "not", "your", "tumhara"}

_PATTERNS = [
    ("padhai",  re.compile(r"\b(?:main|mai|me)\s+(\w+(?:\s+\w+)?)\s+(?:me|mein)\s+padh", re.I)),
    ("city",    re.compile(r"\b(?:main|mai|me)\s+([A-Za-z]{3,15})\s+(?:se|me|mein)\s+(?:hu|hoon|rehta|rehti)\b", re.I)),
    ("kaam",    re.compile(r"\b(?:main|mai)\s+([\w ]{3,25})\s+(?:ka kaam|job)\s+karta\b", re.I)),
    ("pasand",  re.compile(r"\bmujhe\s+([\w ]{3,25})\s+(?:pasand|acha lagta|achi lagti)\b", re.I)),
    ("nafrat",  re.compile(r"\bmujhe\s+([\w ]{3,25})\s+(?:pasand nahi|nafrat)\b", re.I)),
    ("mood",    re.compile(r"\b(?:mujhe|mai|main)\s+(?:apni|apne)?\s*(ex|breakup|gf|bf)\b.{0,25}(?:yaad|miss)", re.I)),
]


def learn(username: str, text: str) -> None:
    """Har incoming message pe — sasta, bina LLM ke."""
    t = (text or "").strip()
    if not t or len(t) > 400:
        return
    for rx in _NAME:
        m = rx.search(t)
        if m:
            name = m.group(1).strip().title()
            if name.lower() not in _STOPNAMES and len(name) >= 3:
                remember(username, "naam", name)
            break
    for key, rx in _PATTERNS:
        m = rx.search(t)
        if m:
            remember(username, key, m.group(1).strip())


# --------------------------------------------------------- LLM learning

_EXTRACT_SYS = (
    "Tu ek memory extractor hai. Diye gaye chat exchange me se user ke baare "
    "me PAKKI, kaam ki, lambe samay tak yaad rakhne layak baatein nikaal. "
    "Sirf JSON de: {\"facts\": {\"key\": \"value\"}}. Key chhoti english me "
    "(naam, ex, gf, city, padhai, kaam, pasand, mood, plan). Agar kuch nayi "
    "pakki baat nahi hai to {\"facts\": {}} de. Guess mat kar."
)


def _extract(username: str, convo: str) -> None:
    try:
        from intelligence import llm_router_v7 as router
        out = router.chat("banter", _EXTRACT_SYS, convo,
                          max_tokens=160, temperature=0.1)
        if not out:
            return
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return
        data = json.loads(m.group(0))
        for k, v in (data.get("facts") or {}).items():
            if isinstance(v, (str, int, float)):
                remember(username, str(k), str(v))
    except Exception:
        logger.debug("[FACTS] llm extract fail", exc_info=True)


def learn_async(username: str, convo: str) -> None:
    """Reply bhejne ke baad background me — user ko wait nahi karna padta."""
    if not convo:
        return
    threading.Thread(target=_extract, args=(username, convo), daemon=True).start()
