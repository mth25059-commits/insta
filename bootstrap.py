"""
Eve v7 — FIRST RUN BOOTSTRAP  (VPS pe repo pull karne ke baad yahi chalao)

    python bootstrap.py

Flow (exactly jaisa maanga gaya):
  STEP 1  IG cookies check   -> secrets/ig_cookies.json  (account found or not)
  STEP 2  Google Drive       -> purana brain mila to restore, warna naya banao
  STEP 3  Telegram           -> bot token + tumhari user id
  STEP 4  "Ab TG pe jao, /start -> API SET karo -> FORCE START dabao"
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from getpass import getpass
from pathlib import Path

BASE = Path(__file__).resolve().parent
SECRETS = BASE / "secrets"
COOKIES = SECRETS / "ig_cookies.json"
EXAMPLE = SECRETS / "ig_cookies.example.json"
ENV_PATH = BASE / ".env"


def line(title: str) -> None:
    print("\n" + "=" * 58)
    print(f" {title}")
    print("=" * 58)


def ask(label: str, default: str = "", secret: bool = False) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        val = (getpass if secret else input)(f"{label}{hint}: ").strip()
        if not val and default:
            return default
        if val:
            return val
        print("  ! khali nahi chalega")


def yes(label: str, default: bool = True) -> bool:
    v = input(f"{label} ({'Y/n' if default else 'y/N'}): ").strip().lower()
    return default if not v else v.startswith("y")


def save_env(cfg: dict) -> None:
    existing: dict = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in raw and not raw.strip().startswith("#"):
                k, _, v = raw.partition("=")
                existing[k.strip()] = v.strip()
    existing.update({k: v for k, v in cfg.items() if v is not None})
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8"
    )
    os.chmod(ENV_PATH, 0o600)


# ---------------------------------------------------------- STEP 1: IG
def step_instagram() -> bool:
    """Do raste: (1) username+password  (2) cookies file. Dono VPS pe chalte hain."""
    line("STEP 1/4  —  INSTAGRAM LOGIN")
    SECRETS.mkdir(parents=True, exist_ok=True)
    print("  1) Username + Password  (aasan, 2FA/OTP terminal me poochhega)")
    print("  2) Cookies / sessionid  (sabse safe — challenge ka risk kam)")
    choice = input("  Kaunsa? [1/2, default 1]: ").strip() or "1"
    if choice == "1":
        return _login_password()
    return step_cookies()


def _login_password() -> bool:
    user = ask("IG username")
    pwd = ask("IG password", secret=True)
    save_env({"IG_USERNAME": user, "IG_PASSWORD": pwd,
              "IG_SESSION_PATH": str(BASE / "ig_session.json")})
    print("  Login kar rahe hain... (pehli baar 20-40 sec lag sakte hain)")
    try:
        from instagrapi import Client
        from instagrapi.exceptions import TwoFactorRequired
        cl = Client()
        cl.delay_range = [1, 3]
        try:
            cl.login(user, pwd)
        except TwoFactorRequired:
            code = ask("2FA code (authenticator/SMS)")
            cl.login(user, pwd, verification_code=code)
        info = cl.account_info()
        cl.dump_settings(BASE / "ig_session.json")
    except Exception as e:
        print(f"  X LOGIN FAIL — {e}")
        print("    Agar 'challenge_required' aaya: phone/browser se us IP ka login "
              "approve karo, ya option 2 (cookies) use karo.")
        return False
    print(f"  ✓ ACCOUNT FOUND — @{info.username} ({info.full_name or '-'})")
    print(f"  ✓ Session save: {BASE / 'ig_session.json'} (dobara login nahi hoga)")
    return True


def step_cookies() -> bool:
    line("STEP 1/4  —  INSTAGRAM COOKIES")
    SECRETS.mkdir(parents=True, exist_ok=True)

    if not COOKIES.exists():
        if EXAMPLE.exists():
            shutil.copy(EXAMPLE, COOKIES)
        print(f"  Cookies file bana di: {COOKIES}")
        print("  Ab isme apni IG cookies daalo. Format:")
        print("""
  {
    "username": "tumhara_ig_username",
    "cookies": {
      "sessionid":  "...",
      "ds_user_id": "...",
      "csrftoken":  "...",
      "mid":        "...",
      "ig_did":     "..."
    }
  }

  Nikalne ka tarika: browser me IG login -> F12 DevTools ->
  Application -> Cookies -> https://www.instagram.com -> ye 5 value copy.
  (instagrapi ka dump_settings() JSON bhi seedha chipka sakte ho.)
