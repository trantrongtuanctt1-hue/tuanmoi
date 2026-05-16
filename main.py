"""
main.py — Entry point
Deploy: Railway worker process
"""
import asyncio
import logging
import signal
import sys

from bot import TradingBot

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Tắt bớt log của thư viện ngoài
logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger("main")


async def main():
    bot = TradingBot()

    loop = asyncio.get_event_loop()

    def _shutdown(sig, frame):
        logger.info(f"Signal {sig} received — shutting down…")
        loop.create_task(bot.stop())

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        await bot.run()
    except (KeyboardInterrupt, SystemExit):
        await bot.stop()
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        await bot.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
