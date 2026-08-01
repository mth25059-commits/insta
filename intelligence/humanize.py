"""
Eve v7 — humanizer. Reply ka timing insaan jaisa lage.

Rule: jitna bada sentence utna zyada time, chhota sentence = kam time.
    3 word  -> ~1.7s
    7 word  -> ~2.9s
    15 word -> ~7.9s
    30 word -> ~14.2s
Clamp: min 1.2s, max 22s. Har baar thoda random jitter.
"""
from __future__ import annotations

import random
import time

MIN_DELAY = 1.2
MAX_DELAY = 22.0
JITTER = 0.4

# per-word "typing" speed (sec) — jitna bada sentence, utna zyada time
WPS_FAST = 0.30      # chhota msg: taez
WPS_MID = 0.62       # medium
WPS_SLOW = 0.42      # bahut lamba: thoda speed up (copy-paste feel na aaye)
READ_BASE = 0.8      # padhne ka time


def word_count(text: str) -> int:
    return max(1, len((text or "").split()))


def delay_for(text: str) -> float:
    """Kitni der 'type' karna chahiye. Chhota = km time, bada = zyada time."""
    w = word_count(text)
    if w <= 7:
        d = READ_BASE + WPS_FAST * w
    elif w <= 15:
        d = READ_BASE + WPS_FAST * 7 + WPS_MID * (w - 7)
    else:
        d = READ_BASE + WPS_FAST * 7 + WPS_MID * 8 + WPS_SLOW * (w - 15)
    d += random.uniform(-JITTER, JITTER)
    return round(max(MIN_DELAY, min(d, MAX_DELAY)), 2)


def sleep_like_human(text: str) -> float:
    d = delay_for(text)
    time.sleep(d)
    return d


def split_bursts(text: str, max_len: int = 180) -> list[str]:
    """
    Lamba reply ek hi dialog-box me na jaye — insaan 2 chhote msg bhejta hai.
    Sentence boundary pe todta hai, warna as-is.
    """
    text = (text or "").strip()
    if len(text) <= max_len:
        return [text] if text else []

    parts: list[str] = []
    cur = ""
    for chunk in text.replace("\n", " ").split(". "):
        chunk = chunk.strip()
        if not chunk:
            continue
        candidate = f"{cur}. {chunk}".strip(". ") if cur else chunk
        if len(candidate) > max_len and cur:
            parts.append(cur.strip())
            cur = chunk
        else:
            cur = candidate
    if cur:
        parts.append(cur.strip())
    return parts[:3] or [text[:max_len]]
