"""
Fetcher — Binance Futures primary + OKX fallback tự động
══════════════════════════════════════════════════════════
• Binance fapi.binance.com  — public, không API key
  - Limit 1500 nến/request → lấy đủ 200 nến 4H + 100 nến 1H trong 1 call
  - ~300–400 USDT perpetual symbols
• OKX www.okx.com           — fallback tự động nếu Binance bị block/lỗi
  - Limit 100 nến/request
  - ~500+ USDT swap symbols

Giữ tên class BybitFetcher để các file khác (scanner.py, main.py) không cần sửa.
"""

import logging
import asyncio
from typing import Optional, List
import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://fapi.binance.com"
OKX_BASE     = "https://www.okx.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

# Map timeframe string → exchange bar string
BINANCE_TF = {
    "1m": "1m",  "3m": "3m",  "5m": "5m",  "15m": "15m", "30m": "30m",
    "1h": "1h",  "2h": "2h",  "4h": "4h",  "1d": "1d",   "1w": "1w",
}
OKX_TF = {
    "1m": "1m",  "3m": "3m",  "5m": "5m",  "15m": "15m", "30m": "30m",
    "1h": "1H",  "2h": "2H",  "4h": "4H",  "1d": "1D",   "1w": "1W",
}

STABLES = {"BUSD", "USDC", "TUSD", "DAI", "FDUSD", "USDP", "UST"}


