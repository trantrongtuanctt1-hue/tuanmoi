"""
indicators.py — Tính toán indicator theo đúng logic Pine Script v5
SuperTrend, UT Bot, Parabolic SAR, EMA, RSI, ATR, Bollinger, Volume Balance
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Tuple


# ── EMA ──────────────────────────────────────────────────────────────────
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


# ── RSI ──────────────────────────────────────────────────────────────────
def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta  = close.diff()
    gain   = delta.clip(lower=0)
    loss   = (-delta).clip(lower=0)
    avg_g  = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l  = loss.ewm(com=period - 1, adjust=False).mean()
    rs     = avg_g / avg_l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


# ── ATR ──────────────────────────────────────────────────────────────────
def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = 14) -> pd.Series:
    h, l, c1 = high.values, low.values, close.shift(1).values
    tr = np.maximum.reduce([h - l, np.abs(h - c1), np.abs(l - c1)])
    tr_s = pd.Series(tr, index=close.index)
    return tr_s.ewm(alpha=1 / period, adjust=False).mean()


# ── Bollinger Bands ───────────────────────────────────────────────────────
def calc_bollinger(close: pd.Series, period: int = 20,
                   mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    basis = close.rolling(period).mean()
    std   = close.rolling(period).std(ddof=0)
    return basis, basis + mult * std, basis - mult * std


# ── SuperTrend (fixed factor, numpy-accelerated) ─────────────────────────
def calc_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 10, mult: float = 3.0
                    ) -> Tuple[pd.Series, pd.Series]:
    """
    Returns (st_line, direction)  direction: 1=bull, -1=bear
    Logic bám sát Pine Script ta.supertrend()
    """
    atr_v   = calc_atr(high, low, close, period).values
    hl2     = ((high.values + low.values) / 2.0)
    cls     = close.values
    n       = len(cls)

    raw_up  = hl2 + mult * atr_v
    raw_dn  = hl2 - mult * atr_v

    up      = raw_up.copy()
    dn      = raw_dn.copy()
    trend   = np.ones(n, dtype=np.int8)
    st      = np.zeros(n)

    for i in range(1, n):
        # Upper band
        up[i] = raw_up[i] if (raw_up[i] < up[i-1] or cls[i-1] > up[i-1]) else up[i-1]
        # Lower band
        dn[i] = raw_dn[i] if (raw_dn[i] > dn[i-1] or cls[i-1] < dn[i-1]) else dn[i-1]
        # Trend
        if trend[i-1] == 1:
            trend[i] =  1 if cls[i] >= dn[i] else -1
        else:
            trend[i] = -1 if cls[i] <= up[i] else  1
        st[i] = dn[i] if trend[i] == 1 else up[i]

    st[0] = dn[0] if trend[0] == 1 else up[0]
    return (pd.Series(st, index=close.index),
            pd.Series(trend.astype(int), index=close.index))


# ── UT Bot (Trailing Stop với ATR) ───────────────────────────────────────
def calc_ut_bot(close: pd.Series, high: pd.Series, low: pd.Series,
                key_val: float = 1.0, atr_period: int = 10
                ) -> Tuple[pd.Series, pd.Series]:
    """
    Returns (trail, pos)  pos: 1=long, -1=short, 0=flat
    """
    atr_v  = calc_atr(high, low, close, atr_period).values
    nLoss  = key_val * atr_v
    cls    = close.values
    n      = len(cls)

    trail  = np.zeros(n)
    pos    = np.zeros(n, dtype=np.int8)

    # khởi tạo
    trail[0] = cls[0] - nLoss[0]

    for i in range(1, n):
        c, c1, t1, nl = cls[i], cls[i-1], trail[i-1], nLoss[i]
        if c > t1 and c1 > t1:
            trail[i] = max(t1, c - nl)
        elif c < t1 and c1 < t1:
            trail[i] = min(t1, c + nl)
        elif c > t1:
            trail[i] = c - nl
        else:
            trail[i] = c + nl

        if c1 < t1 and c > trail[i]:
            pos[i] = 1
        elif c1 > t1 and c < trail[i]:
            pos[i] = -1
        else:
            pos[i] = pos[i-1]

    return (pd.Series(trail, index=close.index),
            pd.Series(pos.astype(int), index=close.index))


# ── Parabolic SAR ─────────────────────────────────────────────────────────
def calc_psar(high: pd.Series, low: pd.Series,
              af_start: float = 0.02, af_inc: float = 0.02,
              af_max: float = 0.2) -> Tuple[pd.Series, pd.Series]:
    """
    Returns (sar_values, is_bull)
    """
    h   = high.values
    l   = low.values
    n   = len(h)
    sar = np.zeros(n)
    bull = np.ones(n, dtype=bool)
    af   = af_start
    ep   = h[0]
    sar[0] = l[0]

    for i in range(1, n):
        prev_bull = bull[i-1]
        prev_sar  = sar[i-1]
        new_sar   = prev_sar + af * (ep - prev_sar)

        if prev_bull:
            new_sar = min(new_sar, l[i-1], l[i-2] if i >= 2 else l[i-1])
            if l[i] < new_sar:
                bull[i] = False
                new_sar  = ep
                ep       = l[i]
                af       = af_start
            else:
                bull[i] = True
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + af_inc, af_max)
        else:
            new_sar = max(new_sar, h[i-1], h[i-2] if i >= 2 else h[i-1])
            if h[i] > new_sar:
                bull[i] = True
                new_sar  = ep
                ep       = h[i]
                af       = af_start
            else:
                bull[i] = False
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + af_inc, af_max)

        sar[i] = new_sar

    return (pd.Series(sar,  index=high.index),
            pd.Series(bull, index=high.index))


# ── Volume Balance ─────────────────────────────────────────────────────────
def calc_volume_balance(close: pd.Series, open_: pd.Series,
                        volume: pd.Series,
                        lookback: int = 100) -> Tuple[pd.Series, pd.Series]:
    is_bull   = (close >= open_)
    bull_vol  = volume.where(is_bull, 0.0)
    bear_vol  = volume.where(~is_bull, 0.0)
    bull_sum  = bull_vol.rolling(lookback).sum()
    bear_sum  = bear_vol.rolling(lookback).sum()
    total     = bull_sum + bear_sum
    bull_pct  = (bull_sum / total.replace(0, np.nan) * 100).fillna(50)
    bear_pct  = (bear_sum / total.replace(0, np.nan) * 100).fillna(50)
    return bull_pct, bear_pct


# ── RSI direction (giống f_rsiDir trong Pine Script) ─────────────────────
def rsi_direction(rsi_series: pd.Series,
                  lookback: int = 3,
                  threshold: float = 1.5) -> int:
    """1=tăng, -1=giảm, 0=đi ngang"""
    if len(rsi_series) < lookback + 2:
        return 0
    diff = float(rsi_series.iloc[-1]) - float(rsi_series.iloc[-1 - lookback])
    return 1 if diff > threshold else (-1 if diff < -threshold else 0)


# ── TF scoring (giống f_tfBull / f_tfBear) ────────────────────────────────
def tf_score_bull(st_dir: int, ut_pos: int, sar_bull: bool, ema_bull: bool) -> int:
    """Điểm bull 1 TF (0–4). ≥3 = bullish TF"""
    return int(st_dir == 1) + int(ut_pos == 1) + int(sar_bull) + int(ema_bull)


def tf_score_bear(st_dir: int, ut_pos: int, sar_bull: bool, ema_bear: bool) -> int:
    """Điểm bear 1 TF (0–4). ≥3 = bearish TF"""
    return int(st_dir == -1) + int(ut_pos == -1) + int(not sar_bull) + int(ema_bear)


# ── FVG (Fair Value Gap) ─────────────────────────────────────────────────
def has_recent_fvg(high: pd.Series, low: pd.Series, close: pd.Series,
                   min_pct: float = 0.05, lookback: int = 3) -> Tuple[bool, bool]:
    """
    Returns (has_bull_fvg, has_bear_fvg) trong lookback nến gần nhất
    """
    h, l, c = high.values, low.values, close.values
    n = len(h)
    bull_fvg = False
    bear_fvg = False
    for i in range(max(2, n - lookback - 2), n):
        if i < 2:
            continue
        gap_size_bull = (l[i] - h[i-2]) / c[i] * 100 if c[i] > 0 else 0
        gap_size_bear = (l[i-2] - h[i]) / c[i] * 100 if c[i] > 0 else 0
        if l[i] > h[i-2] and gap_size_bull >= min_pct:
            bull_fvg = True
        if h[i] < l[i-2] and gap_size_bear >= min_pct:
            bear_fvg = True
    return bull_fvg, bear_fvg
