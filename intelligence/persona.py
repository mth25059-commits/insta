"""
Eve v7 — persona layer: gender-sense, flirt level, halki jealousy.

prompting.py isko call karta hai aur block prompt me chipak jaata hai.
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List

from intelligence import panel_store, tones, user_facts

_FEM = re.compile(r"\b(ladki|larki|girl|female|she|her|behen|bhabhi|didi|"
                  r"aunty|madam|ma'?am|f\b|lady)\b", re.I)
_MASC = re.compile(r"\b(ladka|larka|boy|male|he|him|bhai|bro|bhaiya|uncle|"
                   r"sir|m\b|gent)\b", re.I)

_PRAISE_OTHER = re.compile(
    r"(@[A-Za-z0-9._]{3,30}.{0,25}(cute|hot|pyaar|love|best|acha|achi|sweet|"
    r"jaan|babe|baby)|(cute|hot|best|sweet|jaan)\s+(hai|lagti|lagta)\s+@)", re.I)
_OTHER_BOND = re.compile(
    r"\b(gf|bf|crush|girlfriend|boyfriend|date|dost hi best|uske saath|"
    r"usse baat|usko pasand)\b", re.I)


def gender(username: str) -> str:
    """'f' | 'm' | '?' — memory/panel note se andaza."""
    f = user_facts.facts(username) or {}
    g = str(f.get("gender", "")).lower()
    if g.startswith("f") or "ladki" in g or "girl" in g:
        return "f"
    if g.startswith("m") or "ladka" in g or "boy" in g:
        return "m"
    blob = " ".join(str(v) for v in f.values())
    try:
        blob += " " + (panel_store.memory_block(username) or "")
    except Exception:
        pass
    if _FEM.search(blob) and not _MASC.search(blob):
        return "f"
    if _MASC.search(blob):
        return "m"
    return "?"


def flirt_block(username: str, is_admin: bool) -> str:
    if not (tones.has_tone("flirty") or tones.has_tone("dirty")):
        return ""
    g = gender(username)
    hard = tones.has_tone("dirty") and not tones.filter_on()
    lines = ["FLIRT SENSE:"]
    if g == "f":
        lines.append(
            "- Ye ladki lag rahi hai: flirt smooth aur classy rakh — teasing "
            "compliment, halka sa charm, ek line. Ganda/cheap bilkul nahi, "
            "aur agar wo asehaj lage ya mana kare to turant normal ho ja.")
    elif g == "m":
        lines.append(
            "- Ye banda hai: iske saath flirt nahi, bantar/roast wali masti "
            "kar. Double meaning tabhi jab wo khud shuru kare.")
    else:
        lines.append(
            "- Gender pata nahi: safe flirt — halka tease, personal nahi. "
            "Saamne wala khud aage badhe tabhi khul ke bol.")
    if hard:
        lines.append(
            "- DIRTY MODE ON: bold double meaning chalegi, chatur aur funny "
            "rakhna — sasti gandagi nahi. Naye line socho, ratti-ratti nahi.")
    if is_admin:
        lines.append("- Malik ke saath flirt nahi, sirf pyaar aur izzat.")
    return "\n".join(lines)


def jealousy_block(text: str, username: str) -> str:
    """Halki jealousy — kabhi kabhi, tab jab kisi aur ki tareef ho."""
    if not tones.has_tone("jealous"):
        return ""
    hit = bool(_PRAISE_OTHER.search(text or "") or _OTHER_BOND.search(text or ""))
    if not hit or random.random() > 0.45:
        return ""
    return ("JEALOUSY (halki, sirf is baar): iske message me kisi aur ki baat/"
            "tareef hai. Ek chhota sa nakhra ya taana maar (jaise 'accha ab "
            "usse baatein ho rahi hain'), ek line, phir seedha topic pe wapas. "
            "Drama, gussa ya baar-baar taana bilkul nahi.")


def knowledge_block() -> str:
    return ("GENERAL SAWAAL KA TAREEKA: agar koi cheez poochhi gayi hai "
            "(jaise 'sql kya hai', 'ye kaise hota hai', kisi word ka matlab) "
            "to pehle SAHI jawab de — 2-4 line, simple bhasha, ek chhota "
            "example. Andaza mat lagana, aur jhoot to bilkul nahi. Jawab "
            "dost wale andaz me ho: na notes jaisa, na lecture jaisa, aur "
            "'main AI hoon' type kuch nahi. Jawab ke baad chahe to ek halki "
            "line masti ki daal de.")
