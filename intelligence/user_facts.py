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


_LABEL = {
    "naam": "iska apna naam",
    "ex_naam": "iske EX ka naam (iska apna naam NAHI)",
    "gf_naam": "iski gf/bf ka naam",
    "dost_naam": "iske dost ka naam",
    "city": "iska sheher",
    "padhai": "padhai",
    "kaam": "kaam/job",
    "pasand": "isko pasand",
    "nafrat": "isko pasand nahi",
    "mood": "iska mood/dukh",
}


def block(username: str) -> str:
    f = facts(username)
    if not f:
        return ""
    lines = [f"- {_LABEL.get(k, k)}: {v}" for k, v in f.items()]
    return (f"@{_u(username)} KE BAARE ME JO PEHLE PATA CHALA (ye yaad hai "
            "tujhe, isko dhyan me rakh ke baat kar, ulta mat poochh; kisi "
            "aur ka naam ise mat chipka):\n"
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
#
# SABSE BADI GALTI JO PEHLE HOTI THI: kisi ne ex ka naam bataya aur bot ne
# use bande ka apna naam maan liya. Ab har naam ke saath "kiska naam hai" bhi
# dekha jaata hai (apna / ex / gf / dost).

_SELF_NAME = [
    re.compile(r"\b(?:mera|mere)\s+naam\s+([A-Za-z][A-Za-z]{2,18})\b", re.I),
    re.compile(r"\b(?:my name is|i am|i'm|myself)\s+([A-Za-z][A-Za-z]{2,18})\b", re.I),
    re.compile(r"\bmujhe\s+([A-Za-z][A-Za-z]{2,18})\s+(?:bulate|kehte|bolte)\b", re.I),
]
_STOPNAMES = {"kya", "nahi", "hai", "bhai", "yaar", "sorry", "good", "bad",
              "eve", "babu", "the", "a", "an", "not", "your", "tumhara",
              "uska", "iska", "mera", "tera", "naam", "pata", "acha", "theek"}

# kis rishtey ki baat chal rahi hai -> naam usi ke khaate me jaayega
_REL = [
    ("ex_naam", re.compile(r"\b(ex|breakup|break\s?up|purani|puraana wala)\b", re.I)),
    ("gf_naam", re.compile(r"\b(gf|girlfriend|bf|boyfriend|crush|gf ka|bf ka)\b", re.I)),
    ("dost_naam", re.compile(r"\b(dost|friend|yaar ka|bestie|bhai ka)\b", re.I)),
]

# "uska naam shivam tha" jaise line -> kisi AUR ka naam
_OTHER_NAME = re.compile(
    r"\b(?:uska|us ka|uski|iska|is ka|unka)\s+naam\s+([A-Za-z][A-Za-z]{2,18})\b", re.I)
# akela naam (jaise bot ne poochha 'kya naam tha' aur user ne 'shivam' bola)
_BARE_NAME = re.compile(r"^([A-Za-z][a-z]{2,15})[\s.!]*$")
_ASKED_NAME = re.compile(r"\bnaam\b.*\b(kya|tha|hai|batao|thi)\b|what.*name", re.I)

_PATTERNS = [
    ("padhai",  re.compile(r"\b(?:main|mai|me)\s+(\w+(?:\s+\w+)?)\s+(?:me|mein)\s+padh", re.I)),
    ("city",    re.compile(r"\b(?:main|mai|me)\s+([A-Za-z]{3,15})\s+(?:se|me|mein)\s+(?:hu|hoon|rehta|rehti)\b", re.I)),
    ("kaam",    re.compile(r"\b(?:main|mai)\s+([\w ]{3,25})\s+(?:ka kaam|job)\s+karta\b", re.I)),
    ("pasand",  re.compile(r"\bmujhe\s+([\w ]{3,25})\s+(?:pasand|acha lagta|achi lagti)\b", re.I)),
    ("nafrat",  re.compile(r"\bmujhe\s+([\w ]{3,25})\s+(?:pasand nahi|nafrat)\b", re.I)),
    ("mood",    re.compile(r"\b(?:mujhe|mai|main)\s+(?:apni|apne)?\s*(ex|breakup|gf|bf)\b.{0,25}(?:yaad|miss)", re.I)),
]


def _clean_name(raw: str) -> str:
    name = (raw or "").strip().title()
    return name if len(name) >= 3 and name.lower() not in _STOPNAMES else ""


def _relation_key(*texts: str) -> str:
    """Aas-paas ki baat dekh ke tay karo naam kiska hai."""
    blob = " ".join(t or "" for t in texts)
    for key, rx in _REL:
        if rx.search(blob):
            return key
    return ""


def learn(username: str, text: str, context: str = "") -> None:
    """
    Har incoming message pe — sasta, bina LLM ke.
    `context` = pichhli 1-2 line (bot ka sawaal + user ki purani baat), isse
    pata chalta hai naam kiska bataya ja raha hai.
    """
    t = (text or "").strip()
    if not t or len(t) > 400:
        return

    rel = _relation_key(t, context)

    # 1) "uska naam X" -> pakka kisi aur ka
    m = _OTHER_NAME.search(t)
    if m:
        name = _clean_name(m.group(1))
        if name:
            remember(username, rel or "dost_naam", name)
    else:
        # 2) "mera naam X" -> apna naam (chahe rishtey ki baat ho rahi ho)
        for rx in _SELF_NAME:
            mm = rx.search(t)
            if mm:
                name = _clean_name(mm.group(1))
                if name:
                    remember(username, "naam", name)
                break
        else:
            # 3) sirf naam bheja (bot ne poochha tha) -> context decide karega
            bare = _BARE_NAME.match(t)
            if bare and _ASKED_NAME.search(context or ""):
                name = _clean_name(bare.group(1))
                if name:
                    remember(username, rel or ("naam" if not rel else rel), name)

    for key, rx in _PATTERNS:
        m = rx.search(t)
        if m:
            remember(username, key, m.group(1).strip())


# --------------------------------------------------------- LLM learning

_EXTRACT_SYS = (
    "Tu ek memory extractor hai. Diye gaye chat exchange me se USER ke baare "
    "me pakki, lambe samay tak yaad rakhne layak baatein nikaal.\n"
    "SABSE ZAROORI: naam kiska hai ye galat mat kar. Agar user apna naam "
    "bataye to key 'naam'. Agar wo apne EX ka naam bataye to key 'ex_naam'. "
    "gf/bf ka naam -> 'gf_naam'. dost ka -> 'dost_naam'. Shak ho to naam "
    "bilkul mat likh.\n"
    "Sirf JSON de: {\"facts\": {\"key\": \"value\"}}. Baaki keys chhoti "
    "english me (city, padhai, kaam, pasand, mood, plan). Kuch nayi pakki "
    "baat na ho to {\"facts\": {}}. Guess mat kar."
)

_ALLOWED = {"naam", "ex_naam", "gf_naam", "dost_naam", "city", "padhai",
            "kaam", "pasand", "nafrat", "mood", "plan"}


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
            k = str(k).strip().lower()
            if k in _ALLOWED and isinstance(v, (str, int, float)):
                remember(username, k, str(v))
    except Exception:
        logger.debug("[FACTS] llm extract fail", exc_info=True)


def learn_async(username: str, convo: str) -> None:
    """Reply bhejne ke baad background me — user ko wait nahi karna padta."""
    if not convo:
        return
    threading.Thread(target=_extract, args=(username, convo), daemon=True).start()
