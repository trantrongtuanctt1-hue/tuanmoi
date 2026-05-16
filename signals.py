"""
Signal engine — 15M ULTRA v2.2 port
Score: 0–10 points. Ngưỡng alert mặc định: 5
Rebalanced để cho tín hiệu thực tế hơn.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field


@dataclass
class SignalResult:
    symbol:    str
    score:     int
    direction: str          # "LONG" | "SHORT" | "NEUTRAL"
    price:     float
    sl:        float
    tp1:       float
    tp2:       float
    reasons:   list[str] = field(default_factory=list)
    timeframe: str = "5m"


# ── helpers ─────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def _atr(df: pd.DataFrame, p: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(span=p, adjust=False).mean()

def _rsi(close: pd.Series, p: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(span=p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=p, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


# ── indicators ───────────────────────────────────────────────────────────────

def supertrend_bull(df: pd.DataFrame, p: int = 10, mult: float = 3.0) -> bool:
    """Returns True if last candle is in bullish supertrend."""
    if len(df) < p + 2:
        return False
    atr  = _atr(df, p)
    hl2  = (df["high"] + df["low"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    bull = True
    st   = upper.iloc[0]
    for i in range(1, len(df)):
        c = df["close"].iloc[i]
        if bull:
            st = max(lower.iloc[i], st)
            if c < st:
                bull = False; st = upper.iloc[i]
        else:
            st = min(upper.iloc[i], st)
            if c > st:
                bull = True;  st = lower.iloc[i]
    return bull


def ut_bot_signal(df: pd.DataFrame, sensitivity: float = 1.0, p: int = 10) -> int:
    """1 = buy cross, -1 = sell cross, 0 = none (checks last 3 bars)."""
    if len(df) < p + 3:
        return 0
    atr   = _atr(df, p) * sensitivity
    close = df["close"]
    trail = [close.iloc[0]]
    for i in range(1, len(df)):
        c = close.iloc[i]; a = atr.iloc[i]; prev = trail[-1]
        trail.append(max(prev, c - a) if c > prev else min(prev, c + a))
    # Check last 3 bars for a recent cross
    for i in range(len(df)-3, len(df)-1):
        if close.iloc[i-1] < trail[i-1] and close.iloc[i] > trail[i]:
            return 1
        if close.iloc[i-1] > trail[i-1] and close.iloc[i] < trail[i]:
            return -1
    return 0


def sar_bull(df: pd.DataFrame, step: float = 0.02, max_af: float = 0.2) -> bool:
    """True = price above SAR (bullish)."""
    if len(df) < 3:
        return False
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values
    bull  = True; af = step; ep = high[0]; sar = low[0]
    for i in range(1, len(df)):
        if bull:
            sar = sar + af * (ep - sar)
            sar = min(sar, low[i-1], low[max(0,i-2)])
            if low[i] < sar:
                bull = False; sar = ep; ep = low[i]; af = step
            else:
                if high[i] > ep: ep = high[i]; af = min(af+step, max_af)
        else:
            sar = sar + af * (ep - sar)
            sar = max(sar, high[i-1], high[max(0,i-2)])
            if high[i] > sar:
                bull = True; sar = ep; ep = high[i]; af = step
            else:
                if low[i] < ep: ep = low[i]; af = min(af+step, max_af)
    return bull


def ema_trend(df: pd.DataFrame) -> int:
    """
    +2 if 9>21>50 (strong bull stack)
    +1 if 9>21
     0 if mixed
    -1 if 9<21
    """
    c    = df["close"]
    e9   = _ema(c, 9).iloc[-1]
    e21  = _ema(c, 21).iloc[-1]
    e50  = _ema(c, 50).iloc[-1]
    if e9 > e21 > e50:
        return 2
    if e9 > e21:
        return 1
    if e9 < e21:
        return -1
    return 0


def rsi_score(df: pd.DataFrame) -> tuple[int, float]:
    """
    Bullish:  >50 = +1, 50-70 = +1 more (ideal zone)
    Bearish: <50 = -1, 30-50 = -1 more
    Returns (score_delta, rsi_value)
    """
    rsi = _rsi(df["close"]).iloc[-1]
    if rsi >= 50:
        pts = 1 + (1 if rsi <= 72 else 0)
    else:
        pts = -1 + (-1 if rsi >= 28 else 0)
    return pts, rsi


def volume_confirm(df: pd.DataFrame) -> bool:
    """Last candle volume > 1.3x 20-bar average."""
    if len(df) < 21:
        return False
    avg = df["volume"].iloc[-21:-1].mean()
    return df["volume"].iloc[-1] > avg * 1.3


def smc_mini(df: pd.DataFrame) -> tuple[int, list[str]]:
    """SMC: BOS + OB, max +2."""
    score = 0; tags = []
    close = df["close"]; high = df["high"]; low = df["low"]
    # BOS up
    if close.iloc[-1] > high.iloc[-20:-1].max():
        score += 1; tags.append("BOS↑")
    elif close.iloc[-1] < low.iloc[-20:-1].min():
        score += 1; tags.append("BOS↓")
    # Order block: big body candle nearby
    body = (df["close"] - df["open"]).abs()
    if len(body) > 10 and body.iloc[-5:-1].max() > body.mean() * 1.8:
        score += 1; tags.append("OB")
    return min(score, 2), tags


# ── main scorer ──────────────────────────────────────────────────────────────

def score_symbol(
    symbol: str,
    df_5m:  pd.DataFrame,
    df_15m: pd.DataFrame,
    df_1h:  pd.DataFrame,
) -> SignalResult:
    reasons: list[str] = []
    score = 0
    close  = df_5m["close"].iloc[-1]
    atr_v  = _atr(df_5m).iloc[-1]

    # 1. Supertrend MTF (+1 each, max +3)
    if supertrend_bull(df_5m):
        score += 1; reasons.append("ST↑5m")
    if len(df_15m) > 20 and supertrend_bull(df_15m):
        score += 1; reasons.append("ST↑15m")
    if len(df_1h)  > 20 and supertrend_bull(df_1h):
        score += 1; reasons.append("ST↑1h")

    # 2. UT Bot — widen window to last 3 bars (+1)
    ut = ut_bot_signal(df_5m)
    if ut == 1:
        score += 1; reasons.append("UTBot↑")

    # 3. SAR (+1)
    if sar_bull(df_5m):
        score += 1; reasons.append("SAR↑")

    # 4. EMA trend (+1 or +2)
    et = ema_trend(df_5m)
    if et == 2:
        score += 2; reasons.append("EMA3x↑")
    elif et == 1:
        score += 1; reasons.append("EMA↑")

    # 5. RSI (±2)
    rsi_pts, rsi_val = rsi_score(df_5m)
    score += rsi_pts
    if rsi_pts > 0:
        reasons.append(f"RSI{rsi_val:.0f}↑")

    # 6. Volume confirmation (+1)
    if volume_confirm(df_5m):
        score += 1; reasons.append("Vol↑")

    # 7. SMC (+0 to +2)
    smc_pts, smc_r = smc_mini(df_5m)
    score  += smc_pts
    reasons += smc_r

    # Direction
    bull_tags = sum(1 for r in reasons if "↑" in r)
    bear_tags = sum(1 for r in reasons if "↓" in r)
    direction = "LONG" if bull_tags > bear_tags else ("SHORT" if bear_tags > bull_tags else "NEUTRAL")

    # SL / TP
    if direction == "LONG":
        sl  = close - 1.5 * atr_v
        tp1 = close + 2.0 * atr_v
        tp2 = close + 3.5 * atr_v
    else:
        sl  = close + 1.5 * atr_v
        tp1 = close - 2.0 * atr_v
        tp2 = close - 3.5 * atr_v

    return SignalResult(
        symbol    = symbol,
        score     = max(0, score),
        direction = direction,
        price     = round(close, 6),
        sl        = round(sl, 6),
        tp1       = round(tp1, 6),
        tp2       = round(tp2, 6),
        reasons   = reasons,
    )
