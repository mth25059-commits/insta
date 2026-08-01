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
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from eve_v7_boot import build_reply_context, on_incoming_message
from intelligence import eve_modes, humanize, runtime_state
from intelligence import llm_router_v7 as router
from storage import database, people

logger = logging.getLogger("eve.ig")

_stop = threading.Event()
_client: Any = None

# thread_id -> last DirectMessage object (reply/slide karne ke liye)
_last_msg_obj: Dict[str, Any] = {}


# ------------------------------------------------------------- login


def login() -> Any:
    """Cookies-first login (workers/ig_login.py). Session cache hota hai."""
    global _client
    if _client is not None:
        return _client
    from workers import ig_login
    _client = ig_login.login()
    return _client


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


def send_reply(thread_id: str, text: str, reply_to: Any = None) -> bool:
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
            humanize.sleep_like_human(part)
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


def _prompt_for(ctx: Dict[str, Any], username: str, text: str,
                history: List[Dict[str, Any]]) -> str:
    lines = [f"{h['ig_username']}: {h['text']}" for h in history if h.get("text")]
    convo = "\n".join(lines[-10:])
    return (
        f"GROUP CHAT (purane messages):\n{convo}\n\n"
        f"ABHI @{username} ne bola: {text}\n\n"
        "Isi ka reply de. Chhota rakh (1-2 line), GC ki bhasha me, "
        "AI jaisa bilkul mat lag."
    )


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
    on_incoming_message(
        username=username,
        text=text,
        thread_id=thread_id,
        ig_user_id=str(msg.get("user_id") or ""),
        thread_title=msg.get("title") or None,
    )

    history = database.recent_messages(thread_id, limit=12)
    new_member = database.is_new_member(thread_id, username)

    ctx = build_reply_context(
        text=text,
        username=username,
        thread_id=thread_id,
        bot_username=config.IG_USERNAME,
        recent_texts=[h["text"] for h in history if h.get("text")],
        recent_usernames=[h["ig_username"] for h in history],
        is_new_member=new_member,
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

    if ctx.get("canned_reply"):
        send_reply(thread_id, ctx["canned_reply"], reply_to)
        return

    route = ctx.get("route") or "banter"
    if open_mode and ctx["reason"] == "open_mode":
        route = "banter"        # casual bakchodi = sasta model

    system = ctx["system_extra"]
    reply = router.chat(
        route,
        system,
        _prompt_for(ctx, username, text, history),
        max_tokens=260,
    )
    if reply:
        send_reply(thread_id, reply.strip().strip('"'), reply_to)
    else:
        logger.error("[IG] koi model reply nahi de paya — keys check kar")


# --------------------------------------------------------------- poll


def _thread_allowed(thread_id: str) -> bool:
    return not config.IG_ALLOWED_THREADS or str(thread_id) in config.IG_ALLOWED_THREADS


def _fetch_new() -> List[Dict[str, Any]]:
    cl = login()
    out: List[Dict[str, Any]] = []
    me = (config.IG_USERNAME or "").lower()

    threads = cl.direct_threads(amount=config.IG_MAX_THREADS)
    for th in threads:
        tid = str(th.id)
        if not _thread_allowed(tid):
            continue
        by_id = {str(u.pk): u for u in (th.users or [])}
        title = th.thread_title or ""
        for m in reversed(th.messages or []):
            if getattr(m, "item_type", "text") != "text" or not getattr(m, "text", ""):
                continue
            user = by_id.get(str(m.user_id))
            uname = (getattr(user, "username", "") or "").lower()
            if not uname or uname == me:
                continue
            out.append({
                "id": str(m.id),
                "thread_id": tid,
                "title": title,
                "username": uname,
                "user_id": str(m.user_id),
                "obj": m,
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

    while not ev.is_set():
        # FORCE STOP: poll bhi mat kar, bas idle rehkar TG panel ka wait.
        if runtime_state.is_dead():
            ev.wait(5)
            continue
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
