"""
🎯 Pump Scanner — Logic chính
Replicates Pine Script: Volume + CVD + BB Squeeze + SMC + EMA Trend
"""

import asyncio
import logging
from typing import Optional

import ccxt.async_support as ccxt
import numpy as np
import pandas as pd

from src.config import Config

logger = logging.getLogger("Scanner")


# ══════════════════════════════════════════════════════════════════════════
#  INDICATOR FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def stdev(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).std(ddof=0)

def calc_volume_score(df: pd.DataFrame, vol_len: int, vol_mult: float, vol_mega_x: float) -> dict:
    """Volume Spike: so sánh volume hiện tại vs EMA volume"""
    vol_ema = ema(df["volume"], vol_len)
    last_vol = df["volume"].iloc[-1]
    last_ema = vol_ema.iloc[-1]
    ratio = last_vol / last_ema if last_ema > 0 else 0.0

    mega  = ratio >= vol_mega_x
    spike = ratio >= vol_mult

    score = 3 if mega else 2 if spike else 0
    return {"vol_ratio": ratio, "vol_spike": spike, "vol_mega": mega, "vol_score": score}

def calc_cvd(df: pd.DataFrame, cvd_len: int) -> dict:
    """CVD proxy = (body/range) * volume — tích lũy"""
    body  = df["close"] - df["open"]
    rng   = df["high"] - df["low"]
    delta = np.where(rng > 0, (body / rng) * df["volume"], 0.0)
    cvd   = pd.Series(delta, index=df.index).cumsum()

    cvd_rising = float(cvd.iloc[-1]) > float(cvd.iloc[-2])

    # Bullish Divergence: giá thấp hơn nhưng CVD cao hơn
    price_low = df["close"].iloc[-1] < df["close"].iloc[-cvd_len:].min()
    cvd_high  = cvd.iloc[-1] > cvd.iloc[-cvd_len]
    cvd_div   = price_low and cvd_high

    cvd_score     = 2 if cvd_rising else 0
    cvd_div_bonus = 1 if cvd_div   else 0
    return {
        "cvd_rising": cvd_rising,
        "cvd_div":    cvd_div,
        "cvd_score":  cvd_score,
        "cvd_div_bonus": cvd_div_bonus,
    }

def calc_bb(df: pd.DataFrame, bb_len: int, bb_mult: float, squeeze_thresh: float) -> dict:
    """Bollinger Bands Squeeze"""
    basis     = sma(df["close"], bb_len)
    dev       = stdev(df["close"], bb_len)
    upper     = basis + bb_mult * dev
    lower     = basis - bb_mult * dev
    width_pct = ((upper - lower) / basis * 100).iloc[-1]

    prev_width = ((upper - lower) / basis * 100).iloc[-2]
    squeeze  = width_pct < squeeze_thresh
    explode  = width_pct > prev_width and width_pct > ((upper - lower) / basis * 100).iloc[-3]

    bb_score = 2 if squeeze else 0
    return {
        "bb_width":   width_pct,
        "bb_squeeze": squeeze,
        "bb_explode": explode,
        "bb_score":   bb_score,
    }

def calc_smc(df: pd.DataFrame, smc_len: int) -> dict:
    """SMC — CHoCH / BOS bằng Pivot Highs/Lows"""
    highs = df["high"].values
    lows  = df["low"].values
    closes = df["close"].values
    n = len(df)

    # Tìm pivot highs/lows (simplified)
    def find_pivots(arr, left, right, mode="high"):
        pivots = []
        for i in range(left, n - right):
            window = arr[i - left: i + right + 1]
            if mode == "high" and arr[i] == max(window):
                pivots.append((i, arr[i]))
            elif mode == "low" and arr[i] == min(window):
                pivots.append((i, arr[i]))
        return pivots

    ph = find_pivots(highs, smc_len, smc_len, "high")
    pl = find_pivots(lows,  smc_len, smc_len, "low")

    last_close  = closes[-1]
    prev_close  = closes[-2]

    # Lấy 2 swing high và 2 swing low gần nhất
    sw_h  = ph[-1][1] if len(ph) >= 1 else None
    sw_h2 = ph[-2][1] if len(ph) >= 2 else None
    sw_l  = pl[-1][1] if len(pl) >= 1 else None

    choch_bull = sw_h is not None and last_close > sw_h and prev_close <= sw_h
    bos_bull   = (sw_h is not None and sw_h2 is not None
                  and sw_h > sw_h2 and last_close > sw_h)
    choch_bear = sw_l is not None and last_close < sw_l and prev_close >= sw_l

    smc_score = 2 if bos_bull else 1 if choch_bull else 0
    return {
        "choch_bull": choch_bull,
        "bos_bull":   bos_bull,
        "choch_bear": choch_bear,
        "smc_score":  smc_score,
    }

def calc_trend(df: pd.DataFrame, ema_fast: int, ema_slow: int) -> dict:
    """EMA Trend Filter"""
    if len(df) < ema_slow:
        return {"trend_up": False, "trend_dn": False, "trend_score": 0}

    ef = ema(df["close"], ema_fast).iloc[-1]
    es = ema(df["close"], ema_slow).iloc[-1]

    trend_up = ef > es
    trend_dn = ef < es
    return {
        "trend_up":    trend_up,
        "trend_dn":    trend_dn,
        "trend_score": 1 if trend_up else 0,
    }

