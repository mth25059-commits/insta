"""
Eve v7 — mode helper (runtime_state ke upar patla wrapper).

ig_worker/tg_panel dono ke liye ek jagah se "abhi kya allowed hai" ka jawab.
"""
from __future__ import annotations

from typing import Dict

from intelligence import runtime_state, tones


def snapshot() -> Dict[str, object]:
    return {
        "mode": runtime_state.get_mode(),
        "label": runtime_state.LABELS[runtime_state.get_mode()],
        "learning": runtime_state.learning_on(),
        "open_reply": runtime_state.open_reply() or tones.fire_on(),
        "fire": tones.fire_on(),
        "tone": tones.get_tone(),
        "filter": tones.filter_on(),
    }


def can_learn() -> bool:
    return runtime_state.learning_on()


def can_reply_open() -> bool:
    """START ya ULTIMATE FIRE — bina mention reply."""
    if runtime_state.is_dead():
        return False
    return runtime_state.open_reply() or tones.fire_on()


def can_reply_at_all() -> bool:
    return not runtime_state.is_dead()


def report() -> str:
    s = snapshot()
    return (f"Mode: {s['label']}\n"
            f"Learning: {'ON' if s['learning'] else 'OFF'}\n"
            f"Open reply: {'ON' if s['open_reply'] else 'OFF'}"
            f"{' (FIRE)' if s['fire'] else ''}\n"
            f"Tone: {s['tone']} | Filter: {'ON' if s['filter'] else 'OFF'}")
