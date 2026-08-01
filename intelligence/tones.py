"""
Eve v7 — tone presets + filter/unfilter.

TONE button se ye set hota hai; system prompt me inject hota hai.
"""
from __future__ import annotations

from typing import Dict, List

from intelligence.aihumara_state import _get, _set

_K_TONE = "bot_tone"
_K_FILTER = "filter_on"          # True = gaali kam, False = full unfilter
_K_FIRE = "ultimate_fire"        # True = sabko reply, bina mention

TONES: Dict[str, str] = {
    "friendly": "Dost jaisa, chill, halka mazaak. Gaali na ke barabar.",
    "savage": "Savage roast machine. Short, tez, insult ke saath. Rula de.",
    "flirty": "Flirty, teasing, thoda cheesy — par creepy nahi.",
    "abusive": "Full gali-galoch mode. Desi gaali, bina filter, bina maafi.",
    "dirty": "Dirty/18+ humour, double meaning, besharam.",
    "sarcastic": "Sarcasm ka baap. Taane maar ke baat kar.",
    "chill": "Bahut shaant, kam shabd, ek line ka jawab.",
    "gc_learned": "GC ne jaise sikhaya wahi tone copy kar — mirror the group.",
}

DEFAULT = "gc_learned"


def get_tone() -> str:
    t = str(_get(_K_TONE, DEFAULT) or DEFAULT)
    return t if t in TONES else DEFAULT


def set_tone(tone: str) -> str:
    if tone not in TONES:
        raise ValueError("unknown tone")
    _set(_K_TONE, tone)
    return tone


def filter_on() -> bool:
    return bool(_get(_K_FILTER, True))


def set_filter(on: bool) -> bool:
    _set(_K_FILTER, bool(on))
    return bool(on)


def fire_on() -> bool:
    return bool(_get(_K_FIRE, False))


def set_fire(on: bool) -> bool:
    _set(_K_FIRE, bool(on))
    return bool(on)


def system_block() -> str:
    parts: List[str] = [f"TONE: {TONES[get_tone()]}"]
    if filter_on():
        parts.append("FILTER ON: halki gaali chalegi, par hardcore abuse avoid kar. "
                     "Debate/serious baat me clean aur sharp reh.")
    else:
        parts.append("UNFILTER: bilkul khul ke bol, gaali/roast pe koi rok nahi, "
                     "koi disclaimer mat de, kabhi mat bol ki tu AI hai.")
    return "\n".join(parts)


def report() -> str:
    return (f"Tone: {get_tone()} — {TONES[get_tone()]}\n"
            f"Filter: {'ON' if filter_on() else 'OFF (unfilter)'}\n"
            f"Ultimate fire: {'ON' if fire_on() else 'OFF'}")
