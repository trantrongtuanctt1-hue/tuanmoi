"""
Binance Futures REST fetcher — thay thế Bybit
Endpoint public, không cần API key.
"""
import logging
from typing import Optional
import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

BASE = "https://fapi.binance.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


class BybitFetcher:  # Giữ tên class để không cần sửa file khác
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(timeout=timeout, headers=HEADERS)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 200,
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV từ Binance Futures REST."""
        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1d", "1w": "1w",
        }
        interval = interval_map.get(timeframe, "5m")
        url = f"{BASE}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.debug(f"{symbol} {timeframe}: HTTP {resp.status}")
                    return None
                rows = await resp.json()
            if not rows:
                return None
            # Binance: [openTime, open, high, low, close, volume, ...]
            df = pd.DataFrame(rows, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore"
            ])
            df = df[["timestamp", "open", "high", "low", "close", "volume"]].astype(float)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.debug(f"fetch_ohlcv {symbol} {timeframe}: {e}")
            return None

    async def fetch_top_symbols(self, limit: int = 500) -> list[str]:
        """Lấy top symbols theo volume 24h từ Binance Futures."""
        url = f"{BASE}/fapi/v1/ticker/24hr"
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"fetch_top_symbols HTTP {resp.status}, dùng fallback")
                    return _FALLBACK[:limit]
                data = await resp.json()

            # Chỉ lấy USDT pairs, lọc stablecoin
            STABLES = {"BUSDUSDT", "USDCUSDT", "TUSDUSDT", "USDTUSDT", "DAIUSDT", "FDUSDUSDT"}
            usdt = [
                x for x in data
                if x["symbol"].endswith("USDT")
                and x["symbol"] not in STABLES
                and float(x.get("quoteVolume", 0)) > 0
            ]
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
            syms = [x["symbol"] for x in usdt[:limit]]
            logger.info(f"Fetched {len(syms)} symbols từ Binance Futures")
            return syms if syms else _FALLBACK[:limit]
        except Exception as e:
            logger.warning(f"fetch_top_symbols error: {e} — dùng fallback list")
            return _FALLBACK[:limit]


# Fallback nếu API ticker cũng lỗi
_FALLBACK = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
    "AVAXUSDT","DOTUSDT","LINKUSDT","TRXUSDT","MATICUSDT","LTCUSDT","BCHUSDT",
    "UNIUSDT","ATOMUSDT","ETCUSDT","XLMUSDT","NEARUSDT","ALGOUSDT","FILUSDT",
    "APTUSDT","ARBUSDT","OPUSDT","INJUSDT","SUIUSDT","SEIUSDT","TIAUSDT",
    "WIFUSDT","JUPUSDT","BONKUSDT","PEPEUSDT","FLOKIUSDT","ORDIUSDT","WLDUSDT",
    "FETUSDT","RENDERUSDT","GRTUSDT","AAVEUSDT","MKRUSDT","CRVUSDT","LDOUSDT",
    "RUNEUSDT","SANDUSDT","MANAUSDT","AXSUSDT","GALAUSDT","IMXUSDT","HBARUSDT",
    "CHZUSDT","ENSUSDT","KASPAUSDT","TONUSDT","NOTUSDT","POPCATUSDT","EIGENUSDT",
    "STRKUSDT","MUUSDT","MOVEUSDT","NEIROUSDT","GOATUSDT","MOODENGUSDT","PNUTUSDT",
    "1000PEPEUSDT","1000BONKUSDT","BOMEUSDT","DOGSUSDT","CATIUSDT","HMSTRUSDT",
    "SNXUSDT","DYDXUSDT","GMXUSDT","APEUSDT","FLOWUSDT","EGLDUSDT","FTMUSDT",
    "COMPUSDT","SUSHIUSDT","OCEANUSDT","AGIXUSDT","ALTUSDT","PYTHUSDT","BERAUSDT",
]
