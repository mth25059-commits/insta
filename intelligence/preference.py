"""
Eve v7 — task-wise model preference.

Har kaam ka apna provider+model, TG panel se set hota hai:

  banter   : normal GC bakchodi  -> groq (sasta, fast)
  roast    : roast / gali / tone -> groq
  debate   : bahas, argument     -> agentrouter (opus 4.8)
  facts    : factual / political -> agentrouter (opus 4.8)
  help     : admin ne /help mara -> agentrouter (opus 4.8)

Har task ka ek fallback chain bhi hai: primary provider fail/quota over ->
next provider. Groq ke andar keys ka loop api_pool khud sambhalta hai.
"""
from __future__ import annotations

from typing import Any, Dict, List

from intelligence.aihumara_state import _get, _set
from intelligence.api_pool import PROVIDERS

TASKS = ("banter", "roast", "debate", "facts", "help")

TASK_LABEL = {
    "banter": "Normal chat",
    "roast": "Roast / gali",
    "debate": "Debate / bahas",
    "facts": "Facts / political",
    "help": "/help (admin support)",
}

DEFAULTS: Dict[str, Dict[str, Any]] = {
    # Groq = free + fast -> normal bakchodi/roast, sabse zyada traffic yahin.
    "banter": {"provider": "groq", "model": None, "fallback": ["agentrouter"]},
    "roast": {"provider": "groq", "model": None, "fallback": ["agentrouter"]},
    # Important/knowledge -> pehle AgentRouter (Opus 4.8, best quality).
    # AgentRouter Hindi/Hinglish ko "content-blocked" (400) deta hai, isliye
    # groq ko fallback me PEHLE rakha -> block aate hi turant groq se reply.
    "debate": {"provider": "agentrouter", "model": "claude-opus-4-8", "fallback": ["groq"]},
    "facts": {"provider": "agentrouter", "model": "claude-opus-4-8", "fallback": ["groq"]},
    "help": {"provider": "agentrouter", "model": "claude-opus-4-8", "fallback": ["groq"]},
}

_K = "task_pref"


def all_prefs() -> Dict[str, Dict[str, Any]]:
    saved = _get(_K, {}) or {}
    out = {}
    for t in TASKS:
        base = dict(DEFAULTS[t])
        base.update(saved.get(t, {}))
        out[t] = base
    return out


def get(task: str) -> Dict[str, Any]:
    return all_prefs().get(task, DEFAULTS["banter"])


def set_pref(task: str, provider: str, model: str | None = None) -> Dict[str, Any]:
    if task not in TASKS:
        raise ValueError("unknown task")
    if provider not in PROVIDERS:
        raise ValueError("unknown provider")
    saved = _get(_K, {}) or {}
    entry = dict(saved.get(task, {}))
    entry["provider"] = provider
    entry["model"] = model or PROVIDERS[provider]["default_model"]
    saved[task] = entry
    _set(_K, saved)
    return get(task)


def chain(task: str) -> List[Dict[str, Any]]:
    """[{'provider':..,'model':..}, ...] — pehla primary, baaki fallback."""
    p = get(task)
    out = [{"provider": p["provider"],
            "model": p.get("model") or PROVIDERS[p["provider"]]["default_model"]}]
    for fb in p.get("fallback", []):
        if fb in PROVIDERS and fb != p["provider"]:
            out.append({"provider": fb, "model": PROVIDERS[fb]["default_model"]})
    return out


def report() -> str:
    lines = ["Model preference (task → provider / model):"]
    for t in TASKS:
        p = get(t)
        model = p.get("model") or PROVIDERS[p["provider"]]["default_model"]
        fb = ", ".join(p.get("fallback", [])) or "—"
        lines.append(f"• {TASK_LABEL[t]}: {PROVIDERS[p['provider']]['label']} / {model}\n   fallback: {fb}")
    return "\n".join(lines)
