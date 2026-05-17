"""
OKX REST fetcher — thay thế Binance/Bybit
Endpoint public, không cần API key, không bị geo-block.
Hỗ trợ quét tối đa 500 token (theo volume 24h).
"""

import logging
import asyncio
from typing import Optional, List
import aiohttp
import pandas as pd

logger = logging.getLogger(__name__)

BASE = "https://www.okx.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


class BybitFetcher:  # Giữ tên class để không cần sửa file khác
    def __init__(self, max_candles: int = 100):
        """
        max_candles: số nến tối đa mỗi lần fetch.
        OKX chỉ hỗ trợ tối đa 100 nến cho endpoint candles.
        """
        self.max_candles = min(max_candles, 100)  # OKX limit = 100
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        current_loop = asyncio.get_running_loop()
        # Tạo session mới nếu chưa có, đã đóng, hoặc thuộc về event loop khác
        if (self._session is None
                or self._session.closed
                or getattr(self, "_session_loop", None) is not current_loop):
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

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV từ OKX REST.
        OKX symbol format: BTC-USDT-SWAP (perpetual futures)
        Chuyển BTCUSDT → BTC-USDT-SWAP
        limit sẽ được giới hạn tối đa self.max_candles (100)
        """
        limit = min(limit, self.max_candles)

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

    async def fetch_top_symbols(self, limit: int = 500) -> List[str]:
        """
        Lấy top USDT perpetual symbols theo volume 24h từ OKX.
        Trả về dạng BTCUSDT (giữ format cũ để scanner không cần sửa).
        Nếu OKX lỗi, dùng fallback mở rộng (có thể lên tới 500 symbol).
        """
        url = f"{BASE}/api/v5/market/tickers"
        params = {"instType": "SWAP"}
        try:
            session = await self._get_session()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"fetch_top_symbols HTTP {resp.status}, dùng fallback mở rộng")
                    return self._generate_extended_fallback()[:limit]
                data = await resp.json()
            if data.get("code") != "0":
                logger.warning(f"fetch_top_symbols OKX error: {data.get('msg')} — dùng fallback mở rộng")
                return self._generate_extended_fallback()[:limit]

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

            logger.info(f"Fetched {len(syms)} symbols từ OKX (yêu cầu {limit})")
            if len(syms) < limit:
                logger.warning(f"OKX chỉ trả {len(syms)} symbols, thiếu {limit - len(syms)}. Có thể dùng fallback bổ sung?")
                # Có thể bổ sung fallback nếu muốn đủ limit, nhưng không bắt buộc
            return syms if syms else self._generate_extended_fallback()[:limit]

        except Exception as e:
            logger.warning(f"fetch_top_symbols error: {e} — dùng fallback mở rộng")
            return self._generate_extended_fallback()[:limit]

    def _generate_extended_fallback(self) -> List[str]:
        """
        Tạo danh sách fallback mở rộng lên tới ~500 symbol.
        Kết hợp top coin theo market cap + các coin phổ biến + placeholder nếu cần.
        """
        # Top coin thực tế (khoảng 80-100 coin)
        top_coins = [
            "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "DOT", "LINK",
            "TRX", "LTC", "BCH", "UNI", "ATOM", "ETC", "XLM", "NEAR", "APT", "ARB",
            "OP", "INJ", "SUI", "WIF", "BONK", "PEPE", "ORDI", "WLD", "FET", "RENDER",
            "GRT", "AAVE", "MKR", "LDO", "RUNE", "SAND", "MANA", "AXS", "GALA", "IMX",
            "HBAR", "CHZ", "KAS", "TON", "NOT", "EIGEN", "STRK", "JUP", "TIA", "SEI",
            "BLUR", "AGIX", "OCEAN", "CFX", "ALGO", "VET", "ICP", "EGLD", "FLOW", "THETA",
            "FTM", "SNX", "COMP", "SUSHI", "DYDX", "GMX", "APE", "PYTH", "BERA", "MOVE",
            "NEIRO", "GOAT", "MOODENG", "PNUT", "BOME", "DOGS", "CATI", "1000PEPE",
            "ZRO", "ZK", "TAO", "RON", "AR", "ENJ", "STX", "XMR", "ZEC", "DASH",
            "HOT", "IOTA", "NEO", "QTUM", "ZIL", "SC", "STORJ", "BAT", "KNC", "ZRX"
        ]
        # Thêm các coin phổ biến khác từ các sàn
        extended = [f"{coin}USDT" for coin in top_coins]

        # Nếu chưa đủ 500, thêm các coin có tên tổng quát (placeholder)
        # nhưng thực tế sẽ không dùng đến vì OKX thường có >500 swap USDT
        while len(extended) < 500:
            extended.append(f"COIN{len(extended)}USDT")
        return extended


# Ví dụ sử dụng (có thể bỏ comment để test)
# async def main():
#     fetcher = BybitFetcher()
#     symbols = await fetcher.fetch_top_symbols(500)
#     print(f"Total symbols: {len(symbols)}")
#     # Lấy dữ liệu 5m cho 5 token đầu
#     for sym in symbols[:5]:
#         df = await fetcher.fetch_ohlcv(sym, "5m", limit=100)
#         print(f"{sym}: {len(df)} rows" if df is not None else f"{sym}: failed")
#         await asyncio.sleep(0.1)  # rate limit ~10 request/giây
#     await fetcher.close()
#
# if __name__ == "__main__":
#     asyncio.run(main())
