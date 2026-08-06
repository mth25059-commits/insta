"""
Eve v7 — entry point.

    python main.py

Ek process me do thread:
  * Instagram worker  (GC padhna + reply)
  * Telegram panel    (control buttons)
Drive sync background me apne aap chalta rehta hai.
"""
from __future__ import annotations

import logging
import signal
import sys
import threading
import time

import config
from eve_v7_boot import boot_v7, shutdown_v7

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eve.main")

_stop = threading.Event()


def _run_tg() -> None:
    from workers import tg_panel_v2
    while not _stop.is_set():
        try:
            tg_panel_v2.main()
        except Exception:
            logger.exception("[MAIN] TG panel crash — 10s me restart")
            _stop.wait(10)


def _run_ig() -> None:
    if config.PLATFORM == "tg":
        from workers import tg_chat_worker as chat_worker
    else:
        from workers import ig_worker as chat_worker
    while not _stop.is_set():
        try:
            chat_worker.run(_stop)
            return
        except SystemExit:
            raise
        except Exception:
            logger.exception("[MAIN] chat worker crash — 30s me restart")
            _stop.wait(30)


def _shutdown(*_a) -> None:
    if _stop.is_set():
        return
    logger.info("[MAIN] shutdown… brain Drive pe bhej rahe hain")
    _stop.set()
    shutdown_v7()


def main() -> None:
    if not config.TG_BOT_TOKEN:
        raise SystemExit("TG_BOT_TOKEN .env me daal — control panel wahi hai")

    boot_v7()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    threads = [
        threading.Thread(target=_run_tg, name="tg-panel", daemon=True),
        threading.Thread(target=_run_ig, name="ig-worker", daemon=True),
    ]
    for t in threads:
        t.start()
    logger.info("[MAIN] Eve v7 live (%s mode) — TG panel me /claimadmin maar",
                config.PLATFORM)

    try:
        while not _stop.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
