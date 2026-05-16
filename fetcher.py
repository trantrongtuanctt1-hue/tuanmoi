"""
OKX REST fetcher — thay thế Binance/Bybit
Endpoint public, không cần API key, không bị geo-block.
"""
import logging
from typing import Optional
import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

BASE = "https://www.okx.com"

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
        """
        Fetch OHLCV từ OKX REST.
        OKX symbol format: BTC-USDT-SWAP (perpetual futures)
        Chuyển BTCUSDT → BTC-USDT-SWAP
        """
        # Convert BTCUSDT → BTC-USDT-SWAP
        if symbol.endswith("USDT") and "-" not in symbol:
            base = symbol[:-4]  # bỏ USDT
            inst_id = f"{base}-USDT-SWAP"
        else:
            inst_id = symbol

        interval_map = {
            "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1H", "2h": "2H", "4h": "4H", "1d": "1D", "1w": "1W",
        }
        bar = interval_map.get(timeframe, "5m")
        url = f"{BASE}/api/v5/market/candles"
        params = {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit),
        }
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.debug(f"{inst_id} {timeframe}: HTTP {resp.status}")
                    return None
                data = await resp.json()
            if data.get("code") != "0":
                logger.debug(f"{inst_id}: {data.get('msg')}")
                return None
            rows = data.get("data", [])
            if not rows:
                return None
            # OKX: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
            # Newest first → reverse
            rows = list(reversed(rows))
            df = pd.DataFrame(rows)
            df = df.iloc[:, :6].copy()
            df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            df = df.astype(float)
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.debug(f"fetch_ohlcv {inst_id} {timeframe}: {e}")
            return None

    async def fetch_top_symbols(self, limit: int = 500) -> list[str]:
        """
        Lấy top USDT perpetual symbols theo volume 24h từ OKX.
        Trả về dạng BTCUSDT (giữ format cũ để scanner không cần sửa).
        """
        url = f"{BASE}/api/v5/market/tickers"
        params = {"instType": "SWAP"}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"fetch_top_symbols HTTP {resp.status}, dùng fallback")
                    return _FALLBACK[:limit]
                data = await resp.json()
            if data.get("code") != "0":
                logger.warning(f"fetch_top_symbols OKX error: {data.get('msg')}")
                return _FALLBACK[:limit]

            items = data.get("data", [])
            # Chỉ lấy USDT-SWAP, filter stablecoin
            STABLES = {"BUSD", "USDC", "TUSD", "DAI", "FDUSD"}
            usdt = [
                x for x in items
                if x["instId"].endswith("-USDT-SWAP")
                and x["instId"].split("-")[0] not in STABLES
                and float(x.get("volCcy24h", 0)) > 0
            ]
            usdt.sort(key=lambda x: float(x.get("volCcy24h", 0)), reverse=True)

            # Convert BTC-USDT-SWAP → BTCUSDT
            syms = []
            for x in usdt[:limit]:
                base = x["instId"].split("-")[0]
                syms.append(f"{base}USDT")

            logger.info(f"Fetched {len(syms)} symbols từ OKX")
            return syms if syms else _FALLBACK[:limit]
        except Exception as e:
            logger.warning(f"fetch_top_symbols error: {e} — dùng fallback list")
            return _FALLBACK[:limit]


# Fallback nếu OKX ticker cũng lỗi
_FALLBACK = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
    "AVAXUSDT","DOTUSDT","LINKUSDT","TRXUSDT","LTCUSDT","BCHUSDT","UNIUSDT",
    "ATOMUSDT","ETCUSDT","XLMUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT",
    "INJUSDT","SUIUSDT","WIFUSDT","BONKUSDT","PEPEUSDT","ORDIUSDT","WLDUSDT",
    "FETUSDT","RENDERUSDT","GRTUSDT","AAVEUSDT","MKRUSDT","LDOUSDT","RUNEUSDT",
    "SANDUSDT","MANAUSDT","AXSUSDT","GALAUSDT","IMXUSDT","HBARUSDT","CHZUSDT",
    "KASPAUSDT","TONUSDT","NOTUSDT","EIGENUSDT","STRKUSDT","MUUSDT","MOVEUSDT",
    "NEIROUSDT","GOATUSDT","MOODENGUSDT","PNUTUSDT","1000PEPEUSDT","BOMEUSDT",
    "DOGSUSDT","CATIUSDT","SNXUSDT","DYDXUSDT","GMXUSDT","APEUSDT","FTMUSDT",
    "COMPUSDT","SUSHIUSDT","AGIXUSDT","PYTHUSDT","BERAUSDT","JUPUSDT","TIAUSDT",
]
