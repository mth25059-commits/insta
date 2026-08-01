"""
Eve v7 — run mode (FORCE START / START / STOP / FORCE STOP).

TG panel isi module ko likhta hai, IG worker isi ko padhta hai.

  FORCE_STOP : sab band. na reply, na learning, na drive sync push.
  STOP       : reply sirf nickname/mention/trigger pe. learning ON.
  START      : har message ka reply (open mode). learning ON.

FORCE_START = pehli baar VPS setup ke baad "sab systems on" ka switch —
ye internally START set karta hai + booted flag laga deta hai.
"""
from __future__ import annotations

from typing import Dict

from intelligence.aihumara_state import _get, _set  # shared BOT_STATE table

_K_RUN = "run_mode"
_K_BOOTED = "force_started_once"

FORCE_STOP = "force_stop"
STOP = "stop"
START = "start"

CHOICES = (FORCE_STOP, STOP, START)

LABELS: Dict[str, str] = {
    FORCE_STOP: "FORCE STOP — sab band (learning bhi)",
    STOP: "STOP — sirf nickname/mention pe reply, learning chalu",
    START: "START — har message ka reply, learning chalu",
}


def get_mode() -> str:
    v = str(_get(_K_RUN, STOP) or STOP)
    return v if v in CHOICES else STOP


def set_mode(mode: str) -> str:
    if mode not in CHOICES:
        raise ValueError(f"mode {CHOICES} me se hona chahiye")
    _set(_K_RUN, mode)
    return mode


def force_start() -> str:
    _set(_K_BOOTED, True)
    return set_mode(START)


def force_stop() -> str:
    return set_mode(FORCE_STOP)


def was_force_started() -> bool:
    return bool(_get(_K_BOOTED, False))


# ------------------------------------------------------------ helpers

def is_dead() -> bool:
    """FORCE STOP = kuch mat kar, message bhi mat padh."""
    return get_mode() == FORCE_STOP


def learning_on() -> bool:
    return get_mode() != FORCE_STOP


def open_reply() -> bool:
    """True = bina mention ke bhi reply karna hai."""
    return get_mode() == START


def status_line() -> str:
    m = get_mode()
    return f"{LABELS[m]}\nforce-start ho chuka: {'haan' if was_force_started() else 'nahi'}"
