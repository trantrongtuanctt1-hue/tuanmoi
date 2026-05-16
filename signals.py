"""
Signal calculator - port of 15M ULTRA Pine Script logic
Calculates: ST AI (simplified), UT Bot, SAR, RSI MTF, SMC bias → Score /11
"""

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─────────────────────────────────────────────────────────────────────────────
# SUPERTREND (simplified best-factor version)
# ─────────────────────────────────────────────────────────────────────────────

def supertrend(high, low, close, factor=3.0, period=10):
    _atr  = atr(high, low, close, period)
    hl2   = (high + low) / 2
    upper = hl2 + factor * _atr
    lower = hl2 - factor * _atr

    trend  = pd.Series(1, index=close.index)
    upper_ = upper.copy()
    lower_ = lower.copy()

    for i in range(1, len(close)):
        prev_upper = upper_.iloc[i-1]
        prev_lower = lower_.iloc[i-1]
        prev_close = close.iloc[i-1]

        upper_.iloc[i] = upper.iloc[i] if prev_close < prev_upper else min(upper.iloc[i], prev_upper)
        lower_.iloc[i] = lower.iloc[i] if prev_close > prev_lower else max(lower.iloc[i], prev_lower)

        if close.iloc[i] > prev_upper:
            trend.iloc[i] = 1
        elif close.iloc[i] < prev_lower:
            trend.iloc[i] = 0
        else:
            trend.iloc[i] = trend.iloc[i-1]

    trail = np.where(trend == 1, lower_, upper_)
    return pd.Series(trend.values, index=close.index), pd.Series(trail, index=close.index)


# ─────────────────────────────────────────────────────────────────────────────
# UT BOT
# ─────────────────────────────────────────────────────────────────────────────

def ut_bot(close, key_val=1.0, atr_period=10):
    _atr   = atr(close, close, close, atr_period)  # simplified: use close as HL proxy
    n_loss = key_val * _atr

    trail  = close.copy() * np.nan
    pos    = pd.Series(0, index=close.index)

    for i in range(1, len(close)):
        src      = close.iloc[i]
        src_prev = close.iloc[i-1]
        t_prev   = trail.iloc[i-1] if not np.isnan(trail.iloc[i-1]) else src

        if src > t_prev and src_prev > t_prev:
            trail.iloc[i] = max(t_prev, src - n_loss.iloc[i])
        elif src < t_prev and src_prev < t_prev:
            trail.iloc[i] = min(t_prev, src + n_loss.iloc[i])
        elif src > t_prev:
            trail.iloc[i] = src - n_loss.iloc[i]
        else:
            trail.iloc[i] = src + n_loss.iloc[i]

        if src_prev < trail.iloc[i-1] and src > trail.iloc[i]:
            pos.iloc[i] =  1
        elif src_prev > trail.iloc[i-1] and src < trail.iloc[i]:
            pos.iloc[i] = -1
        else:
            pos.iloc[i] = pos.iloc[i-1]

    return pos, trail


# ─────────────────────────────────────────────────────────────────────────────
# PARABOLIC SAR
# ─────────────────────────────────────────────────────────────────────────────

def parabolic_sar(high, low, start=0.02, increment=0.02, maximum=0.2):
    sar  = low.copy()
    bull = pd.Series(True, index=high.index)
    af   = start
    ep   = high.iloc[0]

    for i in range(1, len(high)):
        prev_sar  = sar.iloc[i-1]
        prev_bull = bull.iloc[i-1]

        if prev_bull:
            sar.iloc[i] = prev_sar + af * (ep - prev_sar)
            sar.iloc[i] = min(sar.iloc[i], low.iloc[i-1], low.iloc[i-2] if i >= 2 else low.iloc[i-1])
            if low.iloc[i] < sar.iloc[i]:
                bull.iloc[i] = False
                sar.iloc[i]  = ep
                ep = low.iloc[i]
                af = start
            else:
                bull.iloc[i] = True
                if high.iloc[i] > ep:
                    ep = high.iloc[i]
                    af = min(af + increment, maximum)
        else:
            sar.iloc[i] = prev_sar + af * (ep - prev_sar)
            sar.iloc[i] = max(sar.iloc[i], high.iloc[i-1], high.iloc[i-2] if i >= 2 else high.iloc[i-1])
            if high.iloc[i] > sar.iloc[i]:
                bull.iloc[i] = True
                sar.iloc[i]  = ep
                ep = high.iloc[i]
                af = start
            else:
                bull.iloc[i] = False
                if low.iloc[i] < ep:
                    ep = low.iloc[i]
                    af = min(af + increment, maximum)

    return bull, sar


