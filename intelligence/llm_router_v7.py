"""
Eve v7 — LLM router. Task decide karta hai, phir preference chain pe chalta hai.

    router.chat("banter", system, prompt)      -> groq
    router.chat("debate", system, prompt)      -> opus (agentrouter)
    router.classify(text)                      -> "banter"|"roast"|"debate"|"facts"
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from intelligence import api_pool, preference, tones

logger = logging.getLogger("eve.router")

_DEBATE = re.compile(
    r"\b(debate|bahas|argue|argument|proof|saboot|logic|tu galat|galat hai tu|"
    r"prove|source|fact|facts|history|politic|political|modi|congress|bjp|"
    r"election|religion|hindu|muslim|science|constitution|law|kanoon)\b", re.I)
_ROAST = re.compile(
    r"\b(roast|gali|gaali|maa|behen|bsdk|mc|bc|chutiy|randi|lund|gandu|"
    r"loda|jhaat|teri)\b", re.I)


_QUESTION = re.compile(
    r"(\?|\b(kya|kaise|kaisay|kyu|kyun|kyo|kab|kaun|kahan|kitna|kitne|batao|"
    r"bata\s|samjha|explain|matlab|meaning|how|why|what|when|who|where)\b)", re.I)
_FACTUAL = re.compile(
    r"\b(kitna|kitne|kab|kaun sa|price|rate|score|match|result|year|saal|"
    r"population|capital|formula|code|error|padhai|exam|syllabus)\b", re.I)


_KNOWLEDGE = re.compile(
    r"(\b(what|who|why|how|when|which)\s+(is|are|was|does|do|did|to)\b|"
    r"\bkya\s+(hai|hota|hoti|h)\b|\bkaise\s+(hota|kaam|banta|karte|kare)\b|"
    r"\bkyun?\s+hota\b|\bmatlab\b|\bmeaning\b|\bdefine\b|\bexplain\b|"
    r"\bfull\s*form\b|\bdifference\b|\bantar\b|\bsamjha\s*de\b)", re.I)


def is_knowledge(text: str) -> bool:
    return bool(_KNOWLEDGE.search(text or ""))


def classify(text: str) -> str:
    """Kya poochha gaya hai — usi hisaab se dimaag chuno."""
    t = text or ""
    if _DEBATE.search(t) or len(t.split()) > 35:
        return "debate"
    if _KNOWLEDGE.search(t):
        return "facts"          # general knowledge sawaal -> smart model
    if _ROAST.search(t):
        return "roast"
    # sacha sawal (sirf gaali nahi) -> smart model, taaki bewakoofi na bole
    if _QUESTION.search(t) and (_FACTUAL.search(t) or len(t.split()) >= 4):
        return "facts"
    return "banter"


def is_question(text: str) -> bool:
    return bool(_QUESTION.search(text or ""))


def chat(task: str, system: str, prompt: str, *, max_tokens: int = 300,
         temperature: float = 0.9) -> Optional[str]:
    """Preference chain pe try; har provider ke andar keys ka loop."""
    if task not in preference.TASKS:
        task = "banter"
    messages: List[dict] = [
        {"role": "system", "content": f"{system}\n\n{tones.system_block()}"},
        {"role": "user", "content": prompt},
    ]
    for step in preference.chain(task):
        if not api_pool.has_keys(step["provider"]):
            continue
        out = api_pool.call(step["provider"], messages, model=step["model"],
                            max_tokens=max_tokens, temperature=temperature)
        if out:
            logger.info("[ROUTER] %s -> %s/%s", task, step["provider"], step["model"])
            return out
        logger.warning("[ROUTER] %s fail -> next provider", step["provider"])
    return None
