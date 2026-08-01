"""
Eve v7 — humanizer. Reply ka timing insaan jaisa lage.

Rule (user spec):
    7 word  -> ~3.0s
    15 word -> ~10.0s
  => piecewise:  w<=7  : 0.9 + 0.30*w
                 w<=15 : 3.0 + 0.875*(w-7)
                 w>15  : 10.0 + 0.15*(w-15)

Clamp: min 1.2s, max 13s.
"""
from __future__ import annotations

import random
import time

MIN_DELAY = 1.2
MAX_DELAY = 13.0
JITTER = 0.4


def word_count(text: str) -> int:
    return max(1, len((text or "").split()))


def delay_for(text: str) -> float:
    """Kitni der 'type' karna chahiye."""
    w = word_count(text)
    if w <= 7:
        d = 0.9 + 0.30 * w
    elif w <= 15:
        d = 3.0 + 0.875 * (w - 7)
    else:
        d = 10.0 + 0.15 * (w - 15)
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
