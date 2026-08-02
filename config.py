"""
Eve v7 — central config. Sab kuch .env se aata hai.

.env file project root me rakho (dekh .env.example).
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_env() -> None:
    """Chhota sa .env loader — python-dotenv ki zarurat nahi."""
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_env()


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


# ------------------------------------------------------------- storage
DB_PATH = _get("DB_PATH", str(BASE_DIR / "eve.db"))
SESSION_PATH = _get("IG_SESSION_PATH", str(BASE_DIR / "ig_session.json"))

# ------------------------------------------------------------ telegram
TG_BOT_TOKEN = _get("TG_BOT_TOKEN")
TG_ADMIN_IDS = [x.strip() for x in _get("TG_ADMIN_IDS").replace(" ", ",").split(",") if x.strip()]

# ----------------------------------------------------------- instagram
IG_USERNAME = _get("IG_USERNAME")
IG_PASSWORD = _get("IG_PASSWORD")
IG_POLL_SECONDS = int(_get("IG_POLL_SECONDS", "5") or 5)
IG_MAX_THREADS = int(_get("IG_MAX_THREADS", "15") or 15)
IG_MIN_DELAY = float(_get("IG_MIN_DELAY", "1.5") or 1.5)
IG_MAX_DELAY = float(_get("IG_MAX_DELAY", "4.0") or 4.0)
IG_ALLOWED_THREADS = [t for t in _get("IG_ALLOWED_THREADS").split(",") if t.strip()]

# ---------------------------------------------------------------- keys
GROQ_API_KEYS = _get("GROQ_API_KEYS")
GROQ_API_KEY = _get("GROQ_API_KEY")
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_API_KEYS = _get("ANTHROPIC_API_KEYS")
AGENTROUTER_KEY = _get("AGENTROUTER_KEY")
AGENTROUTER_API_KEY = _get("AGENTROUTER_API_KEY")
AGENTROUTER_BASE = _get("AGENTROUTER_BASE", "https://agentrouter.org/v1")
AGENTROUTER_MODEL = _get("AGENTROUTER_MODEL", "claude-opus-4-8")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY")
OPENROUTER_API_KEYS = _get("OPENROUTER_API_KEYS")

# --------------------------------------------------------------- drive
GOOGLE_SERVICE_ACCOUNT_JSON = _get("GOOGLE_SERVICE_ACCOUNT_JSON")
GDRIVE_FOLDER_ID = _get("GDRIVE_FOLDER_ID")
GDRIVE_FOLDER_NAME = _get("GDRIVE_FOLDER_NAME", "EveBrain")
DRIVE_SYNC_INTERVAL = int(_get("DRIVE_SYNC_INTERVAL", "900") or 900)
