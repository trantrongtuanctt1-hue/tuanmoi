"""
main.py — entry point
Chạy: python main.py
"""
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from fetcher  import BybitFetcher
from scanner  import Scanner
from signal_bot import TelegramBot


def main():
    token      = os.environ["TELEGRAM_TOKEN"]
    chat_ids   = os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
    min_score  = int(os.environ.get("MIN_ALERT_SCORE", "8"))
    scan_mins  = int(os.environ.get("SCAN_INTERVAL_MINUTES", "5"))
    max_tokens = int(os.environ.get("MAX_TOKENS", "1000"))

    logger.info("Starting 15M ULTRA Signal Bot (OKX, %d tokens, ultra≥%d)…", max_tokens, min_score)

    # Fetcher/Scanner cho bot Telegram (chạy trong main event loop)
    fetcher_bot = BybitFetcher()
    scanner_bot = Scanner(fetcher_bot, min_score=min_score, max_symbols=max_tokens)
    bot         = TelegramBot(token, scanner_bot)

    # Fetcher/Scanner riêng cho background auto-scan (loop khác)
    fetcher_bg  = BybitFetcher()
    scanner_bg  = Scanner(fetcher_bg, min_score=min_score, max_symbols=max_tokens)

    # Background auto-scan task — dùng scan_for_alert (có cooldown 15 phút)
    async def auto_scan():
        while True:
            await asyncio.sleep(scan_mins * 60)
            try:
                signals = await scanner_bg.scan_for_alert()
                for r in signals:
                    for cid in chat_ids:
                        cid = cid.strip()
                        if cid:
                            await bot.send_signal(cid, r)
            except Exception as e:
                logger.error(f"auto_scan error: {e}")

    # Run bot + background task together
    import threading

    def run_bg():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(auto_scan())

    t = threading.Thread(target=run_bg, daemon=True)
    t.start()

    logger.info("Bot polling started. Press Ctrl+C to stop.")
    bot.run_polling()


if __name__ == "__main__":
    main()
