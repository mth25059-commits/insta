"""
Eve v7 — Telegram control panel (poora control yahi hai).

UX:
  * Neeche hamesha ek PERMANENT KEYBOARD rehta hai (typing ki zarurat nahi).
  * Har menu ek hi message me "edit" hota hai — chat spam nahi hota.
  * Har screen pe breadcrumb + chhota explain line.
  * Jab bot kuch poochhta hai to ❌ CANCEL button milta hai.
  * ❓ HELP me har button ka matlab likha hai.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

import config
from intelligence import (api_pool, panel_store, preference, runtime_state,
                          tones)
from intelligence import member_match
from storage import database

logger = logging.getLogger("eve.tg")

API = "https://api.telegram.org/bot{token}/{method}"
_pending: Dict[int, Dict[str, Any]] = {}     # chat_id -> {action, data}
_panel_msg: Dict[int, int] = {}              # chat_id -> panel message_id


# ------------------------------------------------------------- transport

def _api(method: str, **payload) -> Dict[str, Any]:
    try:
        r = requests.post(API.format(token=config.TG_BOT_TOKEN, method=method),
                          json=payload, timeout=70)
        return r.json()
    except Exception as e:                              # network hiccup
        logger.warning("[TG] %s failed: %s", method, e)
        return {"ok": False}


def send(chat_id: int, text: str, keyboard: Optional[List[List[Dict]]] = None,
         persistent: bool = False) -> Optional[int]:
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text[:4000],
                               "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    elif persistent:
        payload["reply_markup"] = reply_keyboard()
    res = _api("sendMessage", **payload)
    return (res.get("result") or {}).get("message_id")


def screen(chat_id: int, text: str, keyboard: List[List[Dict]],
           message_id: Optional[int] = None) -> None:
    """Panel ko usi message me update karo; na ho paye to naya bhej do."""
    mid = message_id or _panel_msg.get(chat_id)
    if mid:
        res = _api("editMessageText", chat_id=chat_id, message_id=mid,
                   text=text[:4000], disable_web_page_preview=True,
                   reply_markup={"inline_keyboard": keyboard})
        if res.get("ok"):
            _panel_msg[chat_id] = mid
            return
    new_id = send(chat_id, text, keyboard)
    if new_id:
        _panel_msg[chat_id] = new_id


def _btn(text: str, data: str) -> Dict[str, str]:
    return {"text": text, "callback_data": data}


def _back(data: str = "menu") -> List[Dict]:
    return [_btn("⬅️ BACK", data), _btn("🏠 HOME", "menu")]


def reply_keyboard() -> Dict[str, Any]:
    """Neeche fix rehne wala keyboard — bina slash command ke sab kuch."""
    return {
        "keyboard": [
            [{"text": "🎛 PANEL"}, {"text": "📊 STATUS"}],
            [{"text": "▶️ START"}, {"text": "⏸ STOP"}],
            [{"text": "🚀 FORCE START"}, {"text": "🛑 FORCE STOP"}],
            [{"text": "🔥 FIRE"}, {"text": "❓ HELP"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Button dabao — likhne ki zarurat nahi",
    }


def register_commands() -> None:
    _api("setMyCommands", commands=[
        {"command": "panel", "description": "🎛 Control panel kholo"},
        {"command": "status", "description": "📊 Sab kuch ek screen me"},
        {"command": "help", "description": "❓ Har button ka matlab"},
        {"command": "cancel", "description": "❌ Chalu sawaal cancel karo"},
        {"command": "claimadmin", "description": "👑 Khud ko admin banao"},
    ])
    _api("setChatMenuButton", menu_button={"type": "commands"})


# ------------------------------------------------------------------ auth

def _admins() -> List[str]:
    ids = [str(x) for x in (config.TG_ADMIN_IDS or [])]
    from intelligence.aihumara_state import get_tg_admin_id
    extra = get_tg_admin_id()
    if extra and extra not in ids:
        ids.append(extra)
    return ids


def _is_admin(user_id: Any) -> bool:
    a = _admins()
    return not a or str(user_id) in a


# ------------------------------------------------------------------- UI

def main_menu() -> List[List[Dict]]:
    m = runtime_state.get_mode()
    tick = lambda x: " ✅" if m == x else ""
    return [
        [_btn("🚀 FORCE START" + tick("force_start"), "m:force_start"),
         _btn("🛑 FORCE STOP" + tick("force_stop"), "m:force_stop")],
        [_btn("▶️ START" + tick("start"), "m:start"),
         _btn("⏸ STOP" + tick("stop"), "m:stop")],
        [_btn("🔥 FIRE: " + ("ON" if tones.fire_on() else "OFF"), "fire:toggle"),
         _btn(("🔒 FILTER ON" if tones.filter_on() else "🔓 UNFILTERED"), "tone:togglefilter")],
        [_btn("🔑 API KEYS", "api:menu"), _btn("🎯 PREFERENCE", "pref:menu")],
        [_btn("🎭 TONE", "tone:menu"), _btn("🎯 TRIGGER", "trig:menu")],
        [_btn("🧠 MEMORY", "mem:menu"), _btn("🏷 NICKNAME", "nick:menu")],
        [_btn("👑 IG ADMIN", "admin:menu"), _btn("📚 GC / MEMBERS", "st:gc")],
        [_btn("📊 STATUS", "st:show"), _btn("❓ HELP", "help:menu")],
    ]


def status_text() -> str:
    return (
        "🤖 EVE — CONTROL PANEL\n"
        "────────────────────\n"
        f"MODE: {runtime_state.status_line()}\n\n"
        f"{tones.report()}\n\n"
        f"{panel_store.report()}\n\n"
        f"{preference.report()}\n\n"
        f"{api_pool.usage_report()}\n"
        "────────────────────\n"
        "Neeche button dabao. Kuch samajh na aaye → ❓ HELP"
    )


# ------------------------------------------------------------------ help

HELP_PAGES: Dict[str, str] = {
    "modes": (
        "▶️ RUN MODES\n\n"
        "🚀 FORCE START — pehli setup ke baad ye dabao. Polling + learning + "
        "open reply, sab ON. Bot zinda.\n\n"
        "▶️ START — har message ka reply, bina mention ke. Zyadatar Groq "
        "(sasta); factual/debate mile to khud Opus pe shift.\n\n"
        "⏸ STOP — reply sirf nickname/mention/trigger pe. Learning chalu "
        "rehti hai (chup chaap sab padhta rehta hai).\n\n"
        "🛑 FORCE STOP — sab band: reply, learning, polling. Full off.\n\n"
        "🔥 FIRE — START ka hard version: har banda, har msg, koi condition "
        "nahi. Off karo to wapas normal."
    ),
    "api": (
        "🔑 API KEYS\n\n"
        "Provider chuno → ➕ ADD KEY → ek message me jitni chaahe keys "
        "(ek line = ek key, 100 bhi chalengi).\n\n"
        "• Har key add hote hi LIVE TEST hoti hai. Dead key reject: "
        "'HTTP 401' bolke save hi nahi hoti.\n"
        "• Per-key limit (default 2100 req) — limit hit → key #2 → #3 → "
        "loop me wapas #1.\n"
        "• Beech me 401/429 aaya → turant next key. Provider hi mar gaya → "
        "PREFERENCE ka fallback provider.\n"
        "• ♻️ Reset counters — sab keys ka usage 0.\n"
        "• Key pe ❌ dabao → wo key delete."
    ),
    "pref": (
        "🎯 PREFERENCE (kaam ke hisaab se model)\n\n"
        "Har task pe click karke provider badlo:\n"
        "• Normal chat → Groq (sasta, fast)\n"
        "• Roast / gali → Groq\n"
        "• Debate → Opus 4.8 (AgentRouter)\n"
        "• Facts / political → Opus\n"
        "• /help (IG pe admin ka SOS) → Opus\n\n"
        "Fallback chain auto hai: opus fail → anthropic → groq."
    ),
    "tone": (
        "🎭 TONE + FILTER\n\n"
        "TONE = bot ka default mizaaj (savage, flirty, dirty, friendly, "
        "sarcastic, abusive…). Trigger wale user pe uska apna tone chalta "
        "hai, baaki sab pe ye.\n\n"
        "🔓 UNFILTERED — full gaali/roast, koi disclaimer nahi.\n"
        "🔒 FILTER ON — halki gaali, debate me clean-sharp."
    ),
    "trig": (
        "🎯 TRIGGER\n\n"
        "Kisi ek banda ko fix tone me target karna.\n"
        "➕ ADD → `@username` bhejo → galat likha to bot khud closest "
        "match suggest karega ('shayad @xyz') → phir tone chuno.\n"
        "Us user ke har msg pe wahi tone chalega.\n"
        "❌ = ek trigger off, 🚫 = saare off."
    ),
    "mem": (
        "🧠 MEMORY\n\n"
        "Pehle se log set kar do:\n"
        "`@username | naam | boy/girl | note`\n"
        "example: `@rihu | Riya | girl | flirty baat karti hai`\n\n"
        "Baaki bot khud seekhta rehta hai — kaun kaise baat karta hai, "
        "kiska kya naam hai. Sab Drive pe backup hota hai, VPS badlo to "
        "bhi kuch nahi bhoolta."
    ),
    "nick": (
        "🏷 NICKNAME\n\n"
        "Jo naam GC me lene par bot reply kare (jaise 'chotu'). "
        "Ek se zyada nickname chal sakte hain. STOP mode me sirf inhi "
        "naamon ya mention pe reply aata hai."
    ),
    "admin": (
        "👑 IG ADMIN\n\n"
        "IG username + real naam (jaise Dhruv) set karo.\n"
        "• Sirf isi banda ke /order aur /help chalenge.\n"
        "• `/order shut up` → 'malik ki agya' bolke chup.\n"
        "• `/help` → Opus aata hai, poori thread padhke admin ka side "
        "leta hai aur opponent ko facts se phaad deta hai.\n"
        "• Koi Dhruv ko bura bole → bot khud roast kar dega.\n"
        "• Koi aur command de → 'aukat hai teri?' wala rude reply."
    ),
}


def _help_menu() -> List[List[Dict]]:
    return [
        [_btn("▶️ Run modes", "help:modes"), _btn("🔑 API keys", "help:api")],
        [_btn("🎯 Preference", "help:pref"), _btn("🎭 Tone/Filter", "help:tone")],
        [_btn("🎯 Trigger", "help:trig"), _btn("🧠 Memory", "help:mem")],
        [_btn("🏷 Nickname", "help:nick"), _btn("👑 IG admin", "help:admin")],
        [_btn("🏠 HOME", "menu")],
    ]


# ------------------------------------------------------------- sub-menus

def _api_menu() -> List[List[Dict]]:
    rows = [[_btn(f"{meta['label']}  ({len(api_pool.list_keys(p))} keys)", f"api:p:{p}")]
            for p, meta in api_pool.PROVIDERS.items()]
    rows.append([_btn(f"⚙️ Per-key limit: {api_pool.key_limit()}", "api:limit"),
                 _btn("♻️ Reset", "api:reset")])
    rows.append([_btn("❓ Ye kaise kaam karta hai", "help:api")])
    rows.append(_back())
    return rows


def _provider_menu(p: str) -> List[List[Dict]]:
    keys = api_pool.list_keys(p)
    rows = [[_btn("➕ ADD KEY (ek ya 100)", f"api:add:{p}")]]
    for i, k in enumerate(keys):
        flag = "DEAD" if k.get("dead") else f"{k.get('used', 0)}/{api_pool.key_limit()}"
        rows.append([_btn(f"{i+1}. {api_pool.mask(k['key'])} [{flag}] ❌", f"api:del:{p}:{i}")])
    rows.append(_back("api:menu"))
    return rows


def _pref_menu() -> List[List[Dict]]:
    rows = [[_btn(f"{preference.TASK_LABEL[t]} → {preference.get(t)['provider']}", f"pref:t:{t}")]
            for t in preference.TASKS]
    rows.append([_btn("❓ Explain", "help:pref")])
    rows.append(_back())
    return rows


def _pref_provider_menu(task: str) -> List[List[Dict]]:
    rows = [[_btn(meta["label"], f"pref:set:{task}:{p}")]
            for p, meta in api_pool.PROVIDERS.items()]
    rows.append(_back("pref:menu"))
    return rows


def _tone_menu() -> List[List[Dict]]:
    cur = tones.get_tone()
    items = list(tones.TONES)
    rows = [[_btn(("✅ " if items[i] == cur else "") + items[i], f"tone:set:{items[i]}"),
             *( [_btn(("✅ " if items[i+1] == cur else "") + items[i+1], f"tone:set:{items[i+1]}")]
                if i + 1 < len(items) else [])]
            for i in range(0, len(items), 2)]
    rows.append([_btn(("🔒 FILTER ON" if tones.filter_on() else "🔓 UNFILTERED"),
                      "tone:togglefilter"), _btn("❓ Explain", "help:tone")])
    rows.append(_back())
    return rows


def _trig_menu() -> List[List[Dict]]:
    rows = [[_btn("➕ ADD TRIGGER (@username + tone)", "trig:add")]]
    for u, t in panel_store.triggers().items():
        rows.append([_btn(f"@{u} → {t}  ❌", f"trig:del:{u}")])
    rows.append([_btn("🚫 SAB TRIGGER OFF", "trig:clear"), _btn("❓ Explain", "help:trig")])
    rows.append(_back())
    return rows


def _ask(chat_id: int, action: str, text: str, extra: Optional[Dict] = None,
         keyboard: Optional[List[List[Dict]]] = None) -> None:
    """Kuch input maango — hamesha CANCEL button ke saath."""
    data = {"action": action}
    if extra:
        data.update(extra)
    _pending[chat_id] = data
    kb = keyboard or []
    kb = kb + [[_btn("❌ CANCEL", "cancel")]]
    send(chat_id, text, kb)


# ------------------------------------------------------------- callbacks

def handle_callback(chat_id: int, data: str, user_id: Any,
                    message_id: Optional[int] = None) -> None:
    if not _is_admin(user_id):
        send(chat_id, "Aukat hai teri mujhe command dene ki? 😌")
        return

    def show(text: str, kb: List[List[Dict]]) -> None:
        screen(chat_id, text, kb, message_id)

    if data == "menu":
        _pending.pop(chat_id, None)
        show(status_text(), main_menu()); return
    if data == "cancel":
        _pending.pop(chat_id, None)
        show("❌ Cancel. Kuch nahi badla.", main_menu()); return

    # ---- run modes
    if data == "m:force_start":
        runtime_state.force_start()
        show("🚀 FORCE START — sab system ON, open reply mode.\n\n" + status_text(),
             main_menu())
        try:
            from workers import ig_worker
            ig_worker.mark_live_now()      # purane msg ka backlog reply na ho
            send(chat_id, ig_worker.gc_report_text(), [_back()])
        except Exception as e:
            send(chat_id, f"⚠️ GC report fail: {e}", [_back()])
        return
    if data == "m:force_stop":
        runtime_state.force_stop()
        show("🛑 FORCE STOP — polling, learning, reply sab band.\n\n" + status_text(),
             main_menu()); return
    if data == "m:start":
        runtime_state.set_mode(runtime_state.START)
        show("▶️ START — har message ka reply (bina mention).\n\n" + status_text(),
             main_menu()); return
    if data == "m:stop":
        runtime_state.set_mode(runtime_state.STOP)
        show("⏸ STOP — sirf nickname/mention/trigger pe reply, learning chalu.\n\n"
             + status_text(), main_menu()); return

    # ---- help
    if data == "help:menu":
        show("❓ HELP — kis cheez ke baare me jaanna hai?", _help_menu()); return
    if data.startswith("help:"):
        page = data.split(":", 1)[1]
        if page in HELP_PAGES:
            show(HELP_PAGES[page], [_back("help:menu")]); return

    # ---- api keys
    if data == "api:menu":
        show("🔑 API KEYS\n\n" + api_pool.usage_report(), _api_menu()); return
    if data.startswith("api:p:"):
        p = data.split(":")[2]
        show(f"🔑 {api_pool.PROVIDERS[p]['label']} keys", _provider_menu(p)); return
    if data.startswith("api:add:"):
        p = data.split(":")[2]
        _ask(chat_id, "api_add",
             f"{api_pool.PROVIDERS[p]['label']} ki key(s) bhej.\n"
             "Ek line me ek key — 100 keys ek saath bhi chalengi.\n"
             "Har key live test hogi, galat wali reject ho jayegi.",
             {"provider": p}); return
    if data.startswith("api:del:"):
        _, _, p, i = data.split(":")
        api_pool.remove_key(p, int(i))
        show("Key hata di.", _provider_menu(p)); return
    if data == "api:limit":
        _ask(chat_id, "api_limit", "Per-key request limit bhej (jaise 2100)."); return
    if data == "api:reset":
        api_pool.reset_usage()
        show("♻️ Counters reset.\n\n" + api_pool.usage_report(), _api_menu()); return

    # ---- preference
    if data == "pref:menu":
        show("🎯 PREFERENCE\n\n" + preference.report(), _pref_menu()); return
    if data.startswith("pref:t:"):
        t = data.split(":")[2]
        show(f"{preference.TASK_LABEL[t]} ke liye provider chun:",
             _pref_provider_menu(t)); return
    if data.startswith("pref:set:"):
        _, _, t, p = data.split(":")
        preference.set_pref(t, p)
        show("✅ Set ho gaya.\n\n" + preference.report(), _pref_menu()); return

    # ---- tone / filter / fire
    if data == "tone:menu":
        show("🎭 TONE\n\n" + tones.report(), _tone_menu()); return
    if data.startswith("tone:set:"):
        tones.set_tone(data.split(":")[2])
        show("🎭 TONE\n\n" + tones.report(), _tone_menu()); return
    if data == "tone:togglefilter":
        tones.set_filter(not tones.filter_on())
        show(tones.report() + "\n\n" + status_text(), main_menu()); return
    if data == "fire:toggle":
        on = tones.set_fire(not tones.fire_on())
        if on:
            runtime_state.set_mode(runtime_state.START)
        show(f"🔥 Ultimate fire {'ON — sabko reply, bina mention' if on else 'OFF'}\n\n"
             + status_text(), main_menu()); return

    # ---- triggers
    if data == "trig:menu":
        show("🎯 TRIGGER — us user ke har message pe fix tone me reply.", _trig_menu()); return
    if data == "trig:add":
        _ask(chat_id, "trig_user", "Kis user pe trigger? `@username` bhej."); return
    if data.startswith("trig:del:"):
        panel_store.clear_trigger(data.split(":")[2])
        show("Trigger off.", _trig_menu()); return
    if data == "trig:clear":
        panel_store.clear_all_triggers()
        show("Saare trigger off.", _trig_menu()); return
    if data.startswith("trig:pick:"):
        u = data.split(":", 2)[2]
        _pending[chat_id] = {"action": "trig_tone", "username": u}
        rows = [[_btn(t, f"trig:tone:{t}")] for t in tones.TONES]
        send(chat_id, f"@{u} ke liye tone chun:", rows + [[_btn("❌ CANCEL", "cancel")]])
        return
    if data.startswith("trig:tone:"):
        tone = data.split(":")[2]
        p = _pending.pop(chat_id, {})
        if p.get("username"):
            panel_store.set_trigger(p["username"], tone)
            show(f"✅ @{p['username']} → {tone} trigger ON.", _trig_menu())
        else:
            show("Trigger session expire ho gaya, dobara try kar.", _trig_menu())
        return

    # ---- memory
    if data == "mem:menu":
        mem = panel_store.memory()
        txt = "\n".join(f"@{u}: {v}" for u, v in mem.items()) or "Abhi koi memory nahi."
        show("🧠 MEMBER MEMORY\n\n" + txt,
             [[_btn("➕ ADD / EDIT", "mem:add"), _btn("❓ Explain", "help:mem")], _back()])
        return
    if data == "mem:add":
        _ask(chat_id, "mem_add",
             "Format bhej:\n`@username | naam | boy/girl | note`\n"
             "Example: `@rihu | Riya | girl | meri class ki, flirty baat karti hai`")
        return

    # ---- nickname
    if data == "nick:menu":
        rows = [[_btn(f"{n}  ❌", f"nick:del:{n}")] for n in panel_store.nicknames()]
        rows = ([[_btn("➕ ADD NICKNAME", "nick:add"), _btn("❓ Explain", "help:nick")]]
                + rows + [_back()])
        show("🏷 NICKNAME — in naamon pe bot reply karta hai:", rows); return
    if data == "nick:add":
        _ask(chat_id, "nick_add", "Naya nickname bhej (jaise: chotu)."); return
    if data.startswith("nick:del:"):
        panel_store.remove_nickname(data.split(":", 2)[2])
        rows = [[_btn(f"{n}  ❌", f"nick:del:{n}")] for n in panel_store.nicknames()]
        show("Hata diya.", [[_btn("➕ ADD NICKNAME", "nick:add")]] + rows + [_back()]); return

    # ---- ig admin
    if data == "admin:menu":
        show("👑 IG ADMIN\n\n" + panel_store.report(),
             [[_btn("Set IG admin username", "admin:user")],
              [_btn("Set admin ka naam", "admin:name")],
              [_btn("❓ Explain", "help:admin")], _back()]); return
    if data == "admin:user":
        _ask(chat_id, "admin_user", "Admin ka IG username bhej (@ ke saath)."); return
    if data == "admin:name":
        _ask(chat_id, "admin_name", "Admin ka real naam bhej (jaise Dhruv)."); return

    # ---- status
    if data == "st:show":
        show(status_text(), main_menu()); return
    if data == "st:gc":
        show(_gc_report(), [[_btn("🔄 Refresh", "st:gc")], _back()]); return

    show("Unknown button.", main_menu())


def _gc_report() -> str:
    try:
        with database.get_connection() as conn:
            rows = conn.execute(
                "SELECT thread_id, COALESCE(thread_title,'') t,"
                " COUNT(*) c, COUNT(DISTINCT ig_username) u"
                " FROM MESSAGES GROUP BY thread_id ORDER BY c DESC LIMIT 15"
            ).fetchall()
    except Exception as e:
        return f"DB error: {e}"
    if not rows:
        return "Abhi koi GC data nahi — bot ne kuch padha hi nahi."
    out = ["📚 GC LIST"]
    for r in rows:
        out.append(f"• {r['t'] or r['thread_id']} — {r['u']} member, {r['c']} msg")
    return "\n".join(out)


# --------------------------------------------------------- text answers

def handle_pending(chat_id: int, text: str) -> bool:
    p = _pending.get(chat_id)
    if not p:
        return False
    action = p["action"]

    if action == "api_add":
        _pending.pop(chat_id, None)
        added, bad = 0, []
        for line in [x.strip() for x in text.splitlines() if x.strip()]:
            res = api_pool.add_key(p["provider"], line)
            if res["ok"]:
                added += 1
            else:
                bad.append(f"{api_pool.mask(line)}: {res['message']}")
        msg = f"✅ {added} key add hui."
        if bad:
            msg += "\n❌ Reject:\n" + "\n".join(bad[:10])
        send(chat_id, msg, _provider_menu(p["provider"]))
        return True

    if action == "api_limit":
        _pending.pop(chat_id, None)
        try:
            n = api_pool.set_key_limit(int(text.strip()))
            send(chat_id, f"Per-key limit = {n}", _api_menu())
        except Exception:
            send(chat_id, "Number bhej yaar.", _api_menu())
        return True

    if action == "trig_user":
        res = member_match.resolve(text)
        if not res.get("found"):
            sug = res.get("suggestions") or []
            rows = [[_btn("@" + s, f"trig:pick:{s}")] for s in sug[:5]]
            send(chat_id, "❌ Ye member nahi mila." +
                 ("\nShayad inme se — button dabao:" if sug else
                  "\nDobara `@username` bhej."),
                 rows + [[_btn("❌ CANCEL", "cancel")]])
            return True
        _pending[chat_id] = {"action": "trig_tone", "username": res["username"]}
        rows = [[_btn(t, f"trig:tone:{t}")] for t in tones.TONES]
        send(chat_id, f"@{res['username']} ke liye tone chun:",
             rows + [[_btn("❌ CANCEL", "cancel")]])
        return True

    if action == "mem_add":
        _pending.pop(chat_id, None)
        # `|`, `,` ya sirf space — teeno chalenge.
        raw = text.strip()
        if "|" in raw:
            parts = [x.strip() for x in raw.split("|")]
        elif "," in raw:
            parts = [x.strip() for x in raw.split(",")]
        else:
            parts = raw.split(None, 3)
        parts = [p for p in parts if p]
        if not parts:
            send(chat_id, "Format: `@username | naam | boy/girl | note`")
            return True
        res = member_match.resolve(parts[0])
        if not res.get("found"):
            sug = res.get("suggestions") or []
            send(chat_id, "❌ Ye member nahi mila." +
                 ("\nShayad: " + ", ".join("@" + s for s in sug) if sug else "") +
                 "\nSahi username ke saath dobara bhej.",
                 [[_btn("➕ DOBARA", "mem:add")], _back()])
            return True
        uname = res["username"]
        gender = ""
        note_from = 2
        if len(parts) > 2 and parts[2].lower() in ("boy", "girl", "male", "female", "m", "f"):
            gender = parts[2].lower()
            note_from = 3
        note = " ".join(parts[note_from:]).strip() if len(parts) > note_from else ""
        panel_store.set_member(uname,
                               name=parts[1] if len(parts) > 1 else "",
                               gender=gender,
                               note=note)
        saved = panel_store.member(uname)
        send(chat_id,
             f"🧠 Memory save → @{uname}\n"
             f"naam: {saved.get('name') or '—'}\n"
             f"gender: {saved.get('gender') or '—'}\n"
             f"note: {saved.get('note') or '—'}",
             [[_btn("➕ AUR ADD", "mem:add")], _back()])
        return True

    if action == "nick_add":
        _pending.pop(chat_id, None)
        panel_store.add_nickname(text)
        send(chat_id, f"🏷 Nicknames: {', '.join(panel_store.nicknames())}",
             [[_btn("➕ AUR ADD", "nick:add")], _back()])
        return True

    if action == "admin_user":
        _pending.pop(chat_id, None)
        panel_store.set_ig_admin(username=text)
        send(chat_id, panel_store.report(), [_back()])
        return True

    if action == "admin_name":
        _pending.pop(chat_id, None)
        panel_store.set_ig_admin(name=text.strip())
        send(chat_id, panel_store.report(), [_back()])
        return True

    return False


# ------------------------------------------------------------------ loop

# Neeche wale keyboard ka text -> callback
BUTTON_MAP = {
    "🎛 PANEL": "menu",
    "📊 STATUS": "st:show",
    "▶️ START": "m:start",
    "⏸ STOP": "m:stop",
    "🚀 FORCE START": "m:force_start",
    "🛑 FORCE STOP": "m:force_stop",
    "🔥 FIRE": "fire:toggle",
    "❓ HELP": "help:menu",
}


def handle_message(msg: Dict[str, Any]) -> None:
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id")
    text = (msg.get("text") or "").strip()

    if text.startswith("/claimadmin"):
        from intelligence.aihumara_state import set_tg_admin_id
        if config.TG_ADMIN_IDS and str(user_id) not in _admins():
            send(chat_id, "Aukat hai teri? 😌")
            return
        set_tg_admin_id(str(user_id))
        send(chat_id, f"👑 Admin set: {user_id}", persistent=True)
        _panel_msg.pop(chat_id, None)
        screen(chat_id, status_text(), main_menu())
        return

    if not _is_admin(user_id):
        send(chat_id, "Aukat hai teri mujhe command dene ki? 😌")
        return

    if text in ("/start", "/panel", "/menu"):
        _pending.pop(chat_id, None)
        send(chat_id, "🎛 Panel neeche ke buttons se chalta hai — "
                      "likhne ki zarurat nahi.", persistent=True)
        _panel_msg.pop(chat_id, None)
        screen(chat_id, status_text(), main_menu())
        return
    if text in ("/cancel",):
        _pending.pop(chat_id, None)
        send(chat_id, "❌ Cancel.", main_menu())
        return
    if text in ("/help",):
        send(chat_id, "❓ HELP — kis cheez ke baare me jaanna hai?", _help_menu())
        return
    if text == "/status":
        _panel_msg.pop(chat_id, None)
        screen(chat_id, status_text(), main_menu())
        return

    # neeche wale permanent keyboard ka button
    if text in BUTTON_MAP:
        _panel_msg.pop(chat_id, None)
        handle_callback(chat_id, BUTTON_MAP[text], user_id)
        return

    if handle_pending(chat_id, text):
        return

    send(chat_id, "Neeche ke buttons use kar 👇 ya 🎛 PANEL dabao.", persistent=True)


def main() -> None:
    if not config.TG_BOT_TOKEN:
        raise SystemExit("TG_BOT_TOKEN missing")
    register_commands()
    logger.info("[TG] panel live")
    offset = 0
    while True:
        try:
            res = _api("getUpdates", offset=offset, timeout=50,
                       allowed_updates=["message", "callback_query"])
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    _api("answerCallbackQuery", callback_query_id=cq["id"])
                    handle_callback(cq["message"]["chat"]["id"],
                                    cq.get("data", ""), cq["from"]["id"],
                                    cq["message"]["message_id"])
        except Exception:
            logger.exception("[TG] loop error")
            time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    database.init_db()
    main()
