"""
Eve v7 — API key pool + provider fallback.

Idea (user spec):
  * Ek provider me kitni bhi keys daal sakte ho (100 bhi chalengi).
  * Har key pe ek quota counter (default 2100 request). Quota khatam ->
    apne aap key #2, phir #3 ... loop me.
  * Key error de (401/429/5xx) -> turant next key, provider ke andar hi.
  * Provider bhi fail -> preference ka fallback provider.
  * Key add karte waqt live test hota hai — galat key pe panel bolta hai
    "ye key galat hai / dead hai", DB me save nahi hoti.

Providers:
  groq         -> https://api.groq.com/openai/v1          (sasta, fast, default)
  agentrouter  -> https://api.agentrouter.org/v1          (Claude Opus 4.8 yahi se)
  anthropic    -> https://api.anthropic.com/v1  (optional, direct claude)
  openrouter   -> https://openrouter.ai/api/v1  (optional backup)

Sab OpenAI-compatible /chat/completions se chalte hain (anthropic ka apna
messages endpoint handle kiya hua hai).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from intelligence.aihumara_state import _get, _set

logger = logging.getLogger("eve.api")

DEFAULT_KEY_LIMIT = 2100          # per key request quota, TG se badal sakte ho

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "groq": {
        "label": "Groq",
        "base": "https://api.groq.com/openai/v1",
        "style": "openai",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                   "openai/gpt-oss-120b", "qwen/qwen3-32b"],
    },
    "agentrouter": {
        "label": "AgentRouter (Opus 4.8)",
        "base": "https://api.agentrouter.org/v1",
        "style": "openai",
        "default_model": "claude-opus-4-8",
        "models": ["claude-opus-4-8", "claude-sonnet-4-5", "gpt-5.5"],
    },
    "anthropic": {
        "label": "Anthropic (direct)",
        "base": "https://api.anthropic.com/v1",
        "style": "anthropic",
        "default_model": "claude-opus-4-8",
        "models": ["claude-opus-4-8", "claude-sonnet-4-5"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "base": "https://openrouter.ai/api/v1",
        "style": "openai",
        "default_model": "anthropic/claude-opus-4.8",
        "models": ["anthropic/claude-opus-4.8", "google/gemini-2.5-flash"],
    },
}

_K_KEYS = "api_keys"          # {provider: [{key, used, dead, added}]}
_K_LIMIT = "api_key_limit"
_K_CURSOR = "api_key_cursor"  # {provider: index}


# ------------------------------------------------------------- storage

def _keys() -> Dict[str, List[Dict[str, Any]]]:
    data = _get(_K_KEYS, {}) or {}
    return {p: list(v) for p, v in data.items()}


def _save(data: Dict[str, List[Dict[str, Any]]]) -> None:
    _set(_K_KEYS, data)


def key_limit() -> int:
    try:
        return int(_get(_K_LIMIT, DEFAULT_KEY_LIMIT) or DEFAULT_KEY_LIMIT)
    except Exception:
        return DEFAULT_KEY_LIMIT


def set_key_limit(n: int) -> int:
    n = max(10, int(n))
    _set(_K_LIMIT, n)
    return n


def mask(k: str) -> str:
    return f"{k[:6]}…{k[-4:]}" if len(k) > 12 else "…"


def list_keys(provider: str) -> List[Dict[str, Any]]:
    return _keys().get(provider, [])


def add_key(provider: str, key: str, verify: bool = True) -> Dict[str, Any]:
    """Return {'ok': bool, 'message': str}."""
    provider = provider.strip()
    key = (key or "").strip()
    if provider not in PROVIDERS:
        return {"ok": False, "message": f"unknown provider: {provider}"}
    if len(key) < 15:
        return {"ok": False, "message": "ye key bahut chhoti hai — galat lag rahi"}

    data = _keys()
    bucket = data.setdefault(provider, [])
    if any(k["key"] == key for k in bucket):
        return {"ok": False, "message": "ye key pehle se added hai"}

    if verify:
        ok, why = test_key(provider, key)
        if not ok:
            return {"ok": False, "message": f"key reject: {why}"}

    bucket.append({"key": key, "used": 0, "dead": False, "added": int(time.time())})
    _save(data)
    return {"ok": True, "message": f"{PROVIDERS[provider]['label']} key #{len(bucket)} add ({mask(key)})"}


def remove_key(provider: str, index: int) -> bool:
    data = _keys()
    bucket = data.get(provider, [])
    if 0 <= index < len(bucket):
        bucket.pop(index)
        _save(data)
        return True
    return False


def reset_usage(provider: Optional[str] = None) -> None:
    data = _keys()
    for p, bucket in data.items():
        if provider and p != provider:
            continue
        for k in bucket:
            k["used"] = 0
            k["dead"] = False
    _save(data)


def usage_report() -> str:
    data = _keys()
    lim = key_limit()
    if not data:
        return "Koi API key set nahi. API SET → provider → ADD KEY."
    out = [f"Per-key limit: {lim} req"]
    for p, bucket in data.items():
        out.append(f"\n{PROVIDERS.get(p, {}).get('label', p)} — {len(bucket)} key")
        for i, k in enumerate(bucket, 1):
            flag = "DEAD" if k.get("dead") else f"{k.get('used', 0)}/{lim}"
            out.append(f"  {i}. {mask(k['key'])}  [{flag}]")
    return "\n".join(out)


# ------------------------------------------------------------ key pick

def _cursor(provider: str) -> int:
    return int((_get(_K_CURSOR, {}) or {}).get(provider, 0))


def _set_cursor(provider: str, idx: int) -> None:
    cur = _get(_K_CURSOR, {}) or {}
    cur[provider] = idx
    _set(_K_CURSOR, cur)


def _ordered_keys(provider: str) -> List[int]:
    """Active key se shuru, phir loop me baaki keys."""
    bucket = list_keys(provider)
    lim = key_limit()
    live = [i for i, k in enumerate(bucket)
            if not k.get("dead") and int(k.get("used", 0)) < lim]
    if not live:
        return []
    start = _cursor(provider)
    live.sort(key=lambda i: (i < start, i))    # cursor se aage wale pehle
    return live


def _bump(provider: str, index: int, dead: bool = False) -> None:
    data = _keys()
    bucket = data.get(provider, [])
    if not (0 <= index < len(bucket)):
        return
    bucket[index]["used"] = int(bucket[index].get("used", 0)) + 1
    if dead:
        bucket[index]["dead"] = True
    _save(data)
    if dead or bucket[index]["used"] >= key_limit():
        _set_cursor(provider, (index + 1) % max(1, len(bucket)))
    else:
        _set_cursor(provider, index)


# --------------------------------------------------------------- call

def test_key(provider: str, key: str) -> tuple[bool, str]:
    try:
        txt = _raw_call(provider, key, PROVIDERS[provider]["default_model"],
                        [{"role": "user", "content": "ping"}], 8, 0.0, timeout=25)
        return (True, "ok") if txt is not None else (False, "empty response")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        body = (e.response.text[:120] if e.response is not None else "")
        return False, f"HTTP {code} {body}"
    except Exception as e:
        return False, str(e)[:120]


def _raw_call(provider: str, key: str, model: str, messages: List[Dict[str, str]],
              max_tokens: int, temperature: float, timeout: int = 60) -> Optional[str]:
    meta = PROVIDERS[provider]
    if meta["style"] == "anthropic":
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        r = requests.post(
            f"{meta['base']}/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "system": system or None, "messages": chat},
            timeout=timeout,
        )
        r.raise_for_status()
        blocks = r.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks).strip()

    r = requests.post(
        f"{meta['base']}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        json={"model": model, "messages": messages,
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def call(provider: str, messages: List[Dict[str, str]], *, model: Optional[str] = None,
         max_tokens: int = 300, temperature: float = 0.85) -> Optional[str]:
    """
    Ek provider ki saari live keys pe try karo (loop me), pehla success return.
    None = is provider se kuch nahi mila (caller fallback provider try kare).
    """
    if provider not in PROVIDERS:
        return None
    model = model or PROVIDERS[provider]["default_model"]
    bucket = list_keys(provider)
    for idx in _ordered_keys(provider):
        key = bucket[idx]["key"]
        try:
            out = _raw_call(provider, key, model, messages, max_tokens, temperature)
            _bump(provider, idx)
            if out:
                return out
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            dead = code in (401, 403)
            logger.warning("[API] %s key#%s HTTP %s -> next key", provider, idx + 1, code)
            _bump(provider, idx, dead=dead)
        except Exception as e:
            logger.warning("[API] %s key#%s fail: %s", provider, idx + 1, e)
            _bump(provider, idx)
    return None


def has_keys(provider: str) -> bool:
    return bool(_ordered_keys(provider))
