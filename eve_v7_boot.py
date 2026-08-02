"""
Eve v7 — brain boot + decision layer.

    boot_v7()                 -> DB ready, Drive restore, auto-backup ON
    on_incoming_message(...)  -> seekhna (profile update)
    build_reply_context(...)  -> reply dena hai ya nahi + kis route se
    shutdown_v7()             -> final Drive backup
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import config
from intelligence import api_pool, panel_store, runtime_state, tones
from intelligence import llm_router_v7 as router
from storage import database, drive_sync, people

logger = logging.getLogger("eve.boot")

_ORDER = re.compile(r"^/order\b\s*(.*)$", re.I)
_HELP = re.compile(r"/help\b", re.I)
_HELPOVER = re.compile(r"/helpover\b", re.I)

RUDE_REPLY = ("aukat hai teri mujhe command dene ki? ja pehle apna level "
              "check kar.")
ORDER_OK = "malik ki agya sar aankhon par 🙏"


# --------------------------------------------------------------- boot


def boot_v7() -> None:
    database.init_db()
    people.init()
    api_pool.seed_from_env()        # .env ki keys -> pool (verify off = boot fast)
    if drive_sync.available():
        drive_sync.restore()
        database.init_db()          # restore ke baad schema dobara ensure
        people.init()
        drive_sync.start_background()
    api_pool.seed_from_env()        # Drive restore ke baad bhi ensure
    logger.info("[BOOT] Eve v7 ready — mode: %s", runtime_state.get_mode())


def shutdown_v7() -> None:
    try:
        drive_sync.stop_background(final_push=True)
    except Exception:
        logger.exception("[BOOT] final backup fail")


# ------------------------------------------------------------ learning


def on_incoming_message(*, username: str, text: str, thread_id: str,
                        ig_user_id: str = "",
                        thread_title: Optional[str] = None) -> None:
    if not runtime_state.learning_on():
        return
    try:
        people.touch(username, text, ig_user_id)
    except Exception:
        logger.exception("[BOOT] learning fail")


# ------------------------------------------------------------- helpers


def _mentioned(text: str, bot_username: str) -> bool:
    t = (text or "").lower()
    if bot_username and f"@{bot_username.lower()}" in t:
        return True
    return any(re.search(rf"\b{re.escape(n)}\b", t) for n in panel_store.nicknames())


def _gc_style(recent_texts: List[str]) -> str:
    sample = [t for t in (recent_texts or []) if t][-8:]
    if not sample:
        return ""
    return "GC KA STYLE (isi bhasha me bol):\n" + "\n".join(f"- {s}" for s in sample)


# --------------------------------------------------------- main context


def build_reply_context(*, text: str, username: str, thread_id: str,
                        bot_username: str = "",
                        recent_texts: Optional[List[str]] = None,
                        recent_usernames: Optional[List[str]] = None,
                        is_new_member: bool = False,
                        replied_to_bot: bool = False) -> Dict[str, Any]:
    """
    Return:
      should_reply, reason, route, canned_reply, system_extra
    """
    text = text or ""
    is_admin = panel_store.is_admin(username)
    trigger_tone = panel_store.trigger_for(username)
    # @mention, nickname, ya bot ke message pe slide/reply — teeno mention hi hain.
    mentioned = replied_to_bot or _mentioned(text, bot_username or config.IG_USERNAME)

    ctx: Dict[str, Any] = {
        "should_reply": False,
        "reason": "no_trigger",
        "route": "banter",
        "canned_reply": "",
        "system_extra": "",
        "is_admin": is_admin,
    }

    if runtime_state.is_dead():
        ctx["reason"] = "force_stop"
        return ctx

    # ---- admin commands (sirf set kiya hua IG admin) -------------------
    order = _ORDER.match(text.strip())
    if order or _HELP.search(text) or _HELPOVER.search(text):
        if not is_admin:
            ctx.update(should_reply=True, reason="not_admin",
                       canned_reply=RUDE_REPLY)
            return ctx
        if order:
            body = (order.group(1) or "").strip()
            if not body:
                ctx.update(should_reply=True, reason="order",
                           canned_reply=ORDER_OK)
                return ctx
            if re.search(r"\b(shut ?up|chup|band ho|stop)\b", body, re.I):
                runtime_state.set_mode(runtime_state.STOP)
                ctx.update(should_reply=True, reason="order_stop",
                           canned_reply="sorry malik, chup ho gaya 🤐")
                return ctx
            if re.search(r"\b(start|bol|chalu)\b", body, re.I):
                runtime_state.set_mode(runtime_state.START)
                ctx.update(should_reply=True, reason="order_start",
                           canned_reply="ji malik, wapas aa gaya 😈")
                return ctx
            ctx.update(should_reply=True, reason="order_custom", route="help",
                       system_extra=f"MALIK KA ORDER: {body}. Isi ko follow kar.")
            return ctx
        if _HELPOVER.search(text):
            ctx.update(should_reply=True, reason="helpover",
                       canned_reply="theek hai malik, support mode band 👍")
            return ctx
        # /help -> opus support mode
        ctx.update(should_reply=True, reason="help", route="help")
        ctx["system_extra"] = (
            f"{panel_store.admin_block()}\n"
            "MODE: ADMIN SUPPORT. Thread padh ke samajh kaun opponent hai. "
            "Admin ka side le, latest facts aur logic se opponent ko phaad de. "
            "Chhota, sharp, confident."
        )
        return ctx

    # ---- kis wajah se reply -------------------------------------------
    if trigger_tone:
        ctx.update(should_reply=True, reason="trigger")
    elif mentioned:
        ctx.update(should_reply=True, reason="mention")
    elif runtime_state.open_reply() and tones.fire_on():
        ctx.update(should_reply=True, reason="open_mode")
    elif runtime_state.open_reply():
        ctx.update(should_reply=True, reason="open_mode")

    if not ctx["should_reply"]:
        return ctx

    # Sach me naya banda -> intro poochho. Admin, jaana-pehchana banda,
    # panel memory wala banda, ya bot ke msg pe reply karne wala — inse
    # kabhi intro mat maang.
    known = bool(panel_store.member(username)) or people.msg_count(username) > 1
    if (is_new_member and not is_admin and not trigger_tone
            and not replied_to_bot and not known):
        ctx["canned_reply"] = f"@{username} naya lag raha hai — intro de bhai?"
        ctx["reason"] = "new_member"
        return ctx

    ctx["route"] = router.classify(text)

    parts = [
        panel_store.admin_block(),
        panel_store.memory_block(username),
        people.profile_block(username),
        _gc_style(recent_texts or []),
    ]
    # baat me jinka zikr hua, unki bhi memory do -> bot ko context samajh aaye
    for other in set(re.findall(r"@([A-Za-z0-9._]{3,30})", text or "")):
        if other.lower() != (username or "").lower():
            blk = panel_store.memory_block(other)
            if blk:
                parts.append("ZIKR HUA -> " + blk)
    if trigger_tone:
        parts.append(f"TRIGGER TONE (is bande ke liye force): {trigger_tone}")
    if panel_store.is_admin(username):
        parts.append("Ye khud MALIK hai — izzat se baat kar.")
    ctx["system_extra"] = "\n".join(p for p in parts if p)
    return ctx
