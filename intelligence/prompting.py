"""
Eve v7 — prompt builder (IG + TG dono isi ko use karte hain).

Kaam:
  * transcript banata hai jisme har bande ka ASLI NAAM dikhta hai (agar pata
    hai), warna @username.
  * "kya chal raha tha / summary" wale sawaal pakadta hai aur bot ko bolta hai
    ki kisne kya bola wo point-wise bata.
  * yaad-daasht ke rules daalta hai taaki bot naam ulta-pulta na kare.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from intelligence import user_facts

# ---------------------------------------------------------------- window
HISTORY_LIMIT = 45          # kitne purane message prompt me jaate hain
USER_PAST_LIMIT = 12        # us bande ki apni purani lines
SUMMARY_LIMIT = 60          # summary maange to itna peeche tak dekhega

_SUMMARY = re.compile(
    r"(kya\s+(chal|ho)\s*(raha|rha|rahi)\s*(hai|h|tha|th)?|kya\s+baat\s+chal|"
    r"summar|summary|batao\s+kya\s+hua|kya\s+hua\s+yahan|recap|"
    r"kisne\s+kya\s+(bola|kaha)|topic\s+kya|scene\s+kya)", re.I)


def is_summary_query(text: str) -> bool:
    return bool(_SUMMARY.search(text or ""))


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
    "chal rahi ho tabhi roast kar."
)

STYLE_RULES = (
    "Rules: insaan jaisa likh, chhote akshar, thoda typo chalega, "
    "AI/assistant jaisa bilkul mat lag, apne aap ko bot mat bol, "
    "emoji zyada se zyada ek."
)


def build_prompt(*, ctx: Dict[str, Any], username: str, text: str,
                 history: List[Dict[str, Any]],
                 user_past: Optional[List[Dict[str, Any]]] = None,
                 is_question: bool = False) -> str:
    summary_mode = is_summary_query(text)
    limit = SUMMARY_LIMIT if summary_mode else HISTORY_LIMIT
    convo = transcript(history, limit)

    past = ""
    old = [p.get("text") for p in (user_past or []) if p.get("text")]
    if old:
        past = (f"\n{display_name(username)} NE PEHLE YE BOLA THA (yaad rakh, "
                "isse jod ke baat kar, dobara wahi mat poochh):\n"
                + "\n".join(f"- {t}" for t in old[-USER_PAST_LIMIT:]) + "\n")

    my_last = [h["text"] for h in history if h.get("is_bot") and h.get("text")][-3:]
    dont_repeat = ("\nMAINE ABHI YE BOLA HAI (inhe dobara mat bolo, na hi inka "
                   "jaisa): " + " | ".join(my_last)) if my_last else ""

    if summary_mode:
        job = ("Ye banda poochh raha hai ki abhi tak kya chal raha tha. Upar ke "
               "transcript ka SAAF summary de: kisne kya bola. Jiska asli naam "
               "pata hai use naam se likh, jiska nahi pata use @username se. "
               "3-6 chhoti bullet, sach-sach, kuch mat banaa. Jo nahi hua wo "
               "mat likh.")
    elif ctx.get("route") in ("facts", "debate", "news") or is_question:
        job = ("Ye sawaal/baat serious hai — pehle dimaag laga, phir SEEDHA "
               "jawab de. Ghuma ke ya 'pata nahi' mat bol. Jawab sahi ho, "
               "chhota ho (1-3 line), aur GC ki bhasha me ho.")
    else:
        job = ("Casual GC baat hai — samajh ke natural reply de. Line pakad, "
               "usi topic pe bol. Random ya generic ('haha', 'sahi hai') "
               "mat thok, kuch naya add kar. 1-2 line bas.")

    who_line = f"ABHI {display_name(username)} ne bola: {text}"
    if ctx.get("is_admin"):
        who_line += "  <-- ye MALIK hai"

    return (
        f"GROUP CHAT (upar purana, sabse neeche latest):\n{convo}\n"
        f"{past}{dont_repeat}\n\n{who_line}\n\n"
        f"KAAM: {job}\n{MEMORY_RULES}\n{STYLE_RULES}"
    )
