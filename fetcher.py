"""
Bybit V5 REST fetcher — gọi thẳng API, không dùng ccxt load_markets()
Endpoint public, không cần API key.
"""
import asyncio
import logging
from typing import Optional
import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

BASE = "https://api.bybit.com"

# Top 500 USDT perpetual — hardcoded list đảm bảo luôn có data
# Bybit public API không bị block theo region
TOP_SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT",
    "AVAXUSDT","SHIBUSDT","DOTUSDT","LINKUSDT","TRXUSDT","MATICUSDT","LTCUSDT",
    "BCHUSDT","UNIUSDT","ATOMUSDT","ETCUSDT","XLMUSDT","NEARUSDT","ALGOUSDT",
    "FILUSDT","VETUSDT","ICPUSDT","APTUSDT","ARBUSDT","OPUSDT","INJUSDT",
    "SUIUSDT","SEIUSDT","TIAUSDT","PYTHUSDT","WIFUSDT","JUPUSDT","BONKUSDT",
    "PEPEUSDT","FLOKIUSDT","ORDIUSDT","SATSUSDT","1000SATSUSDT","ACEUSDT",
    "ALTUSDT","AIUSDT","AEVOUSDT","PIXELUSDT","PORTALUSDT","MANTAUSDT",
    "STRKUSDT","DYMUSDT","ZETAUSDT","RONINUSDT","WLDUSDT","FETUSDT","AGIXUSDT",
    "OCEANUSDT","RENDERUSDT","TAOUSUSDT","AKASHUSDT","GRTUSDT","RLCUSDT",
    "SNXUSDT","AAVEUSDT","COMPUSDT","MKRUSDT","CRVUSDT","YFIUSDT","SUSHIUSDT",
    "BALUSDT","LRCUSDT","DYDXUSDT","GMXUSDT","PERPUSDT","BLURUSDT","LDOUSDT",
    "RPLUSDT","CBETHUSDT","STETHUSDT","FRAXUSDT","LUSDUSDT","FXSUSDT",
    "CVXUSDT","ANGLEUSDT","PENDELUSDT","RETHUSDT","ANKRUSDT","CELOUSDT",
    "KSMUSDT","ACAUSDT","GLMRUSDT","MOVRUSDT","ASTRUSDT","MGLUSDT","LITUSDT",
    "PHAUSDT","KILTUSDT","BIFROSTUSDT","INTERLAYUSDT","CRABUSDT","DEUSDT",
    "APEUSDT","SANDUSDT","MANAUSDT","AXSUSDT","GALAUSDT","IMXUSDT","ILVUSDT",
    "YGGUSDT","SLPUSDT","RNDRUSDT","HIGHUSDT","FLOWUSDT","XTZUSDT","EGLDUSDT",
    "FTMUSDT","ONEUSDT","ZILUSDT","IOSTUSDT","ONTUSDT","ZENUSDT","WAVESUSDT",
    "SCUSDT","DIAUSDT","BANDUSDT","SRMUSDT","RAYUSDT","MNGOUSUSDT","STEPUSDT",
    "PORTOUSDT","AUDIOUSDT","ENSUSDT","CVPUSDT","POWRUSDT","REQUSDT","STORJUSDT",
    "COTIUSDT","DGBUSDT","HBARUSDT","IOTXUSDT","CELRUSDT","CHZUSDT","HOTUSDT",
    "TFUELUSDT","ARKUSDT","QTUMUSDT","OMGUSDT","SKLUSDT","CVCUSDT","NMRUSDT",
    "OGNUSDT","GTCUSDT","FORTHUSDT","MIRAUSDT","ALPACAUSDT","BAKEUSDT",
    "CAKEUSDT","ALPHAUSUSDT","BELT1USDT","BUNNYUSDT","AUTOUSUSDT","VALUSDT",
    "PORTAUSDT","RUNEUSDT","THORUSDT","LDOUSDT","RPLUSUSDT","SSVUSDT","OBOLUSUSDT",
    "ETHFIUSDT","EIGENUSDT","RSETHUSDT","EZETHUSDT","WEETHUSDT","USDYUSDT",
    "SUSDEUSDT","USDEUSDT","FRXETHUSDT","MEVETHUSDT","ANKRETHUSDT","CBETHUSDT",
    "WSTETHUSDT","RETHUSDT","STETHUSDT","ETHXUSDT","OSETHUSDT","SWETHUSDT",
    "DOGEUSDT","SHIBUSDT","PEPEUSDT","WIFUSDT","BONKUSDT","FLOKIUSDT",
    "MEMEUSDT","TURBOUSUSDT","BRETTUSDT","MOGUSDT","LANDWOLFUSDT","ANDYUSDT",
    "MIGGLESUSDT","BABYDOGEUSDT","KISHUUSDT","AKITAUSDT","HUSKUSDT",
    "LOBOUSUSDT","WOLFUSDT","HOUNDUSDT","SHIBAUSDT","CATUSDT","MOUSEUSDT",
    "1000PEPEUSDT","1000BONKUSDT","1000SHIBUSDT","1000FLOKIUSDT","1000XECUSDT",
    "NOTUSDT","DOGSUSDT","CATIUSDT","HMSTRUSDT","TAPUSDT","BOMBUSDT","KASPAUSDT",
    "TONUSDT","JETTONUSDT","STORUSDT","XUSDT","BOMEUSDT","MEWUSDT","PRCLUSDT",
    "POPCATUSDT","GMEUSDT","ROARUSDT","CHEEMAUSDT","NEIROUSDT","GOATUSDT",
    "MOODENGUSDT","PNUTUSDT","ACTUSDT","BERAUSDT","ETHBTCUSDT","SOLBTCUSDT",
    "AVAXBTCUSDT","LINKBTCUSDT","DOTBTCUSDT","ADABTCUSDT","XRPBTCUSDT",
]

