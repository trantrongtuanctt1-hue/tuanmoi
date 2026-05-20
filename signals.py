"""
Signal engine — Ceez Prime + Buy Sell Signal combo
═══════════════════════════════════════════════════
Context layer  (Ceez Prime  — chạy trên context TF, mặc định 4H):
  ① EMA stack      : 13 > 20 > 50 > 200  (bull) / 13 < 20 < 50 < 200  (bear)
  ② LinReg slope   : hệ số góc linear regression 50 nến
  ③ Market struct  : HH/HL (bull) | LH/LL (bear)
  ④ Fib zone       : giá trong vùng 0.382–0.618 của swing gần nhất
  ⑤ CCI            : CCI > 0 (bull) | CCI < 0 (bear)
  ⑥ ADX + DI       : ADX > 20 và DI+ > DI- (bull) | DI- > DI+ (bear)

Entry layer (Buy Sell Signal — chạy trên entry TF, mặc định 1H):
  ⑦ EMA 5/13 cross + candle confirmation

Điểm: 0–7.  Direction chỉ set khi cross xuất hiện (entry layer kích hoạt).
SL  = low/high của nến cross ± ATR × sl_mult
TP  = entry + risk × rr  (1R / 2R / final-R)
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
    # ── Core ──────────────────────────────────────────────────────────────
    symbol:    str
    direction: str        # "LONG" | "SHORT" | "NEUTRAL"
    score:     int        # 0–7
    price:     float
    sl:        float
    tp1:       float      # 1R
    tp2:       float      # 2R
    tp_final:  float      # RR × risk
    atr:       float
    rr:        float
    risk_pct:  float      # % distance entry → SL

    # ── Context (Ceez Prime) ──────────────────────────────────────────────
    ema_stack:     bool   = False
    linreg_bull:   bool   = False
    struct_ok:     bool   = False
    fib_ok:        bool   = False
    cci_ok:        bool   = False
    adx_ok:        bool   = False

    # ── Entry (Buy Sell Signal) ───────────────────────────────────────────
    entry_cross:    bool  = False
    candle_confirm: bool  = False
    signal_fresh:   bool  = False   # cross ≤ 1 bar ago
    cross_bars_ago: int   = 0

    # ── Detail ────────────────────────────────────────────────────────────
    struct_labels: list[str] = field(default_factory=list)
    ema_e13:  float = 0.0
    ema_e20:  float = 0.0
    ema_e50:  float = 0.0
    ema_e200: float = 0.0
    cci_val:  float = 0.0
    adx_val:  float = 0.0
    di_plus:  float = 0.0
    di_minus: float = 0.0
    fib_pct:  float = 0.0   # % vị trí giá trong range swing (0=low, 100=high)
    fib_zone: str   = "EQ"  # DISC | EQ↓ | EQ | EQ↑ | PREM
    linreg_slope: float = 0.0

    reasons: list[str] = field(default_factory=list)


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
# ① EMA STACK  (Ceez Prime — 13 / 20 / 50 / 200)
# ══════════════════════════════════════════════════════════════════════════

def calc_ema_stack(df: pd.DataFrame) -> dict:
    if len(df) < 201:
        return {"bull": False, "bear": False,
                "e13": 0.0, "e20": 0.0, "e50": 0.0, "e200": 0.0}
    c    = df["close"]
    e13  = float(_ema(c, 13).iloc[-1])
    e20  = float(_ema(c, 20).iloc[-1])
    e50  = float(_ema(c, 50).iloc[-1])
    e200 = float(_ema(c, 200).iloc[-1])
    return {
        "bull": e13 > e20 > e50 > e200,
        "bear": e13 < e20 < e50 < e200,
        "e13": e13, "e20": e20, "e50": e50, "e200": e200,
    }


# ══════════════════════════════════════════════════════════════════════════
# ② LINEAR REGRESSION SLOPE  (Ceez Prime)
# ══════════════════════════════════════════════════════════════════════════

def calc_linreg_slope(df: pd.DataFrame, period: int = 50) -> dict:
    if len(df) < period:
        return {"bull": False, "slope": 0.0}
    tail  = df["close"].tail(period).values
    x     = np.arange(period, dtype=float)
    slope = float(np.polyfit(x, tail, 1)[0])
    return {"bull": slope > 0, "slope": round(slope, 8)}


# ══════════════════════════════════════════════════════════════════════════
# ③ MARKET STRUCTURE  (Ceez Prime — HH/HL vs LH/LL)
# ══════════════════════════════════════════════════════════════════════════

def detect_market_structure(
    df:        pd.DataFrame,
    swing_len: int = 5,
    lookback:  int = 80,
) -> dict:
    """
    Tìm swing highs / lows bằng pivot (N nến mỗi bên).
    Kiểm tra last-2 swing highs và last-2 swing lows.
    """
    empty = {"bull": False, "bear": False, "neutral": True, "labels": [],
             "hh": False, "hl": False, "lh": False, "ll": False}

    tail = df.tail(lookback)
    if len(tail) < swing_len * 2 + 3:
        return empty

    highs = tail["high"].values
    lows  = tail["low"].values
    n     = len(highs)

    sh_prices, sl_prices = [], []
    for i in range(swing_len, n - swing_len):
        win_h = highs[i - swing_len: i + swing_len + 1]
        win_l = lows[i - swing_len:  i + swing_len + 1]
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

    bull    = hh and hl
    bear    = lh and ll

    labels = []
    if hh: labels.append("HH")
    elif lh: labels.append("LH")
    if hl: labels.append("HL")
    elif ll: labels.append("LL")

    return {
        "bull": bull, "bear": bear,
        "neutral": not bull and not bear,
        "labels": labels,
        "hh": hh, "hl": hl, "lh": lh, "ll": ll,
    }


# ══════════════════════════════════════════════════════════════════════════
# ④ FIBONACCI ZONE  (Ceez Prime — swing-based)
# ══════════════════════════════════════════════════════════════════════════

def calc_fib_zone(df: pd.DataFrame, lookback: int = 60) -> dict:
    """
    Xác định vị trí giá trong range swing gần nhất.
    LONG: giá tốt khi ≤ 61.8% (discount / equilibrium)
    SHORT: giá tốt khi ≥ 38.2% (premium / equilibrium)
    """
    tail  = df.tail(lookback)
    swing_high = float(tail["high"].max())
    swing_low  = float(tail["low"].min())
    rng = swing_high - swing_low

    cur = float(df["close"].iloc[-1])

    if rng <= 0:
        return {"in_long_zone": True, "in_short_zone": True,
                "pct": 50.0, "zone": "EQ",
                "fib_382": cur, "fib_500": cur, "fib_618": cur,
                "swing_high": cur, "swing_low": cur}

    pct      = (cur - swing_low) / rng * 100.0
    fib_382  = swing_low + 0.382 * rng
    fib_500  = swing_low + 0.500 * rng
    fib_618  = swing_low + 0.618 * rng

    if pct <= 5:   zone = "DISC"
    elif pct >= 95: zone = "PREM"
    elif cur >= fib_618: zone = "EQ↑"
    elif cur <= fib_382: zone = "EQ↓"
    elif cur >= fib_500: zone = "EQ↑"
    else:           zone = "EQ↓"

    return {
        "in_long_zone":  cur <= fib_618,   # giá dưới 61.8% → discount/EQ, tốt cho LONG
        "in_short_zone": cur >= fib_382,   # giá trên 38.2% → premium/EQ, tốt cho SHORT
        "pct":    round(pct, 1),
        "zone":   zone,
        "fib_382": round(fib_382, 6),
        "fib_500": round(fib_500, 6),
        "fib_618": round(fib_618, 6),
        "swing_high": round(swing_high, 6),
        "swing_low":  round(swing_low, 6),
    }


# ══════════════════════════════════════════════════════════════════════════
# ⑤ CCI  (Ceez Prime — zero-line cross)
# ══════════════════════════════════════════════════════════════════════════

def calc_cci(df: pd.DataFrame, period: int = 20) -> dict:
    if len(df) < period + 2:
        return {"value": 0.0, "bull": False, "bear": False,
                "cross_above": False, "cross_below": False}

    tp  = (df["high"] + df["low"] + df["close"]) / 3
    ma  = tp.rolling(period).mean()
    md  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - ma) / (0.015 * md.replace(0, np.nan))

    cur  = float(cci.iloc[-1])
    prev = float(cci.iloc[-2]) if len(cci) > 1 else cur

    return {
        "value":       round(cur, 2),
        "bull":        cur > 0,
        "bear":        cur < 0,
        "cross_above": prev <= 0 and cur > 0,
        "cross_below": prev >= 0 and cur < 0,
    }


# ══════════════════════════════════════════════════════════════════════════
# ⑥ ADX + DI  (Ceez Prime)
# ══════════════════════════════════════════════════════════════════════════

def calc_adx(df: pd.DataFrame, period: int = 14, min_adx: float = 20.0) -> dict:
    if len(df) < period * 2 + 2:
        return {"adx": 0.0, "di_plus": 0.0, "di_minus": 0.0,
                "trending": False, "bull_di": False, "bear_di": False}

    high  = df["high"]
    low   = df["low"]

    up   = high.diff()
    down = -low.diff()

    pdm = np.where((up > down) & (up > 0),   up,   0.0)
    mdm = np.where((down > up) & (down > 0), down, 0.0)

    pdm_s = pd.Series(pdm, index=df.index)
    mdm_s = pd.Series(mdm, index=df.index)

    atr_s = _atr(df, period)
    atr_s = atr_s.replace(0, np.nan)

    pdi = 100.0 * pdm_s.ewm(span=period, adjust=False).mean() / atr_s
    mdi = 100.0 * mdm_s.ewm(span=period, adjust=False).mean() / atr_s

    dx_denom = (pdi + mdi).replace(0, np.nan)
    dx  = 100.0 * (pdi - mdi).abs() / dx_denom
    adx = dx.ewm(span=period, adjust=False).mean()

    adx_val  = float(adx.iloc[-1])
    pdi_val  = float(pdi.iloc[-1])
    mdi_val  = float(mdi.iloc[-1])

    return {
        "adx":      round(adx_val, 2),
        "di_plus":  round(pdi_val, 2),
        "di_minus": round(mdi_val, 2),
        "trending": adx_val >= min_adx,
        "bull_di":  pdi_val > mdi_val,
        "bear_di":  mdi_val > pdi_val,
    }


# ══════════════════════════════════════════════════════════════════════════
# ⑦ ENTRY SIGNAL  (Buy Sell Signal — EMA 5/13 + candle confirm)
# ══════════════════════════════════════════════════════════════════════════

def detect_entry_signal(
    df:          pd.DataFrame,
    ema_fast:    int   = 5,
    ema_slow:    int   = 13,
    atr_mult_sl: float = 0.5,
    rr:          float = 3.0,
    lookback:    int   = 3,     # tìm cross trong N nến gần nhất
) -> dict:
    """
    Phát hiện EMA 5/13 crossover trong lookback nến gần nhất.
    Tính SL/TP dựa theo nến tạo cross và ATR.
    """
    empty = {
        "buy_cross": False, "sell_cross": False, "cross_bars_ago": 0,
        "candle_bull": False, "candle_bear": False,
        "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "tp_final": 0.0,
        "risk_pct": 0.0, "atr": 0.0,
        "price": float(df["close"].iloc[-1]) if len(df) > 0 else 0.0,
    }

    if len(df) < ema_slow + lookback + 2:
        return empty

    c    = df["close"]
    fast = _ema(c, ema_fast)
    slow = _ema(c, ema_slow)
    atr  = _atr(df, 14)

    atr_val   = float(atr.iloc[-1])
    cur_price = float(c.iloc[-1])

    last        = df.iloc[-1]
    candle_bull = float(last["close"]) > float(last["open"])
    candle_bear = float(last["close"]) < float(last["open"])

    buy_cross  = False
    sell_cross = False
    bars_ago   = 0

    # Tìm cross gần nhất trong lookback bars
    for i in range(1, lookback + 2):
        idx  = -(i)
        idx1 = -(i + 1)
        try:
            f_cur, f_prev = fast.iloc[idx], fast.iloc[idx1]
            s_cur, s_prev = slow.iloc[idx], slow.iloc[idx1]
        except IndexError:
            break

        if f_cur > s_cur and f_prev <= s_prev:
            buy_cross  = True
            bars_ago   = i - 1
            break
        if f_cur < s_cur and f_prev >= s_prev:
            sell_cross = True
            bars_ago   = i - 1
            break

    if not buy_cross and not sell_cross:
        return {**empty, "candle_bull": candle_bull, "candle_bear": candle_bear,
                "atr": atr_val, "price": cur_price}

    # SL/TP từ nến tạo cross
    cross_candle = df.iloc[-1 - bars_ago]

    if buy_cross:
        sl    = float(cross_candle["low"]) - atr_val * atr_mult_sl
        risk  = max(cur_price - sl, atr_val * 0.1)
        tp1   = cur_price + risk * 1.0
        tp2   = cur_price + risk * 2.0
        tpf   = cur_price + risk * rr
    else:  # sell_cross
        sl    = float(cross_candle["high"]) + atr_val * atr_mult_sl
        risk  = max(sl - cur_price, atr_val * 0.1)
        tp1   = cur_price - risk * 1.0
        tp2   = cur_price - risk * 2.0
        tpf   = cur_price - risk * rr

    risk_pct = abs(risk) / cur_price * 100.0 if cur_price > 0 else 0.0

    return {
        "buy_cross":    buy_cross,
        "sell_cross":   sell_cross,
        "cross_bars_ago": bars_ago,
        "candle_bull":  candle_bull,
        "candle_bear":  candle_bear,
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

def score_symbol(
    symbol:      str,
    df_ctx:      pd.DataFrame,         # Context TF (4H) — Ceez Prime
    df_entry:    pd.DataFrame,         # Entry   TF (1H) — Buy Sell Signal
    min_adx:     float = 20.0,
    atr_mult_sl: float = 0.5,
    rr:          float = 3.0,
) -> SignalResult:
    """
    Kết hợp Ceez Prime (context) + Buy Sell Signal (entry).
    Trả SignalResult với direction != NEUTRAL chỉ khi có cross trên entry TF.
    """
    # ── Context layer ──────────────────────────────────────────────────────
    ema  = calc_ema_stack(df_ctx)
    lr   = calc_linreg_slope(df_ctx)
    ms   = detect_market_structure(df_ctx)
    fib  = calc_fib_zone(df_ctx)
    cci  = calc_cci(df_ctx)
    adx  = calc_adx(df_ctx, min_adx=min_adx)

    # ── Entry layer ────────────────────────────────────────────────────────
    entry = detect_entry_signal(df_entry, atr_mult_sl=atr_mult_sl, rr=rr)
    cur_price = entry["price"] or float(df_entry["close"].iloc[-1])

    # ══ Scoring ════════════════════════════════════════════════════════════

    def _long_criteria():
        crit = []
        if ema["bull"]:
            crit.append(("EMA↑Stack",   True))
        else:
            crit.append(("EMA↑Stack",   False))
        crit.append(("LinReg↑",   lr["bull"]))
        crit.append(("HH/HL",     ms["bull"]))
        crit.append((f"Fib{fib['pct']:.0f}%",  fib["in_long_zone"]))
        crit.append((f"CCI+{cci['val'] if 'val' in cci else cci.get('value',0):.0f}", cci["bull"]))
        crit.append((f"ADX{adx['adx']:.0f}↑", adx["trending"] and adx["bull_di"]))
        cnf = entry["buy_cross"] and entry["candle_bull"]
        crit.append(("EMA5×13↑+Cnf", cnf))
        return crit

    def _short_criteria():
        crit = []
        if ema["bear"]:
            crit.append(("EMA↓Stack",  True))
        else:
            crit.append(("EMA↓Stack",  False))
        crit.append(("LinReg↓",  not lr["bull"]))
        crit.append(("LH/LL",    ms["bear"]))
        crit.append((f"Fib{fib['pct']:.0f}%",  fib["in_short_zone"]))
        cci_val = cci.get("value", 0.0)
        crit.append((f"CCI{cci_val:.0f}",  cci["bear"]))
        crit.append((f"ADX{adx['adx']:.0f}↓", adx["trending"] and adx["bear_di"]))
        cnf = entry["sell_cross"] and entry["candle_bear"]
        crit.append(("EMA5×13↓+Cnf", cnf))
        return crit

    long_crit  = _long_criteria()
    short_crit = _short_criteria()

    long_score  = sum(1 for _, ok in long_crit  if ok)
    short_score = sum(1 for _, ok in short_crit if ok)

    long_reasons  = [name for name, ok in long_crit  if ok]
    short_reasons = [name for name, ok in short_crit if ok]

    # ── Direction — chỉ set LONG/SHORT khi có cross ───────────────────────
    has_long_cross  = entry["buy_cross"]  and entry["candle_bull"]
    has_short_cross = entry["sell_cross"] and entry["candle_bear"]

    if has_long_cross and long_score >= short_score:
        direction = "LONG"
        score     = long_score
        reasons   = long_reasons
        sl        = entry["sl"]
        tp1       = entry["tp1"]
        tp2       = entry["tp2"]
        tp_final  = entry["tp_final"]
        risk_pct  = entry["risk_pct"]

    elif has_short_cross and short_score > long_score:
        direction = "SHORT"
        score     = short_score
        reasons   = short_reasons
        sl        = entry["sl"]
        tp1       = entry["tp1"]
        tp2       = entry["tp2"]
        tp_final  = entry["tp_final"]
        risk_pct  = entry["risk_pct"]

    else:
        direction = "NEUTRAL"
        # Vẫn tính score để cho /check biết "context chuẩn bao nhiêu điểm"
        score    = max(long_score, short_score)
        reasons  = long_reasons if long_score >= short_score else short_reasons
        sl = tp1 = tp2 = tp_final = 0.0
        risk_pct = 0.0

    # ── Unpack for dataclass ──────────────────────────────────────────────
    is_long  = direction == "LONG"
    is_short = direction == "SHORT"

    ema_stack_ok = ema["bull"] if is_long else (ema["bear"] if is_short else False)
    fib_ok       = fib["in_long_zone"] if is_long else (fib["in_short_zone"] if is_short else False)
    cci_ok       = cci["bull"] if is_long else (cci["bear"] if is_short else False)
    adx_ok       = (adx["trending"] and adx["bull_di"]) if is_long else \
                   ((adx["trending"] and adx["bear_di"]) if is_short else False)
    struct_ok    = ms["bull"] if is_long else (ms["bear"] if is_short else False)
    entry_cross  = has_long_cross if is_long else (has_short_cross if is_short else False)

    return SignalResult(
        symbol    = symbol,
        direction = direction,
        score     = score,
        price     = round(cur_price, 8),
        sl        = round(sl,       8),
        tp1       = round(tp1,      8),
        tp2       = round(tp2,      8),
        tp_final  = round(tp_final, 8),
        atr       = round(entry["atr"], 8),
        rr        = rr,
        risk_pct  = round(risk_pct, 2),
        # Context
        ema_stack    = ema_stack_ok,
        linreg_bull  = lr["bull"],
        struct_ok    = struct_ok,
        fib_ok       = fib_ok,
        cci_ok       = cci_ok,
        adx_ok       = adx_ok,
        # Entry
        entry_cross     = entry_cross,
        candle_confirm  = entry["candle_bull"] if is_long else entry["candle_bear"],
        signal_fresh    = entry["cross_bars_ago"] <= 1,
        cross_bars_ago  = entry["cross_bars_ago"],
        # Detail
        struct_labels = ms["labels"],
        ema_e13   = ema["e13"],
        ema_e20   = ema["e20"],
        ema_e50   = ema["e50"],
        ema_e200  = ema["e200"],
        cci_val   = cci.get("value", 0.0),
        adx_val   = adx["adx"],
        di_plus   = adx["di_plus"],
        di_minus  = adx["di_minus"],
        fib_pct   = fib["pct"],
        fib_zone  = fib["zone"],
        linreg_slope = lr["slope"],
        reasons   = reasons,
    )
