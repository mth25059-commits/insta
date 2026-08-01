"""
Eve v7 — Instagram login (cookies-first).

Priority:
  1. secrets/ig_cookies.json   (repo pull ke baad tum yahi daalte ho)
  2. IG_SESSION_PATH session dump (pehle login se bana hua)
  3. username + password (.env) — last resort

Cookies format (dono chalte hain):
  A) instagrapi settings dump  -> {"authorization_data": {...}, "cookies": {...}, ...}
  B) simple                    -> {"username": "...", "cookies": {"sessionid": "...", ...}}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import config

logger = logging.getLogger("eve.ig.login")

COOKIE_FILE = Path(config.BASE_DIR) / "secrets" / "ig_cookies.json"


class LoginError(RuntimeError):
    pass


def _read_cookie_file() -> Optional[Dict[str, Any]]:
    if not COOKIE_FILE.exists():
        return None
    try:
        data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise LoginError(f"{COOKIE_FILE} valid JSON nahi hai: {e}") from e
    data.pop("_readme", None)
    return data


def _is_settings_dump(data: Dict[str, Any]) -> bool:
    return "authorization_data" in data or "uuids" in data


def _client() -> Any:
    from instagrapi import Client
    cl = Client()
    cl.delay_range = [1, 3]
    return cl


def _verify(cl: Any) -> Tuple[bool, str]:
    """Account really logged-in hai ya nahi."""
    try:
        info = cl.account_info()
        return True, (getattr(info, "username", "") or "")
    except Exception as e:
        return False, str(e)


def login() -> Any:
    """
    Logged-in instagrapi Client return karta hai, warna LoginError.
    Har successful login ke baad session dump save hota hai (next time instant).
    """
    session_file = Path(config.SESSION_PATH)
    session_file.parent.mkdir(parents=True, exist_ok=True)

    # ---------- 1) cookies file ----------
    data = _read_cookie_file()
    if data:
        cl = _client()
        try:
            if _is_settings_dump(data):
                cl.set_settings(data)
            else:
                cookies = data.get("cookies") or {}
                if not cookies.get("sessionid"):
                    raise LoginError(
                        "ig_cookies.json me `cookies.sessionid` missing hai."
                    )
                cl.set_settings({"cookies": cookies})
                cl.login_by_sessionid(cookies["sessionid"])
            ok, who = _verify(cl)
            if ok:
                cl.dump_settings(session_file)
                logger.info("[IG] cookies se login OK — account: @%s", who)
                return cl
            logger.warning("[IG] cookies se account verify fail: %s", who)
        except LoginError:
            raise
        except Exception as e:
            logger.warning("[IG] cookies login fail: %s", e)

    # ---------- 2) purana session dump ----------
    if session_file.exists():
        cl = _client()
        try:
            cl.load_settings(session_file)
            if config.IG_USERNAME and config.IG_PASSWORD:
                cl.login(config.IG_USERNAME, config.IG_PASSWORD)
            ok, who = _verify(cl)
            if ok:
                logger.info("[IG] session file se login OK — @%s", who)
                return cl
        except Exception as e:
            logger.warning("[IG] session file fail: %s", e)

    # ---------- 3) username + password ----------
    if config.IG_USERNAME and config.IG_PASSWORD:
        cl = _client()
        try:
            cl.login(config.IG_USERNAME, config.IG_PASSWORD)
            ok, who = _verify(cl)
            if ok:
                cl.dump_settings(session_file)
                logger.info("[IG] password se login OK — @%s", who)
                return cl
            raise LoginError(f"login hua par verify fail: {who}")
        except Exception as e:
            raise LoginError(f"password login fail: {e}") from e

    raise LoginError(
        "Koi credential nahi mila.\n"
        f"  -> {COOKIE_FILE} banao (secrets/ig_cookies.example.json copy karke)\n"
        "  -> ya .env me IG_USERNAME / IG_PASSWORD daalo"
    )


def check_account() -> Dict[str, Any]:
    """Setup ke waqt: 'account found or not' ka jawab."""
    try:
        cl = login()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        info = cl.account_info()
        return {
            "ok": True,
            "username": getattr(info, "username", ""),
            "full_name": getattr(info, "full_name", ""),
            "pk": str(getattr(info, "pk", "")),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
