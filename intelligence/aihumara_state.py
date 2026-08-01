"""
Eve v7 — shared key/value state (BOT_STATE table).

IG worker aur TG panel dono isi table ko padhte-likhte hain, isliye panel se
button dabao aur bot turant maan jaata hai.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from storage.database import get_connection

logger = logging.getLogger("eve.state")

_K_TG_ADMIN = "tg_admin_id"
_K_MODEL_FORCE = "model_force"        # default | groq_only | opus_only

MODEL_FORCE_CHOICES = ("default", "groq_only", "opus_only")


def _get(key: str, default: Any = None) -> Any:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM BOT_STATE WHERE key = ?", (key,)
            ).fetchone()
    except Exception as e:
        logger.warning("[STATE] read fail %s: %s", key, e)
        return default
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def _set(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO BOT_STATE (key, value, updated_at)"
            " VALUES (?, ?, datetime('now'))"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = excluded.updated_at",
            (key, payload),
        )


def _del(key: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM BOT_STATE WHERE key = ?", (key,))


# --------------------------------------------------------- TG admin id


def get_tg_admin_id() -> Optional[str]:
    v = _get(_K_TG_ADMIN)
    return str(v) if v else None


def set_tg_admin_id(user_id: str) -> None:
    _set(_K_TG_ADMIN, str(user_id))


def clear_tg_admin_id() -> None:
    _del(_K_TG_ADMIN)


# -------------------------------------------------------- model force


def get_model_force() -> str:
    v = str(_get(_K_MODEL_FORCE, "default") or "default")
    return v if v in MODEL_FORCE_CHOICES else "default"


def set_model_force(value: str) -> None:
    if value not in MODEL_FORCE_CHOICES:
        raise ValueError(f"model force {MODEL_FORCE_CHOICES} me se")
    _set(_K_MODEL_FORCE, value)
