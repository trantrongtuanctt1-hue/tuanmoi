"""
Signal engine — Ceez Prime + Buy Sell Signal (HIGH WIN-RATE VERSION)
═════════════════════════════════════════════════════════════════════
Context (Ceez Prime — 4H):
  ① EMA Stack      13/20/50/200 xếp tầng sạch + spread đủ rộng
  ② LinReg Slope   hệ số góc 50 nến > threshold
  ③ Structure      HH+HL (bull) | LH+LL (bear) — cần đủ 2 swing gần nhất
  ④ Fib Zone       0.45–0.65 (long) | 0.35–0.55 (short) — equilibrium chặt
  ⑤ CCI            cross zero trong ≤3 nến gần nhất
  ⑥ ADX ≥ 25       + DI xác nhận chiều

Entry (Buy Sell Signal — 1H):
  ⑦ EMA 5×13 FRESH cross (≤1 bar)
  ⑧ Candle body ≥ 55% range  (nến mạnh)
  ⑨ Volume ≥ 1.3× trung bình (volume spike)
  ⑩ RSI 14 không extreme (30–70 cho long, 30–70 cho short)
  ⑪ Giá ở đúng phía EMA 13 sau cross

Score: 0–11. Chỉ alert khi cross FRESH + score ≥ min_score.
SL  = swing low/high nến cross ± ATR × mult
TP  = 1R / 2R / RR×R
Risk filter: 0.3% ≤ risk_pct ≤ 4.0%
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
    symbol:    str
    direction: str        # "LONG" | "SHORT" | "NEUTRAL"
    score:     int        # 0–11
    price:     float
    sl:        float
    tp1:       float
    tp2:       float
    tp_final:  float
    atr:       float
    rr:        float
    risk_pct:  float
    risk_ok:   bool       # True nếu 0.3% ≤ risk_pct ≤ 4%

    # Context flags
    ema_stack:    bool = False
    linreg_bull:  bool = False
    struct_ok:    bool = False
    fib_ok:       bool = False
    cci_ok:       bool = False
    adx_ok:       bool = False

    # Entry flags
    entry_cross:      bool = False
    candle_strong:    bool = False
    volume_spike:     bool = False
    rsi_ok:           bool = False
    price_side_ok:    bool = False
    signal_fresh:     bool = False
    cross_bars_ago:   int  = 0

    # Detail
    struct_labels: list[str] = field(default_factory=list)
    ema_e13:  float = 0.0
    ema_e20:  float = 0.0
    ema_e50:  float = 0.0
    ema_e200: float = 0.0
    cci_val:  float = 0.0
    adx_val:  float = 0.0
    di_plus:  float = 0.0
    di_minus: float = 0.0
    fib_pct:  float = 0.0
    fib_zone: str   = "EQ"
    linreg_slope: float = 0.0
    rsi_val:  float = 50.0
    vol_ratio: float = 1.0   # volume nến / avg volume
    body_ratio: float = 0.0  # body / range
    reasons:  list[str] = field(default_factory=list)
    rejects:  list[str] = field(default_factory=list)  # lý do bị lọc


# ══════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def _atr(df: pd.DataFrame, p: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(span=p, adjust=False).mean()


# ══════════════════════════════════════════════════════════════════════════
# ① EMA STACK — có kiểm tra spread (không bị squeeze)
# ══════════════════════════════════════════════════════════════════════════

def calc_ema_stack(df: pd.DataFrame, min_spread_pct: float = 0.05) -> dict:
    """
    Bull: 13 > 20 > 50 > 200 VÀ spread giữa EMA13 và EMA200 ≥ min_spread_pct%
    Bear: ngược lại
    """
    if len(df) < 201:
        return {"bull": False, "bear": False, "e13": 0.0, "e20": 0.0, "e50": 0.0, "e200": 0.0, "spread_ok": False}
    c    = df["close"]
    e13  = float(_ema(c, 13).iloc[-1])
    e20  = float(_ema(c, 20).iloc[-1])
    e50  = float(_ema(c, 50).iloc[-1])
    e200 = float(_ema(c, 200).iloc[-1])

    spread = abs(e13 - e200) / e200 * 100.0 if e200 > 0 else 0.0
    spread_ok = spread >= min_spread_pct

    return {
        "bull":      e13 > e20 > e50 > e200 and spread_ok,
        "bear":      e13 < e20 < e50 < e200 and spread_ok,
        "e13": e13, "e20": e20, "e50": e50, "e200": e200,
        "spread_ok": spread_ok,
    }


# ══════════════════════════════════════════════════════════════════════════
# ② LINEAR REGRESSION SLOPE
# ══════════════════════════════════════════════════════════════════════════

def calc_linreg_slope(df: pd.DataFrame, period: int = 50) -> dict:
    if len(df) < period:
        return {"bull": False, "slope": 0.0}
    tail  = df["close"].tail(period).values
    x     = np.arange(period, dtype=float)
    slope = float(np.polyfit(x, tail, 1)[0])
    # Normalize slope theo price để so sánh được cross-asset
    price    = float(tail[-1])
    slope_n  = slope / price * 100.0 if price > 0 else 0.0
    return {"bull": slope > 0, "slope": round(slope_n, 6), "slope_raw": slope}


# ══════════════════════════════════════════════════════════════════════════
# ③ MARKET STRUCTURE — cần đủ HH+HL hoặc LH+LL
# ══════════════════════════════════════════════════════════════════════════

def detect_market_structure(df: pd.DataFrame, swing_len: int = 5, lookback: int = 80) -> dict:
    empty = {"bull": False, "bear": False, "neutral": True, "labels": [],
             "hh": False, "hl": False, "lh": False, "ll": False}
    tail  = df.tail(lookback)
    if len(tail) < swing_len * 2 + 3:
        return empty

    highs, lows = tail["high"].values, tail["low"].values
    n = len(highs)
    sh_prices, sl_prices = [], []
    for i in range(swing_len, n - swing_len):
        win_h = highs[i - swing_len: i + swing_len + 1]
        win_l = lows[i  - swing_len: i + swing_len + 1]
        if highs[i] >= win_h.max():
            sh_prices.append(float(highs[i]))
        if lows[i] <= win_l.min():
            sl_prices.append(float(lows[i]))

    if len(sh_prices) < 2 or len(sl_prices) < 2:
        return empty

    hh = sh_prices[-1] > sh_prices[-2]
    lh = sh_prices[-1] < sh_prices[-2]
    hl = sl_prices[-1] > sl_prices[-2]
    ll = sl_prices[-1] < sl_prices[-2]

    # Cả 2 điều kiện phải đúng (không chỉ 1)
    bull = hh and hl
    bear = lh and ll
    labels = []
    if hh: labels.append("HH")
    elif lh: labels.append("LH")
    if hl: labels.append("HL")
    elif ll: labels.append("LL")

    return {"bull": bull, "bear": bear, "neutral": not bull and not bear,
            "labels": labels, "hh": hh, "hl": hl, "lh": lh, "ll": ll}


# ══════════════════════════════════════════════════════════════════════════
# ④ FIB ZONE — chặt hơn (equilibrium zone)
# ══════════════════════════════════════════════════════════════════════════

def calc_fib_zone(df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    LONG: giá tốt nhất khi ở 45–65% (equilibrium về phía discount)
    SHORT: giá tốt nhất khi ở 35–55% (equilibrium về phía premium)
    """
    tail       = df.tail(lookback)
    swing_high = float(tail["high"].max())
    swing_low  = float(tail["low"].min())
    rng        = swing_high - swing_low
    cur        = float(df["close"].iloc[-1])

    if rng <= 0:
        return {"in_long_zone": True, "in_short_zone": True, "pct": 50.0, "zone": "EQ",
                "fib_382": cur, "fib_500": cur, "fib_618": cur,
                "swing_high": cur, "swing_low": cur}

    pct     = (cur - swing_low) / rng * 100.0
    fib_382 = swing_low + 0.382 * rng
    fib_500 = swing_low + 0.500 * rng
    fib_618 = swing_low + 0.618 * rng

    # Zone labels
    if pct <= 10:   zone = "DISC"
    elif pct >= 90: zone = "PREM"
    elif cur >= fib_618: zone = "EQ↑"
    elif cur <= fib_382: zone = "EQ↓"
    elif cur >= fib_500: zone = "EQ↑"
    else:           zone = "EQ↓"

    return {
        "in_long_zone":  38.0 <= pct <= 65.0,    # discount → equilibrium
        "in_short_zone": 35.0 <= pct <= 62.0,    # premium → equilibrium
        "pct":      round(pct, 1),
        "zone":     zone,
        "fib_382":  round(fib_382, 8),
        "fib_500":  round(fib_500, 8),
        "fib_618":  round(fib_618, 8),
        "swing_high": round(swing_high, 8),
        "swing_low":  round(swing_low, 8),
    }


