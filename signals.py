"""
Signal Engine — 15M ULTRA v3.0
Hợp nhất đầy đủ TẤT CẢ điều kiện từ 2 PineScript:
  1. SXL Sniper + MSB-OB + Vol Balance [Tuan]
  2. ⚡ 15M ULTRA — ST AI + UT + SMC + SAR + RSI + MTF

Score tổng: 0–11 điểm (giống PineScript Section N)
  ─ Core Checklist  6 điều kiện (SMC Swing + SMC Internal + ST AI + UT Bot + SAR + Zone)
  ─ MTF Context     +2 (1h+4h+1d đồng thuận)
  ─ MTF Bridge      +1 (30m)
  ─ MTF Momentum    +1 (5m)
  ─ RSI MTF         +1 (>=4/6 TF đồng hướng)

Bonus fields (từ SXL): SXL confluences, Vol Balance, Spike, Leverage, Premium
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalResult:
    symbol:    str
    score:     int
    direction: str
    price:     float
    sl:        float
    tp1:       float
    tp2:       float
    reasons:   list = field(default_factory=list)
    timeframe: str = "5m"
    buy_score:  int = 0
    sell_score: int = 0
    verdict:    str = "NEUTRAL"
    entry_tip:  str = "Chờ"
    ck_st_ai:       bool = False
    ck_ut_bot:      bool = False
    ck_sar:         bool = False
    ck_smc_swing:   bool = False
    ck_smc_int:     bool = False
    ck_zone:        bool = False
    checklist_score: int = 0
    mtf_momentum: str = "="
    mtf_bridge:   str = "="
    mtf_context:  str = "="
    rsi_val:        float = 50.0
    rsi_bull_count: int   = 0
    rsi_bear_count: int   = 0
    zone_txt:  str   = "EQ"
    zone_pct:  float = 50.0
    l_score:    int  = 0
    s_score:    int  = 0
    is_premium: bool = False
    bull_pct:    float = 0.0
    bear_pct:    float = 0.0
    vol_confirm: bool  = False
    is_spike:        bool  = False
    spike_direction: str   = ""
    spike_pct:       float = 0.0
    leverage: int   = 1
    lev_risk: str   = "Rat cao"
    atr_pct:  float = 0.0
    st_ai_bull:    bool = False
    ut_pos:        int  = 0
    sar_bull:      bool = False
    smc_swing:     int  = 0
    smc_internal:  int  = 0
    market_bias:   str  = "BULL"
    in_ob_zone:    bool = False
    rr_ratio: float = 2.0


def _ema(s, p):
    return s.ewm(span=p, adjust=False).mean()

def _sma(s, p):
    return s.rolling(p, min_periods=1).mean()

def _stdev(s, p):
    return s.rolling(p, min_periods=1).std(ddof=0)

def _atr(df, p=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(span=p, adjust=False).mean()

def _rsi(close, p=14):
    d = close.diff()
    g = d.clip(lower=0).ewm(span=p, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=p, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def supertrend_ai(df, atr_p=10, factor=3.0):
    if len(df) < atr_p + 2:
        return {"is_bull": True, "os": 1}
    atr  = _atr(df, atr_p)
    hl2  = (df["high"] + df["low"]) / 2
    upper = hl2 + factor * atr
    lower = hl2 - factor * atr
    os = 1
    upper_st = float(upper.iloc[0])
    lower_st = float(lower.iloc[0])
    for i in range(1, len(df)):
        c  = float(df["close"].iloc[i])
        c1 = float(df["close"].iloc[i-1])
        u  = float(upper.iloc[i])
        lo = float(lower.iloc[i])
        upper_st = min(u, upper_st) if c1 < upper_st else u
        lower_st = max(lo, lower_st) if c1 > lower_st else lo
        if   c > upper_st: os = 1
        elif c < lower_st: os = 0
    return {"is_bull": os == 1, "os": os}


def ut_bot(df, key_val=1.0, atr_per=10):
    if len(df) < atr_per + 3:
        return {"ut_pos": 0}
    close = df["close"]
    atr   = _atr(df, atr_per)
    trail = float(close.iloc[0])
    ut_pos = 0
    for i in range(1, len(df)):
        c  = float(close.iloc[i])
        c1 = float(close.iloc[i-1])
        t1 = trail
        nl = float(atr.iloc[i]) * key_val
        if   c > t1 and c1 > t1: trail = max(t1, c - nl)
        elif c < t1 and c1 < t1: trail = min(t1, c + nl)
        elif c > t1: trail = c - nl
        else:        trail = c + nl
        if   c1 < t1 and c > trail: ut_pos = 1
        elif c1 > t1 and c < trail: ut_pos = -1
    return {"ut_pos": ut_pos}


def parabolic_sar(df, start=0.02, inc=0.02, max_af=0.2):
    if len(df) < 3:
        return {"sar_bull": True}
    high  = df["high"].values
    low   = df["low"].values
    bull  = True; af = start; ep = high[0]; sar = low[0]
    for i in range(1, len(df)):
        if bull:
            sar = sar + af * (ep - sar)
            sar = min(sar, low[i-1], low[max(0, i-2)])
            if low[i] < sar:
                bull = False; sar = ep; ep = low[i]; af = start
            elif high[i] > ep:
                ep = high[i]; af = min(af + inc, max_af)
        else:
            sar = sar + af * (ep - sar)
            sar = max(sar, high[i-1], high[max(0, i-2)])
            if high[i] > sar:
                bull = True; sar = ep; ep = high[i]; af = start
            elif low[i] < ep:
                ep = low[i]; af = min(af + inc, max_af)
    return {"sar_bull": bull}


def smc_structure(df, swing_len=50, internal_len=5):
    if len(df) < swing_len + 2:
        return {"swing_bias": 0, "internal_bias": 0, "has_bos": False, "has_choch": False}
    close = df["close"]; high = df["high"]; low = df["low"]

    sh = high.rolling(swing_len * 2 + 1, center=True, min_periods=1).max()
    sl = low.rolling(swing_len * 2 + 1, center=True, min_periods=1).min()
    sh_mask = (high == sh)
    sl_mask = (low  == sl)

    swing_highs = high[sh_mask].dropna()
    swing_lows  = low[sl_mask].dropna()

    swing_bias = 0; has_bos = False; has_choch = False
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        cur    = float(close.iloc[-1])
        last_h = float(swing_highs.iloc[-1]); prev_h = float(swing_highs.iloc[-2])
        last_l = float(swing_lows.iloc[-1]);  prev_l = float(swing_lows.iloc[-2])
        if cur > last_h:
            swing_bias = 1;  has_bos = True
        elif cur < last_l:
            swing_bias = -1; has_bos = True
        elif last_h < prev_h and last_l > prev_l:
            swing_bias = -1; has_choch = True
        elif last_h > prev_h and last_l < prev_l:
            swing_bias = 1;  has_choch = True
        else:
            swing_bias = 1 if last_h > prev_h else -1

    sh_i = high.rolling(internal_len * 2 + 1, center=True, min_periods=1).max()
    sl_i = low.rolling(internal_len * 2 + 1, center=True, min_periods=1).min()
    ih = high[high == sh_i].dropna()
    il = low[low   == sl_i].dropna()
    internal_bias = 0
    if len(ih) >= 2 and len(il) >= 2:
        cur = float(close.iloc[-1])
        if   cur > float(ih.iloc[-1]): internal_bias = 1
        elif cur < float(il.iloc[-1]): internal_bias = -1
        else: internal_bias = 1 if float(ih.iloc[-1]) > float(ih.iloc[-2]) else -1

    return {"swing_bias": swing_bias, "internal_bias": internal_bias,
            "has_bos": has_bos, "has_choch": has_choch}


def rsi_mtf_dir(df, rsi_len=14, lookback=3, threshold=1.5):
    if df is None or len(df) < rsi_len + lookback + 1:
        return 0, 50.0
    rsi  = _rsi(df["close"], rsi_len)
    cur  = float(rsi.iloc[-1])
    prev = float(rsi.iloc[-1 - lookback]) if len(rsi) > lookback else float(rsi.iloc[0])
    diff = cur - prev
    d = 1 if diff > threshold else (-1 if diff < -threshold else 0)
    return d, round(cur, 1)


def zone_classification(df, swing_len=50):
    if len(df) < swing_len:
        return {"zone": "EQ", "pct": 50.0, "in_premium": False, "in_discount": False}
    window    = df.tail(swing_len * 2)
    top       = float(window["high"].max())
    bot       = float(window["low"].min())
    z_range   = top - bot
    cur       = float(df["close"].iloc[-1])
    if z_range <= 0:
        return {"zone": "EQ", "pct": 50.0, "in_premium": False, "in_discount": False,
                "swing_top": top, "swing_bot": bot}
    pct       = (cur - bot) / z_range * 100
    prem_line = top - 0.05 * z_range
    disc_line = bot + 0.05 * z_range
    eq_high   = bot + 0.525 * z_range
    eq_low    = bot + 0.475 * z_range
    in_prem   = cur >= prem_line
    in_disc   = cur <= disc_line
    if   in_prem:       zone = "PREM"
    elif in_disc:       zone = "DISC"
    elif cur >= eq_high: zone = "EQ+"
    elif cur <= eq_low:  zone = "EQ-"
    else:               zone = "EQ"
    return {"zone": zone, "pct": round(pct, 1),
            "in_premium": in_prem, "in_discount": in_disc,
            "swing_top": top, "swing_bot": bot}


def _tf_bull_score(st_bull, ut_pos, sar_bull, smc_swing):
    return int(st_bull) + int(ut_pos == 1) + int(sar_bull) + int(smc_swing == 1)

def _tf_bear_score(st_bull, ut_pos, sar_bull, smc_swing):
    return int(not st_bull) + int(ut_pos == -1) + int(not sar_bull) + int(smc_swing == -1)


def sxl_confluences(df):
    c = df["close"]; h = df["high"]; lo = df["low"]
    e1 = float(_ema(c, 20).iloc[-1]); e2 = float(_ema(c, 50).iloc[-1]); e3 = float(_ema(c, 200).iloc[-1])
    rsi_s = _rsi(c, 14); cr = float(rsi_s.iloc[-1])
    bb_b  = float(_sma(c, 20).iloc[-1]); bb_d = float(_stdev(c, 20).iloc[-1]) * 2.0
    mom   = c - c.shift(4); cm = float(mom.iloc[-1]); pm = float(mom.iloc[-2]) if len(mom) > 2 else 0.0
    n = len(df) - 1
    def bfvg(i):
        if i < 2: return False
        g = float(lo.iloc[i]) - float(h.iloc[i-2])
        return g > 0 and g / float(c.iloc[i]) * 100 >= 0.05
    def sfvg(i):
        if i < 2: return False
        g = float(lo.iloc[i-2]) - float(h.iloc[i])
        return g > 0 and g / float(c.iloc[i]) * 100 >= 0.05
    has_bfvg = any(bfvg(n - j) for j in [1,2,3] if n-j >= 0)
    has_sfvg = any(sfvg(n - j) for j in [1,2,3] if n-j >= 0)
    cv = float(c.iloc[-1])
    lc1 = e1>e2 and e2>e3; lc2 = cv < bb_b - bb_d*0.3; lc3 = cr>40 and cr<65; lc4 = has_bfvg; lc5 = cm>0 and cm>pm
    sc1 = e1<e2 and e2<e3; sc2 = cv > bb_b + bb_d*0.3; sc3 = cr<60 and cr>35; sc4 = has_sfvg; sc5 = cm<0 and cm<pm
    return {"lc1":lc1,"lc2":lc2,"lc3":lc3,"lc4":lc4,"lc5":lc5,
            "sc1":sc1,"sc2":sc2,"sc3":sc3,"sc4":sc4,"sc5":sc5,
            "l_score": sum([lc1,lc2,lc3,lc4,lc5]),
            "s_score": sum([sc1,sc2,sc3,sc4,sc5])}


def volume_balance(df, lookback=100):
    t  = df.tail(lookback); ib = t["close"] >= t["open"]
    bv = t.loc[ib,  "volume"].sum(); sv = t.loc[~ib, "volume"].sum()
    tot = bv + sv
    if tot == 0: return {"bull_pct": 50.0, "bear_pct": 50.0}
    return {"bull_pct": round(bv/tot*100,1), "bear_pct": round(sv/tot*100,1)}


def spike_detector(df, atr_series, pct_thresh=3.0, atr_mult=2.5):
    close = df["close"]; body = abs(float(close.iloc[-1]) - float(df["open"].iloc[-1]))
    prev  = float(close.iloc[-2]) if len(close) > 1 else float(close.iloc[-1])
    cur   = float(close.iloc[-1]); atr_v = float(atr_series.iloc[-1])
    chg   = abs(cur - prev) / prev * 100.0 if prev != 0 else 0.0
    spk   = chg >= pct_thresh or (atr_v > 0 and body >= atr_v * atr_mult)
    return {"is_spike": spk,
            "spike_direction": ("BULL" if cur > prev else "BEAR") if spk else "",
            "spike_pct": round(chg, 1)}


def leverage_advisor(atr_val, price, sl_mult=1.5):
    atr_pct = (atr_val / price * 100.0) if price > 0 else 0.0
    raw     = round(2.0 / (sl_mult * atr_pct)) if atr_pct > 0 else 1
    lev     = next((s for s in [20,15,10,7,5,3,2,1] if raw >= s), 1)
    risk    = ("🟢 Thap" if lev>=15 else "🟡 Trung binh" if lev>=7 else "🟠 Cao" if lev>=3 else "🔴 Rat cao")
    return {"leverage": lev, "lev_risk": risk, "atr_pct": round(atr_pct, 3)}


def reversal_candles(df, pin_ratio=2.0, doji_pct=0.05):
    if len(df) < 3: return {"rc_bull": False, "rc_bear": False, "rc_tags": []}
    c=df["close"]; o=df["open"]; h=df["high"]; lo=df["low"]
    bull_c = float(c.iloc[-1]) > float(o.iloc[-1]); bear_c = not bull_c
    body = abs(float(c.iloc[-1]) - float(o.iloc[-1]))
    rng  = float(h.iloc[-1]) - float(lo.iloc[-1])
    uw   = float(h.iloc[-1]) - max(float(c.iloc[-1]), float(o.iloc[-1]))
    lw   = min(float(c.iloc[-1]), float(o.iloc[-1])) - float(lo.iloc[-1])
    tags = []
    if bear_c and float(c.iloc[-2])>float(o.iloc[-2]) and float(c.iloc[-1])<float(o.iloc[-2]) and float(o.iloc[-1])>float(c.iloc[-2]): tags.append("Engulf down")
    if bull_c and float(c.iloc[-2])<float(o.iloc[-2]) and float(c.iloc[-1])>float(o.iloc[-2]) and float(o.iloc[-1])<float(c.iloc[-2]): tags.append("Engulf up")
    if body > 0:
        if lw >= body*pin_ratio and uw <= body*0.5: tags.append("Hammer")
        if uw >= body*pin_ratio and lw <= body*0.5: tags.append("ShootStar")
    if rng > 0 and body/rng <= doji_pct: tags.append("Doji")
    if len(df) >= 3:
        b2 = abs(float(c.iloc[-3]) - float(o.iloc[-3])); b1 = abs(float(c.iloc[-2]) - float(o.iloc[-2]))
        mid = (float(o.iloc[-3]) + float(c.iloc[-3])) / 2
        if float(c.iloc[-3]) < float(o.iloc[-3]) and b2 > b1*2 and bull_c and float(c.iloc[-1]) > mid: tags.append("MorningStar")
        if float(c.iloc[-3]) > float(o.iloc[-3]) and b2 > b1*2 and bear_c and float(c.iloc[-1]) < mid: tags.append("EveningStar")
    rc_bull = any(t in ["Engulf up","Hammer","MorningStar"] for t in tags)
    rc_bear = any(t in ["Engulf down","ShootStar","EveningStar"] for t in tags)
    return {"rc_bull": rc_bull, "rc_bear": rc_bear, "rc_tags": tags}


def score_symbol(symbol, df_5m, df_15m, df_1h,
                 df_30m=None, df_4h=None, df_1d=None,
                 sl_mult=1.5, tp1_mult=1.5, tp2_mult=3.0):

    if df_30m is None: df_30m = df_15m
    if df_4h  is None: df_4h  = df_1h
    if df_1d  is None: df_1d  = df_1h

    reasons   = []
    close_val = float(df_5m["close"].iloc[-1])
    atr_s     = _atr(df_5m, 14)
    atr_val   = float(atr_s.iloc[-1])

    # Core indicators on 5m
    st   = supertrend_ai(df_5m)
    ut   = ut_bot(df_5m)
    sar  = parabolic_sar(df_5m)
    smc  = smc_structure(df_5m)
    zone = zone_classification(df_5m)

    st_ai_bull   = st["is_bull"]
    ut_pos_cur   = ut["ut_pos"]
    sar_bull_cur = sar["sar_bull"]
    smc_swing    = smc["swing_bias"]
    smc_int      = smc["internal_bias"]

    def _tf_sigs(df):
        if df is None or len(df) < 15:
            return st_ai_bull, ut_pos_cur, sar_bull_cur, smc_swing
        return (supertrend_ai(df)["is_bull"], ut_bot(df)["ut_pos"],
                parabolic_sar(df)["sar_bull"], smc_structure(df)["swing_bias"])

    st5, ut5, sar5, smc5     = st_ai_bull, ut_pos_cur, sar_bull_cur, smc_swing
    st30, ut30, sar30, smc30 = _tf_sigs(df_30m)
    st1h, ut1h, sar1h, smc1h = _tf_sigs(df_1h)
    st4h, ut4h, sar4h, smc4h = _tf_sigs(df_4h)
    st1d, ut1d, sar1d, smc1d = _tf_sigs(df_1d)

    b5   = _tf_bull_score(st5,  ut5,  sar5,  smc5)
    s5   = _tf_bear_score(st5,  ut5,  sar5,  smc5)
    b30  = _tf_bull_score(st30, ut30, sar30, smc30)
    s30  = _tf_bear_score(st30, ut30, sar30, smc30)
    b1h  = _tf_bull_score(st1h, ut1h, sar1h, smc1h)
    s1h  = _tf_bear_score(st1h, ut1h, sar1h, smc1h)
    b4h  = _tf_bull_score(st4h, ut4h, sar4h, smc4h)
    s4h  = _tf_bear_score(st4h, ut4h, sar4h, smc4h)
    b1d  = _tf_bull_score(st1d, ut1d, sar1d, smc1d)
    s1d  = _tf_bear_score(st1d, ut1d, sar1d, smc1d)

    mtm_bull = b5  >= 3;  mtm_bear = s5  >= 3
    brg_bull = b30 >= 3;  brg_bear = s30 >= 3
    ctx_bull = b1h >= 3 and b4h >= 3 and b1d >= 3
    ctx_bear = s1h >= 3 and s4h >= 3 and s1d >= 3

    # RSI MTF
    rsi_dirs = []
    rsi_vals = []
    for df_tf in [df_5m, df_15m, df_30m, df_1h, df_4h, df_1d]:
        d, v = rsi_mtf_dir(df_tf)
        rsi_dirs.append(d); rsi_vals.append(v)
    rsi_bull_cnt = sum(1 for d in rsi_dirs if d ==  1)
    rsi_bear_cnt = sum(1 for d in rsi_dirs if d == -1)
    rsi_cur      = rsi_vals[0]

    # Zone
    in_prem = zone["in_premium"]; in_disc = zone["in_discount"]

    # BUY checklist /6
    ck_sw_b  = smc_swing == 1
    ck_in_b  = smc_int   == 1
    ck_st_b  = st_ai_bull
    ck_ut_b  = ut_pos_cur == 1
    ck_sar_b = sar_bull_cur
    ck_z_b   = not in_prem
    buy_core = sum([ck_sw_b, ck_in_b, ck_st_b, ck_ut_b, ck_sar_b, ck_z_b])

    # SELL checklist /6
    ck_sw_s  = smc_swing == -1
    ck_in_s  = smc_int   == -1
    ck_st_s  = not st_ai_bull
    ck_ut_s  = ut_pos_cur == -1
    ck_sar_s = not sar_bull_cur
    ck_z_s   = not in_disc
    sell_core = sum([ck_sw_s, ck_in_s, ck_st_s, ck_ut_s, ck_sar_s, ck_z_s])

    # Total /11
    buy_total  = buy_core  + (2 if ctx_bull else 0) + (1 if brg_bull else 0) + (1 if mtm_bull else 0) + (1 if rsi_bull_cnt >= 4 else 0)
    sell_total = sell_core + (2 if ctx_bear else 0) + (1 if brg_bear else 0) + (1 if mtm_bear else 0) + (1 if rsi_bear_cnt >= 4 else 0)

    # Verdict
    if   buy_total  >= 9: verdict = "STRONG BUY"
    elif buy_total  >= 7: verdict = "BUY"
    elif sell_total >= 9: verdict = "STRONG SELL"
    elif sell_total >= 7: verdict = "SELL"
    elif buy_total  >= 5: verdict = "LEAN BUY"
    elif sell_total >= 5: verdict = "LEAN SELL"
    else:                 verdict = "NEUTRAL"

    if   buy_total  >= 9: tip = "BOS break + SAR flip -> BUY"
    elif buy_total  >= 7: tip = "Pullback OB/FVG -> BUY"
    elif sell_total >= 9: tip = "BOS break + SAR flip -> SELL"
    elif sell_total >= 7: tip = "Retest OB/FVG -> SELL"
    elif buy_total  >= 5: tip = f"Can {7-buy_total} them (BUY)"
    elif sell_total >= 5: tip = f"Can {7-sell_total} them (SELL)"
    else:                 tip = "Cho — chua du dieu kien"

    # Direction
    if   buy_total  >= 7: direction = "LONG"
    elif sell_total >= 7: direction = "SHORT"
    elif buy_total  > sell_total and buy_total  >= 5: direction = "LONG"
    elif sell_total > buy_total  and sell_total >= 5: direction = "SHORT"
    else: direction = "NEUTRAL"

    # SXL
    sxl  = sxl_confluences(df_5m)
    l_sc = sxl["l_score"]; s_sc = sxl["s_score"]

    sxl_tags = []
    if direction == "LONG":
        if sxl["lc1"]: sxl_tags.append("EMA Stack Up")
        if sxl["lc2"]: sxl_tags.append("BB Pullback")
        if sxl["lc3"]: sxl_tags.append("RSI Zone Bull")
        if sxl["lc4"]: sxl_tags.append("FVG Bull")
        if sxl["lc5"]: sxl_tags.append("Momentum Up")
    else:
        if sxl["sc1"]: sxl_tags.append("EMA Stack Dn")
        if sxl["sc2"]: sxl_tags.append("BB Reject")
        if sxl["sc3"]: sxl_tags.append("RSI Zone Bear")
        if sxl["sc4"]: sxl_tags.append("FVG Bear")
        if sxl["sc5"]: sxl_tags.append("Momentum Dn")

    # Vol / Spike / Lev / RC
    vb       = volume_balance(df_5m)
    spk      = spike_detector(df_5m, atr_s)
    lev      = leverage_advisor(atr_val, close_val, sl_mult)
    rc       = reversal_candles(df_5m)
    bull_pct = vb["bull_pct"]; bear_pct = vb["bear_pct"]
    vol_conf = (direction=="LONG" and bull_pct>bear_pct) or (direction=="SHORT" and bear_pct>bull_pct)
    in_ob    = zone["zone"] in ("DISC","EQ-") if direction=="LONG" else zone["zone"] in ("PREM","EQ+")
    is_prem  = in_ob and ((direction=="LONG" and smc_swing==1) or (direction=="SHORT" and smc_swing==-1))

    # Reasons
    if direction == "LONG":
        if ck_st_b:  reasons.append("ST_AI Bull")
        if ck_ut_b:  reasons.append("UT_Bot Long")
        if ck_sar_b: reasons.append("SAR Bull")
        if ck_sw_b:  reasons.append("SMC Swing Bull")
        if ck_in_b:  reasons.append("SMC Internal Bull")
        if smc["has_bos"]:   reasons.append("BOS Up")
        if smc["has_choch"]: reasons.append("CHoCH Up")
    elif direction == "SHORT":
        if ck_st_s:  reasons.append("ST_AI Bear")
        if ck_ut_s:  reasons.append("UT_Bot Short")
        if ck_sar_s: reasons.append("SAR Bear")
        if ck_sw_s:  reasons.append("SMC Swing Bear")
        if ck_in_s:  reasons.append("SMC Internal Bear")
        if smc["has_bos"]:   reasons.append("BOS Down")
        if smc["has_choch"]: reasons.append("CHoCH Down")

    if ctx_bull: reasons.append("MTF 1h+4h+1d Bull")
    elif ctx_bear: reasons.append("MTF 1h+4h+1d Bear")
    if brg_bull: reasons.append("MTF 30m Bull")
    elif brg_bear: reasons.append("MTF 30m Bear")
    if mtm_bull: reasons.append("MTF 5m Bull")
    elif mtm_bear: reasons.append("MTF 5m Bear")
    if rsi_bull_cnt >= 4: reasons.append(f"RSI MTF Bull {rsi_bull_cnt}/6")
    if rsi_bear_cnt >= 4: reasons.append(f"RSI MTF Bear {rsi_bear_cnt}/6")
    reasons += sxl_tags[:3]
    reasons.append(f"Zone:{zone['zone']} {zone['pct']:.0f}%")
    if spk["is_spike"]: reasons.append(f"Spike {spk['spike_direction']} {spk['spike_pct']}%")
    if in_ob and rc["rc_tags"]: reasons.append(rc["rc_tags"][0])

    # SL/TP
    if direction == "LONG":
        sl = close_val - sl_mult * atr_val
        tp1 = close_val + tp1_mult * atr_val
        tp2 = close_val + tp2_mult * atr_val
    elif direction == "SHORT":
        sl = close_val + sl_mult * atr_val
        tp1 = close_val - tp1_mult * atr_val
        tp2 = close_val - tp2_mult * atr_val
    else:
        sl = close_val - sl_mult * atr_val
        tp1 = close_val + tp1_mult * atr_val
        tp2 = close_val + tp2_mult * atr_val

    def _arrow(bull, bear): return "Up" if bull >= 3 else ("Dn" if bear >= 3 else "=")

    if direction == "LONG":
        cl_sc = buy_core; ck_st=ck_st_b; ck_ut=ck_ut_b; ck_sar_=ck_sar_b; ck_sw=ck_sw_b; ck_in=ck_in_b; ck_z=ck_z_b
    else:
        cl_sc = sell_core; ck_st=ck_st_s; ck_ut=ck_ut_s; ck_sar_=ck_sar_s; ck_sw=ck_sw_s; ck_in=ck_in_s; ck_z=ck_z_s

    return SignalResult(
        symbol=symbol, score=max(buy_total, sell_total),
        direction=direction, price=round(close_val,6),
        sl=round(sl,6), tp1=round(tp1,6), tp2=round(tp2,6),
        reasons=reasons, timeframe="5m",
        buy_score=buy_total, sell_score=sell_total,
        verdict=verdict, entry_tip=tip,
        ck_st_ai=ck_st, ck_ut_bot=ck_ut, ck_sar=ck_sar_,
        ck_smc_swing=ck_sw, ck_smc_int=ck_in, ck_zone=ck_z,
        checklist_score=cl_sc,
        mtf_momentum=_arrow(b5,s5), mtf_bridge=_arrow(b30,s30),
        mtf_context=_arrow(b1h and b4h and b1d, s1h and s4h and s1d),
        rsi_val=rsi_cur, rsi_bull_count=rsi_bull_cnt, rsi_bear_count=rsi_bear_cnt,
        zone_txt=zone["zone"], zone_pct=zone["pct"],
        l_score=l_sc, s_score=s_sc, is_premium=is_prem,
        bull_pct=bull_pct, bear_pct=bear_pct, vol_confirm=vol_conf,
        is_spike=spk["is_spike"], spike_direction=spk["spike_direction"], spike_pct=spk["spike_pct"],
        leverage=lev["leverage"], lev_risk=lev["lev_risk"], atr_pct=lev["atr_pct"],
        st_ai_bull=st_ai_bull, ut_pos=ut_pos_cur, sar_bull=sar_bull_cur,
        smc_swing=smc_swing, smc_internal=smc_int,
        market_bias="BULL" if smc_swing >= 0 else "BEAR",
        in_ob_zone=in_ob, rr_ratio=round(tp2_mult/sl_mult, 1),
    )
