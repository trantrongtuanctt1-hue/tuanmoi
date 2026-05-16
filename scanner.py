"""
Scanner — orchestrates data fetching → scoring → alert dedup
Runs every 5 minutes via APScheduler
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from src.fetcher import BybitFetcher
from src.signals import compute_score

logger = logging.getLogger(__name__)

# Prevent spam: don't re-alert same symbol+direction within N minutes
COOLDOWN_MINUTES = 15


class Scanner:
    def __init__(self, fetcher: BybitFetcher, alert_callback=None):
        self.fetcher        = fetcher
        self.alert_callback = alert_callback   # async fn(symbol, score, price)
        self._last_alert: dict[str, datetime] = {}   # symbol → last alert time

    def _in_cooldown(self, symbol: str) -> bool:
        last = self._last_alert.get(symbol)
        if last is None:
            return False
        return datetime.utcnow() - last < timedelta(minutes=COOLDOWN_MINUTES)

    def _mark_alerted(self, symbol: str):
        self._last_alert[symbol] = datetime.utcnow()

    async def check_symbol(self, symbol: str) -> Optional[dict]:
        """Fetch + score a single symbol. Returns {score, price} or None."""
        try:
            dfs = await self.fetcher.fetch_all_tfs(symbol)
            if dfs is None:
                return None
            score = compute_score(dfs)
            price = float(dfs['15m']['close'].iloc[-1])
            return {'symbol': symbol, 'score': score, 'price': price}
        except Exception as e:
            logger.warning(f"check_symbol {symbol}: {e}")
            return None

    async def scan_all(self, min_volume_usd=50_000_000, max_symbols=30) -> list:
        """Scan top symbols, return all results sorted by max score."""
        top = await self.fetcher.get_top_symbols(
            min_volume_usd=min_volume_usd,
            max_symbols=max_symbols
        )
        symbols = [t['symbol'] for t in top]
        logger.info(f"Scanning {len(symbols)} symbols...")

        # Semaphore: don't hammer Binance with too many concurrent requests
        sem     = asyncio.Semaphore(5)
        results = []

        async def _fetch_one(sym):
            async with sem:
                result = await self.check_symbol(sym)
                if result:
                    results.append(result)
                await asyncio.sleep(0.1)   # polite rate limit

        await asyncio.gather(*[_fetch_one(s) for s in symbols])
        results.sort(key=lambda x: max(x['score']['total_buy'], x['score']['total_sell']), reverse=True)
        logger.info(f"Scan complete: {len(results)} results")
        return results

    async def run_auto_scan(self, chat_ids: list, min_score=7):
        """
        Called by scheduler every 5 minutes.
        Pushes alerts for symbols crossing min_score threshold.
        """
        logger.info("Auto-scan triggered")
        try:
            signals = await self.scan_all()
        except Exception as e:
            logger.error(f"Auto-scan failed: {e}")
            return

        for s in signals:
            sym    = s['symbol']
            score  = s['score']
            price  = s['price']
            tb, ts = score['total_buy'], score['total_sell']

            if max(tb, ts) < min_score:
                continue
            if self._in_cooldown(sym):
                continue

            self._mark_alerted(sym)
            logger.info(f"Alert: {sym} BUY={tb} SELL={ts}")

            if self.alert_callback:
                for chat_id in chat_ids:
                    try:
                        await self.alert_callback(chat_id, sym, score, price)
                    except Exception as e:
                        logger.error(f"Push alert to {chat_id} failed: {e}")
