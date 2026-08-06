"""
Eve v7 — Instagram worker (body). instagrapi ke through GC/DM padhta hai,
Eve ka brain (eve_v7_boot) se decide karta hai, aur reply bhejta hai.

Chalane ka tarika: `python main.py` (ye worker + TG panel dono uthata hai).
"""
from __future__ import annotations

import logging
import random
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from eve_v7_boot import build_reply_context, on_incoming_message
from intelligence import (eve_modes, humanize, prompting, runtime_state,
                          user_facts)
from intelligence import llm_router_v7 as router
from storage import database, people

logger = logging.getLogger("eve.ig")

_stop = threading.Event()
_client: Any = None

# thread_id -> last DirectMessage object (reply/slide karne ke liye)
_last_msg_obj: Dict[str, Any] = {}

# Is waqt se pehle ke messages = purana backlog -> sirf seekho, reply mat karo.
_live_since: datetime = datetime.now(timezone.utc)

# TG alert throttle
_last_alert: float = 0.0


def mark_live_now() -> None:
    """START/FORCE START ya worker boot pe call — backlog spam rok deta hai."""
    global _live_since
    _live_since = datetime.now(timezone.utc)


def _is_backlog(ts: Any) -> bool:
    if not isinstance(ts, datetime):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < _live_since


# ------------------------------------------------------------- login


def login() -> Any:
    """Cookies-first login (workers/ig_login.py). Session cache hota hai."""
    global _client
    if _client is not None:
        return _client
    from workers import ig_login
    _client = ig_login.login()
    # apna username/pk yaad rakho — self-message skip aur "bot ko reply" detect
    # dono isi se chalte hain.
    try:
        me = _client.account_info()
        if getattr(me, "username", ""):
            config.IG_USERNAME = me.username.lower()
    except Exception:
        pass
    return _client


