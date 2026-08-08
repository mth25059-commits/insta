"""
React debug — "react nahi ho raha" ka asli reason batata hai.

Chalao:
    python tools/test_react.py

Kya karta hai: GC me aaya last message uthata hai aur us pe 😢 lagane ki
koshish karta hai, phir Telegram ka POORA jawab print karta hai. Bot ke
normal log me ye error chhup jaata hai, yahan saaf dikhega.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import config

EMOJI = "😢"


def api(method: str, **payload):
    url = f"https://api.telegram.org/bot{config.TG_CHAT_BOT_TOKEN}/{method}"
    return requests.post(url, json=payload, timeout=30).json()


def main() -> None:
    if not config.TG_CHAT_BOT_TOKEN:
        print("X TG_CHAT_BOT_TOKEN .env me nahi mila")
        return

    who = api("getMe")
    if not who.get("ok"):
        print(f"X token galat: {who.get('description')}")
        return
    print(f"OK bot = @{who['result'].get('username')}")

    ups = api("getUpdates", limit=20)
    if not ups.get("ok"):
        print(f"X getUpdates fail: {ups.get('description')}")
        return

    msgs = [u["message"] for u in ups.get("result", [])
            if u.get("message") and u["message"].get("text")]
    if not msgs:
        print("X koi recent message nahi mila.\n"
              "  GC me kuch bhejo, phir ye script dobara chalao.\n"
              "  (Agar bot abhi chal raha hai to wo updates kha jaata hai —\n"
              "   pehle bot band karo, phir GC me msg bhejo, phir ye chalao.)")
        return

    m = msgs[-1]
    chat_id = m["chat"]["id"]
    msg_id = m["message_id"]
    print(f"   last msg #{msg_id} in {chat_id}: {m.get('text','')[:40]!r}")

    res = api("setMessageReaction", chat_id=chat_id, message_id=msg_id,
              reaction=[{"type": "emoji", "emoji": EMOJI}])
    print(f"\n   setMessageReaction -> {res}")

    if res.get("ok"):
        print(f"\nOK REACT LAG GAYA — GC me {EMOJI} dekh lo.")
        print("   Matlab react kaam karta hai. Bot me nahi dikh raha to")
        print("   VPS pe naya code pull nahi hua: git pull origin main")
    else:
        d = (res.get("description") or "").lower()
        print(f"\nX REACT FAIL: {res.get('description')}")
        if "not enough rights" in d or "chat_admin" in d:
            print("   -> Bot ko group me ADMIN banao (ya reactions allow karo).")
        elif "reaction is not valid" in d or "invalid" in d:
            print("   -> Group me custom reaction list set hai jisme ye emoji")
            print("      nahi hai. Group Settings > Reactions > All allow karo.")
        elif "message to react not found" in d or "not found" in d:
            print("   -> Message bahut purana ho gaya. GC me naya msg bhej ke")
            print("      turant ye script chalao.")
        else:
            print("   -> Upar wala Telegram error hi asli wajah hai.")


if __name__ == "__main__":
    main()