""")
        input("  Cookies daal ke ENTER dabao... ")

    try:
        data = json.loads(COOKIES.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  X ig_cookies.json valid JSON nahi hai: {e}")
        return False
    sid = (data.get("cookies") or {}).get("sessionid", "")
    if "authorization_data" not in data and (not sid or "PASTE" in sid):
        print("  X sessionid abhi tak placeholder hai. Pehle cookies bharo.")
        return False

    print("  Account check kar rahe hain...")
    try:
        from workers import ig_login
        res = ig_login.check_account()
    except Exception as e:
        print(f"  X login module error: {e}")
        return False

    if not res.get("ok"):
        print(f"  X ACCOUNT NOT FOUND — {res.get('error')}")
        print("    Cookies expire ho gayi hongi. Fresh nikaal ke dobara chalao.")
        return False

    print(f"  ✓ ACCOUNT FOUND — @{res['username']} ({res.get('full_name') or '-'})")
    save_env({"IG_USERNAME": res["username"],
              "IG_SESSION_PATH": str(BASE / "ig_session.json")})
    return True


# ------------------------------------------------------- STEP 2: Drive
def step_drive() -> bool:
    line("STEP 2/4  —  GOOGLE DRIVE BRAIN")
    print("  Drive me bot ki poori memory (eve.db) rehti hai.")
    print("  Chahiye: service-account JSON key + us folder pe Editor access.")
    sa = ask("Service account JSON ka path", str(BASE / "secrets" / "sa.json"))
    if not Path(sa).exists():
        print(f"  X {sa} nahi mila — file upload karke dobara chalao.")
        return False
    folder = input("Drive folder id (khali = bot khud dhundhega/banayega): ").strip()
    db_path = BASE / "eve.db"

    save_env({"GOOGLE_SERVICE_ACCOUNT_JSON": sa,
              "DB_PATH": str(db_path),
              "DRIVE_SYNC_INTERVAL": "900"})

    try:
        folder_id, restored = _drive_smart(sa, folder, db_path)
    except Exception as e:
        print(f"  X Drive fail: {e}")
        return False

    save_env({"GDRIVE_FOLDER_ID": folder_id})
    if restored:
        print("  ✓ PURANA BRAIN MIL GAYA — restore ho gaya, bot kuch nahi bhoola.")
    else:
        print("  ✓ Purana brain nahi mila — naya brain banaya gaya.")
    return True


def _drive_smart(sa_path: str, folder_id: str, db_path: Path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    creds = service_account.Credentials.from_service_account_file(
        sa_path, scopes=["https://www.googleapis.com/auth/drive"])
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    if not folder_id:
        q = ("mimeType='application/vnd.google-apps.folder' and "
             "name='EveBrain' and trashed=false")
        files = svc.files().list(q=q, fields="files(id)", pageSize=1
                                 ).execute().get("files", [])
        if files:
            folder_id = files[0]["id"]
            print(f"  purana EveBrain folder mila: {folder_id}")
        else:
            folder_id = svc.files().create(
                body={"name": "EveBrain",
                      "mimeType": "application/vnd.google-apps.folder"},
                fields="id").execute()["id"]
            print(f"  naya EveBrain folder bana: {folder_id}")

    found = svc.files().list(
        q=f"'{folder_id}' in parents and name='eve.db' and trashed=false",
        fields="files(id,modifiedTime,size)", pageSize=1
    ).execute().get("files", [])
    if not found:
        return folder_id, False

    f = found[0]
    print(f"  eve.db mila (modified {f.get('modifiedTime')}, {f.get('size')}B)")
    if db_path.exists() and not yes("  Local db replace karein?", True):
        return folder_id, False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open(db_path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, svc.files().get_media(fileId=f["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
    return folder_id, True


# ---------------------------------------------------- STEP 3: Telegram
def step_telegram() -> bool:
    line("STEP 3/4  —  TELEGRAM CONTROL PANEL")
    print("  @BotFather -> /newbot -> token")
    print("  @userinfobot -> /start -> numeric user id")
    token = ask("TG bot token", secret=True)
    uid = ask("Tumhari TG user id")
    save_env({"TG_BOT_TOKEN": token, "TG_ADMIN_IDS": uid})

    try:
        from storage import database
        from intelligence import aihumara_state
        database.init_db()
        aihumara_state.set_tg_admin_id(uid)
    except Exception as e:
        print(f"  (note) admin id db me save nahi hui: {e}")
    print("  ✓ Telegram set")
    return True


# --------------------------------------------------------- STEP 4: go
def step_go() -> None:
    line("STEP 4/4  —  AB TELEGRAM PE JAO")
    print("""
  1) Terminal me chalao:      python main.py
  2) Telegram pe apne bot ko: /start
  3) Panel me:  [API SET]  ->  Groq keys daalo (comma se kitni bhi)
                           ->  Opus/Anthropic key daalo
  4) Phir dabao: [FORCE START]

     FORCE START  = pehli baar full setup ke baad sab systems ON
     START        = har message ka reply (bina mention ke)
     STOP         = sirf nickname/mention pe reply, learning chalu
     FORCE STOP   = sab band — reply, learning, sab
""")


def main() -> int:
    print("EVE v7 — BOOTSTRAP")
    if not step_instagram():
        return 1
    if not step_drive():
        return 1
    if not step_telegram():
        return 1
    step_go()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
