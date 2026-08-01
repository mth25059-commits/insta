"""
Eve v7 — member matcher.

TG panel me jab tum `@username` do (trigger set / memory add), to ye
check karta hai ki wo banda GC me exist karta hai ya nahi.
Galat likha to closest username suggest karta hai.
"""
from __future__ import annotations

import difflib
import re
from typing import Dict, List, Optional

from storage.database import get_connection

_CLEAN = re.compile(r"[^a-z0-9._]")


def normalize(username: str) -> str:
    u = (username or "").strip().lstrip("@").lower()
    return _CLEAN.sub("", u)


def known_usernames(thread_id: Optional[str] = None) -> List[str]:
    """Jitne bhi log bot ne kabhi dekhe (optionally ek hi GC ke)."""
    sql = "SELECT DISTINCT ig_username FROM MESSAGES WHERE ig_username IS NOT NULL"
    args: tuple = ()
    if thread_id:
        sql += " AND thread_id = ?"
        args = (str(thread_id),)
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return sorted({(r["ig_username"] or "").lower() for r in rows if r["ig_username"]})


def resolve(username: str, thread_id: Optional[str] = None,
            limit: int = 3) -> Dict[str, object]:
    """
    Return:
      {"found": True,  "username": "dhruv"}
      {"found": False, "suggestions": ["dhruv_x", "dhruvv"], "message": "..."}
    """
    u = normalize(username)
    if not u:
        return {"found": False, "suggestions": [],
                "message": "Username khali hai — `@name` bhej."}

    pool = known_usernames(thread_id)
    if u in pool:
        return {"found": True, "username": u, "suggestions": []}

    # 1) substring match (typo se zyada common: aadha naam likh dena)
    subs = [p for p in pool if u in p or p in u][:limit]
    # 2) fuzzy
    fuzzy = difflib.get_close_matches(u, pool, n=limit, cutoff=0.6)

    seen: List[str] = []
    for cand in subs + fuzzy:
        if cand not in seen:
            seen.append(cand)
    seen = seen[:limit]

    if seen:
        opts = ", ".join(f"@{s}" for s in seen)
        msg = f"@{u} nahi mila. Shayad ye: {opts}"
    else:
        msg = f"@{u} nahi mila — ye member GC me abhi tak dikha hi nahi."
    return {"found": False, "username": u, "suggestions": seen, "message": msg}
