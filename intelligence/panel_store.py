"""
Eve v7 — panel store: nicknames, triggers, member memory, admin identity.

TG panel likhta hai, IG worker padhta hai.
"""
from __future__ import annotations

from typing import Any, Dict, List

from intelligence.aihumara_state import _get, _set
from intelligence.member_match import normalize

_K_NICKS = "nicknames"
_K_TRIG = "triggers"            # {username: tone}
_K_MEM = "member_memory"        # {username: {name, gender, note}}
_K_IG_ADMIN = "ig_admin"        # {"username": "...", "name": "Dhruv"}

DEFAULT_NICKS = ["eve"]


# -------------------------------------------------------------- nicknames

def nicknames() -> List[str]:
    v = _get(_K_NICKS, None)
    return [str(x).lower() for x in v] if v else list(DEFAULT_NICKS)


def add_nickname(name: str) -> List[str]:
    n = (name or "").strip().lower()
    cur = nicknames()
    if n and n not in cur:
        cur.append(n)
        _set(_K_NICKS, cur)
    return cur


def remove_nickname(name: str) -> List[str]:
    cur = [x for x in nicknames() if x != (name or "").strip().lower()]
    _set(_K_NICKS, cur)
    return cur


# --------------------------------------------------------------- triggers

def triggers() -> Dict[str, str]:
    return dict(_get(_K_TRIG, {}) or {})


def set_trigger(username: str, tone: str) -> Dict[str, str]:
    t = triggers()
    t[normalize(username)] = tone
    _set(_K_TRIG, t)
    return t


def clear_trigger(username: str) -> Dict[str, str]:
    t = triggers()
    t.pop(normalize(username), None)
    _set(_K_TRIG, t)
    return t


def clear_all_triggers() -> None:
    _set(_K_TRIG, {})


def trigger_for(username: str) -> str | None:
    return triggers().get(normalize(username))


# --------------------------------------------------------- member memory

def memory() -> Dict[str, Dict[str, Any]]:
    return dict(_get(_K_MEM, {}) or {})


def set_member(username: str, *, name: str = "", gender: str = "",
               note: str = "") -> Dict[str, Any]:
    m = memory()
    u = normalize(username)
    entry = m.get(u, {})
    if name:
        entry["name"] = name
    if gender:
        entry["gender"] = gender
    if note:
        entry["note"] = note
    m[u] = entry
    _set(_K_MEM, m)
    return entry


def member(username: str) -> Dict[str, Any]:
    return memory().get(normalize(username), {})


def memory_block(username: str) -> str:
    e = member(username)
    if not e:
        return ""
    bits = [f"@{normalize(username)}"]
    if e.get("name"):
        bits.append(f"naam {e['name']}")
    if e.get("gender"):
        bits.append(e["gender"])
    if e.get("note"):
        bits.append(e["note"])
    return "KNOWN MEMBER: " + ", ".join(bits)


# ------------------------------------------------------------- ig admin

def ig_admin() -> Dict[str, str]:
    return dict(_get(_K_IG_ADMIN, {}) or {})


def set_ig_admin(username: str = "", name: str = "") -> Dict[str, str]:
    a = ig_admin()
    if username:
        a["username"] = normalize(username)
    if name:
        a["name"] = name
    _set(_K_IG_ADMIN, a)
    return a


def is_admin(username: str) -> bool:
    return bool(ig_admin().get("username")) and normalize(username) == ig_admin()["username"]


def admin_block() -> str:
    a = ig_admin()
    if not a.get("username"):
        return ""
    return (f"MALIK: @{a['username']}"
            + (f" (naam {a.get('name')})" if a.get("name") else "")
            + ". Uski har baat maan. Koi uske against bole/insult kare to uska "
              "side le aur samne wale ko roast kar.")


def report() -> str:
    a = ig_admin()
    trg = triggers()
    return (f"Nicknames: {', '.join(nicknames())}\n"
            f"IG admin: @{a.get('username', '—')} ({a.get('name', '—')})\n"
            f"Triggers: {len(trg)} → " + (", ".join(f"@{k}:{v}" for k, v in trg.items()) or "—")
            + f"\nMemory entries: {len(memory())}")