# ─────────────────────────────────────────────────────────────────────────────
# SMC BIAS (simplified: using swing high/low structure)
# ─────────────────────────────────────────────────────────────────────────────

def smc_bias(high, low, close, swing_len=50):
    """Returns +1 (bullish), -1 (bearish), 0 (neutral)"""
    n      = len(close)
    bias   = pd.Series(0, index=close.index)
    window = min(swing_len, n // 2)

    for i in range(window, n):
        segment_h = high.iloc[i-window:i]
        segment_l = low.iloc[i-window:i]
        recent_h  = high.iloc[i-5:i].mean()
        recent_l  = low.iloc[i-5:i].mean()

        if recent_h > segment_h.mean() and recent_l > segment_l.mean():
            bias.iloc[i] = 1
        elif recent_h < segment_h.mean() and recent_l < segment_l.mean():
            bias.iloc[i] = -1

    return bias


# ─────────────────────────────────────────────────────────────────────────────
# RSI DIRECTION (multi-TF — called per TF df externally)
# ─────────────────────────────────────────────────────────────────────────────

def rsi_dir(rsi_series, lookback=3, threshold=1.5):
    cur  = rsi_series.iloc[-1]
    prev = rsi_series.iloc[-1 - lookback]
    diff = cur - prev
    if diff > threshold:
        return 1
    elif diff < -threshold:
        return -1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# MASTER SCORE (mirrors Pine Script Section M + N)
# ─────────────────────────────────────────────────────────────────────────────

def compute_score(dfs: dict) -> dict:
    """
    dfs: {
        '5m': df_5m, '15m': df_15m, '30m': df_30m,
        '1h': df_1h, '4h': df_4h, '1d': df_1d
    }
    Each df must have columns: open, high, low, close, volume
    Returns dict with buy_score, sell_score, total_buy, total_sell, signals
    """

    def _calc(df):
        h, l, c = df['high'], df['low'], df['close']
        st_trend, _  = supertrend(h, l, c, factor=3.0, period=10)
        ut_pos,   _  = ut_bot(c, key_val=1.0, atr_period=10)
        sar_bull, _  = parabolic_sar(h, l)
        smc          = smc_bias(h, l, c)
        rsi_s        = rsi(c, 14)
        return {
            'st':  int(st_trend.iloc[-1]),     # 1=bull 0=bear
            'ut':  int(ut_pos.iloc[-1]),        # 1 / -1 / 0
            'sar': bool(sar_bull.iloc[-1]),
            'smc': int(smc.iloc[-1]),           # +1 / -1 / 0
            'rsi': rsi_s,
        }

    results = {tf: _calc(df) for tf, df in dfs.items()}
    base    = results['15m']

    # ── 6 core conditions (Section M) ────────────────────────────────────
    ck_st_bull  = base['st']  == 1
    ck_st_bear  = base['st']  == 0
    ck_ut_bull  = base['ut']  == 1
    ck_ut_bear  = base['ut']  == -1
    ck_sar_bull = base['sar']
    ck_sar_bear = not base['sar']
    ck_smc_bull = base['smc'] == 1
    ck_smc_bear = base['smc'] == -1

    buy_score  = sum([ck_smc_bull, ck_st_bull, ck_ut_bull, ck_sar_bull, ck_smc_bull])
    sell_score = sum([ck_smc_bear, ck_st_bear, ck_ut_bear, ck_sar_bear, ck_smc_bear])

    # ── MTF score bonus (mirrors Section L logic) ─────────────────────────
    def _tf_bull(r):
        return (1 if r['st'] == 1 else 0) + (1 if r['ut'] == 1 else 0) + \
               (1 if r['sar'] else 0)     + (1 if r['smc'] == 1 else 0)

    def _tf_bear(r):
        return (1 if r['st'] == 0 else 0) + (1 if r['ut'] == -1 else 0) + \
               (0 if r['sar'] else 1)     + (1 if r['smc'] == -1 else 0)

    mtm_bull = _tf_bull(results['5m'])  >= 3
    mtm_bear = _tf_bear(results['5m'])  >= 3
    brg_bull = _tf_bull(results['30m']) >= 3
    brg_bear = _tf_bear(results['30m']) >= 3
    ctx_bull = (_tf_bull(results['1h']) >= 3 and
                _tf_bull(results['4h']) >= 3 and
                _tf_bull(results['1d']) >= 3)
    ctx_bear = (_tf_bear(results['1h']) >= 3 and
                _tf_bear(results['4h']) >= 3 and
                _tf_bear(results['1d']) >= 3)

    # ── RSI MTF count ─────────────────────────────────────────────────────
    rsi_bull_count = sum(
        rsi_dir(results[tf]['rsi']) == 1
        for tf in ['5m','15m','30m','1h','4h','1d']
    )
    rsi_bear_count = sum(
        rsi_dir(results[tf]['rsi']) == -1
        for tf in ['5m','15m','30m','1h','4h','1d']
    )

    total_buy  = buy_score  + (2 if ctx_bull else 0) + (1 if brg_bull else 0) + \
                 (1 if mtm_bull else 0) + (1 if rsi_bull_count >= 4 else 0)
    total_sell = sell_score + (2 if ctx_bear else 0) + (1 if brg_bear else 0) + \
                 (1 if mtm_bear else 0) + (1 if rsi_bear_count >= 4 else 0)

    # ── Verdict ───────────────────────────────────────────────────────────
    if total_buy >= 9:
        verdict, emoji = 'STRONG BUY',  '🚀'
    elif total_buy >= 7:
        verdict, emoji = 'BUY',         '✅'
    elif total_sell >= 9:
        verdict, emoji = 'STRONG SELL', '🔻'
    elif total_sell >= 7:
        verdict, emoji = 'SELL',        '✅'
    elif total_buy >= 5:
        verdict, emoji = 'LEAN BUY',    '↑'
    elif total_sell >= 5:
        verdict, emoji = 'LEAN SELL',   '↓'
    else:
        verdict, emoji = 'NEUTRAL',     '⏳'

    return {
        'buy_score':  buy_score,
        'sell_score': sell_score,
        'total_buy':  total_buy,
        'total_sell': total_sell,
        'verdict':    verdict,
        'emoji':      emoji,
        'mtf': {
            'momentum_bull': mtm_bull,
            'momentum_bear': mtm_bear,
            'bridge_bull':   brg_bull,
            'bridge_bear':   brg_bear,
            'context_bull':  ctx_bull,
            'context_bear':  ctx_bear,
        },
        'rsi_bull': rsi_bull_count,
        'rsi_bear': rsi_bear_count,
        'checklist': {
            'st':  '▲' if ck_st_bull  else '▼',
            'ut':  '▲' if ck_ut_bull  else ('▼' if ck_ut_bear else '●'),
            'sar': '▲' if ck_sar_bull else '▼',
            'smc': '▲' if ck_smc_bull else ('▼' if ck_smc_bear else '●'),
        },
        'close': base.get('close_price', 0),
    }
