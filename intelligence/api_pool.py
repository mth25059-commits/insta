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
  agentrouter  -> https://agentrouter.org/v1               (Claude Opus 4.8 yahi se)
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

import config
from intelligence.aihumara_state import _get, _set

logger = logging.getLogger("eve.api")

# Aliyun WAF (agentrouter.org) blocks the default python-requests UA -> HTML challenge
# page instead of JSON. Always send a browser-like UA.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

DEFAULT_KEY_LIMIT = 2100          # per key request quota, TG se badal sakte ho

# Har API call ka max wait. Timeout hone par hi fallback provider (groq) try
# hota hai — matlab ye jitna bada, utni der user ko intezaar. .env me
# API_TIMEOUT=25 daal ke chhota kar sakte ho (GC me 25-30s zyada practical hai).
API_TIMEOUT = int(getattr(config, "API_TIMEOUT", 0) or 120)

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
        # AgentRouter Claude ke liye Anthropic-compatible chahiye:
        #   POST {base}/v1/messages  (base = https://agentrouter.org, /v1 khud lagta hai)
        #   Authorization: Bearer <key>   +   User-Agent: claude-cli ...  +  x-app: cli
        # Bina in headers ke wo "unauthorized client detected" (401) deta hai.
        # Sirf claude-opus-4-8 hi abhi live hai (4-6/4-7/sonnet = "no channel").
        "label": "AgentRouter (Opus 4.8)",
        "base": "https://agentrouter.org",
        "style": "agentrouter",
        "default_model": "claude-opus-4-8",
        "models": ["claude-opus-4-8"],
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

# Ye providers pe key add karte waqt live test NAHI hota (WAF/region block ki
# wajah se sahi key bhi reject ho jaati thi). Jo key daali, wahi save.
NO_VERIFY = {"agentrouter"}


_K_CFG = "provider_cfg"          # {provider: {"base":..,"model":..}} — TG se set


def cfg(provider: str) -> Dict[str, str]:
    return dict((_get(_K_CFG, {}) or {}).get(provider, {}))


def set_cfg(provider: str, *, base: str = "", model: str = "") -> Dict[str, str]:
    """TG panel se base URL / model badalna."""
    data = _get(_K_CFG, {}) or {}
    entry = dict(data.get(provider, {}))
    if base:
        entry["base"] = base.strip()
    if model:
        entry["model"] = model.strip()
    data[provider] = entry
    _set(_K_CFG, data)
    return entry


def base_url(provider: str) -> str:
    """TG override > .env > default. '/v1' apne aap lag jaata hai."""
    base = cfg(provider).get("base") or PROVIDERS[provider]["base"]
    if provider == "agentrouter" and not cfg(provider).get("base"):
        base = (getattr(config, "AGENTROUTER_BASE", "") or base).strip()
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return base


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

    if verify and provider not in NO_VERIFY:
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

def default_model(provider: str) -> str:
    saved = cfg(provider).get("model")
    if saved:
        return saved
    if provider == "agentrouter":
        return (getattr(config, "AGENTROUTER_MODEL", "")
                or PROVIDERS[provider]["default_model"])
    return PROVIDERS[provider]["default_model"]


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
        txt = _raw_call(provider, key, default_model(provider),
                        [{"role": "user", "content": "ping"}], 8, 0.0, timeout=25)
        return (True, "ok") if txt is not None else (False, "empty response")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        body = (e.response.text[:120] if e.response is not None else "")
        return False, f"HTTP {code} {body}"
    except Exception as e:
        return False, str(e)[:120]


def _raw_call(provider: str, key: str, model: str, messages: List[Dict[str, str]],
              max_tokens: int, temperature: float, timeout: int = 0) -> Optional[str]:
    meta = PROVIDERS[provider]
    base = base_url(provider)
    timeout = timeout or API_TIMEOUT

    # AgentRouter Claude: Anthropic /v1/messages, par auth Bearer + Claude Code
    # jaise headers chahiye (warna 401 "unauthorized client detected").
    if meta["style"] == "agentrouter":
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        r = requests.post(
            f"{base}/messages",
            headers={"Authorization": f"Bearer {key}",
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json",
                     "accept": "application/json",
                     "x-app": "cli",
                     "user-agent": "claude-cli/1.0.0 (external, cli)"},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "system": system or None, "messages": chat},
            timeout=timeout,
        )
        r.raise_for_status()
        try:
            blocks = r.json().get("content", [])
        except ValueError:
            raise RuntimeError(f"non-JSON from agentrouter (WAF?): {r.text[:120]}")
        # thinking + text dono blocks aate hain — sirf text chahiye
        return "".join(b.get("text", "") for b in blocks
                       if b.get("type") == "text").strip()

    if meta["style"] == "anthropic":
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        r = requests.post(
            f"{base}/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json",
                     "accept": "application/json", "user-agent": UA},
            json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                  "system": system or None, "messages": chat},
            timeout=timeout,
        )
        r.raise_for_status()
        blocks = r.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks).strip()

    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json",
                 "accept": "application/json", "user-agent": UA},
        json={"model": model, "messages": messages,
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=timeout,
    )
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"non-JSON response from {provider} (WAF/HTML?): {r.text[:120]}")
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"bad payload from {provider}: {str(data)[:160]}")


def call(provider: str, messages: List[Dict[str, str]], *, model: Optional[str] = None,
         max_tokens: int = 300, temperature: float = 0.85) -> Optional[str]:
    """
    Ek provider ki saari live keys pe try karo (loop me), pehla success return.
    None = is provider se kuch nahi mila (caller fallback provider try kare).
    """
    if provider not in PROVIDERS:
        return None
    model = model or default_model(provider)
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
            body = (e.response.text[:200] if e.response is not None else "")
            dead = code in (401, 403)
            # content-blocked = content ka masla hai, key ka nahi (AgentRouter
            # Hindi/Hinglish block karta hai). Baaki keys pe bhi wahi 400 aayega,
            # isliye turant nikal jao -> caller seedha fallback provider (groq)
            # se reply le lega. Warna 10 keys = 10 bekaar call + delay.
            if code == 400 and "content-blocked" in body:
                logger.info("[API] %s content-blocked -> fallback provider", provider)
                _bump(provider, idx)
                return None
            logger.warning("[API] %s key#%s HTTP %s -> next key", provider, idx + 1, code)
            _bump(provider, idx, dead=dead)
        except Exception as e:
            logger.warning("[API] %s key#%s fail: %s", provider, idx + 1, e)
            _bump(provider, idx)
    return None


def has_keys(provider: str) -> bool:
    return bool(_ordered_keys(provider))


# ------------------------------------------------------- seed from .env

_ENV_MAP = {
    "groq": ("GROQ_API_KEYS", "GROQ_API_KEY"),
    "agentrouter": ("AGENTROUTER_API_KEYS", "AGENTROUTER_API_KEY", "AGENTROUTER_KEY",
                    "ANTHROPIC_AUTH_TOKEN"),
    "anthropic": ("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY"),
}


def seed_from_env(verify: bool = False) -> None:
    """.env me di gayi keys ko pool me daal do (boot pe). Comma se multiple."""
    for provider, names in _ENV_MAP.items():
        for name in names:
            raw = getattr(config, name, "") or ""
            for key in [k.strip() for k in raw.split(",") if k.strip()]:
                res = add_key(provider, key, verify=verify)
                if res["ok"]:
                    logger.info("[API] env seed -> %s %s", provider, mask(key))