class BybitFetcher:
    def __init__(self, max_candles: int = 1500):
        """
        max_candles:
          Binance hỗ trợ tối đa 1500 nến/request.
          OKX chỉ hỗ trợ tối đa 100 nến/request.
          Khi fallback OKX, limit sẽ tự động bị cap xuống 100.
        """
        self.max_candles_binance = min(max_candles, 1500)
        self.max_candles_okx     = 100
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_loop = None

        # Trạng thái: True = Binance OK, False = đang dùng OKX fallback
        self._binance_ok: bool = True
        # Đếm lỗi liên tiếp để quyết định chuyển hẳn sang OKX
        self._binance_fail_count: int = 0
        self._FAIL_THRESHOLD = 3   # sau 3 lỗi liên tiếp → fallback OKX

    # ─────────────────────────────────────────────
    # SESSION
    # ─────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        current_loop = asyncio.get_running_loop()
        if (self._session is None
                or self._session.closed
                or self._session_loop is not current_loop):
            if self._session and not self._session.closed:
                try:
                    await self._session.close()
                except Exception:
                    pass
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout, headers=HEADERS)
            self._session_loop = current_loop
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ─────────────────────────────────────────────
    # FETCH OHLCV — PUBLIC
    # ─────────────────────────────────────────────

    async def fetch_ohlcv(
        self,
        symbol:    str,
        timeframe: str = "5m",
        limit:     int = 200,
    ) -> Optional[pd.DataFrame]:
        """
        Tự động dùng Binance hoặc OKX tùy trạng thái.
        Nếu Binance lỗi → thử OKX ngay lần đó và tăng fail count.
        Nếu fail count vượt ngưỡng → chuyển hẳn sang OKX cho đến khi
        fetch_top_symbols() thành công lại với Binance.
        """
        if self._binance_ok:
            df = await self._fetch_binance(symbol, timeframe, limit)
            if df is not None:
                self._binance_fail_count = 0
                return df
            # Binance lỗi
            self._binance_fail_count += 1
            if self._binance_fail_count >= self._FAIL_THRESHOLD:
                logger.warning(
                    f"Binance lỗi {self._binance_fail_count} lần liên tiếp "
                    f"→ chuyển sang OKX fallback."
                )
                self._binance_ok = False
            # Thử OKX ngay lần này
            return await self._fetch_okx(symbol, timeframe, limit)
        else:
            return await self._fetch_okx(symbol, timeframe, limit)

    # ─────────────────────────────────────────────
    # BINANCE OHLCV
    # ─────────────────────────────────────────────

    async def _fetch_binance(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int,
    ) -> Optional[pd.DataFrame]:
        """
        Binance USDM Futures klines.
        Symbol format: BTCUSDT (giữ nguyên).
        Limit: tối đa 1500.
        """
        limit  = min(limit, self.max_candles_binance)
        bar    = BINANCE_TF.get(timeframe, "5m")
        url    = f"{BINANCE_BASE}/fapi/v1/klines"
        params = {
            "symbol":   symbol,
            "interval": bar,
            "limit":    str(limit),
        }
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.debug(f"[Binance] {symbol} {timeframe}: HTTP {resp.status}")
                    return None
                data = await resp.json()
            if not isinstance(data, list) or len(data) == 0:
                return None
            # Binance: [open_time, open, high, low, close, volume, ...]
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
            df = df.astype(float)
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.debug(f"[Binance] fetch_ohlcv {symbol} {timeframe}: {e}")
            return None

    # ─────────────────────────────────────────────
    # OKX OHLCV
    # ─────────────────────────────────────────────

    async def _fetch_okx(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int,
    ) -> Optional[pd.DataFrame]:
        """
        OKX USDT perpetual (SWAP) klines.
        Symbol: BTCUSDT → BTC-USDT-SWAP.
        Limit: tối đa 100.
        """
        limit = min(limit, self.max_candles_okx)

        if symbol.endswith("USDT") and "-" not in symbol:
            inst_id = f"{symbol[:-4]}-USDT-SWAP"
        else:
            inst_id = symbol

        bar    = OKX_TF.get(timeframe, "5m")
        url    = f"{OKX_BASE}/api/v5/market/candles"
        params = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.debug(f"[OKX] {inst_id} {timeframe}: HTTP {resp.status}")
                    return None
                data = await resp.json()
            if data.get("code") != "0":
                logger.debug(f"[OKX] {inst_id}: {data.get('msg')}")
                return None
            rows = data.get("data", [])
            if not rows:
                return None
            rows = list(reversed(rows))
            df = pd.DataFrame(rows).iloc[:, :6].copy()
            df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
            df = df.astype(float)
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.debug(f"[OKX] fetch_ohlcv {inst_id} {timeframe}: {e}")
            return None

    # ─────────────────────────────────────────────
    # FETCH TOP SYMBOLS — PUBLIC
    # ─────────────────────────────────────────────

    async def fetch_top_symbols(self, limit: int = 500) -> List[str]:
        """
        Ưu tiên Binance. Nếu lỗi hoặc đang ở OKX fallback → thử OKX.
        Sau mỗi lần fetch_top_symbols thành công với Binance → reset về Binance.
        """
        if self._binance_ok:
            syms = await self._fetch_symbols_binance(limit)
            if syms:
                self._binance_fail_count = 0
                logger.info(f"[Binance] {len(syms)} symbols (yêu cầu {limit})")
                return syms
            logger.warning("[Binance] fetch_top_symbols thất bại → thử OKX")

        # OKX
        syms = await self._fetch_symbols_okx(limit)
        if syms:
            logger.info(f"[OKX] {len(syms)} symbols (fallback)")
            return syms

        logger.warning("Cả Binance lẫn OKX đều thất bại → dùng fallback cứng")
        return self._fallback_symbols()[:limit]

    async def _fetch_symbols_binance(self, limit: int) -> List[str]:
        """
        Binance USDM Futures: lấy tất cả USDT perpetual, sort theo quoteVolume 24h.
        """
        url = f"{BINANCE_BASE}/fapi/v1/ticker/24hr"
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.debug(f"[Binance] ticker/24hr HTTP {resp.status}")
                    return []
                data = await resp.json()
            if not isinstance(data, list):
                return []

            # Lọc USDT perpetual, bỏ stablecoin
            usdt = [
                x for x in data
                if isinstance(x, dict)
                and str(x.get("symbol", "")).endswith("USDT")
                and str(x.get("symbol", ""))[:-4] not in STABLES
                and float(x.get("quoteVolume", 0)) > 0
            ]
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
            syms = [x["symbol"] for x in usdt[:limit]]
            return syms
        except Exception as e:
            logger.debug(f"[Binance] _fetch_symbols_binance: {e}")
            return []

    async def _fetch_symbols_okx(self, limit: int) -> List[str]:
        """
        OKX USDT SWAP: sort theo volCcy24h.
        """
        url    = f"{OKX_BASE}/api/v5/market/tickers"
        params = {"instType": "SWAP"}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
            if data.get("code") != "0":
                return []
            items = [
                x for x in data.get("data", [])
                if x["instId"].endswith("-USDT-SWAP")
                and x["instId"].split("-")[0] not in STABLES
                and float(x.get("volCcy24h", 0)) > 0
            ]
            items.sort(key=lambda x: float(x.get("volCcy24h", 0)), reverse=True)
            return [f"{x['instId'].split('-')[0]}USDT" for x in items[:limit]]
        except Exception as e:
            logger.debug(f"[OKX] _fetch_symbols_okx: {e}")
            return []

    # ─────────────────────────────────────────────
    # FALLBACK CỨNG
    # ─────────────────────────────────────────────

    def _fallback_symbols(self) -> List[str]:
        top = [
            "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK",
            "TRX", "LTC", "BCH", "UNI", "ATOM", "ETC", "XLM", "NEAR", "APT", "ARB",
            "OP", "INJ", "SUI", "WIF", "BONK", "PEPE", "ORDI", "WLD", "FET", "RENDER",
            "GRT", "AAVE", "MKR", "LDO", "RUNE", "SAND", "MANA", "AXS", "GALA", "IMX",
            "HBAR", "CHZ", "KAS", "TON", "NOT", "EIGEN", "STRK", "JUP", "TIA", "SEI",
            "BLUR", "AGIX", "OCEAN", "CFX", "ALGO", "VET", "ICP", "EGLD", "FLOW", "THETA",
            "FTM", "SNX", "COMP", "SUSHI", "DYDX", "GMX", "APE", "PYTH", "BERA", "MOVE",
            "NEIRO", "GOAT", "MOODENG", "PNUT", "BOME", "DOGS", "CATI", "ZRO", "ZK",
            "TAO", "RON", "AR", "ENJ", "STX", "XMR", "ZEC", "DASH", "HOT", "IOTA",
            "NEO", "QTUM", "ZIL", "SC", "STORJ", "BAT", "KNC", "ZRX", "1000PEPE", "ORDI",
        ]
        return [f"{c}USDT" for c in top]

    # ─────────────────────────────────────────────
    # DEBUG HELPER
    # ─────────────────────────────────────────────

    @property
    def active_source(self) -> str:
        return "Binance" if self._binance_ok else "OKX (fallback)"