def _alert(text: str) -> None:
    """Zaroori problem TG pe bhej do (throttle: 10 min me ek baar)."""
    global _last_alert
    now = time.time()
    if now - _last_alert < 600:
        return
    _last_alert = now
    try:
        import requests
        from intelligence.aihumara_state import get_tg_admin_id
        ids = [i for i in (list(config.TG_ADMIN_IDS or []) + [get_tg_admin_id()]) if i]
        for cid in set(str(i) for i in ids):
            requests.post(
                f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": text}, timeout=20)
    except Exception:
        logger.debug("[IG] alert bhejne me dikkat")


# --------------------------------------------------- open-mode throttle

# START mode me bot har ek msg pe nahi bolega — GC me spam + IG block se bachne
# ke liye per-thread cooldown. Mention / slide / trigger / malik pe ye lagu nahi.
OPEN_COOLDOWN = 25.0        # itne sec me ek se zyada open-mode reply nahi
OPEN_CHANCE = 0.55          # cooldown ke baad bhi har baar nahi bolega
_last_open: Dict[str, float] = {}


def _open_allowed(thread_id: str) -> bool:
    now = time.time()
    if now - _last_open.get(thread_id, 0.0) < OPEN_COOLDOWN:
        return False
    if random.random() > OPEN_CHANCE:
        return False
    _last_open[thread_id] = now
    return True


# ------------------------------------------------------- send helpers


def _send_one(cl: Any, thread_id: str, text: str, reply_to: Any = None) -> None:
    """Quote/slide ke saath bhejne ki koshish, warna normal send."""
    if reply_to is not None:
        try:
            cl.direct_send(text, thread_ids=[int(thread_id)],
                           reply_to_message=reply_to)
            return
        except TypeError:
            pass                      # purana instagrapi — reply support nahi
        except Exception as e:
            logger.debug("[IG] quote reply fail (%s) — plain bhej rahe", e)
    cl.direct_send(text, thread_ids=[int(thread_id)])


def send_reply(thread_id: str, text: str, reply_to: Any = None,
               fast: bool = False) -> bool:
    """
    Human timing: 5 word ~3s, 10 word ~4.5s. Lamba reply 2-3 burst me.
    Har reply us user ke message pe slide (quote) hota hai.
    """
    if not text:
        return False
    cl = login()
    bursts = humanize.split_bursts(text)
    sent = False
    for i, part in enumerate(bursts):
        try:
            humanize.sleep_like_human(part, fast=fast and i == 0)
            _send_one(cl, thread_id, part, reply_to if i == 0 else None)
            database.log_message(
                ig_message_id=f"bot-{thread_id}-{time.time()}-{i}",
                thread_id=thread_id,
                ig_username=config.IG_USERNAME,
                text=part,
                is_bot=True,
            )
            sent = True
        except Exception as e:
            logger.warning("[IG] send fail (%s): %s", thread_id, e)
            break
    return sent


# --------------------------------------------------------- reply build


def handle_message(msg: Dict[str, Any]) -> None:
    username = msg["username"]
    text = msg["text"]
    thread_id = msg["thread_id"]
    reply_to = msg.get("obj")

    # FORCE STOP = sab band, learning bhi nahi.
    if runtime_state.is_dead():
        return

    # 1) Seekhna hamesha chalta hai — STOP mode me bhi.
    database.log_message(
        ig_message_id=msg["id"],
        thread_id=thread_id,
        thread_title=msg.get("title", ""),
        ig_username=username,
        ig_user_id=str(msg.get("user_id") or ""),
        text=text,
    )
    prev = database.recent_messages(thread_id, limit=4)
    on_incoming_message(
        username=username,
        text=text,
        thread_id=thread_id,
        ig_user_id=str(msg.get("user_id") or ""),
        thread_title=msg.get("title") or None,
        context=prompting.last_bot_line(prev),
    )

    # Purana backlog (bot band tha / abhi boot hua): seekh liya, reply nahi.
    if _is_backlog(msg.get("ts")):
        logger.debug("[IG] backlog skip (%s)", msg["id"])
        return

    history = database.recent_messages(thread_id, limit=prompting.SUMMARY_LIMIT)
    user_past = database.user_messages(thread_id, username, limit=prompting.USER_PAST_LIMIT)
    new_member = database.is_new_member(thread_id, username)


    ctx = build_reply_context(
        text=text,
        username=username,
        thread_id=thread_id,
        bot_username=config.IG_USERNAME,
        recent_texts=[h["text"] for h in history if h.get("text")],
        recent_usernames=[h["ig_username"] for h in history],
        is_new_member=new_member,
        replied_to_bot=bool(msg.get("replied_to_bot")),
    )

    # START mode: bina mention ke bhi reply, aur cost bachane ke liye groq.
    open_mode = runtime_state.open_reply()
    if open_mode and not ctx.get("should_reply"):
        ctx["should_reply"] = True
        ctx["reason"] = "open_mode"
        ctx.setdefault("route", "banter")

    if not ctx["should_reply"]:
        logger.debug("[IG] skip (%s)", ctx["reason"])
        return

    # Direct baat (mention / nickname / slide / trigger / malik) = hamesha,
    # aur turant. Baaki open-mode bakchodi throttle hoti hai.
    direct = ctx["reason"] in ("mention", "trigger", "order", "order_stop",
                               "order_start", "order_custom", "help",
                               "helpover", "not_admin", "new_member")
    if not direct and ctx["reason"] == "open_mode" and not _open_allowed(thread_id):
        logger.debug("[IG] open-mode throttle skip (%s)", thread_id)
        return

    if ctx.get("canned_reply"):
        send_reply(thread_id, ctx["canned_reply"], reply_to, fast=direct)
        return

    route = ctx.get("route") or "banter"
    if (open_mode and ctx["reason"] == "open_mode"
            and route not in ("facts", "debate", "news")):
        route = "banter"        # casual bakchodi = sasta model

    system = ctx["system_extra"]
    # sawal/bahas me kam creativity (sahi jawab), bakchodi me zyada masti
    smart = route in ("facts", "debate", "help", "news")
    reply = router.chat(
        "facts" if route == "news" else route,
        system,
        prompting.build_prompt(ctx=ctx, username=username, text=text,
                               history=history, user_past=user_past,
                               is_question=router.is_question(text)),
        max_tokens=320 if smart else 220,
        temperature=0.5 if smart else 0.95,
    )
    if reply:
        reply = reply.strip().strip('"')
        send_reply(thread_id, reply, reply_to, fast=direct)
        # Reply ke baad background me yaad-daasht update (naam, ex, plan...)
        try:
            user_facts.learn_async(
                username,
                f"Eve(pehle): {prompting.last_bot_line(history)}\n"
                f"@{username}: {text}\nEve: {reply}")
        except Exception:
            logger.debug("[IG] facts learn fail")
    else:
        logger.error("[IG] koi model reply nahi de paya — keys check kar")
        _alert("⚠️ Eve: koi AI model reply nahi de paya (saari API keys fail).\n"
               "Panel → API KEYS me key check kar / dusre provider ki key add kar.")



# --------------------------------------------------------------- poll


def _thread_allowed(thread_id: str) -> bool:
    return not config.IG_ALLOWED_THREADS or str(thread_id) in config.IG_ALLOWED_THREADS


def _fetch_new() -> List[Dict[str, Any]]:
    cl = login()
    out: List[Dict[str, Any]] = []
    me = (config.IG_USERNAME or "").lower()
    my_pk = str(getattr(cl, "user_id", "") or "")

    threads = cl.direct_threads(amount=config.IG_MAX_THREADS)
    for th in threads:
        tid = str(th.id)
        if not _thread_allowed(tid):
            continue
        by_id = {str(u.pk): u for u in (th.users or [])}
        title = th.thread_title or ""
        # Pehli baar thread dikha -> saare current members "purane" mark.
        database.seed_thread_members(
            tid, [(getattr(u, "username", "") or "") for u in (th.users or [])])
        for m in reversed(th.messages or []):
            if getattr(m, "item_type", "text") != "text" or not getattr(m, "text", ""):
                continue
            user = by_id.get(str(m.user_id))
            uname = (getattr(user, "username", "") or "").lower()
            if not uname or uname == me or (my_pk and str(m.user_id) == my_pk):
                continue
            # Kisi ne bot ke message pe slide/reply kiya? = mention jaisa hi.
            replied_to_bot = False
            rep = (getattr(m, "replied_to_message", None)
                   or getattr(m, "reply", None)
                   or getattr(m, "replied_to", None))
            if rep is not None:
                r_uid = str(getattr(rep, "user_id", "") or "")
                r_user = by_id.get(r_uid)
                r_name = (getattr(r_user, "username", "") or "").lower()
                r_text = str(getattr(rep, "text", "") or "").strip().lower()
                replied_to_bot = bool(
                    (my_pk and r_uid == my_pk) or (me and r_name == me))
                if not replied_to_bot and r_text:
                    # id/user na mile to bhi: kya wo line bot ne hi bheji thi?
                    replied_to_bot = database.was_bot_text(tid, r_text)
            out.append({
                "id": str(m.id),
                "thread_id": tid,
                "title": title,
                "username": uname,
                "user_id": str(m.user_id),
                "obj": m,
                "ts": getattr(m, "timestamp", None),
                "replied_to_bot": replied_to_bot,
                "text": m.text,
            })
    return out



# ----------------------------------------------------- GC live snapshot


def gc_snapshot(max_threads: int = 10) -> List[Dict[str, Any]]:
    """
    Live IG se GC list + members nikalta hai (FORCE START report ke liye).
    Return: [{"thread_id","title","member_count","members":[...]}]
    """
    cl = login()
    out: List[Dict[str, Any]] = []
    for th in cl.direct_threads(amount=max_threads):
        tid = str(th.id)
        if not _thread_allowed(tid):
            continue
        members = [(getattr(u, "username", "") or "").lower()
                   for u in (th.users or []) if getattr(u, "username", "")]
        out.append({
            "thread_id": tid,
            "title": th.thread_title or tid,
            "member_count": len(members),
            "members": sorted(members),
        })
    return out


def gc_report_text(max_threads: int = 10) -> str:
    """FORCE START pe TG panel me bhejne wali report."""
    try:
        snaps = gc_snapshot(max_threads)
    except Exception as e:
        return f"⚠️ GC report nahi mil payi (IG login/cookies check kar): {e}"
    if not snaps:
        return "Koi GC nahi mila — allowed threads / cookies check kar."
    lines = [f"👥 LIVE GC REPORT ({len(snaps)} chat)"]
    for s in snaps:
        names = ", ".join(f"@{m}" for m in s["members"][:25])
        extra = " …" if s["member_count"] > 25 else ""
        lines.append(f"\n• {s['title']} — {s['member_count']} member\n  {names}{extra}")
    return "\n".join(lines)


def _already_seen(message_id: str) -> bool:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM MESSAGES WHERE ig_message_id = ?", (message_id,)
        ).fetchone()
    return row is not None


def run(stop_event: Optional[threading.Event] = None) -> None:
    ev = stop_event or _stop
    logger.info("[IG] worker start — run mode: %s", runtime_state.get_mode())
    backoff = config.IG_POLL_SECONDS
    mark_live_now()
    was_dead = runtime_state.is_dead()

    while not ev.is_set():
        # FORCE STOP: poll bhi mat kar, bas idle rehkar TG panel ka wait.
        if runtime_state.is_dead():
            was_dead = True
            ev.wait(5)
            continue
        if was_dead:
            # Abhi FORCE STOP se wapas aaye — beech ka backlog reply mat kar.
            mark_live_now()
            was_dead = False
        try:
            for msg in _fetch_new():
                if ev.is_set() or runtime_state.is_dead():
                    break
                if _already_seen(msg["id"]):
                    continue
                try:
                    handle_message(msg)
                except Exception:
                    logger.exception("[IG] message handle fail")
            backoff = config.IG_POLL_SECONDS
        except Exception as e:
            logger.warning("[IG] poll fail: %s (retry %ss)", e, backoff)
            backoff = min(backoff * 2, 300)
        ev.wait(backoff)

    logger.info("[IG] worker band")


def stop() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    from eve_v7_boot import boot_v7
    boot_v7()
    run()
