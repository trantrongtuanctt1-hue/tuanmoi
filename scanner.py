"""
Scanner — quét tối đa 500 token song song, cooldown chống spam
v3.0: fetch 6 TF (5m, 15m, 30m, 1h, 4h, 1d) cho ULTRA scoring
"""
import asyncio
import logging
import time
from typing import Optional

from fetcher import BybitFetcher
from signals import SignalResult, score_symbol

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 900   # 15 phút giữa 2 alert cùng symbol
CONCURRENCY      = 30    # giảm từ 50 → 30 vì mỗi symbol giờ fetch 6 TF


class Scanner:
    def __init__(
        self,
        fetcher: BybitFetcher,
        min_score: int = 5,
        max_symbols: int = 1000,
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
            # Fetch 6 timeframes đồng thời
            df5, df15, df30, df1h, df4h, df1d = await asyncio.gather(
                self.fetcher.fetch_ohlcv(symbol, "5m",  100),
                self.fetcher.fetch_ohlcv(symbol, "15m",  60),
                self.fetcher.fetch_ohlcv(symbol, "30m",  60),
                self.fetcher.fetch_ohlcv(symbol, "1h",   60),
                self.fetcher.fetch_ohlcv(symbol, "4h",   60),
                self.fetcher.fetch_ohlcv(symbol, "1d",   60),
            )

            # Bắt buộc có 5m (để SXL engine chạy)
            if df5 is None or len(df5) < 50:
                return None

            # 15m fallback về 5m nếu fetch lỗi
            if df15 is None or len(df15) < 20:
                df15 = df5

            result = score_symbol(
                symbol,
                df_5m  = df5,
                df_15m = df15,
                df_1h  = df1h,
                df_30m = df30,
                df_4h  = df4h,
                df_1d  = df1d,
            )

            # Threshold: dùng ultra_buy/sell score làm tiêu chí chính
            # Nếu ultra score ≥5 HOẶC sxl score ≥ min_score → giữ
            passes = (
                result.ultra_buy_score  >= self.min_score or
                result.ultra_sell_score >= self.min_score or
                result.score            >= self.min_score
            )
            return result if passes else None

        except Exception as e:
            logger.debug(f"{symbol}: {e}")
            return None

    async def scan_all(self) -> list[SignalResult]:
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"Scanning {len(symbols)} symbols (6 TF each)…")

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

        # Sắp xếp: ưu tiên ultra score, sau đó sxl score
        signals.sort(
            key=lambda x: (max(x.ultra_buy_score, x.ultra_sell_score), x.score),
            reverse=True,
        )
        logger.info(f"Found {len(signals)} signals ≥ {self.min_score}")
        return signals

    async def scan_symbol(self, symbol: str) -> Optional[SignalResult]:
        """Quét 1 token theo yêu cầu (bỏ qua cooldown)."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return await self._analyse_one(sym)
