"""
main.py — Entrypoint
Wires: BinanceFetcher → Scanner → SignalBot → APScheduler
"""

import asyncio
import logging
import os
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval  import IntervalTrigger
from dotenv import load_dotenv

load_dotenv()

from src.fetcher  import BybitFetcher
from src.scanner  import Scanner
from src.bot      import SignalBot

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = '%(asctime)s  %(levelname)-8s  %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)


# ── Config from env ───────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.getenv('TELEGRAM_TOKEN',  '')
TELEGRAM_CHAT_IDS = [c.strip() for c in os.getenv('TELEGRAM_CHAT_IDS', '').split(',') if c.strip()]
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')    # optional, public data is free
BINANCE_SECRET  = os.getenv('BINANCE_SECRET',  '')
SCAN_INTERVAL   = int(os.getenv('SCAN_INTERVAL_MINUTES', '5'))
MIN_SCORE       = int(os.getenv('MIN_ALERT_SCORE', '7'))
MIN_VOLUME_USD  = float(os.getenv('MIN_VOLUME_USD', '50000000'))
MAX_SYMBOLS     = int(os.getenv('MAX_SYMBOLS', '30'))


async def main():
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set. Check .env")
        sys.exit(1)
    if not TELEGRAM_CHAT_IDS:
        logger.error("TELEGRAM_CHAT_IDS not set. Check .env")
        sys.exit(1)

    logger.info("Starting 15M ULTRA Signal Bot...")

    # ── Binance ───────────────────────────────────────────────────────────
    fetcher = BybitFetcher(BINANCE_API_KEY, BINANCE_SECRET)
    await fetcher.connect()

    # ── Scanner ───────────────────────────────────────────────────────────
    scanner = Scanner(fetcher)

    # ── Telegram Bot ──────────────────────────────────────────────────────
    bot = SignalBot(TELEGRAM_TOKEN, scanner)

    # Wire alert callback: scanner → bot.push_alert
    async def _push(chat_id, symbol, score, price):
        await bot.push_alert(chat_id, symbol, score, price)

    scanner.alert_callback = _push

    # ── Scheduler ─────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scanner.run_auto_scan,
        trigger   = IntervalTrigger(minutes=SCAN_INTERVAL),
        args      = [TELEGRAM_CHAT_IDS, MIN_SCORE],
        id        = 'auto_scan',
        name      = f'Auto-scan every {SCAN_INTERVAL}m',
        replace_existing = True,
        max_instances    = 1,
    )
    scheduler.start()
    logger.info(f"Scheduler: auto-scan every {SCAN_INTERVAL} min, alert threshold score ≥{MIN_SCORE}")

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown(scheduler, fetcher)))

    # ── Run bot (blocks) ──────────────────────────────────────────────────
    logger.info("Bot running. Press Ctrl+C to stop.")
    bot.run()


async def _shutdown(scheduler, fetcher):
    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    await fetcher.close()
    sys.exit(0)


if __name__ == '__main__':
    asyncio.run(main())