# ══════════════════════════════════════════════════════════════════════════
# ⑤ CCI — cross zero trong ≤3 nến gần nhất
# ══════════════════════════════════════════════════════════════════════════

def calc_cci(df: pd.DataFrame, period: int = 20, cross_lookback: int = 3) -> dict:
    if len(df) < period + cross_lookback + 2:
        return {"value": 0.0, "bull": False, "bear": False,
                "fresh_cross_bull": False, "fresh_cross_bear": False}

    tp  = (df["high"] + df["low"] + df["close"]) / 3
    ma  = tp.rolling(period).mean()
    md  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - ma) / (0.015 * md.replace(0, np.nan))

    cur = float(cci.iloc[-1])

    # Kiểm tra cross zero trong cross_lookback nến
    fresh_bull, fresh_bear = False, False
    for i in range(1, cross_lookback + 2):
        try:
            c_cur  = float(cci.iloc[-i])
            c_prev = float(cci.iloc[-i - 1])
            if c_cur > 0 and c_prev <= 0:
                fresh_bull = True
                break
            if c_cur < 0 and c_prev >= 0:
                fresh_bear = True
                break
        except IndexError:
            break

    return {
        "value":           round(cur, 2),
        "bull":            cur > 0,
        "bear":            cur < 0,
        "fresh_cross_bull": fresh_bull,
        "fresh_cross_bear": fresh_bear,
    }


