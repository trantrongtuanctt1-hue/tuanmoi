"""
Bybit OHLCV fetcher using CCXT — no python-binance dependency
"""
import asyncio
import logging
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd

logger = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "5m":  "5m",
    "15m": "15m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
}

class BybitFetcher:
    def __init__(self):
        self.exchange = ccxt.bybit({
            "enableRateLimit": True,
            "options": {"defaultType": "linear"},
        })

    async def close(self):
        await self.exchange.close()

    def _to_ccxt_symbol(self, symbol: str) -> str:
        """BTCUSDT → BTC/USDT:USDT"""
        if "/" in symbol:
            return symbol
        base = symbol.replace("USDT", "")
        return f"{base}/USDT:USDT"

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 200,
    ) -> Optional[pd.DataFrame]:
        tf = TIMEFRAME_MAP.get(timeframe, timeframe)
        ccxt_sym = self._to_ccxt_symbol(symbol)
        try:
            raw = await self.exchange.fetch_ohlcv(ccxt_sym, tf, limit=limit)
            if not raw:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)
            return df
        except Exception as e:
            logger.warning(f"fetch_ohlcv {symbol} {timeframe}: {e}")
            return None

    async def fetch_top_symbols(self, limit: int = 500) -> list[str]:
        """Lấy top symbols theo volume 24h, trả về dạng BTCUSDT"""
        try:
            await self.exchange.load_markets()
            tickers = await self.exchange.fetch_tickers()
            usdt_perps = {
                k: v for k, v in tickers.items()
                if k.endswith("/USDT:USDT") and v.get("quoteVolume")
            }
            sorted_syms = sorted(
                usdt_perps.items(),
                key=lambda x: x[1].get("quoteVolume", 0),
                reverse=True,
            )[:limit]
            # Convert BTC/USDT:USDT → BTCUSDT
            result = []
            for sym, _ in sorted_syms:
                base = sym.split("/")[0]
                result.append(f"{base}USDT")
            return result
        except Exception as e:
            logger.error(f"fetch_top_symbols: {e}")
            return []
