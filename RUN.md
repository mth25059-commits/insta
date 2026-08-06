# Eve v7 — chalane ka tarika (VPS)

Control panel = **Telegram bot**. Instagram pe body, Telegram pe dimaag ka remote.

## 1. Setup

```bash
git clone <repo> /root/eve && cd /root/eve
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # token, IG login, keys bhar
python main.py
```

## 2. Pehli baar

1. Telegram pe apne bot ko `/claimadmin` bhej — panel tera ho jayega.
2. `/panel` → buttons:
   - ▶️ START / ⏸ STOP (sirf learning) / 👑 ADMIN-ONLY / 🔥 ULTIMATE FIRE
   - 🏷 Nicknames (chotu, eve… jitne chahe)
   - 👑 IG admin username set (dhruv)
   - 🎭 Tone · 🔓 Unfilter · 🎯 Trigger (username + tone) · 🧠 People memory
   - 🔑 API Keys (groq ki 12 key daal — 100 req/key rotate + failover; anthropic/opus alag)
   - ☁️ Drive (backup / restore / status) · 📊 Stats

## 3. 24x7 (systemd)

`/etc/systemd/system/eve.service`:

```ini
[Unit]
Description=Eve v7 IG bot
After=network-online.target

[Service]
WorkingDirectory=/root/eve
ExecStart=/root/eve/venv/bin/python main.py
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now eve
journalctl -u eve -f
```

`SIGTERM` pe brain ka final backup Drive pe chala jata hai, isliye VPS
badalne pe naye server par sirf `.env` + `sa.json` rakho — boot pe Drive se
memory wapas aa jayegi.

## 4. Dhyan rakhne wali baat

- Instagram unofficial automation = ban risk. Burner account use kar,
  `IG_MIN_DELAY/IG_MAX_DELAY` kam mat kar, poll 5s se neeche mat le ja.
- Pehla login same IP pe kar jahan bot chalega, warna challenge aayega.
- `IG_ALLOWED_THREADS` me sirf apni GC ki id daal de to bot bahar kahin
  reply nahi karega.

## VPS pe update kaise kare (running bot)

```bash
cd /root/eve            # jahan repo clone hai
git pull                # naye changes
pip install -r requirements.txt   # (kabhi kabhi hi zaroori)
systemctl restart eve   # ya: pkill -f "python main.py" && nohup python main.py &
```
Memory (eve.db) waise ki waisi rehti hai — kuch bhoolega nahi.
Platform badalna ho (ig <-> tg) to `.env` me `PLATFORM=tg` kar ke restart.
