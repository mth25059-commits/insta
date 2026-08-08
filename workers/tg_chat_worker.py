"""
Eve v7 — TELEGRAM CHAT worker (Instagram wale worker ka TG version).

Setup me agar PLATFORM=tg chuna hai to bot Instagram ki jagah ek Telegram
group me baithta hai. Dimaag, memory, mode (START/STOP), nickname, roast,
summary — sab bilkul same hai, sirf jagah alag.

Zaroori: control panel wala bot aur GC me baithne wala bot ALAG hone chahiye
(ek hi token pe do getUpdates nahi chal sakte).
"""
from __future__ import annotations

import logging
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config
from eve_v7_boot import build_reply_context, on_incoming_message
from intelligence import humanize, prompting, runtime_state, user_facts
from intelligence import llm_router_v7 as router
from storage import database

logger = logging.getLogger("eve.tg_chat")

_stop = threading.Event()
_me: Dict[str, Any] = {}
_live_since: float = time.time()

OPEN_COOLDOWN = 25.0
OPEN_CHANCE = 0.55
REACT_CHANCE = 0.25          # normal chat pe itni baar hi react (spam se bachne ko)
_last_open: Dict[str, float] = {}


def mark_live_now() -> None:
    global _live_since
    _live_since = time.time()


def _api(method: str, **payload) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{config.TG_CHAT_BOT_TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=60)
    return r.json()


def me() -> Dict[str, Any]:
    global _me
    if not _me:
        res = _api("getMe")
        _me = res.get("result", {}) or {}
        if _me.get("username"):
            config.TG_BOT_USERNAME = _me["username"]
    return _me


# Telegram free-plan par ye emojis hi react ke liye allowed hain.
_REACT_POOL = {
    "love": "❤", "fire": "🔥", "laugh": "😁", "sad": "😢",
    "wow": "😱", "ok": "👍", "clap": "👏", "think": "🤔",
    "salute": "🫡", "party": "🎉",
}
# Mood/route -> react emoji. Recall/yaad, sad baat, roast sab ka apna react.
_REACT_MAP = {
    "recall": "❤", "memory": "❤", "sad": "😢", "roast": "🔥",
    "facts": "🤔", "debate": "🫡", "news": "🔥", "banter": "😁",
}


def react(chat_id: str, message_id: int, emoji: str) -> None:
    """Ek message pe emoji reaction laga do (best-effort, fail-safe)."""
    if not message_id or emoji not in _REACT_POOL.values():
        return
    try:
        _api("setMessageReaction", chat_id=chat_id, message_id=message_id,
             reaction=[{"type": "emoji", "emoji": emoji}])
    except Exception as e:
        logger.debug("[TG-CHAT] react fail: %s", e)


_SAD_RE = re.compile(
    r"\b(sad|dukh|rona|ro raha|udaas|akela|depress|miss|breakup|"
    r"tut gaya|dard|rula|marne|thak gaya)\b|yaad\s+a\w*", re.I)
_RECALL_RE = re.compile(
    r"\b(yaad\s+(hai|dila|rakh)|recall|remember|pehle\s+bola|"
    r"maine\s+btaya|tune\s+bola)\b", re.I)


def _pick_react(text: str, route: str) -> Optional[str]:
    """User ke text + route ke mood se ek react emoji chuno (ya None).

    Dukh/recall wali baat pe hamesha react (wahin pe react ka matlab banta
    hai). Normal bakchodi pe kabhi-kabhi, warna har message pe emoji spam.
    """
    t = text or ""
    if _SAD_RE.search(t):
        return _REACT_MAP["sad"]            # 😢 dukh/miss/yaad wali baat
    if _RECALL_RE.search(t):
        return _REACT_MAP["recall"]         # ❤ purani baat recall
    if random.random() > REACT_CHANCE:
        return None
    return _REACT_MAP.get(route)            # roast🔥 facts🤔 debate🫡 banter😁


def _allowed(chat_id: str) -> bool:
    return (not config.TG_CHAT_ALLOWED_GROUPS
            or str(chat_id) in config.TG_CHAT_ALLOWED_GROUPS)


def _open_allowed(chat_id: str) -> bool:
    now = time.time()
    if now - _last_open.get(chat_id, 0.0) < OPEN_COOLDOWN:
        return False
    if random.random() > OPEN_CHANCE:
        return False
    _last_open[chat_id] = now
    return True


def send_reply(chat_id: str, text: str, reply_to: Optional[int] = None,
               fast: bool = False) -> bool:
    if not text:
        return False
    sent = False
    for i, part in enumerate(humanize.split_bursts(text)):
        try:
            _api("sendChatAction", chat_id=chat_id, action="typing")
            humanize.sleep_like_human(part, fast=fast and i == 0)
            payload: Dict[str, Any] = {"chat_id": chat_id, "text": part}
            if reply_to and i == 0:
                payload["reply_to_message_id"] = reply_to
            _api("sendMessage", **payload)
            database.log_message(
                ig_message_id=f"bot-{chat_id}-{time.time()}-{i}",
                thread_id=str(chat_id),
                ig_username=(me().get("username") or "eve").lower(),
                text=part,
                is_bot=True,
            )
            sent = True
        except Exception as e:
            logger.warning("[TG-CHAT] send fail: %s", e)
            break
    return sent


