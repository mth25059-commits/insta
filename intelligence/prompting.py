"""
Eve v7 — prompt builder (IG + TG dono isi ko use karte hain).

Kaam:
  * transcript banata hai jisme har bande ka ASLI NAAM dikhta hai (agar pata
    hai), warna @username.
  * "kya chal raha tha / summary" wale sawaal pakadta hai aur bot ko bolta hai
    ki kisne kya bola wo point-wise bata.
  * yaad-daasht ke rules daalta hai taaki bot naam ulta-pulta na kare.
  * ek waqt me EK hi bande ki baat pakadta hai — do logon ki baatein mix nahi.
  * slide/quote (kisi message pe reply) samajhta hai — "iska matlab?" jaise
    sawaal ka jawab us quote ke hisaab se aata hai.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from intelligence import persona, user_facts

# ---------------------------------------------------------------- window
HISTORY_LIMIT = 45          # kitne purane message prompt me jaate hain
USER_PAST_LIMIT = 12        # us bande ki apni purani lines
SUMMARY_LIMIT = 60          # summary maange to itna peeche tak dekhega
THREAD_FOCUS_LIMIT = 10     # us bande ke saath ka apna silsila

_SUMMARY = re.compile(
    r"(kya\s+(chal|ho)\s*(raha|rha|rahi)\s*(hai|h|tha|th)?|kya\s+baat\s+chal|"
    r"summar|summary|batao\s+kya\s+hua|kya\s+hua\s+yahan|recap|"
    r"kisne\s+kya\s+(bola|kaha)|topic\s+kya|scene\s+kya)", re.I)

_MEANING = re.compile(
    r"(matlab|mtlb|meaning|kya\s+bola|kya\s+kaha|ye\s+kya\s+hai|translate|"
    r"iska\s+kya|samjha\s*de|explain)", re.I)


def is_summary_query(text: str) -> bool:
    return bool(_SUMMARY.search(text or ""))


def is_meaning_query(text: str) -> bool:
    return bool(_MEANING.search(text or ""))


# ----------------------------------------------------------- name lookup

def display_name(username: str) -> str:
    """Naam pata hai to 'Shivam (@user)', warna sirf '@user'."""
    u = (username or "").lstrip("@")
    if not u:
        return "@unknown"
    name = (user_facts.facts(u) or {}).get("naam", "").strip()
    return f"{name} (@{u})" if name else f"@{u}"


def transcript(history: List[Dict[str, Any]], limit: int,
               bot_label: str = "MAIN (Eve)") -> str:
    lines: List[str] = []
    seen_last = ""
    for h in history[-limit:]:
        txt = (h.get("text") or "").strip()
        if not txt or txt == seen_last:
            continue
        seen_last = txt
        who = bot_label if h.get("is_bot") else display_name(h.get("ig_username", ""))
        lines.append(f"{who}: {txt}")
    return "\n".join(lines) or "(abhi tak kuch nahi)"


def focus_thread(history: List[Dict[str, Any]], username: str,
                 limit: int = THREAD_FOCUS_LIMIT) -> str:
    """Sirf is bande ki lines + unke aas-paas ka bot reply — mix na ho."""
    u = (username or "").lstrip("@").lower()
    picked: List[str] = []
    hist = history[-HISTORY_LIMIT:]
    for i, h in enumerate(hist):
        txt = (h.get("text") or "").strip()
        if not txt:
            continue
        who = (h.get("ig_username") or "").lstrip("@").lower()
        if not h.get("is_bot") and who == u:
            picked.append(f"{display_name(u)}: {txt}")
            nxt = hist[i + 1] if i + 1 < len(hist) else None
            if nxt and nxt.get("is_bot") and nxt.get("text"):
                picked.append(f"MAIN (Eve): {str(nxt['text']).strip()}")
    return "\n".join(picked[-limit * 2:])


def last_bot_line(history: List[Dict[str, Any]]) -> str:
    for h in reversed(history):
        if h.get("is_bot") and h.get("text"):
            return str(h["text"])
    return ""


# --------------------------------------------------------- prompt build

MEMORY_RULES = (
    "YAAD-DAASHT KE PAKKE RULE:\n"
    "1. Upar ka poora transcript tune hi suna hai — usi ka silsila pakad.\n"
    "2. Kisi ne jo naam bataya wo KISKA naam tha ye dhyan rakh. Agar baat ex / "
    "gf / bf / dost ki chal rahi thi aur usne naam bataya, to wo USKA APNA "
    "naam NAHI hai — wo uske ex/dost ka naam hai. Bande ka apna naam sirf tab "
    "maan jab wo khud bole 'mera naam ... hai'.\n"
    "3. Jo baat pehle bata di gayi (naam, ex, plan, mood, city) wo dobara mat "
    "poochh aur ulta mat samajh.\n"
    "4. Confuse ho to guess mat kar — ek chhota clarify sawaal pooch.\n"
    "5. Emotion samajh: banda dukhi hai to mazak mat maar, saath de. Masti "
    "chal rahi ho tabhi roast kar.\n"
    "6. Kal/pehle jo baat hui thi uska reference aa jaye to yaad rakh aur usi "
    "silsile me jod ke bol."
)

FOCUS_RULES = (
    "EK HI BAAT PAKAD (bahut zaroori):\n"
    "- GC me kai log alag-alag topic pe bol rahe hote hain. Tu SIRF us bande "
    "ko jawab de raha hai jiska message abhi aaya hai, aur SIRF uske topic pe.\n"
    "- Dusre logon ki baatein (family talk, unka masla) sirf background hain — "
    "unhe is jawab me mat ghusa, na hi do topic mila ke ek khichdi reply bana.\n"
    "- Agar do log ek saath alag cheez poochh rahe hain to jiska message abhi "
    "hai bas usi ka jawab, dusre ko chhod de."
)

STYLE_RULES = (
    "Rules: insaan jaisa likh, chhote akshar, thoda typo chalega, "
    "AI/assistant jaisa bilkul mat lag, apne aap ko bot mat bol, "
    "emoji zyada se zyada ek."
)


def build_prompt(*, ctx: Dict[str, Any], username: str, text: str,
                 history: List[Dict[str, Any]],
                 user_past: Optional[List[Dict[str, Any]]] = None,
                 is_question: bool = False,
                 quoted_text: str = "",
                 quoted_author: str = "") -> str:
    summary_mode = is_summary_query(text)
    limit = SUMMARY_LIMIT if summary_mode else HISTORY_LIMIT
    convo = transcript(history, limit)

    past = ""
    old = [p.get("text") for p in (user_past or []) if p.get("text")]
    if old:
        past = (f"\n{display_name(username)} NE PEHLE YE BOLA THA (yaad rakh, "
                "isse jod ke baat kar, dobara wahi mat poochh):\n"
                + "\n".join(f"- {t}" for t in old[-USER_PAST_LIMIT:]) + "\n")

    focus = focus_thread(history, username)
    focus_block = (f"\nSIRF {display_name(username)} KE SAATH KI BAAT "
                   f"(isi ka silsila aage badha):\n{focus}\n") if focus else ""

    my_last = [h["text"] for h in history if h.get("is_bot") and h.get("text")][-3:]
    dont_repeat = ("\nMAINE ABHI YE BOLA HAI (inhe dobara mat bolo, na hi inka "
                   "jaisa): " + " | ".join(my_last)) if my_last else ""

    quote_block = ""
    quoted_text = (quoted_text or "").strip()
    if quoted_text:
        qa = display_name(quoted_author) if quoted_author else "kisi"
        quote_block = (
            f"\nISNE SLIDE (reply) KIYA HAI IS MESSAGE PE — {qa} ka message:\n"
            f"\"{quoted_text}\"\n")
        if is_meaning_query(text):
            quote_block += (
                "AUR POOCHH RAHA HAI ISKA MATLAB. Dhyan de: sawaal TERE apne "
                "message pe nahi hai — us quote wali line ka matlab poochha "
                "gaya hai. Agar wo kisi aur bhasha me hai to seedha uska "
                "matlab/translation samjha, saaf aur chhota. Apni pichhli baat "
                "ka jawab mat de.\n")

    if summary_mode:
        job = ("Ye banda poochh raha hai ki abhi tak kya chal raha tha. Upar ke "
               "transcript ka SAAF summary de: kisne kya bola. Jiska asli naam "
               "pata hai use naam se likh, jiska nahi pata use @username se. "
               "3-6 chhoti bullet, sach-sach, kuch mat banaa. Jo nahi hua wo "
               "mat likh.")
    elif ctx.get("route") in ("facts", "debate", "news") or is_question:
        job = ("Ye sawaal/baat serious hai — pehle dimaag laga, phir SEEDHA "
               "sahi jawab de (2-4 line), ek chhota example ya reason ke saath. "
               "Ghuma ke, 'pata nahi' ya galat jawab mat de. Bhasha GC wali "
               "dost jaisi rakh, lecture mat de.")
    else:
        job = ("Casual GC baat hai — samajh ke natural reply de. Line pakad, "
               "usi topic pe bol. Random ya generic ('haha', 'sahi hai') "
               "mat thok, kuch naya add kar. 1-2 line bas.")

    who_line = f"ABHI {display_name(username)} ne bola: {text}"
    if ctx.get("is_admin"):
        who_line += "  <-- ye MALIK hai"

    extras = "\n".join(x for x in (
        persona.knowledge_block(),
        persona.flirt_block(username, bool(ctx.get("is_admin"))),
        persona.jealousy_block(text, username),
    ) if x)

    return (
        f"GROUP CHAT (upar purana, sabse neeche latest):\n{convo}\n"
        f"{focus_block}{past}{quote_block}{dont_repeat}\n\n{who_line}\n\n"
        f"KAAM: {job}\n{FOCUS_RULES}\n{MEMORY_RULES}\n{extras}\n{STYLE_RULES}"
    )
