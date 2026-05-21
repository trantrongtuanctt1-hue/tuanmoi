"""
Signal engine — Ceez Prime + Buy Sell Signal
═════════════════════════════════════════════
Scanner logic (khác indicator):
  Indicator : chờ cross → vào lệnh
  Scanner   : tìm coin đang SETUP tốt → user watch → chờ cross vào

Context (Ceez Prime — 4H):  6 điểm
  ① EMA Stack 13/20/50/200 xếp tầng + spread ≥ 0.3%
  ② LinReg slope dương/âm
  ③ Market Structure HH+HL | LH+LL (cần đủ 2)
  ④ Fib Zone 0.30–0.70 (equilibrium + discount/premium)
  ⑤ CCI > 0 hoặc < 0
  ⑥ ADX ≥ 20 + DI đúng chiều

Entry quality (Buy Sell Signal — 1H):  5 điểm
  ⑦ EMA fast > slow (LONG) | fast < slow (SHORT) — hướng đúng
  ⑧ RSI 25–75 — không extreme
  ⑨ Candle body ≥ 40% range
  ⑩ Volume ≥ 1.1× trung bình
  ⑪ Price đúng phía EMA 13

Bonus (không tính score, chỉ dùng để sort):
  ★ Cross FRESH (≤ 3 bar) → ưu tiên lên đầu danh sách
  ★ Cross gần đây (4–8 bar) → ưu tiên hơn chưa cross

Risk filter: 0.2% ≤ risk_pct ≤ 5%
Score pass: context ≥ 4/6 VÀ entry ≥ 3/5 VÀ tổng ≥ 6/11
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


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
    risk_ok:   bool

    # Context flags (6)
    ema_stack:   bool = False
    linreg_bull: bool = False
    struct_ok:   bool = False
    fib_ok:      bool = False
    cci_ok:      bool = False
    adx_ok:      bool = False

    # Entry flags (5)
    entry_cross:   bool = False   # EMA fast > slow (direction ok)
    rsi_ok:        bool = False
    candle_strong: bool = False
    volume_spike:  bool = False
    price_side_ok: bool = False

    # Cross status (bonus sort, không tính score)
    has_fresh_cross:  bool = False   # cross ≤ 3 bar
    has_recent_cross: bool = False   # cross 4–8 bar
    cross_bars_ago:   int  = -1      # -1 = không tìm thấy cross trong 8 bar
    signal_fresh:     bool = False   # = has_fresh_cross

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
    rsi_val:   float = 50.0
    vol_ratio: float = 1.0
    body_ratio: float = 0.0
    ema_spread_pct: float = 0.0   # khoảng cách EMA fast-slow (%)
    reasons:  list[str] = field(default_factory=list)
    rejects:  list[str] = field(default_factory=list)


# ═══════════════════════════════════
# HELPERS
# ═══════════════════════════════════

def _ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def _atr(df: pd.DataFrame, p: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(span=p, adjust=False).mean()


# ① EMA STACK
def calc_ema_stack(df: pd.DataFrame, min_spread_pct: float = 0.3) -> dict:
    if len(df) < 201:
        return {"bull": False, "bear": False,
                "e13": 0.0, "e20": 0.0, "e50": 0.0, "e200": 0.0}
    c    = df["close"]
    e13  = float(_ema(c, 13).iloc[-1])
    e20  = float(_ema(c, 20).iloc[-1])
    e50  = float(_ema(c, 50).iloc[-1])
    e200 = float(_ema(c, 200).iloc[-1])
    spread = abs(e13 - e200) / e200 * 100.0 if e200 > 0 else 0.0
    spread_ok = spread >= min_spread_pct
    return {
        "bull": e13 > e20 > e50 > e200 and spread_ok,
        "bear": e13 < e20 < e50 < e200 and spread_ok,
        "e13": e13, "e20": e20, "e50": e50, "e200": e200,
    }


# ② LINREG SLOPE
def calc_linreg_slope(df: pd.DataFrame, period: int = 50) -> dict:
    if len(df) < period:
        return {"bull": False, "slope": 0.0}
    tail  = df["close"].tail(period).values
    x     = np.arange(period, dtype=float)
    slope = float(np.polyfit(x, tail, 1)[0])
    price = float(tail[-1])
    slope_n = slope / price * 100.0 if price > 0 else 0.0
    return {"bull": slope > 0, "slope": round(slope_n, 6)}


# ③ MARKET STRUCTURE
def detect_market_structure(df: pd.DataFrame, swing_len: int = 5, lookback: int = 80) -> dict:
    empty = {"bull": False, "bear": False, "neutral": True,
             "labels": [], "hh": False, "hl": False, "lh": False, "ll": False}
    tail  = df.tail(lookback)
    if len(tail) < swing_len * 2 + 3:
        return empty
    highs, lows = tail["high"].values, tail["low"].values
    n = len(highs)
    sh_prices, sl_prices = [], []
    for i in range(swing_len, n - swing_len):
        win_h = highs[i - swing_len: i + swing_len + 1]
        win_l = lows[i  - swing_len: i + swing_len + 1]
        if highs[i] >= win_h.max(): sh_prices.append(float(highs[i]))
        if lows[i]  <= win_l.min(): sl_prices.append(float(lows[i]))
    if len(sh_prices) < 2 or len(sl_prices) < 2:
        return empty
    hh = sh_prices[-1] > sh_prices[-2]
    lh = sh_prices[-1] < sh_prices[-2]
    hl = sl_prices[-1] > sl_prices[-2]
    ll = sl_prices[-1] < sl_prices[-2]
    labels = []
    if hh: labels.append("HH")
    elif lh: labels.append("LH")
    if hl: labels.append("HL")
    elif ll: labels.append("LL")
    return {"bull": hh and hl, "bear": lh and ll,
            "neutral": not (hh and hl) and not (lh and ll),
            "labels": labels, "hh": hh, "hl": hl, "lh": lh, "ll": ll}


# ④ FIB ZONE (rộng hơn: 0.30–0.70)
def calc_fib_zone(df: pd.DataFrame, lookback: int = 60) -> dict:
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
    if pct <= 10:    zone = "DISC"
    elif pct >= 90:  zone = "PREM"
    elif cur >= fib_618: zone = "EQ↑"
    elif cur <= fib_382: zone = "EQ↓"
    elif cur >= fib_500: zone = "EQ↑"
    else:            zone = "EQ↓"
    return {
        "in_long_zone":  30.0 <= pct <= 70.0,   # không ở đỉnh/đáy tuyệt đối
        "in_short_zone": 30.0 <= pct <= 70.0,
        "pct":    round(pct, 1), "zone": zone,
        "fib_382": fib_382, "fib_500": fib_500, "fib_618": fib_618,
        "swing_high": swing_high, "swing_low": swing_low,
    }


# ⑤ CCI
def calc_cci(df: pd.DataFrame, period: int = 20) -> dict:
    if len(df) < period + 2:
        return {"value": 0.0, "bull": False, "bear": False}
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    ma  = tp.rolling(period).mean()
    md  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - ma) / (0.015 * md.replace(0, np.nan))
    cur = float(cci.iloc[-1])
    return {"value": round(cur, 2), "bull": cur > 0, "bear": cur < 0}


# ⑥ ADX + DI
def calc_adx(df: pd.DataFrame, period: int = 14, min_adx: float = 20.0) -> dict:
    if len(df) < period * 2 + 2:
        return {"adx": 0.0, "di_plus": 0.0, "di_minus": 0.0,
                "trending": False, "bull_di": False, "bear_di": False}
    high, low = df["high"], df["low"]
    up, down  = high.diff(), -low.diff()
    pdm = pd.Series(np.where((up > down) & (up > 0),   up,   0.0), index=df.index)
    mdm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_s = _atr(df, period).replace(0, np.nan)
    pdi = 100.0 * pdm.ewm(span=period, adjust=False).mean() / atr_s
    mdi = 100.0 * mdm.ewm(span=period, adjust=False).mean() / atr_s
    dx  = 100.0 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    adx_val = float(adx.iloc[-1])
    pdi_val = float(pdi.iloc[-1])
    mdi_val = float(mdi.iloc[-1])
    return {
        "adx": round(adx_val, 2), "di_plus": round(pdi_val, 2), "di_minus": round(mdi_val, 2),
        "trending": adx_val >= min_adx,
        "bull_di":  pdi_val > mdi_val,
        "bear_di":  mdi_val > pdi_val,
    }


# ⑦–⑪ ENTRY QUALITY + CROSS DETECTION
def detect_entry(
    df:             pd.DataFrame,
    ema_fast:       int   = 5,
    ema_slow:       int   = 13,
    atr_mult_sl:    float = 0.5,
    rr:             float = 3.0,
    vol_avg_period: int   = 20,
    vol_min_ratio:  float = 1.1,
    body_min_ratio: float = 0.40,
    rsi_period:     int   = 14,
    cross_lookback: int   = 8,    # tìm cross trong 8 bar gần nhất (bonus sort)
) -> dict:
    need = max(ema_slow, rsi_period, vol_avg_period) + cross_lookback + 2
    cur_price = float(df["close"].iloc[-1]) if len(df) > 0 else 0.0
    empty = {
        "bull_dir": False, "bear_dir": False,
        "has_fresh_cross": False, "has_recent_cross": False, "cross_bars_ago": -1,
        "candle_strong": False, "body_ratio": 0.0,
        "volume_spike": False, "vol_ratio": 1.0,
        "rsi_ok_long": False, "rsi_ok_short": False, "rsi_val": 50.0,
        "price_side_ok_long": False, "price_side_ok_short": False,
        "ema_spread_pct": 0.0,
        "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "tp_final": 0.0,
        "risk_pct": 0.0, "atr": 0.0, "price": cur_price,
    }
    if len(df) < need:
        return empty

    c    = df["close"]
    fast = _ema(c, ema_fast)
    slow = _ema(c, ema_slow)
    atr  = _atr(df, 14)

    atr_val    = float(atr.iloc[-1])
    cur_price  = float(c.iloc[-1])
    fast_cur   = float(fast.iloc[-1])
    slow_cur   = float(slow.iloc[-1])
    spread_pct = abs(fast_cur - slow_cur) / slow_cur * 100.0 if slow_cur > 0 else 0.0

    # Hướng EMA (không cần cross)
    bull_dir = fast_cur > slow_cur
    bear_dir = fast_cur < slow_cur

    # RSI
    delta   = c.diff()
    gain    = delta.clip(lower=0).ewm(span=rsi_period, adjust=False).mean()
    loss    = (-delta.clip(upper=0)).ewm(span=rsi_period, adjust=False).mean()
    rsi     = 100.0 - 100.0 / (1.0 + gain / loss.replace(0, np.nan))
    rsi_val = float(rsi.iloc[-1])

    # Volume
    vol       = df["volume"]
    vol_avg   = float(vol.tail(vol_avg_period + 1).iloc[:-1].mean())
    vol_cur   = float(vol.iloc[-1])
    vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 1.0

    # Candle body (nến cuối)
    last = df.iloc[-1]
    c_range = float(last["high"]) - float(last["low"])
    c_body  = abs(float(last["close"]) - float(last["open"]))
    body_ratio = c_body / c_range if c_range > 0 else 0.0

    # Tìm cross gần nhất trong cross_lookback bar (dùng để sort, không hard-require)
    has_fresh_cross  = False
    has_recent_cross = False
    cross_bars_ago   = -1
    for i in range(1, cross_lookback + 2):
        try:
            f_c, f_p = fast.iloc[-i], fast.iloc[-i - 1]
            s_c, s_p = slow.iloc[-i], slow.iloc[-i - 1]
        except IndexError:
            break
        is_bull_cross = f_c > s_c and f_p <= s_p
        is_bear_cross = f_c < s_c and f_p >= s_p
        if is_bull_cross or is_bear_cross:
            cross_bars_ago = i - 1
            if cross_bars_ago <= 3:
                has_fresh_cross  = True
            else:
                has_recent_cross = True
            break

    # SL/TP
    if bull_dir:
        sl_base = float(df["low"].iloc[-5:].min())
        sl      = sl_base - atr_val * atr_mult_sl
        risk    = max(cur_price - sl, atr_val * 0.1)
        tp1, tp2, tpf = cur_price + risk, cur_price + risk * 2, cur_price + risk * rr
        ps_long  = cur_price > slow_cur
        ps_short = False
    else:
        sl_base = float(df["high"].iloc[-5:].max())
        sl      = sl_base + atr_val * atr_mult_sl
        risk    = max(sl - cur_price, atr_val * 0.1)
        tp1, tp2, tpf = cur_price - risk, cur_price - risk * 2, cur_price - risk * rr
        ps_long  = False
        ps_short = cur_price < slow_cur

    risk_pct = abs(risk) / cur_price * 100.0 if cur_price > 0 else 0.0

    return {
        "bull_dir": bull_dir, "bear_dir": bear_dir,
        "has_fresh_cross": has_fresh_cross, "has_recent_cross": has_recent_cross,
        "cross_bars_ago":  cross_bars_ago,
        "candle_strong":   body_ratio >= body_min_ratio,
        "body_ratio":      round(body_ratio, 2),
        "volume_spike":    vol_ratio >= vol_min_ratio,
        "vol_ratio":       round(vol_ratio, 2),
        "rsi_ok_long":     25.0 <= rsi_val <= 75.0,
        "rsi_ok_short":    25.0 <= rsi_val <= 75.0,
        "rsi_val":         round(rsi_val, 1),
        "price_side_ok_long":  ps_long,
        "price_side_ok_short": ps_short,
        "ema_spread_pct":  round(spread_pct, 3),
        "sl":      round(sl,  8), "tp1": round(tp1, 8),
        "tp2":     round(tp2, 8), "tp_final": round(tpf, 8),
        "risk_pct": round(risk_pct, 2), "atr": atr_val, "price": cur_price,
    }


# ═══════════════════════════════════
# MAIN SCORER
# ═══════════════════════════════════

RISK_MIN_PCT = 0.2
RISK_MAX_PCT = 5.0

def score_symbol(
    symbol:      str,
    df_ctx:      pd.DataFrame,
    df_entry:    pd.DataFrame,
    min_adx:     float = 20.0,
    atr_mult_sl: float = 0.5,
    rr:          float = 3.0,
) -> SignalResult:

    ema  = calc_ema_stack(df_ctx)
    lr   = calc_linreg_slope(df_ctx)
    ms   = detect_market_structure(df_ctx)
    fib  = calc_fib_zone(df_ctx)
    cci  = calc_cci(df_ctx)
    adx  = calc_adx(df_ctx, min_adx=min_adx)
    entry = detect_entry(df_entry, atr_mult_sl=atr_mult_sl, rr=rr)

    cur_price = entry["price"] or float(df_entry["close"].iloc[-1])

    # Direction dựa trên EMA direction (không cần cross)
    if entry["bull_dir"] and (ema["bull"] or lr["bull"] or adx["bull_di"]):
        direction = "LONG"
    elif entry["bear_dir"] and (ema["bear"] or not lr["bull"] or adx["bear_di"]):
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    is_long  = direction == "LONG"
    is_short = direction == "SHORT"

    def _criteria(is_l: bool) -> list[tuple[str, bool]]:
        # Context (6)
        crit = [
            ("EMA-Stack",  ema["bull"] if is_l else ema["bear"]),
            ("LinReg",     lr["bull"]  if is_l else not lr["bull"]),
            ("Structure",  ms["bull"]  if is_l else ms["bear"]),
            (f"Fib{fib['pct']:.0f}%", fib["in_long_zone"] if is_l else fib["in_short_zone"]),
            ("CCI",        cci["bull"] if is_l else cci["bear"]),
            (f"ADX{adx['adx']:.0f}", adx["trending"] and (adx["bull_di"] if is_l else adx["bear_di"])),
        ]
        # Entry quality (5) — không có cross requirement
        crit += [
            ("EMA-Dir",     entry["bull_dir"] if is_l else entry["bear_dir"]),
            ("RSI",         entry["rsi_ok_long"] if is_l else entry["rsi_ok_short"]),
            (f"Cnd{entry['body_ratio']:.0%}", entry["candle_strong"]),
            (f"Vol{entry['vol_ratio']:.1f}x", entry["volume_spike"]),
            ("PriceSide",   entry["price_side_ok_long"] if is_l else entry["price_side_ok_short"]),
        ]
        return crit

    if direction != "NEUTRAL":
        crit  = _criteria(is_long)
    else:
        l_c = _criteria(True)
        s_c = _criteria(False)
        crit = l_c if sum(1 for _, ok in l_c if ok) >= sum(1 for _, ok in s_c if ok) else s_c

    score   = sum(1 for _, ok in crit if ok)
    reasons = [n for n, ok in crit if ok]
    rejects = [n for n, ok in crit if not ok]

    sl       = entry["sl"]       if direction != "NEUTRAL" else 0.0
    tp1      = entry["tp1"]      if direction != "NEUTRAL" else 0.0
    tp2      = entry["tp2"]      if direction != "NEUTRAL" else 0.0
    tp_final = entry["tp_final"] if direction != "NEUTRAL" else 0.0
    risk_pct = entry["risk_pct"]
    risk_ok  = (RISK_MIN_PCT <= risk_pct <= RISK_MAX_PCT) if direction != "NEUTRAL" else True

    ema_stack_ok = ema["bull"] if is_long else (ema["bear"] if is_short else False)
    fib_ok       = fib["in_long_zone"] if is_long else (fib["in_short_zone"] if is_short else False)
    cci_ok       = cci["bull"] if is_long else (cci["bear"] if is_short else False)
    adx_ok       = adx["trending"] and (adx["bull_di"] if is_long else (adx["bear_di"] if is_short else False))
    struct_ok    = ms["bull"] if is_long else (ms["bear"] if is_short else False)
    ps_ok        = entry["price_side_ok_long"] if is_long else (entry["price_side_ok_short"] if is_short else False)

    return SignalResult(
        symbol=symbol, direction=direction, score=score,
        price=round(cur_price, 8), sl=round(sl, 8),
        tp1=round(tp1, 8), tp2=round(tp2, 8), tp_final=round(tp_final, 8),
        atr=round(entry["atr"], 8), rr=rr,
        risk_pct=round(risk_pct, 2), risk_ok=risk_ok,
        # Context
        ema_stack=ema_stack_ok, linreg_bull=lr["bull"],
        struct_ok=struct_ok, fib_ok=fib_ok, cci_ok=cci_ok, adx_ok=adx_ok,
        # Entry
        entry_cross=entry["bull_dir"] if is_long else (entry["bear_dir"] if is_short else False),
        rsi_ok=entry["rsi_ok_long"] if is_long else (entry["rsi_ok_short"] if is_short else False),
        candle_strong=entry["candle_strong"],
        volume_spike=entry["volume_spike"],
        price_side_ok=ps_ok,
        # Cross bonus
        has_fresh_cross=entry["has_fresh_cross"],
        has_recent_cross=entry["has_recent_cross"],
        cross_bars_ago=entry["cross_bars_ago"],
        signal_fresh=entry["has_fresh_cross"],
        # Detail
        struct_labels=ms["labels"],
        ema_e13=ema["e13"], ema_e20=ema["e20"], ema_e50=ema["e50"], ema_e200=ema["e200"],
        cci_val=cci.get("value", 0.0),
        adx_val=adx["adx"], di_plus=adx["di_plus"], di_minus=adx["di_minus"],
        fib_pct=fib["pct"], fib_zone=fib["zone"], linreg_slope=lr["slope"],
        rsi_val=entry["rsi_val"], vol_ratio=entry["vol_ratio"],
        body_ratio=entry["body_ratio"], ema_spread_pct=entry["ema_spread_pct"],
        reasons=reasons, rejects=rejects,
    )