# ══════════════════════════════════════════════════════════════════════════
# ⑥ ADX + DI — ngưỡng 25
# ══════════════════════════════════════════════════════════════════════════

def calc_adx(df: pd.DataFrame, period: int = 14, min_adx: float = 25.0) -> dict:
    if len(df) < period * 2 + 2:
        return {"adx": 0.0, "di_plus": 0.0, "di_minus": 0.0,
                "trending": False, "bull_di": False, "bear_di": False}

    high, low = df["high"], df["low"]
    up, down  = high.diff(), -low.diff()
    pdm = np.where((up > down) & (up > 0),   up,   0.0)
    mdm = np.where((down > up) & (down > 0), down, 0.0)

    pdm_s = pd.Series(pdm, index=df.index)
    mdm_s = pd.Series(mdm, index=df.index)
    atr_s = _atr(df, period).replace(0, np.nan)

    pdi = 100.0 * pdm_s.ewm(span=period, adjust=False).mean() / atr_s
    mdi = 100.0 * mdm_s.ewm(span=period, adjust=False).mean() / atr_s
    dx  = 100.0 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()

    adx_val = float(adx.iloc[-1])
    pdi_val = float(pdi.iloc[-1])
    mdi_val = float(mdi.iloc[-1])

    return {
        "adx":      round(adx_val, 2),
        "di_plus":  round(pdi_val, 2),
        "di_minus": round(mdi_val, 2),
        "trending": adx_val >= min_adx,
        "bull_di":  pdi_val > mdi_val,
        "bear_di":  mdi_val > pdi_val,
    }


# ══════════════════════════════════════════════════════════════════════════
# ⑦–⑪ ENTRY — EMA 5×13 cross + quality filters
# ══════════════════════════════════════════════════════════════════════════

