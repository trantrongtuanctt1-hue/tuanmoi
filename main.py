"""
main.py — entry point
Env vars:
  TELEGRAM_TOKEN   — bắt buộc
  MIN_SCORE        — ngưỡng score, default 7 (tối đa 11)
  MAX_TOKENS       — số token quét, default 500
  CTX_TF           — context TF, default 4h
  ENTRY_TF         — entry TF,   default 1h
  MIN_ADX          — ngưỡng ADX, default 25
  ATR_MULT_SL      — ATR × SL,   default 0.5
  RR               — Risk:Reward, default 3.0
"""

import logging
import os
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

from fetcher    import BybitFetcher
from scanner    import Scanner
from signal_bot import TelegramBot


def main():
    token      = os.environ["TELEGRAM_TOKEN"]
    min_score  = int(os.environ.get("MIN_SCORE",   "6"))
    max_tokens = int(os.environ.get("MAX_TOKENS",  "500"))
    ctx_tf     = os.environ.get("CTX_TF",   "4h")
    entry_tf   = os.environ.get("ENTRY_TF", "1h")
    min_adx    = float(os.environ.get("MIN_ADX",     "20"))
    atr_mult   = float(os.environ.get("ATR_MULT_SL", "0.5"))
    rr         = float(os.environ.get("RR",          "3.0"))

    logger.info(
        f"Starting | ctx={ctx_tf} entry={entry_tf} "
        f"score≥{min_score}/11 ctx≥3 entry≥2 ADX≥{min_adx} SL×{atr_mult} RR={rr} tokens={max_tokens}"
    )

    fetcher = BybitFetcher()
    scanner = Scanner(
        fetcher      = fetcher,
        min_score    = min_score,
        max_symbols  = max_tokens,
        ctx_tf       = ctx_tf,
        entry_tf     = entry_tf,
        min_adx      = min_adx,
        atr_mult_sl  = atr_mult,
        rr           = rr,
    )
    bot = TelegramBot(token, scanner)
    logger.info("Bot polling started.")
    bot.run_polling()


if __name__ == "__main__":
    main()
