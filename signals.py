"""
Signal engine v3.0
──────────────────
SXL Sniper (5 confluences) — giữ nguyên
+ 15M ULTRA port từ PineScript:
    ① SuperTrend AI   (best ATR-factor qua performance tracking)
    ② UT Bot          (trailing stop Long/Short)
    ③ Parabolic SAR
    ④ RSI MTF         (direction trên 6 TF: 5m 15m 30m 1h 4h 1d)
    ⑤ Zone Classifier (PREM / EQ↑ / EQ / EQ↓ / DISC)
    ⑥ MTF 3 tầng      (Momentum 5m / Bridge 30m / Context 1h+4h+1d)
    ⑦ ULTRA Score     (0–11 điểm, verdict như PineScript)

Hệ thống điểm:
  SXL score  : 0–10  (giữ, dùng cho SL/TP cũ)
  ULTRA score: 0–11  (mới, verdict như bảng PineScript)
    Base 15m (max 6): ST AI + UT Bot + SAR + SMC Swing + SMC Internal + Zone ok
    MTF (max 5)     : Momentum +1 / Bridge +1 / Context +2 / RSI≥4 +1
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════
# DATACLASS
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class SignalResult:
    # ── Core ───────────────────────────────────────────────────────────────
    symbol:     str
    score:      int          # SXL score 0-10
    direction:  str          # "LONG" | "SHORT" | "NEUTRAL"
    price:      float
    sl:         float
    tp1:        float
    tp2:        float
    reasons:    list[str] = field(default_factory=list)
    timeframe:  str = "15m"

    # ── SXL Sniper ─────────────────────────────────────────────────────────
    l_score:    int   = 0
    s_score:    int   = 0
    is_premium: bool  = False

    # ── Volume Balance ─────────────────────────────────────────────────────
    bull_pct:    float = 0.0
    bear_pct:    float = 0.0
    vol_confirm: bool  = False

    # ── Spike Detector ─────────────────────────────────────────────────────
    is_spike:        bool  = False
    spike_direction: str   = ""
    spike_pct:       float = 0.0

    # ── Leverage Advisor ───────────────────────────────────────────────────
    leverage:  int   = 1
    lev_risk:  str   = "🔴 Rất cao"
    atr_pct:   float = 0.0

    # ── MSB ────────────────────────────────────────────────────────────────
    market_bias: str  = "BULL"
    in_ob_zone:  bool = False

    # ── NEW: 15M ULTRA individual indicators (trên df_15m) ─────────────────
    st_ai_bull:     bool  = False   # SuperTrend AI
    st_ai_factor:   float = 3.0     # best factor được chọn
    ut_pos_val:     int   = 0       # 1=LONG / -1=SHORT / 0=FLAT
    sar_bull_val:   bool  = False   # Parabolic SAR
    smc_swing_bull: int   = 0       # 1=BULL / -1=BEAR (MSB swing)
    smc_int_bull:   int   = 0       # 1=BULL / -1=BEAR (internal – dùng df_5m)

    # ── Zone ───────────────────────────────────────────────────────────────
    zone:     str = "EQ"   # PREM | EQ↑ | EQ | EQ↓ | DISC
    zone_pct: int = 50     # % vị trí trong range 0-100

    # ── RSI MTF ────────────────────────────────────────────────────────────
    rsi_bull_count: int = 0   # số TF RSI tăng (0-6)
    rsi_bear_count: int = 0

    # ── MTF Confluence ─────────────────────────────────────────────────────
    mtf_momentum_bull: bool = False   # 5m bull≥3/4
    mtf_momentum_bear: bool = False
    mtf_bridge_bull:   bool = False   # 30m bull≥3/4
    mtf_bridge_bear:   bool = False
    mtf_context_bull:  bool = False   # 1h+4h+1d đồng thời ≥3/4 bull
    mtf_context_bear:  bool = False

    # ── ULTRA Score (15m) ──────────────────────────────────────────────────
    ultra_buy_score:  int = 0    # 0-11
    ultra_sell_score: int = 0
    ultra_verdict:    str = "⏳ NEUTRAL"
    ultra_verdict_color: str = "gray"   # "green" | "red" | "gray"

    # ── ULTRA Score 1h ─────────────────────────────────────────────────────
    ultra_1h_buy:     int = 0
    ultra_1h_sell:    int = 0
    ultra_1h_verdict: str = "⏳ NEUTRAL"
    ultra_1h_color:   str = "gray"

    # ── ULTRA Score 4h ─────────────────────────────────────────────────────
    ultra_4h_buy:     int = 0
    ultra_4h_sell:    int = 0
    ultra_4h_verdict: str = "⏳ NEUTRAL"
    ultra_4h_color:   str = "gray"


# ══════════════════════════════════════════════════════════════════════════
# HELPERS — giữ nguyên + bổ sung
# ══════════════════════════════════════════════════════════════════════════

def _ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def _sma(s: pd.Series, p: int) -> pd.Series:
    return s.rolling(p, min_periods=1).mean()

def _stdev(s: pd.Series, p: int) -> pd.Series:
    return s.rolling(p, min_periods=1).std(ddof=0)

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


# ══════════════════════════════════════════════════════════════════════════
# ① SUPERTREND AI  (port từ Section E-G PineScript)
#   Thử các factor từ min→max, chọn factor có performance cao nhất
#   Không cần K-means clustering: dùng argmax perf → tương đương "Best cluster"
# ══════════════════════════════════════════════════════════════════════════

def supertrend_ai(
    df:         pd.DataFrame,
    length:     int   = 10,
    min_mult:   float = 1.0,
    max_mult:   float = 5.0,
    step:       float = 0.5,
    perf_alpha: int   = 10,
) -> tuple[bool, float]:
    """
    Returns (is_bull, best_factor).
    Thử 9 factor mặc định (1.0→5.0 bước 0.5), track performance mỗi factor.
    Factor nào có EMA(performance) cao nhất → chọn.
    """
    n_min = length + 5
    if len(df) < n_min:
        return False, 3.0

    # Giới hạn bars để tăng tốc (100 bars là đủ)
    df = df.tail(100)
    atr  = _atr(df, length).values
    hl2  = ((df["high"] + df["low"]) / 2).values
    c    = df["close"].values
    n    = len(c)
    alpha = 2.0 / (perf_alpha + 1)

    factors = np.arange(min_mult, max_mult + step / 2, step)
    best_perf   = -np.inf
    best_trend  = 0
    best_factor = float(min_mult)

    for factor in factors:
        upper = hl2 + atr * factor
        lower = hl2 - atr * factor

        st_upper = np.empty(n)
        st_lower = np.empty(n)
        trend    = np.zeros(n, dtype=np.int8)

        st_upper[0] = upper[0]
        st_lower[0] = lower[0]

        for i in range(1, n):
            # Upper band: nếu close[i-1] < prev_upper → giữ min, ngược lại reset
            st_upper[i] = min(upper[i], st_upper[i-1]) if c[i-1] < st_upper[i-1] else upper[i]
            # Lower band: nếu close[i-1] > prev_lower → giữ max, ngược lại reset
            st_lower[i] = max(lower[i], st_lower[i-1]) if c[i-1] > st_lower[i-1] else lower[i]

            if   c[i] > st_upper[i]: trend[i] = 1
            elif c[i] < st_lower[i]: trend[i] = 0
            else:                    trend[i] = trend[i - 1]

        # Output = lower nếu bull, upper nếu bear
        output = np.where(trend == 1, st_lower, st_upper)

        # Performance EMA: ret[i] = (close[i] - close[i-1]) × sign(close[i-1] - output[i-1])
        perf = 0.0
        for i in range(1, n):
            sign_val = 1.0 if c[i-1] > output[i-1] else -1.0
            ret  = (c[i] - c[i-1]) * sign_val
            perf += alpha * (ret - perf)

        if perf > best_perf:
            best_perf   = perf
            best_trend  = int(trend[-1])
            best_factor = float(factor)

    return bool(best_trend), best_factor


# ══════════════════════════════════════════════════════════════════════════
# ② UT BOT  (port từ Section H PineScript)
#   Trailing stop adaptive theo ATR × keyValue
# ══════════════════════════════════════════════════════════════════════════

def ut_bot(
    df:      pd.DataFrame,
    key_val: float = 1.0,
    atr_per: int   = 10,
) -> tuple[int, float]:
    """
    Returns (position, trail_value).
    position: 1=LONG / -1=SHORT / 0=FLAT (carry previous)
    """
    if len(df) < atr_per + 2:
        return 0, float(df["close"].iloc[-1])

    c     = df["close"].values
    atr   = _atr(df, atr_per).values
    n_loss = key_val * atr
    n     = len(c)

    trail = np.zeros(n)
    pos   = np.zeros(n, dtype=np.int8)

    # Init
    trail[0] = c[0] - n_loss[0] if c[0] > (c[1] if n > 1 else c[0]) else c[0] + n_loss[0]

    for i in range(1, n):
        prev_t = trail[i - 1]
        cur_c  = c[i]
        prev_c = c[i - 1]

        if cur_c > prev_t and prev_c > prev_t:
            trail[i] = max(prev_t, cur_c - n_loss[i])
        elif cur_c < prev_t and prev_c < prev_t:
            trail[i] = min(prev_t, cur_c + n_loss[i])
        elif cur_c > prev_t:
            trail[i] = cur_c - n_loss[i]
        else:
            trail[i] = cur_c + n_loss[i]

        # Crossover detection
        if prev_c < prev_t and cur_c > trail[i]:
            pos[i] = 1
        elif prev_c > prev_t and cur_c < trail[i]:
            pos[i] = -1
        else:
            pos[i] = pos[i - 1]

    return int(pos[-1]), float(trail[-1])


# ══════════════════════════════════════════════════════════════════════════
# ③ PARABOLIC SAR  (port từ Section H2 PineScript)
# ══════════════════════════════════════════════════════════════════════════

def parabolic_sar(
    df:      pd.DataFrame,
    start:   float = 0.02,
    inc:     float = 0.02,
    max_af:  float = 0.2,
) -> tuple[bool, float]:
    """Returns (is_bull, sar_value)."""
    if len(df) < 3:
        return True, float(df["low"].iloc[-1])

    high = df["high"].values
    low  = df["low"].values
    n    = len(high)

    bull = True
    sar  = low[0]
    ep   = high[0]
    af   = start

    for i in range(1, n):
        if bull:
            sar = sar + af * (ep - sar)
            # SAR không được cao hơn low của 2 nến trước
            sar = min(sar, low[i - 1], low[i - 2] if i > 1 else low[i - 1])
            if low[i] < sar:           # flip to bear
                bull = False
                sar  = ep
                ep   = low[i]
                af   = start
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + inc, max_af)
        else:
            sar = sar + af * (ep - sar)
            sar = max(sar, high[i - 1], high[i - 2] if i > 1 else high[i - 1])
            if high[i] > sar:          # flip to bull
                bull = True
                sar  = ep
                ep   = high[i]
                af   = start
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + inc, max_af)

    return bull, float(sar)


# ══════════════════════════════════════════════════════════════════════════
# ④ RSI DIRECTION  (port từ Section H3 PineScript)
#   Trả 1 (tăng) / -1 (giảm) / 0 (flat)
# ══════════════════════════════════════════════════════════════════════════

def rsi_direction(
    df:        Optional[pd.DataFrame],
    length:    int   = 14,
    lookback:  int   = 3,
    threshold: float = 1.5,
) -> int:
    """So sánh RSI hiện tại với RSI 'lookback' nến trước."""
    if df is None or len(df) < length + lookback + 2:
        return 0
    rsi  = _rsi(df["close"], length)
    cur  = rsi.iloc[-1]
    prev = rsi.iloc[-1 - lookback]
    if np.isnan(cur) or np.isnan(prev):
        return 0
    diff = cur - prev
    if diff >  threshold: return  1
    if diff < -threshold: return -1
    return 0


# ══════════════════════════════════════════════════════════════════════════
# ⑤ ZONE CLASSIFIER  (port từ Section M PineScript)
#   PREM ≥95% | EQ↑ 52.5-95% | EQ 47.5-52.5% | EQ↓ 5-47.5% | DISC ≤5%
# ══════════════════════════════════════════════════════════════════════════

def zone_classify(
    df:       pd.DataFrame,
    lookback: int = 100,
) -> tuple[str, int]:
    """Returns (zone_name, pct_in_range 0-100)."""
    tail   = df.tail(lookback)
    t_high = tail["high"].max()
    t_low  = tail["low"].min()
    cur    = df["close"].iloc[-1]
    rng    = t_high - t_low

    if rng <= 0:
        return "EQ", 50

    pct = int(round((cur - t_low) / rng * 100))
    pct = max(0, min(100, pct))

    premium_line  = t_high - 0.05 * rng   # ≥95%
    discount_line = t_low  + 0.05 * rng   # ≤5%
    eq_high       = t_low  + 0.525 * rng  # 52.5%
    eq_low        = t_low  + 0.475 * rng  # 47.5%

    if cur >= premium_line:  return "PREM", pct
    if cur <= discount_line: return "DISC", pct
    if cur >= eq_high:       return "EQ↑",  pct
    if cur <= eq_low:        return "EQ↓",  pct
    return "EQ", pct


# ══════════════════════════════════════════════════════════════════════════
# ⑥ TF INDICATORS HELPER  (dùng simple ST thay vì ST-AI cho MTF nhanh hơn)
# ══════════════════════════════════════════════════════════════════════════

def _tf_ind(df: Optional[pd.DataFrame]) -> dict:
    """Tính ST bull/bear, UT pos, SAR bull, MSB bias cho 1 TF."""
    if df is None or len(df) < 20:
        return {"st": False, "ut": 0, "sar": False, "smc": 0}
    return {
        "st":  supertrend_bull(df),
        "ut":  ut_bot(df)[0],
        "sar": parabolic_sar(df)[0],
        "smc": 1 if msb_bias(df)["market_bias"] == "BULL" else -1,
    }

def _tf_bull_cnt(ind: dict) -> int:
    """Đếm số điều kiện BULL trong 1 TF (max 4, giống PineScript f_tfBull)."""
    return (
        (1 if ind["st"]      else 0) +
        (1 if ind["ut"] == 1 else 0) +
        (1 if ind["sar"]     else 0) +
        (1 if ind["smc"] == 1 else 0)
    )

def _tf_bear_cnt(ind: dict) -> int:
    """Đếm số điều kiện BEAR trong 1 TF (max 4)."""
    return (
        (1 if not ind["st"]       else 0) +
        (1 if ind["ut"] == -1     else 0) +
        (1 if not ind["sar"]      else 0) +
        (1 if ind["smc"] == -1    else 0)
    )


# ══════════════════════════════════════════════════════════════════════════
# EXISTING: SXL SNIPER (5 confluences) — giữ nguyên
# ══════════════════════════════════════════════════════════════════════════

def sxl_confluences(
    df: pd.DataFrame,
    ema_fast: int   = 20,
    ema_slow: int   = 50,
    ema_trend: int  = 200,
    rsi_len:   int  = 14,
    rsi_ob:    float = 65.0,
    rsi_os:    float = 35.0,
    bb_len:    int  = 20,
    bb_mult:   float = 2.0,
    fvg_min:   float = 0.05,
) -> dict:
    c  = df["close"]
    h  = df["high"]
    lo = df["low"]

    e1  = _ema(c, ema_fast).iloc[-1]
    e2  = _ema(c, ema_slow).iloc[-1]
    e3  = _ema(c, ema_trend).iloc[-1]
    rsi = _rsi(c, rsi_len)

    bb_basis = _sma(c, bb_len)
    bb_dev   = _stdev(c, bb_len) * bb_mult
    bb_upper = bb_basis + bb_dev
    bb_lower = bb_basis - bb_dev
    mom      = c - c.shift(4)

    def _bull_fvg(i):
        if i < 2: return False
        gap = lo.iloc[i] - h.iloc[i-2]
        return gap > 0 and gap / c.iloc[i] * 100 >= fvg_min

    def _bear_fvg(i):
        if i < 2: return False
        gap = lo.iloc[i-2] - h.iloc[i]
        return gap > 0 and gap / c.iloc[i] * 100 >= fvg_min

    n = len(df) - 1
    has_bull_fvg = any(_bull_fvg(n - j) for j in [1, 2, 3] if n - j >= 0)
    has_bear_fvg = any(_bear_fvg(n - j) for j in [1, 2, 3] if n - j >= 0)

    cur_rsi  = rsi.iloc[-1]
    cur_bb_b = bb_basis.iloc[-1]
    cur_bb_d = bb_dev.iloc[-1]
    cur_c    = c.iloc[-1]
    cur_mom  = mom.iloc[-1]
    prev_mom = mom.iloc[-2] if len(mom) > 2 else 0

    lc1 = e1 > e2 and e2 > e3
    lc2 = cur_c < cur_bb_b - cur_bb_d * 0.3
    lc3 = cur_rsi > 40 and cur_rsi < rsi_ob
    lc4 = has_bull_fvg
    lc5 = cur_mom > 0 and cur_mom > prev_mom

    sc1 = e1 < e2 and e2 < e3
    sc2 = cur_c > cur_bb_b + cur_bb_d * 0.3
    sc3 = cur_rsi < 60 and cur_rsi > rsi_os
    sc4 = has_bear_fvg
    sc5 = cur_mom < 0 and cur_mom < prev_mom

    l_score = sum([lc1, lc2, lc3, lc4, lc5])
    s_score = sum([sc1, sc2, sc3, sc4, sc5])

    return {
        "lc1": lc1, "lc2": lc2, "lc3": lc3, "lc4": lc4, "lc5": lc5,
        "sc1": sc1, "sc2": sc2, "sc3": sc3, "sc4": sc4, "sc5": sc5,
        "l_score": l_score, "s_score": s_score,
        "rsi": cur_rsi,
        "bb_upper": bb_upper.iloc[-1],
        "bb_lower": bb_lower.iloc[-1],
        "bb_basis": cur_bb_b,
    }


# ══════════════════════════════════════════════════════════════════════════
# EXISTING: VOLUME BALANCE, SPIKE, LEVERAGE, MSB, REVERSAL — giữ nguyên
# ══════════════════════════════════════════════════════════════════════════

def volume_balance(df: pd.DataFrame, lookback: int = 100) -> dict:
    df_tail = df.tail(lookback)
    is_bull  = df_tail["close"] >= df_tail["open"]
    bull_vol = df_tail.loc[is_bull,  "volume"].sum()
    bear_vol = df_tail.loc[~is_bull, "volume"].sum()
    total    = bull_vol + bear_vol
    if total == 0:
        return {"bull_pct": 50.0, "bear_pct": 50.0}
    return {
        "bull_pct": round(bull_vol / total * 100, 1),
        "bear_pct": round(bear_vol / total * 100, 1),
    }


def spike_detector(
    df: pd.DataFrame,
    atr_series: pd.Series,
    pct_thresh: float = 3.0,
    atr_mult:   float = 2.5,
) -> dict:
    close = df["close"]
    opn   = df["open"]
    body       = (close - opn).abs().iloc[-1]
    prev_close = close.iloc[-2] if len(close) > 1 else close.iloc[-1]
    cur_close  = close.iloc[-1]
    atr_val    = atr_series.iloc[-1]
    price_chg_pct = abs(cur_close - prev_close) / prev_close * 100.0 if prev_close != 0 else 0.0
    is_spike  = price_chg_pct >= pct_thresh or (atr_val > 0 and body >= atr_val * atr_mult)
    spike_dir = ""
    if is_spike:
        spike_dir = "BULL" if cur_close > prev_close else "BEAR"
    return {"is_spike": is_spike, "spike_direction": spike_dir, "spike_pct": round(price_chg_pct, 1)}


def leverage_advisor(atr_val: float, price: float, sl_mult: float = 1.5) -> dict:
    atr_pct = (atr_val / price * 100.0) if price > 0 else 0.0
    lev_raw = round(2.0 / (sl_mult * atr_pct)) if atr_pct > 0 else 1
    steps   = [20, 15, 10, 7, 5, 3, 2, 1]
    lev     = next((s for s in steps if lev_raw >= s), 1)
    risk    = (
        "🟢 Thấp"       if lev >= 15 else
        "🟡 Trung bình" if lev >= 7  else
        "🟠 Cao"        if lev >= 3  else
        "🔴 Rất cao"
    )
    return {"leverage": lev, "lev_risk": risk, "atr_pct": round(atr_pct, 3)}


def msb_bias(df: pd.DataFrame, zz_len: int = 9) -> dict:
    if len(df) < zz_len * 3:
        return {"market_bias": "BULL", "in_ob_zone": False}
    h  = df["high"]
    lo = df["low"]
    recent      = df.tail(zz_len * 4)
    high_peaks  = recent["high"].nlargest(2).sort_index()
    low_troughs = recent["low"].nsmallest(2).sort_index()
    bias = "BULL"
    try:
        h_vals = high_peaks.values
        l_vals = low_troughs.values
        if   h_vals[-1] > h_vals[0] and l_vals[-1] > l_vals[0]: bias = "BULL"
        elif h_vals[-1] < h_vals[0] and l_vals[-1] < l_vals[0]: bias = "BEAR"
        else:
            ema50 = _ema(df["close"], 50).iloc[-1]
            bias  = "BULL" if df["close"].iloc[-1] > ema50 else "BEAR"
    except Exception:
        pass
    atr_v      = _atr(df).iloc[-1]
    cur        = df["close"].iloc[-1]
    swing_low  = lo.tail(zz_len * 2).min()
    swing_high = h.tail(zz_len * 2).max()
    in_ob = (
        (bias == "BULL" and cur <= swing_low  + atr_v * 2) or
        (bias == "BEAR" and cur >= swing_high - atr_v * 2)
    )
    return {"market_bias": bias, "in_ob_zone": in_ob}


def reversal_candles(df: pd.DataFrame, pin_ratio: float = 2.0, doji_pct: float = 0.05) -> dict:
    if len(df) < 3:
        return {"rc_bull": False, "rc_bear": False, "rc_tags": []}
    c  = df["close"]; o  = df["open"]
    h  = df["high"];  lo = df["low"]
    bull_c = c.iloc[-1] > o.iloc[-1]
    bear_c = c.iloc[-1] < o.iloc[-1]
    body       = abs(c.iloc[-1] - o.iloc[-1])
    rng        = h.iloc[-1] - lo.iloc[-1]
    upper_wick = h.iloc[-1] - max(c.iloc[-1], o.iloc[-1])
    lower_wick = min(c.iloc[-1], o.iloc[-1]) - lo.iloc[-1]
    tags = []
    if bear_c and c.iloc[-2] > o.iloc[-2]:
        if c.iloc[-1] < o.iloc[-2] and o.iloc[-1] > c.iloc[-2]: tags.append("⚡ Engulf↓")
    if bull_c and c.iloc[-2] < o.iloc[-2]:
        if c.iloc[-1] > o.iloc[-2] and o.iloc[-1] < c.iloc[-2]: tags.append("⚡ Engulf↑")
    if body > 0:
        if lower_wick >= body * pin_ratio and upper_wick <= body * 0.5: tags.append("🔨 Hammer")
        if upper_wick >= body * pin_ratio and lower_wick <= body * 0.5: tags.append("🌠 ShootStar")
    if rng > 0 and body / rng <= doji_pct: tags.append("✚ Doji")
    if len(df) >= 3:
        body2 = abs(c.iloc[-3] - o.iloc[-3])
        body1 = abs(c.iloc[-2] - o.iloc[-2])
        mid   = (o.iloc[-3] + c.iloc[-3]) / 2
        if c.iloc[-3] < o.iloc[-3] and body2 > body1 * 2 and bull_c and c.iloc[-1] > mid:
            tags.append("🌅 MorningStar")
        if c.iloc[-3] > o.iloc[-3] and body2 > body1 * 2 and bear_c and c.iloc[-1] < mid:
            tags.append("🌆 EveningStar")
    rc_bull = any("↑" in t or "Hammer" in t or "Morning" in t for t in tags)
    rc_bear = any("↓" in t or "Shoot"  in t or "Evening" in t for t in tags)
    return {"rc_bull": rc_bull, "rc_bear": rc_bear, "rc_tags": tags}


def supertrend_bull(df: pd.DataFrame, p: int = 10, mult: float = 3.0) -> bool:
    """Simple supertrend (không AI), dùng cho MTF TFs để tiết kiệm thời gian."""
    if len(df) < p + 2:
        return False
    atr  = _atr(df, p)
    hl2  = (df["high"] + df["low"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    bull  = True
    st    = upper.iloc[0]
    for i in range(1, len(df)):
        c = df["close"].iloc[i]
        if bull:
            st = max(lower.iloc[i], st)
            if c < st: bull = False; st = upper.iloc[i]
        else:
            st = min(upper.iloc[i], st)
            if c > st: bull = True;  st = lower.iloc[i]
    return bull


# ══════════════════════════════════════════════════════════════════════════
# ULTRA VERDICT helper
# ══════════════════════════════════════════════════════════════════════════

def _ultra_verdict(buy: int, sell: int) -> tuple[str, str]:
    """Trả (verdict_text, color_hint) theo ngưỡng PineScript."""
    if   buy  >= 9: return "🚀 STRONG BUY",  "green"
    elif buy  >= 7: return "✅ BUY",          "green"
    elif sell >= 9: return "🔻 STRONG SELL",  "red"
    elif sell >= 7: return "✅ SELL",          "red"
    elif buy  >= 5: return "↑ LEAN BUY",      "green"
    elif sell >= 5: return "↓ LEAN SELL",     "red"
    else:           return "⏳ NEUTRAL",       "gray"


# ══════════════════════════════════════════════════════════════════════════
# ULTRA SCORE FOR ANY TF  (tách từ score_symbol để tái dùng cho 1h / 4h)
# ══════════════════════════════════════════════════════════════════════════

def _ultra_score_for_tf(
    df_cur:  Optional[pd.DataFrame],   # TF đang tính (15m / 1h / 4h …)
    df_5m:   Optional[pd.DataFrame],
    df_15m:  Optional[pd.DataFrame],
    df_30m:  Optional[pd.DataFrame],
    df_1h:   Optional[pd.DataFrame],
    df_4h:   Optional[pd.DataFrame],
    df_1d:   Optional[pd.DataFrame],
    rsi_len:       int   = 14,
    rsi_lookback:  int   = 3,
    rsi_threshold: float = 1.5,
) -> dict:
    """
    Tính ULTRA score (0-11) cho TF bất kỳ — logic giống 15M ULTRA engine.

    Trả dict:
      buy, sell           : int  0-11
      verdict, color      : str
      st_ai_bull          : bool
      st_ai_factor        : float
      ut_pos_val          : int   1 / -1 / 0
      sar_bull_val        : bool
      smc_swing_v         : int   1 / -1
      smc_int_v           : int   1 / -1  (luôn dùng df_5m)
      zone, zone_pct      : str, int
      rsi_bull, rsi_bear  : int  (count trên 6 TF)
      mtf_ctx_bull/bear   : bool
    """
    _empty = {
        "buy": 0, "sell": 0, "verdict": "⏳ NEUTRAL", "color": "gray",
        "st_ai_bull": False, "st_ai_factor": 3.0,
        "ut_pos_val": 0, "sar_bull_val": False,
        "smc_swing_v": 0, "smc_int_v": 0,
        "zone": "EQ", "zone_pct": 50,
        "rsi_bull": 0, "rsi_bear": 0,
        "mtf_ctx_bull": False, "mtf_ctx_bear": False,
    }
    if df_cur is None or len(df_cur) < 20:
        return _empty
    if df_5m is None or len(df_5m) < 20:
        return _empty

    # ── Base indicators (trên df_cur) ──────────────────────────────────────
    st_ai_is_bull, st_ai_factor = supertrend_ai(df_cur)
    ut_pos_val, _               = ut_bot(df_cur)
    sar_bull_val, _             = parabolic_sar(df_cur)

    msb_cur     = msb_bias(df_cur)
    smc_swing_v = 1 if msb_cur["market_bias"] == "BULL" else -1

    msb_5m      = msb_bias(df_5m)
    smc_int_v   = 1 if msb_5m["market_bias"] == "BULL" else -1

    zone_name, zone_pct = zone_classify(df_cur)
    not_premium  = zone_name != "PREM"
    not_discount = zone_name != "DISC"

    # ── RSI MTF (6 TF: 5m 15m 30m 1h 4h 1d) ────────────────────────────
    rsi_dirs = [
        rsi_direction(df_5m,  rsi_len, rsi_lookback, rsi_threshold),
        rsi_direction(df_15m, rsi_len, rsi_lookback, rsi_threshold),
        rsi_direction(df_30m, rsi_len, rsi_lookback, rsi_threshold),
        rsi_direction(df_1h,  rsi_len, rsi_lookback, rsi_threshold),
        rsi_direction(df_4h,  rsi_len, rsi_lookback, rsi_threshold),
        rsi_direction(df_1d,  rsi_len, rsi_lookback, rsi_threshold),
    ]
    rsi_bull_count = sum(1 for d in rsi_dirs if d ==  1)
    rsi_bear_count = sum(1 for d in rsi_dirs if d == -1)

    # ── MTF 3 tầng (giống 15m: Momentum 5m / Bridge 30m / Context 1h+4h+1d)
    ind_5m  = _tf_ind(df_5m)
    ind_30m = _tf_ind(df_30m)
    ind_1h  = _tf_ind(df_1h)
    ind_4h  = _tf_ind(df_4h)
    ind_1d  = _tf_ind(df_1d)

    mtf_momentum_bull = _tf_bull_cnt(ind_5m)  >= 3
    mtf_momentum_bear = _tf_bear_cnt(ind_5m)  >= 3
    mtf_bridge_bull   = _tf_bull_cnt(ind_30m) >= 3
    mtf_bridge_bear   = _tf_bear_cnt(ind_30m) >= 3
    mtf_context_bull  = (_tf_bull_cnt(ind_1h) >= 3 and
                         _tf_bull_cnt(ind_4h) >= 3 and
                         _tf_bull_cnt(ind_1d) >= 3)
    mtf_context_bear  = (_tf_bear_cnt(ind_1h) >= 3 and
                         _tf_bear_cnt(ind_4h) >= 3 and
                         _tf_bear_cnt(ind_1d) >= 3)

    # ── ULTRA Score (0-11) ───────────────────────────────────────────────
    buy_base  = sum([st_ai_is_bull, ut_pos_val == 1,  sar_bull_val,
                     smc_swing_v == 1,  smc_int_v == 1,  not_premium])
    sell_base = sum([not st_ai_is_bull, ut_pos_val == -1, not sar_bull_val,
                     smc_swing_v == -1, smc_int_v == -1, not_discount])

    ultra_buy  = min(11, max(0,
        buy_base
        + (2 if mtf_context_bull  else 0)
        + (1 if mtf_bridge_bull   else 0)
        + (1 if mtf_momentum_bull else 0)
        + (1 if rsi_bull_count >= 4 else 0)
    ))
    ultra_sell = min(11, max(0,
        sell_base
        + (2 if mtf_context_bear  else 0)
        + (1 if mtf_bridge_bear   else 0)
        + (1 if mtf_momentum_bear else 0)
        + (1 if rsi_bear_count >= 4 else 0)
    ))

    verdict, color = _ultra_verdict(ultra_buy, ultra_sell)

    return {
        "buy":            ultra_buy,
        "sell":           ultra_sell,
        "verdict":        verdict,
        "color":          color,
        "st_ai_bull":     st_ai_is_bull,
        "st_ai_factor":   st_ai_factor,
        "ut_pos_val":     ut_pos_val,
        "sar_bull_val":   sar_bull_val,
        "smc_swing_v":    smc_swing_v,
        "smc_int_v":      smc_int_v,
        "zone":           zone_name,
        "zone_pct":       zone_pct,
        "rsi_bull":       rsi_bull_count,
        "rsi_bear":       rsi_bear_count,
        "mtf_ctx_bull":   mtf_context_bull,
        "mtf_ctx_bear":   mtf_context_bear,
    }


# ══════════════════════════════════════════════════════════════════════════
# MAIN SCORER  (v3.0 — kết hợp SXL + 15M ULTRA)
# ══════════════════════════════════════════════════════════════════════════

def score_symbol(
    symbol:  str,
    df_5m:   pd.DataFrame,
    df_15m:  pd.DataFrame,
    df_1h:   pd.DataFrame,
    # Timeframes mới (có thể None nếu fetch lỗi)
    df_30m:  Optional[pd.DataFrame] = None,
    df_4h:   Optional[pd.DataFrame] = None,
    df_1d:   Optional[pd.DataFrame] = None,
    # SXL params
    min_confluences: int   = 3,
    vol_lookback:    int   = 100,
    vol_thresh:      float = 60.0,
    spike_pct_thr:   float = 3.0,
    spike_atr_thr:   float = 2.5,
    sl_mult:         float = 1.5,
    tp1_mult:        float = 2.0,
    tp2_mult:        float = 3.5,
    # ULTRA RSI params
    rsi_len:         int   = 14,
    rsi_lookback:    int   = 3,
    rsi_threshold:   float = 1.5,
) -> SignalResult:

    reasons: list[str] = []
    score = 0

    # ── Dùng df_15m làm "current TF" cho ULTRA (giống bảng PineScript ở 15M)
    df_cur = df_15m if df_15m is not None and len(df_15m) >= 20 else df_5m

    close_val = df_cur["close"].iloc[-1]
    atr_s     = _atr(df_5m, 14)
    atr_val   = atr_s.iloc[-1]
    atr_cur   = _atr(df_cur, 14).iloc[-1]

    # ══════════════════════════════════════════════════════════════════════
    # PHẦN A: SXL ENGINE (giữ từ v2, chạy trên df_5m)
    # ══════════════════════════════════════════════════════════════════════
    sxl    = sxl_confluences(df_5m)
    l_sc   = sxl["l_score"]
    s_sc   = sxl["s_score"]
    l_sig  = l_sc >= min_confluences
    s_sig  = s_sc >= min_confluences

    sxl_tags_long  = []
    sxl_tags_short = []
    if sxl["lc1"]: sxl_tags_long.append("EMA↑Stack")
    if sxl["lc2"]: sxl_tags_long.append("BB↓Pullback")
    if sxl["lc3"]: sxl_tags_long.append("RSI↑Zone")
    if sxl["lc4"]: sxl_tags_long.append("FVG↑Bull")
    if sxl["lc5"]: sxl_tags_long.append("Mom↑")
    if sxl["sc1"]: sxl_tags_short.append("EMA↓Stack")
    if sxl["sc2"]: sxl_tags_short.append("BB↑Reject")
    if sxl["sc3"]: sxl_tags_short.append("RSI↓Zone")
    if sxl["sc4"]: sxl_tags_short.append("FVG↓Bear")
    if sxl["sc5"]: sxl_tags_short.append("Mom↓")

    msb        = msb_bias(df_5m)
    market_bias = msb["market_bias"]
    in_ob       = msb["in_ob_zone"]

    vb         = volume_balance(df_5m, vol_lookback)
    bull_pct   = vb["bull_pct"]
    bear_pct   = vb["bear_pct"]
    vol_long   = bull_pct > bear_pct
    vol_short  = bear_pct > bull_pct
    vol_dom    = bull_pct >= vol_thresh or bear_pct >= vol_thresh

    spk        = spike_detector(df_5m, atr_s, spike_pct_thr, spike_atr_thr)
    lev        = leverage_advisor(atr_val, df_5m["close"].iloc[-1], sl_mult)
    rc         = reversal_candles(df_5m)
    st_5m      = supertrend_bull(df_5m)
    st_15m     = len(df_15m) > 20 and supertrend_bull(df_15m) if df_15m is not None else False
    st_1h      = len(df_1h)  > 20 and supertrend_bull(df_1h)  if df_1h  is not None else False

    # SXL Scoring
    if l_sig:
        pts = min(3, l_sc - min_confluences + 1)
        score += pts; reasons += sxl_tags_long[:pts]
    elif s_sig:
        pts = min(3, s_sc - min_confluences + 1)
        score += pts; reasons += sxl_tags_short[:pts]

    if (l_sig and market_bias == "BULL") or (s_sig and market_bias == "BEAR"):
        score += 1; reasons.append(f"MSB↑{market_bias}")

    if in_ob and (l_sig or s_sig):
        score += 1; reasons.append("OB/BB★Zone")

    if (l_sig and vol_long) or (s_sig and vol_short):
        score += 1
        reasons.append(f"Vol▲{bull_pct}%" if l_sig else f"Vol▼{bear_pct}%")
        if vol_dom: score += 1; reasons.append("VolDominant")

    if l_sig:
        st_pts = sum([st_5m, st_15m, st_1h])
        pts    = min(2, st_pts - 1) if st_pts >= 2 else 0
        if pts > 0:
            score += pts
            tfs = [t for t, b in [("5m", st_5m), ("15m", st_15m), ("1h", st_1h)] if b]
            reasons.append(f"ST↑{'&'.join(tfs)}")
    elif s_sig:
        st_pts = sum([not st_5m, not st_15m, not st_1h])
        pts    = min(2, st_pts - 1) if st_pts >= 2 else 0
        if pts > 0: score += pts; reasons.append("ST↓MTF")

    if in_ob and rc["rc_tags"]:
        if (l_sig and rc["rc_bull"]) or (s_sig and rc["rc_bear"]):
            score += 1; reasons.append(rc["rc_tags"][0])

    if spk["is_spike"]:
        if (l_sig and spk["spike_direction"] == "BEAR") or \
           (s_sig and spk["spike_direction"] == "BULL"):
            score = max(0, score - 1)
            reasons.append(f"⚡SpikeCaution{spk['spike_pct']}%")
        else:
            reasons.append(f"⚡Spike{spk['spike_direction']}{spk['spike_pct']}%")

    # ══════════════════════════════════════════════════════════════════════
    # PHẦN B: ULTRA ENGINE  (15m + 1h + 4h)
    # ══════════════════════════════════════════════════════════════════════

    _tf_args = (df_5m, df_15m, df_30m, df_1h, df_4h, df_1d,
                rsi_len, rsi_lookback, rsi_threshold)

    # B-15m: ULTRA score trên khung 15m (giống v3.0 cũ)
    u15 = _ultra_score_for_tf(df_cur, *_tf_args)

    # B-1h: ULTRA score trên khung 1h
    u1h = _ultra_score_for_tf(df_1h, *_tf_args)

    # B-4h: ULTRA score trên khung 4h
    u4h = _ultra_score_for_tf(df_4h, *_tf_args)

    # Alias 15m fields (giữ tên cũ để không đổi code phía dưới)
    st_ai_is_bull   = u15["st_ai_bull"]
    st_ai_factor    = u15["st_ai_factor"]
    ut_pos_val      = u15["ut_pos_val"]
    sar_bull_val    = u15["sar_bull_val"]
    smc_swing_v     = u15["smc_swing_v"]
    smc_int_v       = u15["smc_int_v"]
    zone_name       = u15["zone"]
    zone_pct        = u15["zone_pct"]
    rsi_bull_count  = u15["rsi_bull"]
    rsi_bear_count  = u15["rsi_bear"]
    mtf_momentum_bull = _tf_bull_cnt(_tf_ind(df_5m))  >= 3
    mtf_momentum_bear = _tf_bear_cnt(_tf_ind(df_5m))  >= 3
    mtf_bridge_bull   = _tf_bull_cnt(_tf_ind(df_30m)) >= 3
    mtf_bridge_bear   = _tf_bear_cnt(_tf_ind(df_30m)) >= 3
    mtf_context_bull  = u15["mtf_ctx_bull"]
    mtf_context_bear  = u15["mtf_ctx_bear"]

    ultra_buy    = u15["buy"]
    ultra_sell   = u15["sell"]
    verdict      = u15["verdict"]
    verdict_color = u15["color"]

    # Tổng hợp điểm cao nhất qua cả 3 TF (dùng cho direction + tags)
    best_buy  = max(ultra_buy,  u1h["buy"],  u4h["buy"])
    best_sell = max(ultra_sell, u1h["sell"], u4h["sell"])

    # Indicators 15m cũ (dùng cho check bên dưới)
    ck_st_buy  = st_ai_is_bull
    ck_ut_buy  = ut_pos_val == 1
    ck_sar_buy = sar_bull_val
    ck_st_sell  = not st_ai_is_bull
    ck_ut_sell  = ut_pos_val == -1
    ck_sar_sell = not sar_bull_val

    # ══════════════════════════════════════════════════════════════════════
    # PHẦN C: DIRECTION & SL/TP (ưu tiên điểm cao nhất trong 15m/1h/4h)
    # ══════════════════════════════════════════════════════════════════════
    if best_buy >= 5 and best_buy >= best_sell:
        direction = "LONG"
    elif best_sell >= 5 and best_sell > best_buy:
        direction = "SHORT"
    elif l_sig and l_sc >= s_sc:
        direction = "LONG"
    elif s_sig and s_sc > l_sc:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    # SL/TP dựa trên ATR của current TF (15m)
    sl_a  = atr_cur * sl_mult
    tp1_a = atr_cur * tp1_mult
    tp2_a = atr_cur * tp2_mult

    if direction == "LONG":
        sl  = close_val - sl_a
        tp1 = close_val + tp1_a
        tp2 = close_val + tp2_a
    elif direction == "SHORT":
        sl  = close_val + sl_a
        tp1 = close_val - tp1_a
        tp2 = close_val - tp2_a
    else:
        sl  = close_val - sl_a
        tp1 = close_val + tp1_a
        tp2 = close_val + tp2_a

    is_premium_flag = (
        (direction == "LONG"  and market_bias == "BULL" and in_ob) or
        (direction == "SHORT" and market_bias == "BEAR" and in_ob)
    )
    vol_confirm = (direction == "LONG" and vol_long) or (direction == "SHORT" and vol_short)

    # Thêm ULTRA tags vào reasons (15m)
    ultra_tags = []
    if ck_st_buy or ck_st_sell:
        ultra_tags.append(f"ST-AI({'▲' if st_ai_is_bull else '▼'} F{st_ai_factor:.1f})")
    if ck_ut_buy or ck_ut_sell:
        ultra_tags.append(f"UT({'LONG' if ut_pos_val==1 else 'SHORT'})")
    if ck_sar_buy or ck_sar_sell:
        ultra_tags.append(f"SAR({'▲' if sar_bull_val else '▼'})")
    if mtf_context_bull or mtf_context_bear:
        ultra_tags.append("CTX✓")
    # Thêm tag nếu 1h hoặc 4h có STRONG BUY/SELL
    if u1h["buy"] >= 9:
        ultra_tags.append("1H🚀SB")
    elif u1h["sell"] >= 9:
        ultra_tags.append("1H🔻SS")
    if u4h["buy"] >= 9:
        ultra_tags.append("4H🚀SB")
    elif u4h["sell"] >= 9:
        ultra_tags.append("4H🔻SS")
    if ultra_tags:
        reasons += ultra_tags[:4]

    return SignalResult(
        symbol      = symbol,
        score       = min(10, max(0, score)),
        direction   = direction,
        price       = round(close_val, 6),
        sl          = round(sl,  6),
        tp1         = round(tp1, 6),
        tp2         = round(tp2, 6),
        reasons     = reasons,
        timeframe   = "15m",
        l_score     = l_sc,
        s_score     = s_sc,
        is_premium  = is_premium_flag,
        bull_pct    = bull_pct,
        bear_pct    = bear_pct,
        vol_confirm = vol_confirm,
        is_spike        = spk["is_spike"],
        spike_direction = spk["spike_direction"],
        spike_pct       = spk["spike_pct"],
        leverage        = lev["leverage"],
        lev_risk        = lev["lev_risk"],
        atr_pct         = lev["atr_pct"],
        market_bias     = market_bias,
        in_ob_zone      = in_ob,
        # ULTRA fields
        st_ai_bull      = st_ai_is_bull,
        st_ai_factor    = st_ai_factor,
        ut_pos_val      = ut_pos_val,
        sar_bull_val    = sar_bull_val,
        smc_swing_bull  = smc_swing_v,
        smc_int_bull    = smc_int_v,
        zone            = zone_name,
        zone_pct        = zone_pct,
        rsi_bull_count  = rsi_bull_count,
        rsi_bear_count  = rsi_bear_count,
        mtf_momentum_bull = mtf_momentum_bull,
        mtf_momentum_bear = mtf_momentum_bear,
        mtf_bridge_bull   = mtf_bridge_bull,
        mtf_bridge_bear   = mtf_bridge_bear,
        mtf_context_bull  = mtf_context_bull,
        mtf_context_bear  = mtf_context_bear,
        ultra_buy_score   = ultra_buy,
        ultra_sell_score  = ultra_sell,
        ultra_verdict     = verdict,
        ultra_verdict_color = verdict_color,
        # ULTRA 1h
        ultra_1h_buy      = u1h["buy"],
        ultra_1h_sell     = u1h["sell"],
        ultra_1h_verdict  = u1h["verdict"],
        ultra_1h_color    = u1h["color"],
        # ULTRA 4h
        ultra_4h_buy      = u4h["buy"],
        ultra_4h_sell     = u4h["sell"],
        ultra_4h_verdict  = u4h["verdict"],
        ultra_4h_color    = u4h["color"],
    )
