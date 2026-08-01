"""
Eve v7 — Google Drive brain sync.

eve.db ko Drive ke folder (default naam: EveBrain) me upload karta hai aur
boot pe wahi se restore. Isliye VPS badlo, memory nahi jaati.

Service account JSON: config.GOOGLE_SERVICE_ACCOUNT_JSON
Folder id (optional):  config.GDRIVE_FOLDER_ID  — khali chhodo to naam se dhundhta hai.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

import config
from storage import database

logger = logging.getLogger("eve.drive")

FOLDER_NAME = getattr(config, "GDRIVE_FOLDER_NAME", "") or "EveBrain"
DB_NAME = "eve.db"

_service: Any = None
_folder_id: Optional[str] = None
_stop = threading.Event()


def available() -> bool:
    p = config.GOOGLE_SERVICE_ACCOUNT_JSON
    return bool(p) and Path(p).exists()


def _svc() -> Any:
    global _service
    if _service is not None:
        return _service
    from google.oauth2.service_account import Credentials      # type: ignore
    from googleapiclient.discovery import build                # type: ignore

    creds = Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def folder_id() -> Optional[str]:
    """Config ka id, warna naam se dhundho, warna bana do."""
    global _folder_id
    if _folder_id:
        return _folder_id
    if config.GDRIVE_FOLDER_ID:
        _folder_id = config.GDRIVE_FOLDER_ID
        return _folder_id
    try:
        res = _svc().files().list(
            q=("mimeType='application/vnd.google-apps.folder' and trashed=false"
               f" and name='{FOLDER_NAME}'"),
            fields="files(id,name)", pageSize=10,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files = res.get("files", [])
        if files:
            _folder_id = files[0]["id"]
            logger.info("[DRIVE] purana folder mila: %s", _folder_id)
            return _folder_id
        meta = {"name": FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder"}
        created = _svc().files().create(body=meta, fields="id",
                                        supportsAllDrives=True).execute()
        _folder_id = created["id"]
        logger.info("[DRIVE] naya folder banaya: %s", _folder_id)
        return _folder_id
    except Exception as e:
        logger.warning("[DRIVE] folder fail: %s", e)
        return None


def _find_db() -> Optional[str]:
    fid = folder_id()
    if not fid:
        return None
    res = _svc().files().list(
        q=f"'{fid}' in parents and name='{DB_NAME}' and trashed=false",
        fields="files(id,name,modifiedTime)", pageSize=5,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def restore() -> bool:
    """Drive pe purana brain hai to local eve.db replace kar do."""
    if not available():
        logger.info("[DRIVE] service account nahi — local brain hi chalega")
        return False
    try:
        from googleapiclient.http import MediaIoBaseDownload    # type: ignore
        file_id = _find_db()
        if not file_id:
            logger.info("[DRIVE] purana brain nahi mila — naya banega")
            return False
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, _svc().files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = dl.next_chunk()
        path = database.db_path()
        database.reset_thread_connection()
        path.write_bytes(buf.getvalue())
        logger.info("[DRIVE] ✓ purana brain restore ho gaya (%s bytes)",
                    path.stat().st_size)
        return True
    except Exception as e:
        logger.warning("[DRIVE] restore fail: %s", e)
        return False


def push() -> bool:
    """Local eve.db Drive pe bhej do (update ya create)."""
    if not available():
        return False
    try:
        from googleapiclient.http import MediaFileUpload        # type: ignore
        path = database.db_path()
        if not path.exists():
            return False
        media = MediaFileUpload(str(path), resumable=False)
        file_id = _find_db()
        if file_id:
            _svc().files().update(fileId=file_id, media_body=media,
                                  supportsAllDrives=True).execute()
        else:
            fid = folder_id()
            if not fid:
                return False
            _svc().files().create(
                body={"name": DB_NAME, "parents": [fid]},
                media_body=media, fields="id", supportsAllDrives=True,
            ).execute()
        logger.info("[DRIVE] ✓ brain backup ho gaya")
        return True
    except Exception as e:
        msg = str(e)
        if "storageQuota" in msg or "storage quota" in msg:
            logger.warning(
                "[DRIVE] push fail: service account ka apna storage 0 hai. "
                "Fix: '%s' folder me khud se ek khali file '%s' upload kar do "
                "(ya Shared Drive use karo) — uske baad Eve usi file ko update "
                "karta rahega aur backup chalu ho jayega.", FOLDER_NAME, DB_NAME)
        else:
            logger.warning("[DRIVE] push fail: %s", msg)
        return False



# ------------------------------------------------------- background loop


def start_background() -> None:
    if not available():
        return

    def _loop() -> None:
        while not _stop.is_set():
            _stop.wait(max(60, config.DRIVE_SYNC_INTERVAL))
            if _stop.is_set():
                break
            push()

    threading.Thread(target=_loop, name="drive-sync", daemon=True).start()
    logger.info("[DRIVE] auto-backup har %ss", config.DRIVE_SYNC_INTERVAL)


def stop_background(final_push: bool = True) -> None:
    _stop.set()
    if final_push:
        push()


def status() -> str:
    if not available():
        return "Drive: OFF (service account JSON nahi mila)"
    fid = folder_id() or "—"
    return (f"Drive: ON\nFolder: {FOLDER_NAME} ({fid})\n"
            f"Auto-backup: har {config.DRIVE_SYNC_INTERVAL}s\n"
            f"Last check: {time.strftime('%H:%M:%S')}")
