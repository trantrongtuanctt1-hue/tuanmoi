"""
Binance data fetcher — pulls OHLCV for multiple timeframes
Uses python-binance (free, no API key needed for public market data)
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from binance import AsyncClient

logger = logging.getLogger(__name__)

TIMEFRAMES = {
    '5m':  AsyncClient.KLINE_INTERVAL_5MINUTE,
    '15m': AsyncClient.KLINE_INTERVAL_15MINUTE,
    '30m': AsyncClient.KLINE_INTERVAL_30MINUTE,
    '1h':  AsyncClient.KLINE_INTERVAL_1HOUR,
    '4h':  AsyncClient.KLINE_INTERVAL_4HOUR,
    '1d':  AsyncClient.KLINE_INTERVAL_1DAY,
}

CANDLE_LIMIT = {
    '5m':  200,
    '15m': 200,
    '30m': 150,
    '1h':  150,
    '4h':  100,
    '1d':  100,
}


def _parse_klines(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=[
        'open_time','open','high','low','close','volume',
        'close_time','quote_vol','trades','taker_base','taker_quote','ignore'
    ])
    for col in ['open','high','low','close','volume']:
        df[col] = df[col].astype(float)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)
    return df[['open','high','low','close','volume']]


class BinanceFetcher:
    def __init__(self, api_key: str = '', api_secret: str = ''):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.client: Optional[AsyncClient] = None

    async def connect(self):
        self.client = await AsyncClient.create(self.api_key, self.api_secret)
        logger.info("Binance client connected")

    async def close(self):
        if self.client:
            await self.client.close_connection()

    async def fetch_ohlcv(self, symbol: str, tf: str) -> pd.DataFrame:
        interval = TIMEFRAMES[tf]
        limit    = CANDLE_LIMIT[tf]
        raw      = await self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        return _parse_klines(raw)

    async def fetch_all_tfs(self, symbol: str) -> dict:
        """Fetch all 6 timeframes concurrently"""
        tasks = {
            tf: self.fetch_ohlcv(symbol, tf)
            for tf in TIMEFRAMES
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        dfs = {}
        for tf, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"{symbol} {tf} fetch error: {result}")
                return None
            dfs[tf] = result
        return dfs

    async def get_top_symbols(self, quote='USDT', min_volume_usd=50_000_000, max_symbols=30) -> list:
        """
        Return top symbols by 24h volume, filtered by min volume.
        Excludes stablecoins, leveraged tokens.
        """
        EXCLUDE = {'USDC','BUSD','TUSD','USDT','DAI','FDUSD','USDP',
                   'UP','DOWN','BEAR','BULL','3L','3S'}
        tickers = await self.client.get_ticker()
        filtered = []
        for t in tickers:
            sym = t['symbol']
            if not sym.endswith(quote):
                continue
            base = sym[:-len(quote)]
            if any(kw in base for kw in EXCLUDE):
                continue
            try:
                vol_usd = float(t['quoteVolume'])
                price   = float(t['lastPrice'])
                pct     = float(t['priceChangePercent'])
                if vol_usd >= min_volume_usd and price > 0:
                    filtered.append({
                        'symbol':  sym,
                        'volume':  vol_usd,
                        'price':   price,
                        'change':  pct,
                    })
            except (ValueError, KeyError):
                continue

        filtered.sort(key=lambda x: x['volume'], reverse=True)
        return filtered[:max_symbols]

    async def get_current_price(self, symbol: str) -> float:
        t = await self.client.get_symbol_ticker(symbol=symbol)
        return float(t['price'])
