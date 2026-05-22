"""
indicators.py — Trend Meter calculations
Ported from Pine Script (Lij_MC) sang Python
"""

import pandas as pd
import numpy as np


# ══════════════════════════════════════════════
#   BASE MATH
# ══════════════════════════════════════════════

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def calc_rsi(close: pd.Series, period: int) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


def calc_fast_macd_hist(close: pd.Series) -> pd.Series:
    """Fast MACD (8, 21, 5) — Trend Meter 1."""
    macd   = ema(close, 8) - ema(close, 21)
    signal = ema(macd, 5)
    return macd - signal


def calc_wave_trend(df: pd.DataFrame, n1: int = 9, n2: int = 12):
    """WaveTrend oscillator — bonus confirmation."""
    hlc3 = (df["high"] + df["low"] + df["close"]) / 3
    _esa  = ema(hlc3, n1)
    _de   = ema((hlc3 - _esa).abs(), n1)
    _ci   = (hlc3 - _esa) / (0.015 * _de + 1e-10)
    wt1   = ema(_ci, n2)
    wt2   = sma(wt1, 3)
    return wt1, wt2


# ══════════════════════════════════════════════
#   RAW → DATAFRAME
# ══════════════════════════════════════════════

def to_df(raw_ohlcv: list) -> pd.DataFrame:
    """Chuyển raw ccxt OHLCV list → DataFrame."""
    df = pd.DataFrame(
        raw_ohlcv,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df = df.astype({
        "open": float, "high": float, "low": float,
        "close": float, "volume": float,
    })
    return df.reset_index(drop=True)


# ══════════════════════════════════════════════
#   MAIN ANALYZE
# ══════════════════════════════════════════════

def analyze(raw_ohlcv: list) -> dict:
    """
    Phân tích Trend Meter từ raw OHLCV data.

    Trả về dict:
      tm1, tm2, tm3          — Trend Meters (bool)
      tb1, tb2               — Trend Bars (bool)
      all_green, all_red     — Tất cả align (bool)
      just_turned_green/red  — Vừa đổi màu (bool)
      green_count            — Số TM đang xanh (0-3)
      wt_cross_up/down       — WaveTrend cross (bool)
      rsi5, rsi13, close     — Giá trị tham khảo
    """
    df    = to_df(raw_ohlcv)
    close = df["close"]

    # ── Trend Meter 1: Fast MACD histogram > 0 ──────────
    hist     = calc_fast_macd_hist(close)
    tm1_cur  = bool(hist.iloc[-1] > 0)
    tm1_prev = bool(hist.iloc[-2] > 0)

    # ── Trend Meter 2: RSI 13 > 50 ──────────────────────
    rsi13    = calc_rsi(close, 13)
    tm2_cur  = bool(rsi13.iloc[-1] > 50)
    tm2_prev = bool(rsi13.iloc[-2] > 50)

    # ── Trend Meter 3: RSI 5 > 50 ───────────────────────
    rsi5     = calc_rsi(close, 5)
    tm3_cur  = bool(rsi5.iloc[-1] > 50)
    tm3_prev = bool(rsi5.iloc[-2] > 50)

    # ── Trend Bar 1: EMA 5 > EMA 11 ─────────────────────
    tb1 = bool(ema(close, 5).iloc[-1] > ema(close, 11).iloc[-1])

    # ── Trend Bar 2: EMA 13 > SMA 36 ────────────────────
    tb2 = bool(ema(close, 13).iloc[-1] > sma(close, 36).iloc[-1])

    # ── WaveTrend Cross ──────────────────────────────────
    wt1, wt2 = calc_wave_trend(df)
    wt_cross_up   = bool(wt1.iloc[-1] >  wt2.iloc[-1] and wt1.iloc[-2] <= wt2.iloc[-2])
    wt_cross_down = bool(wt1.iloc[-1] <  wt2.iloc[-1] and wt1.iloc[-2] >= wt2.iloc[-2])

    # ── Aggregate ────────────────────────────────────────
    all_green_cur  = tm1_cur  and tm2_cur  and tm3_cur
    all_red_cur    = not tm1_cur  and not tm2_cur  and not tm3_cur
    all_green_prev = tm1_prev and tm2_prev and tm3_prev
    all_red_prev   = not tm1_prev and not tm2_prev and not tm3_prev

    green_count = sum([tm1_cur, tm2_cur, tm3_cur])

    return {
        # Trend Meters
        "tm1": tm1_cur,
        "tm2": tm2_cur,
        "tm3": tm3_cur,
        # Trend Bars
        "tb1": tb1,
        "tb2": tb2,
        # Status
        "all_green":         all_green_cur,
        "all_red":           all_red_cur,
        "just_turned_green": all_green_cur and not all_green_prev,
        "just_turned_red":   all_red_cur   and not all_red_prev,
        "green_count":       green_count,
        # WaveTrend
        "wt_cross_up":   wt_cross_up,
        "wt_cross_down": wt_cross_down,
        # Raw values
        "rsi5":  round(float(rsi5.iloc[-1]),  1),
        "rsi13": round(float(rsi13.iloc[-1]), 1),
        "close": float(close.iloc[-1]),
    }
