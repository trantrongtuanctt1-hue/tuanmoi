"""
Signal engine — port of 15M ULTRA v2.2 Pine Script logic
Indicators: Supertrend AI, UT Bot, SAR, SMC structure, RSI, MTF
Score: 0–11 points
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class SignalResult:
    symbol: str
    score: int
    direction: str          # "LONG" | "SHORT" | "NEUTRAL"
    price: float
    sl: float
    tp1: float
    tp2: float
    reasons: list[str]
    timeframe: str = "5m"


# ─── helpers ────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ─── individual indicators ──────────────────────────────────────────────────

def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    atr  = _atr(df, period)
    hl2  = (df["high"] + df["low"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    st   = pd.Series(index=df.index, dtype=float)
    bull = pd.Series(True, index=df.index)

    for i in range(1, len(df)):
        prev_st   = st.iloc[i - 1] if i > 1 else upper.iloc[i]
        prev_bull = bull.iloc[i - 1] if i > 1 else True
        close     = df["close"].iloc[i]

        if prev_bull:
            cur_st = max(lower.iloc[i], prev_st) if close > prev_st else upper.iloc[i]
            bull.iloc[i] = close > cur_st
        else:
            cur_st = min(upper.iloc[i], prev_st) if close < prev_st else lower.iloc[i]
            bull.iloc[i] = close > cur_st
        st.iloc[i] = cur_st

    return bull  # True = bullish


def ut_bot(df: pd.DataFrame, sensitivity: float = 1.0, atr_period: int = 10):
    """UT Bot Alert — returns Series: 1 buy, -1 sell, 0 neutral"""
    atr    = _atr(df, atr_period) * sensitivity
    close  = df["close"]
    trail  = pd.Series(index=df.index, dtype=float)
    signal = pd.Series(0, index=df.index, dtype=int)

    for i in range(1, len(df)):
        prev  = trail.iloc[i - 1] if i > 1 else close.iloc[i]
        c     = close.iloc[i]
        a     = atr.iloc[i]
        if c > prev:
            trail.iloc[i] = max(prev, c - a)
        else:
            trail.iloc[i] = min(prev, c + a)
        if close.iloc[i - 1] < trail.iloc[i - 1] and c > trail.iloc[i]:
            signal.iloc[i] = 1
        elif close.iloc[i - 1] > trail.iloc[i - 1] and c < trail.iloc[i]:
            signal.iloc[i] = -1

    return signal


def parabolic_sar(df: pd.DataFrame, step: float = 0.02, max_af: float = 0.2):
    """Returns Series: True = price above SAR (bullish)"""
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    n     = len(df)
    sar   = np.zeros(n)
    bull  = np.ones(n, dtype=bool)
    af    = step
    ep    = low[0]
    sar[0] = high[0]

    for i in range(1, n):
        if bull[i - 1]:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            sar[i] = min(sar[i], low[i - 1], low[max(0, i - 2)])
            if low[i] < sar[i]:
                bull[i] = False
                sar[i]  = ep
                ep       = low[i]
                af       = step
            else:
                bull[i] = True
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + step, max_af)
        else:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            sar[i] = max(sar[i], high[i - 1], high[max(0, i - 2)])
            if high[i] > sar[i]:
                bull[i] = True
                sar[i]  = ep
                ep       = high[i]
                af       = step
            else:
                bull[i] = False
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + step, max_af)

    return pd.Series(bull, index=df.index)


def smc_score(df: pd.DataFrame) -> tuple[int, list[str]]:
    """
    Smart Money Concept mini-score (0–4):
    - BOS (Break of Structure)
    - OB (Order Block proximity)
    - FVG (Fair Value Gap)
    - Liquidity sweep
    """
    score   = 0
    reasons = []
    close   = df["close"]
    high    = df["high"]
    low     = df["low"]

    # BOS: recent high broken
    if close.iloc[-1] > high.iloc[-20:-1].max():
        score += 1
        reasons.append("BOS↑")
    elif close.iloc[-1] < low.iloc[-20:-1].min():
        score += 1
        reasons.append("BOS↓")

    # Order Block: last bearish candle before big bull move
    body = (df["close"] - df["open"]).abs()
    big  = body.iloc[-10:-1]
    if len(big) and big.max() > body.mean() * 1.5:
        score += 1
        reasons.append("OB")

    # FVG: gap between candle[-3].high and candle[-1].low
    if len(df) >= 3:
        if low.iloc[-1] > high.iloc[-3]:
            score += 1
            reasons.append("FVG↑")
        elif high.iloc[-1] < low.iloc[-3]:
            score += 1
            reasons.append("FVG↓")

    # Liquidity sweep: wick below recent lows then close above
    wick_low = low.iloc[-1]
    prev_low = low.iloc[-20:-1].min()
    if wick_low < prev_low and close.iloc[-1] > prev_low:
        score += 1
        reasons.append("LiqSweep")

    return min(score, 4), reasons


# ─── main scorer ────────────────────────────────────────────────────────────

def score_symbol(
    symbol: str,
    df_5m:  pd.DataFrame,
    df_15m: pd.DataFrame,
    df_1h:  pd.DataFrame,
) -> SignalResult:
    reasons: list[str] = []
    score   = 0
    close   = df_5m["close"].iloc[-1]
    atr_val = _atr(df_5m).iloc[-1]

    # 1. Supertrend 5m (1 pt)
    st_bull = supertrend(df_5m).iloc[-1]
    if st_bull:
        score += 1; reasons.append("ST↑5m")

    # 2. Supertrend 15m (1 pt)
    if len(df_15m) > 20:
        st15 = supertrend(df_15m).iloc[-1]
        if st15:
            score += 1; reasons.append("ST↑15m")

    # 3. Supertrend 1h (1 pt)
    if len(df_1h) > 20:
        st1h = supertrend(df_1h).iloc[-1]
        if st1h:
            score += 1; reasons.append("ST↑1h")

    # 4. UT Bot 5m (1 pt)
    ut = ut_bot(df_5m).iloc[-1]
    if ut == 1:
        score += 1; reasons.append("UTBot↑")

    # 5. Parabolic SAR (1 pt)
    sar_bull = parabolic_sar(df_5m).iloc[-1]
    if sar_bull:
        score += 1; reasons.append("SAR↑")

    # 6–7. RSI (2 pts)
    rsi_val = _rsi(df_5m["close"]).iloc[-1]
    if 45 < rsi_val < 70:
        score += 1; reasons.append(f"RSI{rsi_val:.0f}")
    if rsi_val > 50:
        score += 1; reasons.append("RSI>50")

    # 8. EMA cross (1 pt)
    ema9  = _ema(df_5m["close"], 9).iloc[-1]
    ema21 = _ema(df_5m["close"], 21).iloc[-1]
    if ema9 > ema21:
        score += 1; reasons.append("EMA↑")

    # 9–11. SMC (up to 3 pts capped at 3)
    smc, smc_r = smc_score(df_5m)
    smc_pts = min(smc, 3)
    score  += smc_pts
    reasons += smc_r

    # Direction
    bull_count = sum(1 for r in reasons if "↑" in r or r.startswith("RSI"))
    bear_count = sum(1 for r in reasons if "↓" in r)
    direction  = "LONG" if bull_count >= 3 else ("SHORT" if bear_count >= 2 else "NEUTRAL")

    # SL/TP
    sl  = close - 1.5 * atr_val if direction == "LONG" else close + 1.5 * atr_val
    tp1 = close + 2.0 * atr_val if direction == "LONG" else close - 2.0 * atr_val
    tp2 = close + 3.5 * atr_val if direction == "LONG" else close - 3.5 * atr_val

    return SignalResult(
        symbol    = symbol,
        score     = min(score, 11),
        direction = direction,
        price     = round(close, 6),
        sl        = round(sl, 6),
        tp1       = round(tp1, 6),
        tp2       = round(tp2, 6),
        reasons   = reasons,
    )
