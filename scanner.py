"""
Scanner — quét tối đa 500 token song song, cooldown chống spam
"""
import asyncio
import logging
import time
from typing import Optional

from fetcher import BybitFetcher
from signals import SignalResult, score_symbol

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 900   # 15 phút giữa 2 alert cùng symbol
CONCURRENCY      = 20    # số coroutines song song


class Scanner:
    def __init__(
        self,
        fetcher: BybitFetcher,
        min_score: int = 7,
        max_symbols: int = 500,
    ):
        self.fetcher      = fetcher
        self.min_score    = min_score
        self.max_symbols  = max_symbols
        self._last_alert: dict[str, float] = {}

    def _in_cooldown(self, symbol: str) -> bool:
        last = self._last_alert.get(symbol, 0)
        return (time.time() - last) < COOLDOWN_SECONDS

    def _mark_alert(self, symbol: str):
        self._last_alert[symbol] = time.time()

    async def _analyse_one(self, symbol: str) -> Optional[SignalResult]:
        try:
            df5, df15, df1h = await asyncio.gather(
                self.fetcher.fetch_ohlcv(symbol, "5m",  200),
                self.fetcher.fetch_ohlcv(symbol, "15m", 100),
                self.fetcher.fetch_ohlcv(symbol, "1h",  100),
            )
            if df5 is None or len(df5) < 50:
                return None
            if df15 is None: df15 = df5
            if df1h  is None: df1h  = df5

            result = score_symbol(symbol, df5, df15, df1h)
            return result if result.score >= self.min_score else None
        except Exception as e:
            logger.debug(f"{symbol}: {e}")
            return None

    async def scan_all(self) -> list[SignalResult]:
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"Scanning {len(symbols)} symbols…")

        sem     = asyncio.Semaphore(CONCURRENCY)
        signals: list[SignalResult] = []

        async def limited(sym):
            async with sem:
                return await self._analyse_one(sym)

        results = await asyncio.gather(*[limited(s) for s in symbols])

        for r in results:
            if r and not self._in_cooldown(r.symbol):
                self._mark_alert(r.symbol)
                signals.append(r)

        signals.sort(key=lambda x: x.score, reverse=True)
        logger.info(f"Found {len(signals)} signals ≥ {self.min_score}")
        return signals

    async def scan_symbol(self, symbol: str) -> Optional[SignalResult]:
        """Quét 1 token theo yêu cầu (bỏ qua cooldown)"""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return await self._analyse_one(sym)