def compute_pump_score(df: pd.DataFrame, cfg: Config) -> dict:
    """Tính toán tổng hợp Pump Score từ OHLCV dataframe"""
    # Cần ít nhất max(ema_slow, 50) nến
    min_bars = max(cfg.EMA_SLOW, cfg.BB_LEN, cfg.VOL_LEN) + 10
    if len(df) < min_bars:
        return None

    vol  = calc_volume_score(df, cfg.VOL_LEN, cfg.VOL_MULT, cfg.VOL_MEGA_X)
    cvd  = calc_cvd(df, cfg.CVD_LEN)
    bb   = calc_bb(df, cfg.BB_LEN, cfg.BB_MULT, cfg.BB_SQUEEZE_THRESH)
    smc  = calc_smc(df, cfg.SMC_LEN)
    tr   = calc_trend(df, cfg.EMA_FAST, cfg.EMA_SLOW)

    total_raw = (
        vol["vol_score"] +
        cvd["cvd_score"] +
        cvd["cvd_div_bonus"] +
        bb["bb_score"] +
        smc["smc_score"] +
        tr["trend_score"]
    )
    score = min(total_raw, 10)

    detail = {**vol, **cvd, **bb, **smc, **tr}
    return {"score": score, "total_raw": total_raw, "detail": detail}


# ══════════════════════════════════════════════════════════════════════════
#  SCANNER CLASS
# ══════════════════════════════════════════════════════════════════════════

class PumpScanner:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.exchange = None

    async def _get_exchange(self):
        if self.exchange is None:
            ex_class = getattr(ccxt, self.cfg.EXCHANGE)
            self.exchange = ex_class({
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
            await self.exchange.load_markets()
        return self.exchange

    async def _fetch_ohlcv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        ex = await self._get_exchange()
        limit = max(self.cfg.EMA_SLOW, 300) + 50
        try:
            bars = await ex.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not bars or len(bars) < 50:
                return None
            df = pd.DataFrame(bars, columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.astype(float)
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            return df
        except Exception as e:
            logger.debug(f"Fetch {symbol} lỗi: {e}")
            return None

    async def scan_one(self, symbol: str, timeframe: Optional[str] = None) -> dict:
        tf = timeframe or self.cfg.TIMEFRAME
        # Chuẩn hóa: EDENUSDT -> EDEN/USDT:USDT (futures)
        sym = symbol.replace("USDT", "/USDT:USDT") if ":" not in symbol and "/" not in symbol else symbol
        # Fallback: thử spot
        if "/" not in sym:
            sym = symbol.replace("USDT", "") + "/USDT"

        df = await self._fetch_ohlcv(sym, tf)
        if df is None:
            raise ValueError(f"Không lấy được dữ liệu cho {symbol}")

        result = compute_pump_score(df, self.cfg)
        if result is None:
            raise ValueError(f"Không đủ dữ liệu cho {symbol}")

        return {
            "symbol":    symbol,
            "timeframe": tf,
            "price":     df["close"].iloc[-1],
            **result,
        }

    async def _scan_symbol(self, symbol: str, sem: asyncio.Semaphore) -> Optional[dict]:
        async with sem:
            try:
                df = await self._fetch_ohlcv(symbol, self.cfg.TIMEFRAME)
                if df is None:
                    return None
                result = compute_pump_score(df, self.cfg)
                if result is None:
                    return None
                clean = symbol.replace("/USDT:USDT", "USDT").replace("/USDT", "USDT")
                return {
                    "symbol":    clean,
                    "timeframe": self.cfg.TIMEFRAME,
                    "price":     df["close"].iloc[-1],
                    **result,
                }
            except Exception as e:
                logger.debug(f"Skip {symbol}: {e}")
                return None

    async def scan_all(self) -> list[dict]:
        ex = await self._get_exchange()

        # Lấy danh sách USDT futures, sort theo volume
        try:
            tickers = await ex.fetch_tickers()
            usdt_pairs = [
                (sym, t.get("quoteVolume", 0) or 0)
                for sym, t in tickers.items()
                if sym.endswith("/USDT:USDT")
            ]
            usdt_pairs.sort(key=lambda x: x[1], reverse=True)
            symbols = [s for s, _ in usdt_pairs[: self.cfg.TOP_N]]
        except Exception:
            # Fallback: lấy từ markets
            symbols = [s for s in ex.markets if s.endswith("/USDT:USDT")][: self.cfg.TOP_N]

        logger.info(f"📡 Scan {len(symbols)} symbols [{self.cfg.TIMEFRAME}]")

        sem = asyncio.Semaphore(self.cfg.CONCURRENCY)
        tasks = [self._scan_symbol(sym, sem) for sym in symbols]
        results = await asyncio.gather(*tasks)

        valid = [r for r in results if r is not None]
        logger.info(f"✅ {len(valid)}/{len(symbols)} symbols OK")
        return valid

    async def close(self):
        if self.exchange:
            await self.exchange.close()