def handle_message(m: Dict[str, Any]) -> None:
    chat = m.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    frm = m.get("from") or {}
    text = (m.get("text") or "").strip()
    if not chat_id or not text or frm.get("is_bot"):
        return
    if not _allowed(chat_id):
        return
    if runtime_state.is_dead():
        return

    username = (frm.get("username")
                or f"{frm.get('first_name','user')}_{frm.get('id')}").lower()
    msg_id = m.get("message_id")

    database.log_message(
        ig_message_id=f"tg-{chat_id}-{msg_id}",
        thread_id=chat_id,
        thread_title=chat.get("title", ""),
        ig_username=username,
        ig_user_id=str(frm.get("id") or ""),
        text=text,
    )
    prev = database.recent_messages(chat_id, limit=4)
    on_incoming_message(username=username, text=text, thread_id=chat_id,
                        ig_user_id=str(frm.get("id") or ""),
                        thread_title=chat.get("title") or None,
                        context=prompting.last_bot_line(prev))

    if (m.get("date") or 0) < _live_since - 5:
        return                                   # purana backlog: sirf seekha

    bot_user = (me().get("username") or "").lower()
    rep = m.get("reply_to_message") or {}
    replied_to_bot = bool((rep.get("from") or {}).get("is_bot")
                          and ((rep.get("from") or {}).get("username", "").lower()
                               == bot_user))

    q_text = str(rep.get("text") or "").strip()
    q_author = "" if replied_to_bot else str(
        (rep.get("from") or {}).get("username") or "")

    history = database.recent_messages(chat_id, limit=prompting.SUMMARY_LIMIT)
    user_past = database.user_messages(chat_id, username,
                                       limit=prompting.USER_PAST_LIMIT)

    ctx = build_reply_context(
        text=text, username=username, thread_id=chat_id,
        bot_username=bot_user,
        recent_texts=[h["text"] for h in history if h.get("text")],
        recent_usernames=[h["ig_username"] for h in history],
        is_new_member=False,
        replied_to_bot=replied_to_bot,
    )

    open_mode = runtime_state.open_reply()
    if open_mode and not ctx.get("should_reply"):
        ctx["should_reply"] = True
        ctx["reason"] = "open_mode"
        ctx.setdefault("route", "banter")
    if not ctx["should_reply"]:
        return

    direct = ctx["reason"] != "open_mode"
    if not direct and not _open_allowed(chat_id):
        return

    if ctx.get("canned_reply"):
        send_reply(chat_id, ctx["canned_reply"], msg_id, fast=direct)
        return

    route = ctx.get("route") or "banter"
    smart = route in ("facts", "debate", "help", "news")
    reply = router.chat(
        "facts" if route == "news" else route,
        ctx["system_extra"],
        prompting.build_prompt(ctx=ctx, username=username, text=text,
                               history=history, user_past=user_past,
                               is_question=router.is_question(text),
                               quoted_text=q_text, quoted_author=q_author),
        max_tokens=320 if smart else 220,
        temperature=0.5 if smart else 0.95,
    )
    if reply:
        reply = reply.strip().strip('"')
        # Mood/recall ke hisaab se user ke message pe react (❤🔥😢🤔…), phir reply.
        emoji = _pick_react(text, route)
        if emoji:
            react(chat_id, msg_id, emoji)
        send_reply(chat_id, reply, msg_id, fast=direct)
        try:
            user_facts.learn_async(
                username,
                f"Eve(pehle): {prompting.last_bot_line(prev)}\n"
                f"@{username}: {text}\nEve: {reply}")
        except Exception:
            logger.debug("[TG-CHAT] facts learn fail")
    else:
        logger.error("[TG-CHAT] koi model reply nahi de paya — keys check kar")


def group_report() -> str:
    """FORCE START pe TG panel me bhejne wali report (TG mode)."""
    rows: List[str] = []
    try:
        chats = database.thread_titles() if hasattr(database, "thread_titles") else []
    except Exception:
        chats = []
    for cid in (config.TG_CHAT_ALLOWED_GROUPS or [c for c, _ in chats]):
        try:
            info = _api("getChat", chat_id=cid).get("result", {}) or {}
            cnt = _api("getChatMemberCount", chat_id=cid).get("result", "?")
            rows.append(f"• {info.get('title', cid)} — {cnt} member (id {cid})")
        except Exception as e:
            rows.append(f"• {cid} — info nahi mila ({e})")
    if not rows:
        return ("TG mode: koi group set nahi. Bot ko group me add kar aur "
                ".env me TG_CHAT_ALLOWED_GROUPS me chat id daal.")
    return "👥 LIVE TG GROUP REPORT\n" + "\n".join(rows)


def run(stop_event: Optional[threading.Event] = None) -> None:
    ev = stop_event or _stop
    if not config.TG_CHAT_BOT_TOKEN:
        logger.error("[TG-CHAT] TG_CHAT_BOT_TOKEN missing — worker band")
        return
    info = me()
    logger.info("[TG-CHAT] live as @%s", info.get("username"))
    mark_live_now()
    offset = 0
    was_dead = runtime_state.is_dead()
    while not ev.is_set():
        if runtime_state.is_dead():
            was_dead = True
            ev.wait(5)
            continue
        if was_dead:
            mark_live_now()
            was_dead = False
        try:
            res = _api("getUpdates", offset=offset, timeout=40,
                       allowed_updates=["message"])
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message")
                if m:
                    try:
                        handle_message(m)
                    except Exception:
                        logger.exception("[TG-CHAT] handle fail")
        except Exception as e:
            logger.warning("[TG-CHAT] poll fail: %s", e)
            ev.wait(5)
    logger.info("[TG-CHAT] worker band")


def stop() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    from eve_v7_boot import boot_v7
    boot_v7()
    run()
