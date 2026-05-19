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
    min_score  = int(os.environ.get("MIN_ALERT_SCORE", "8"))
    max_tokens = int(os.environ.get("MAX_TOKENS", "1000"))

    logger.info("Starting 15M ULTRA Signal Bot (OKX, %d tokens, ultra≥%d)…", max_tokens, min_score)

    fetcher_bot = BybitFetcher()
    scanner_bot = Scanner(fetcher_bot, min_score=min_score, max_symbols=max_tokens)
    bot         = TelegramBot(token, scanner_bot)

    logger.info("Bot polling started. Press Ctrl+C to stop.")
    bot.run_polling()


if __name__ == "__main__":
    main()
