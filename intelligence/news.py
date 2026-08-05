"""
Eve v7 — NEWS (bilkul free, koi API key nahi).

Google News RSS se latest headlines uthata hai. India + Hindi/English dono.

    news.is_news_query(text)  -> True/False
    news.headlines("kerala protest")  -> [{title, source, when}]
    news.block(text)          -> prompt me daalne wala text
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Dict, List
from xml.etree import ElementTree as ET

logger = logging.getLogger("eve.news")

RSS = ("https://news.google.com/rss/search?q={q}+when:7d"
       "&hl=en-IN&gl=IN&ceid=IN:en")
TOP = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_CACHE: Dict[str, tuple] = {}       # query -> (ts, items)
CACHE_TTL = 300                      # 5 min

_NEWS_WORDS = re.compile(
    r"\b(news|khabar|khabre|headline|breaking|kya hua|kya chal raha|update|"
    r"latest|aaj\s?kal|taza|protest|andolan|riot|dango|hadsa|accident|"
    r"election|chunav|result|match|score|bill|attack|blast|earthquake|"
    r"bhukamp|strike|hartal|scam|arrest|verdict|budget|war|jung)\b", re.I)
_TIMEY = re.compile(r"\b(aaj|today|abhi|kal|yesterday|is hafte|this week|2026)\b", re.I)


def is_news_query(text: str) -> bool:
    t = text or ""
    if not _NEWS_WORDS.search(t):
        return False
    # "news" jaisa saaf word ho, ya time wala hint ho, ya sawal ho
    return bool(re.search(r"\b(news|khabar|khabre|headline|breaking|latest)\b", t, re.I)
                or _TIMEY.search(t) or "?" in t
                or re.search(r"\b(kya|kaise|kab|kitne|batao|bata)\b", t, re.I))


_STOP = {"eve", "babu", "bhai", "yaar", "kya", "hua", "hai", "me", "mein",
         "ka", "ki", "ke", "aaj", "abhi", "batao", "bata", "news", "khabar",
         "khabre", "latest", "breaking", "update", "sun", "na", "to", "toh",
         "the", "what", "happened", "in", "tell", "about", "today"}


def query_from(text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", text or "")
    keep = [w for w in words if w.lower() not in _STOP]
    return " ".join(keep[:6]).strip()


def _fetch(url: str) -> List[Dict[str, str]]:
    import requests
    r = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out: List[Dict[str, str]] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        src = item.findtext("{*}source") or item.findtext("source") or ""
        out.append({
            "title": title,
            "source": (src or "").strip(),
            "when": (item.findtext("pubDate") or "").strip(),
        })
        if len(out) >= 6:
            break
    return out


def headlines(query: str = "") -> List[Dict[str, str]]:
    key = (query or "__top__").lower()
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    url = RSS.format(q=urllib.parse.quote_plus(query)) if query else TOP
    try:
        items = _fetch(url)
    except Exception as e:
        logger.warning("[NEWS] fetch fail: %s", e)
        return []
    if not items and query:
        try:
            items = _fetch(TOP)
        except Exception:
            items = []
    _CACHE[key] = (time.time(), items)
    return items


def block(text: str) -> str:
    """Prompt me chipkane wala latest-news context."""
    items = headlines(query_from(text))
    if not items:
        return ""
    lines = []
    for it in items[:5]:
        src = f" ({it['source']})" if it.get("source") else ""
        lines.append(f"- {it['title']}{src}")
    return ("AAJ KI ASLI KHABREIN (Google News se abhi uthai hui — inhi me se "
            "sach bol, apne se news mat banana):\n" + "\n".join(lines))
