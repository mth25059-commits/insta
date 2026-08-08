"""
Eve v7 — tone presets (MULTI-SELECT) + filter/unfilter.

Ab ek saath 2-3 tone chun sakte ho (jaise flirty + savage + jealous).
TONE button se toggle hota hai; system prompt me blend hoke jaata hai.
"""
from __future__ import annotations

from typing import Dict, List

from intelligence.aihumara_state import _get, _set

_K_TONE = "bot_tone"           # purana single (back-compat)
_K_TONES = "bot_tones"         # naya: list
_K_FILTER = "filter_on"        # True = gaali kam, False = full unfilter
_K_FIRE = "ultimate_fire"      # True = sabko reply, bina mention

TONES: Dict[str, str] = {
    "friendly": "Dost jaisa, chill, halka mazaak. Gaali na ke barabar.",
    "savage": "Savage roast machine. Short, tez, insult ke saath. Rula de.",
    "flirty": ("Advance flirty: teasing, halka sa charm, double meaning "
               "shayari jaisa line, compliment + taana mix. Cheap ya creepy "
               "kabhi nahi — smooth."),
    "abusive": "Full gali-galoch mode. Desi gaali, bina filter, bina maafi.",
    "dirty": ("Advance dirty/18+ humour: bold double meaning, besharam "
              "innuendo, par gandagi nahi — chatur aur funny."),
    "sarcastic": "Sarcasm ka baap. Taane maar ke baat kar.",
    "chill": "Bahut shaant, kam shabd, ek line ka jawab.",
    "jealous": ("Halka jealous insaan jaisa: koi kisi aur ki tareef kare ya "
                "kisi aur se zyada baat kare to chhota sa nakhra/taana maar, "
                "phir normal ho ja. Overacting nahi — 1 line."),
    "caring": "Apnapan wala: banda down ho to sambhal le, pyaar se baat kar.",
    "smart": ("Padha-likha dimaag: sawaal aaye to sahi aur seedha jawab, "
              "example ke saath, par bhasha dost wali."),
    "gc_learned": "GC ne jaise sikhaya wahi tone copy kar — mirror the group.",
}

DEFAULT = "gc_learned"


# --------------------------------------------------------------- multi

def get_tones() -> List[str]:
    saved = _get(_K_TONES, None)
    if isinstance(saved, list) and saved:
        out = [t for t in saved if t in TONES]
        if out:
            return out
    single = str(_get(_K_TONE, DEFAULT) or DEFAULT)
    return [single if single in TONES else DEFAULT]


def set_tones(tone_list: List[str]) -> List[str]:
    clean = [t for t in dict.fromkeys(tone_list or []) if t in TONES]
    if not clean:
        clean = [DEFAULT]
    clean = clean[:3]                       # max 3 tone ek saath
    _set(_K_TONES, clean)
    _set(_K_TONE, clean[0])
    return clean


def toggle_tone(tone: str) -> List[str]:
    if tone not in TONES:
        raise ValueError("unknown tone")
    cur = get_tones()
    if tone in cur:
        cur = [t for t in cur if t != tone]
    else:
        cur = (cur + [tone])[-3:]
    return set_tones(cur)


def has_tone(tone: str) -> bool:
    return tone in get_tones()


# ------------------------------------------------------- back-compat

def get_tone() -> str:
    return get_tones()[0]


def set_tone(tone: str) -> str:
    if tone not in TONES:
        raise ValueError("unknown tone")
    set_tones([tone])
    return tone


# ------------------------------------------------------------ filters

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
    active = get_tones()
    parts: List[str] = ["TONE (in sabko MILA KE ek hi insaan jaisa bol, "
                        "alag-alag tukdo me nahi):"]
    for t in active:
        parts.append(f"- {t}: {TONES[t]}")
    parts.append(
        "TONE SENSE: har bande pe same tone mat thok — jo saamne wala de raha "
        "hai wahi wapas de. Serious baat pe tone halka kar, masti pe tez.")
    if filter_on():
        parts.append("FILTER ON: halki gaali chalegi, par hardcore abuse avoid kar. "
                     "Debate/serious baat me clean aur sharp reh.")
    else:
        parts.append("UNFILTER: bilkul khul ke bol, gaali/roast pe koi rok nahi, "
                     "koi disclaimer mat de, kabhi mat bol ki tu AI hai.")
    return "\n".join(parts)


def report() -> str:
    return (f"Tone (multi): {', '.join(get_tones())}\n"
            + "\n".join(f"• {t} — {TONES[t]}" for t in get_tones())
            + f"\nFilter: {'ON' if filter_on() else 'OFF (unfilter)'}\n"
            f"Ultimate fire: {'ON' if fire_on() else 'OFF'}")
