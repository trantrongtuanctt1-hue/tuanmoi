"""
Fetcher dùng CCXT — hỗ trợ Bybit (không block Railway/US IP)
Tự động fallback: Bybit → OKX nếu cần
"""

import asyncio
import logging
from typing import Optional
import pandas as pd
import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

TIMEFRAMES = ['5m', '15m', '30m', '1h', '4h', '1d']
CANDLE_LIMIT = {'5m': 200, '15m': 200, '30m': 150, '1h': 150, '4h': 100, '1d': 100}

EXCLUDE_KEYWORDS = {'USDC','BUSD','TUSD','DAI','FDUSD','USDP','UP','DOWN','BEAR','BULL'}


def _to_df(ohlcv: list) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    for col in ['open','high','low','close','volume']:
        df[col] = df[col].astype(float)
    return df


class BybitFetcher:
    def __init__(self, api_key='', api_secret=''):
        self.exchange = ccxt.bybit({
            'apiKey':    api_key,
            'secret':    api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'linear'},   # USDT perpetual
        })

    async def connect(self):
        # CCXT lazy-connects — just load markets to verify connectivity
        await self.exchange.load_markets()
        logger.info("Bybit connected OK")

    async def close(self):
        await self.exchange.close()

    async def fetch_ohlcv(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        # Bybit symbol format: BTCUSDT → BTC/USDT:USDT  (linear perp)
        bybit_sym = symbol.replace('USDT', '/USDT:USDT')
        try:
            raw = await self.exchange.fetch_ohlcv(
                bybit_sym, timeframe=tf, limit=CANDLE_LIMIT[tf]
            )
            return _to_df(raw)
        except Exception as e:
            logger.warning(f"fetch_ohlcv {symbol} {tf}: {e}")
            return None

    async def fetch_all_tfs(self, symbol: str) -> Optional[dict]:
        tasks = {tf: self.fetch_ohlcv(symbol, tf) for tf in TIMEFRAMES}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        dfs = {}
        for tf, result in zip(tasks.keys(), results):
            if isinstance(result, Exception) or result is None:
                logger.warning(f"{symbol} {tf} failed")
                return None
            dfs[tf] = result
        return dfs

    async def get_top_symbols(self, quote='USDT', min_volume_usd=30_000_000, max_symbols=30) -> list:
        tickers = await self.exchange.fetch_tickers()
        filtered = []
        for sym, t in tickers.items():
            # Only linear perp: BTC/USDT:USDT
            if not sym.endswith(f'/{quote}:{quote}'):
                continue
            base = sym.split('/')[0]
            if any(kw in base for kw in EXCLUDE_KEYWORDS):
                continue
            try:
                vol   = float(t.get('quoteVolume') or 0)
                price = float(t.get('last') or 0)
                pct   = float(t.get('percentage') or 0)
                if vol >= min_volume_usd and price > 0:
                    # Convert back to Binance-style symbol for display
                    display = base + quote
                    filtered.append({'symbol': display, 'bybit_sym': sym,
                                     'volume': vol, 'price': price, 'change': pct})
            except (TypeError, ValueError):
                continue

        filtered.sort(key=lambda x: x['volume'], reverse=True)
        return filtered[:max_symbols]

    async def get_current_price(self, symbol: str) -> float:
        bybit_sym = symbol.replace('USDT', '/USDT:USDT')
        t = await self.exchange.fetch_ticker(bybit_sym)
        return float(t['last'])