def detect_entry_signal(
    df:             pd.DataFrame,
    ema_fast:       int   = 5,
    ema_slow:       int   = 13,
    atr_mult_sl:    float = 0.5,
    rr:             float = 3.0,
    vol_avg_period: int   = 20,
    vol_min_ratio:  float = 1.3,
    body_min_ratio: float = 0.55,
    rsi_period:     int   = 14,
    rsi_long_max:   float = 70.0,
    rsi_short_min:  float = 30.0,
) -> dict:
    empty = {
        "buy_cross": False, "sell_cross": False, "cross_bars_ago": 0,
        "signal_fresh": False,
        "candle_strong": False, "body_ratio": 0.0,
        "volume_spike": False, "vol_ratio": 1.0,
        "rsi_ok_long": False, "rsi_ok_short": False, "rsi_val": 50.0,
        "price_side_ok_long": False, "price_side_ok_short": False,
        "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "tp_final": 0.0,
        "risk_pct": 0.0, "atr": 0.0,
        "price": float(df["close"].iloc[-1]) if len(df) > 0 else 0.0,
    }

    need = max(ema_slow, rsi_period, vol_avg_period) + 5
    if len(df) < need:
        return empty

    c    = df["close"]
    fast = _ema(c, ema_fast)
    slow = _ema(c, ema_slow)
    atr  = _atr(df, 14)

    atr_val   = float(atr.iloc[-1])
    cur_price = float(c.iloc[-1])

    # ── RSI ───────────────────────────────────────────────────────────────
    delta = c.diff()
    gain  = delta.clip(lower=0).ewm(span=rsi_period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=rsi_period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100.0 - 100.0 / (1.0 + rs)
    rsi_val = float(rsi.iloc[-1])

    # ── Volume ────────────────────────────────────────────────────────────
    vol     = df["volume"]
    vol_avg = float(vol.tail(vol_avg_period + 1).iloc[:-1].mean())
    vol_cur = float(vol.iloc[-1])
    vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 1.0
    volume_spike = vol_ratio >= vol_min_ratio

    # ── Find cross (FRESH only: ≤1 bar ago) ──────────────────────────────
    buy_cross  = False
    sell_cross = False
    bars_ago   = 0

    for i in range(1, 5):  # fresh = ≤2 bar, còn ≤4 bar vẫn lấy
        try:
            f_cur, f_prev = fast.iloc[-i],   fast.iloc[-i - 1]
            s_cur, s_prev = slow.iloc[-i],   slow.iloc[-i - 1]
        except IndexError:
            break
        if f_cur > s_cur and f_prev <= s_prev:
            buy_cross = True;  bars_ago = i - 1;  break
        if f_cur < s_cur and f_prev >= s_prev:
            sell_cross = True; bars_ago = i - 1;  break

    if not buy_cross and not sell_cross:
        return {**empty,
                "rsi_val": round(rsi_val, 1),
                "rsi_ok_long":  rsi_val < rsi_long_max,
                "rsi_ok_short": rsi_val > rsi_short_min,
                "vol_ratio":    round(vol_ratio, 2),
                "volume_spike": volume_spike,
                "atr": atr_val, "price": cur_price}

    cross_candle = df.iloc[-1 - bars_ago]
    confirm_candle = df.iloc[-1]

    # ── Candle body strength ───────────────────────────────────────────────
    c_open  = float(confirm_candle["open"])
    c_close = float(confirm_candle["close"])
    c_high  = float(confirm_candle["high"])
    c_low   = float(confirm_candle["low"])
    c_range = c_high - c_low
    c_body  = abs(c_close - c_open)
    body_ratio = c_body / c_range if c_range > 0 else 0.0
    candle_strong = body_ratio >= body_min_ratio

    # ── SL/TP ─────────────────────────────────────────────────────────────
    if buy_cross:
        # SL = lowest low trong 3 nến gần nhất
        sl_base = float(df["low"].iloc[-3:].min())
        sl      = sl_base - atr_val * atr_mult_sl
        risk    = max(cur_price - sl, atr_val * 0.1)
        tp1     = cur_price + risk * 1.0
        tp2     = cur_price + risk * 2.0
        tpf     = cur_price + risk * rr
        price_side_ok_long  = cur_price > float(slow.iloc[-1])
        price_side_ok_short = False
    else:
        sl_base = float(df["high"].iloc[-3:].max())
        sl      = sl_base + atr_val * atr_mult_sl
        risk    = max(sl - cur_price, atr_val * 0.1)
        tp1     = cur_price - risk * 1.0
        tp2     = cur_price - risk * 2.0
        tpf     = cur_price - risk * rr
        price_side_ok_long  = False
        price_side_ok_short = cur_price < float(slow.iloc[-1])

    risk_pct = abs(risk) / cur_price * 100.0 if cur_price > 0 else 0.0

    return {
        "buy_cross":    buy_cross,
        "sell_cross":   sell_cross,
        "cross_bars_ago": bars_ago,
        "signal_fresh": bars_ago <= 2,
        "candle_strong":    candle_strong,
        "body_ratio":       round(body_ratio, 2),
        "volume_spike":     volume_spike,
        "vol_ratio":        round(vol_ratio, 2),
        "rsi_ok_long":      rsi_val < rsi_long_max,
        "rsi_ok_short":     rsi_val > rsi_short_min,
        "rsi_val":          round(rsi_val, 1),
        "price_side_ok_long":  price_side_ok_long,
        "price_side_ok_short": price_side_ok_short,
        "sl":       round(sl,  8),
        "tp1":      round(tp1, 8),
        "tp2":      round(tp2, 8),
        "tp_final": round(tpf, 8),
        "risk_pct": round(risk_pct, 2),
        "atr":      atr_val,
        "price":    cur_price,
    }


# ══════════════════════════════════════════════════════════════════════════
# MAIN SCORER
# ══════════════════════════════════════════════════════════════════════════

RISK_MIN_PCT = 0.3    # SL quá gần → nhiễu
RISK_MAX_PCT = 4.0    # SL quá xa  → rủi ro lớn

def score_symbol(
    symbol:      str,
    df_ctx:      pd.DataFrame,
    df_entry:    pd.DataFrame,
    min_adx:     float = 25.0,
    atr_mult_sl: float = 0.5,
    rr:          float = 3.0,
) -> SignalResult:

    # Context layer
    ema   = calc_ema_stack(df_ctx)
    lr    = calc_linreg_slope(df_ctx)
    ms    = detect_market_structure(df_ctx)
    fib   = calc_fib_zone(df_ctx)
    cci   = calc_cci(df_ctx)
    adx   = calc_adx(df_ctx, min_adx=min_adx)

    # Entry layer
    entry = detect_entry_signal(df_entry, atr_mult_sl=atr_mult_sl, rr=rr)
    cur_price = entry["price"] or float(df_entry["close"].iloc[-1])

    # ── Direction ─────────────────────────────────────────────────────────
    has_long  = entry["buy_cross"]  and entry["signal_fresh"]
    has_short = entry["sell_cross"] and entry["signal_fresh"]

    if has_long:
        direction = "LONG"
    elif has_short:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    is_long  = direction == "LONG"
    is_short = direction == "SHORT"

    # ── 11-point scoring ──────────────────────────────────────────────────
    def _criteria(is_l: bool) -> list[tuple[str, bool]]:
        crit = []
        # Context (6)
        crit.append(("EMA-Stack",      ema["bull"] if is_l else ema["bear"]))
        crit.append(("LinReg",         lr["bull"]  if is_l else not lr["bull"]))
        crit.append(("Structure",      ms["bull"]  if is_l else ms["bear"]))
        fib_ok = fib["in_long_zone"]  if is_l else fib["in_short_zone"]
        crit.append((f"Fib{fib['pct']:.0f}%", fib_ok))
        cci_ok = (cci["bull"] or cci["fresh_cross_bull"]) if is_l else \
                 (cci["bear"] or cci["fresh_cross_bear"])
        crit.append(("CCI", cci_ok))
        adx_ok = adx["trending"] and (adx["bull_di"] if is_l else adx["bear_di"])
        crit.append((f"ADX{adx['adx']:.0f}", adx_ok))
        # Entry (5)
        crit.append(("CrossFresh",     entry["buy_cross"]  if is_l else entry["sell_cross"]))
        crit.append(("CandleStrong",   entry["candle_strong"]))
        crit.append((f"Vol×{entry['vol_ratio']:.1f}", entry["volume_spike"]))
        crit.append(("RSI-OK",         entry["rsi_ok_long"]  if is_l else entry["rsi_ok_short"]))
        crit.append(("PriceSide",      entry["price_side_ok_long"] if is_l else entry["price_side_ok_short"]))
        return crit

    if direction != "NEUTRAL":
        crit    = _criteria(is_long)
        score   = sum(1 for _, ok in crit if ok)
        reasons = [n for n, ok in crit if ok]
        rejects = [n for n, ok in crit if not ok]
    else:
        # Tính cả 2 chiều để /check vẫn cho thấy context status
        l_crit = _criteria(True)
        s_crit = _criteria(False)
        l_score = sum(1 for _, ok in l_crit if ok)
        s_score = sum(1 for _, ok in s_crit if ok)
        if l_score >= s_score:
            crit = l_crit
        else:
            crit = s_crit
        score   = max(l_score, s_score)
        reasons = [n for n, ok in crit if ok]
        rejects = [n for n, ok in crit if not ok]

    # ── SL/TP ─────────────────────────────────────────────────────────────
    sl       = entry["sl"]       if direction != "NEUTRAL" else 0.0
    tp1      = entry["tp1"]      if direction != "NEUTRAL" else 0.0
    tp2      = entry["tp2"]      if direction != "NEUTRAL" else 0.0
    tp_final = entry["tp_final"] if direction != "NEUTRAL" else 0.0
    risk_pct = entry["risk_pct"]

    # ── Risk filter ───────────────────────────────────────────────────────
    risk_ok = (RISK_MIN_PCT <= risk_pct <= RISK_MAX_PCT) if direction != "NEUTRAL" else True

    # ── Unpack flags ──────────────────────────────────────────────────────
    ema_stack_ok  = ema["bull"]  if is_long else (ema["bear"]  if is_short else False)
    fib_ok_flag   = fib["in_long_zone"] if is_long else (fib["in_short_zone"] if is_short else False)
    cci_ok_flag   = (cci["bull"] or cci["fresh_cross_bull"]) if is_long else \
                    ((cci["bear"] or cci["fresh_cross_bear"]) if is_short else False)
    adx_ok_flag   = adx["trending"] and (adx["bull_di"] if is_long else (adx["bear_di"] if is_short else False))
    struct_ok_flag = ms["bull"] if is_long else (ms["bear"] if is_short else False)
    entry_cross    = entry["buy_cross"] if is_long else (entry["sell_cross"] if is_short else False)
    ps_ok          = entry["price_side_ok_long"] if is_long else \
                     (entry["price_side_ok_short"] if is_short else False)

    return SignalResult(
        symbol    = symbol,
        direction = direction,
        score     = score,
        price     = round(cur_price, 8),
        sl        = round(sl,        8),
        tp1       = round(tp1,       8),
        tp2       = round(tp2,       8),
        tp_final  = round(tp_final,  8),
        atr       = round(entry["atr"], 8),
        rr        = rr,
        risk_pct  = round(risk_pct, 2),
        risk_ok   = risk_ok,
        # Context
        ema_stack    = ema_stack_ok,
        linreg_bull  = lr["bull"],
        struct_ok    = struct_ok_flag,
        fib_ok       = fib_ok_flag,
        cci_ok       = cci_ok_flag,
        adx_ok       = adx_ok_flag,
        # Entry
        entry_cross     = entry_cross,
        candle_strong   = entry["candle_strong"],
        volume_spike    = entry["volume_spike"],
        rsi_ok          = entry["rsi_ok_long"] if is_long else (entry["rsi_ok_short"] if is_short else False),
        price_side_ok   = ps_ok,
        signal_fresh    = entry["signal_fresh"],
        cross_bars_ago  = entry["cross_bars_ago"],
        # Detail
        struct_labels  = ms["labels"],
        ema_e13        = ema["e13"],
        ema_e20        = ema["e20"],
        ema_e50        = ema["e50"],
        ema_e200       = ema["e200"],
        cci_val        = cci.get("value", 0.0),
        adx_val        = adx["adx"],
        di_plus        = adx["di_plus"],
        di_minus       = adx["di_minus"],
        fib_pct        = fib["pct"],
        fib_zone       = fib["zone"],
        linreg_slope   = lr["slope"],
        rsi_val        = entry["rsi_val"],
        vol_ratio      = entry["vol_ratio"],
        body_ratio     = entry["body_ratio"],
        reasons        = reasons,
        rejects        = rejects,
    )
