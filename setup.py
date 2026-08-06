"""
Eve v7 — First-run setup wizard.

    python setup.py

Ye ek baar chalao (VPS pe). Ye sab kuch pooch ke .env bana dega,
Instagram me login karke session save karega, aur Google Drive me
purani memory (brain) dhundh ke wapas le aayega — agar mili to.
Nahi mili to naya brain folder bana dega.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

BASE = Path(os.environ.get("EVE_HOME", "/root/eve"))
ENV_PATH = Path(__file__).resolve().parent / ".env"


# ----------------------------------------------------------------- helpers
def ask(label: str, default: str = "", secret: bool = False) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        val = (getpass.getpass if secret else input)(f"{label}{hint}: ").strip()
        if not val and default:
            return default
        if val:
            return val
        print("  ! khali nahi chhod sakte")


def yes(label: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    v = input(f"{label} ({d}): ").strip().lower()
    if not v:
        return default
    return v.startswith("y")


def write_env(cfg: dict) -> None:
    lines = [f"{k}={v}" for k, v in cfg.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)
    print(f"\n[OK] .env likh diya -> {ENV_PATH} (chmod 600)")


# ----------------------------------------------------------------- steps
def step_platform(cfg: dict) -> None:
    print("\n=== 0/4  BOT KAHAN CHALEGA? ===")
    print("  1) ig  -> Instagram group chat (default)")
    print("  2) tg  -> Telegram group")
    choice = input("Platform (ig/tg) [ig]: ").strip().lower() or "ig"
    cfg["PLATFORM"] = "tg" if choice.startswith("t") else "ig"


def step_tg_chat(cfg: dict) -> None:
    print("\n=== TELEGRAM GROUP BOT ===")
    print("  Ye control panel wale bot se ALAG bot hona chahiye.")
    print("  @BotFather -> /newbot -> token. Phir BotFather me")
    print("  /setprivacy -> Disable (warna group ke saare msg nahi dikhte).")
    cfg["TG_CHAT_BOT_TOKEN"] = ask("Group wale bot ka token", secret=True)
    cfg["TG_CHAT_ADMIN_IDS"] = ask("Tumhari Telegram user id (malik)")
    cfg["TG_CHAT_ALLOWED_GROUPS"] = input(
        "Group chat id (khali = sab group; @myidbot se milegi): ").strip()


def step_telegram(cfg: dict) -> None:
    print("\n=== 1/4  TELEGRAM CONTROL PANEL ===")
    print("  @BotFather -> /newbot -> token copy karo")
    print("  Apni numeric user id: @userinfobot ko /start bhejo")
    cfg["TG_BOT_TOKEN"] = ask("Telegram bot token", secret=True)
    cfg["TG_ADMIN_IDS"] = ask("Tumhari Telegram user id (comma se multiple)")


def step_instagram(cfg: dict) -> None:
    print("\n=== 2/4  INSTAGRAM LOGIN ===")
    print("  Username + password chahiye (bot account ka).")
    print("  Login SIRF is VPS ke IP se hoga -> session file save hogi,")
    print("  uske baad har restart pe dobara password nahi maangega.")
    user = ask("IG username")
    pwd = ask("IG password", secret=True)
    session = BASE / "ig_session.json"
    cfg["IG_USERNAME"] = user
    cfg["IG_PASSWORD"] = pwd
    cfg["IG_SESSION_PATH"] = str(session)
    cfg["IG_POLL_SECONDS"] = "5"
    cfg["IG_MAX_THREADS"] = "15"
    cfg["IG_MIN_DELAY"] = "1.5"
    cfg["IG_MAX_DELAY"] = "4.0"
    cfg["IG_ALLOWED_THREADS"] = ""

    if not yes("Abhi login test karein?", True):
        return
    try:
        from instagrapi import Client
        from instagrapi.exceptions import TwoFactorRequired
    except ImportError:
        print("  ! instagrapi install nahi hai -> pip install -r requirements.txt")
        return

    cl = Client()
    session.parent.mkdir(parents=True, exist_ok=True)
    if session.exists():
        try:
            cl.load_settings(session)
            cl.login(user, pwd)
            cl.get_timeline_feed()
            print("  [OK] purani session file se login ho gaya")
            return
        except Exception:
            print("  purani session invalid — fresh login")
            cl = Client()
    try:
        cl.login(user, pwd)
    except TwoFactorRequired:
        code = ask("2FA code (authenticator/SMS)")
        cl.login(user, pwd, verification_code=code)
    except Exception as exc:
        print(f"  ! login fail: {exc}")
        print("  Tip: IG app me is IP se ek baar manually login/verify karo, phir dobara chalao.")
        return
    cl.dump_settings(session)
    print(f"  [OK] IG login done, session saved -> {session}")


def step_drive(cfg: dict) -> None:
    print("\n=== 3/4  GOOGLE DRIVE BRAIN (1TB) ===")
    print("  Chahiye: Google Cloud service-account JSON key file.")
    print("  console.cloud.google.com -> IAM -> Service Accounts -> Keys -> JSON")
    print("  Phir Drive me ek folder banao aur us service account ke email ko")
    print("  us folder pe 'Editor' access do. Folder id = URL ka last part.")

    sa = ask("Service account JSON ka full path", str(BASE / "sa.json"))
    cfg["GOOGLE_SERVICE_ACCOUNT_JSON"] = sa
    cfg["DRIVE_SYNC_INTERVAL"] = "900"
    folder = input("Drive folder id (khali chhodo to bot khud dhundhega/banayega): ").strip()
    cfg["GDRIVE_FOLDER_ID"] = folder
    cfg["DB_PATH"] = str(BASE / "eve.db")

    if not Path(sa).exists():
        print(f"  ! {sa} nahi mila — file upload karke dobara setup chala lena.")
        return

    print("\n  Drive me purani memory dhundh raha hoon...")
    try:
        found = _drive_probe(sa, folder, Path(cfg["DB_PATH"]))
    except Exception as exc:
        print(f"  ! Drive check fail: {exc}")
        return
    if found:
        print("  [OK] PURANI MEMORY MIL GAYI — restore kar li. Bot kuch nahi bhoolega.")
    else:
        print("  [OK] Koi purani memory nahi mili — naya brain banaya gaya.")


def _drive_probe(sa_path: str, folder_id: str, db_path: Path) -> bool:
    """Purana eve.db Drive se dhoondh ke restore karo; warna naya folder bana do."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    creds = service_account.Credentials.from_service_account_file(
        sa_path, scopes=["https://www.googleapis.com/auth/drive"]
    )
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    if not folder_id:
        q = ("mimeType='application/vnd.google-apps.folder' and "
             "name='EveBrain' and trashed=false")
        res = svc.files().list(q=q, fields="files(id,name)", pageSize=1).execute()
        files = res.get("files", [])
        if files:
            folder_id = files[0]["id"]
            print(f"  purana 'EveBrain' folder mila: {folder_id}")
        else:
            meta = {"name": "EveBrain",
                    "mimeType": "application/vnd.google-apps.folder"}
            folder_id = svc.files().create(body=meta, fields="id").execute()["id"]
            print(f"  naya 'EveBrain' folder banaya: {folder_id}")
        _patch_env_folder(folder_id)

    res = svc.files().list(
        q=f"'{folder_id}' in parents and name='eve.db' and trashed=false",
        fields="files(id,name,modifiedTime,size)", pageSize=1,
    ).execute()
    files = res.get("files", [])
    if not files:
        return False

    f = files[0]
    print(f"  eve.db mila (modified {f.get('modifiedTime')}, {f.get('size')} bytes)")
    if db_path.exists() and not yes("  Local db ko Drive wali se replace karein?", True):
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    req = svc.files().get_media(fileId=f["id"])
    with open(db_path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
    return True


_FOLDER_CACHE: dict = {}


def _patch_env_folder(folder_id: str) -> None:
    _FOLDER_CACHE["GDRIVE_FOLDER_ID"] = folder_id


def step_ai(cfg: dict) -> None:
    print("\n=== 4/4  AI KEYS ===")
    print("  Groq = normal baat-cheet + learning (multiple keys, auto rotate).")
    print("  Opus/Claude = sirf debate/help/political ke liye.")
    cfg["GROQ_API_KEYS"] = input("Groq keys (comma se, baad me TG panel se bhi daal sakte ho): ").strip()
    cfg["ANTHROPIC_API_KEY"] = input("Anthropic key (optional): ").strip()
    cfg["AGENTROUTER_KEY"] = input("AgentRouter key (optional): ").strip()
    cfg["AGENTROUTER_BASE"] = "https://agentrouter.org"
    cfg["AGENTROUTER_MODEL"] = "claude-opus-4-8"


# ----------------------------------------------------------------- main
def main() -> int:
    print("=" * 58)
    print(" EVE v7 — SETUP WIZARD")
    print("=" * 58)
    BASE.mkdir(parents=True, exist_ok=True)

    if ENV_PATH.exists() and not yes(f"{ENV_PATH} already hai. Overwrite?", False):
        print("Cancel.")
        return 0

    cfg: dict = {}
    step_platform(cfg)
    step_telegram(cfg)
    if cfg.get("PLATFORM") == "tg":
        step_tg_chat(cfg)
    else:
        step_instagram(cfg)
    step_drive(cfg)
    step_ai(cfg)
    if _FOLDER_CACHE.get("GDRIVE_FOLDER_ID"):
        cfg["GDRIVE_FOLDER_ID"] = _FOLDER_CACHE["GDRIVE_FOLDER_ID"]

    write_env(cfg)
    print("\nAb chalao:  python main.py")
    print("Telegram pe apne bot ko /start bhejo -> control panel khul jayega.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