# Deduplicate and cap at 200 reliable symbols
_seen = set()
SYMBOLS: list[str] = []
for s in TOP_SYMBOLS:
    if s not in _seen:
        _seen.add(s)
        SYMBOLS.append(s)
SYMBOLS = SYMBOLS[:200]


class BybitFetcher:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
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
        """Fetch OHLCV từ Bybit V5 REST trực tiếp."""
        interval_map = {"1m":"1","3m":"3","5m":"5","15m":"15","30m":"30",
                        "1h":"60","2h":"120","4h":"240","1d":"D","1w":"W"}
        interval = interval_map.get(timeframe, "5")
        url = f"{BASE}/v5/market/kline"
        params = {"category":"linear","symbol":symbol,"interval":interval,"limit":limit}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                data = await resp.json()
            if data.get("retCode") != 0:
                logger.debug(f"{symbol} {timeframe}: {data.get('retMsg')}")
                return None
            rows = data["result"]["list"]
            if not rows:
                return None
            # Bybit returns newest first → reverse
            rows = list(reversed(rows))
            df = pd.DataFrame(rows, columns=["timestamp","open","high","low","close","volume","turnover"])
            df = df[["timestamp","open","high","low","close","volume"]].astype(float)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.debug(f"fetch_ohlcv {symbol} {timeframe}: {e}")
            return None

    async def fetch_top_symbols(self, limit: int = 500) -> list[str]:
        """Lấy top symbols theo volume từ Bybit tickers."""
        url = f"{BASE}/v5/market/tickers"
        params = {"category": "linear"}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                data = await resp.json()
            if data.get("retCode") != 0:
                logger.warning("fetch_top_symbols fallback to hardcoded list")
                return SYMBOLS[:limit]
            items = data["result"]["list"]
            # Filter USDT perps, sort by turnover24h
            usdt = [x for x in items if x["symbol"].endswith("USDT") and float(x.get("turnover24h", 0)) > 0]
            usdt.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
            syms = [x["symbol"] for x in usdt[:limit]]
            logger.info(f"Fetched {len(syms)} symbols from Bybit")
            return syms if syms else SYMBOLS[:limit]
        except Exception as e:
            logger.warning(f"fetch_top_symbols error: {e} — using hardcoded list")
            return SYMBOLS[:limit]
