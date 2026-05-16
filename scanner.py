"""
scanner.py — Async OKX scanner, MTF analysis, scoring logic
Tái hiện hoàn toàn logic từ:
  • SXL Sniper + MSB-OB + Vol Balance
  • 15M ULTRA — ST AI + UT Bot + SMC + SAR + RSI + MTF
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import ccxt.async_support as ccxt
import numpy as np
import pandas as pd

from config import *
from indicators import (
    calc_ema, calc_rsi, calc_atr, calc_bollinger,
    calc_supertrend, calc_ut_bot, calc_psar,
    calc_volume_balance, has_recent_fvg,
    rsi_direction, tf_score_bull, tf_score_bear,
)

logger = logging.getLogger(__name__)


# ── Signal dataclass ──────────────────────────────────────────────────────
@dataclass
class SignalResult:
    symbol:       str
    score_buy:    int
    score_sell:   int
    verdict:      str
    emoji:        str
    price:        float
    atr:          float
    atr_pct:      float
    rsi:          float
    bull_vol:     float
    bear_vol:     float
    # 15M checklist
    st_bull:      bool
    ut_bull:      bool
    sar_bull:     bool
    ema_bull:     bool   # EMA20 > EMA50 > EMA200
    fvg_bull:     bool
    fvg_bear:     bool
    # MTF
    mtf_5m:       str
    mtf_30m:      str
    mtf_1h:       str
    mtf_4h:       str
    mtf_1d:       str
    # RSI MTF
    rsi_bull_cnt: int
    rsi_bear_cnt: int
    # R:R
    sl:           float
    tp1:          float
    tp2:          float
    rr:           float
    is_long:      bool
    timestamp:    float = field(default_factory=time.time)

    # ── Derived props ─────────────────────────────────────────────────────
    @property
    def is_strong_buy(self):  return self.score_buy  >= 9
    @property
    def is_buy(self):         return self.score_buy  >= 7
    @property
    def is_lean_buy(self):    return self.score_buy  >= 5
    @property
    def is_strong_sell(self): return self.score_sell >= 9
    @property
    def is_sell(self):        return self.score_sell >= 7
    @property
    def is_lean_sell(self):   return self.score_sell >= 5
    @property
    def best_score(self):     return max(self.score_buy, self.score_sell)

    def display_symbol(self) -> str:
        """BTC/USDT:USDT  →  BTC"""
        return self.symbol.split("/")[0]


# ── OKX Scanner class ─────────────────────────────────────────────────────
class OKXScanner:

    def __init__(self):
        self.exchange = ccxt.okx({
            "apiKey":    OKX_API_KEY,
            "secret":    OKX_SECRET,
            "password":  OKX_PASSPHRASE,
            "enableRateLimit": True,
            "rateLimit": 100,          # ms giữa requests
            "options":   {"defaultType": "swap"},
        })
        self._sem    = asyncio.Semaphore(CONCURRENCY)
        self._cache: Dict[str, Tuple[pd.DataFrame, float]] = {}

    async def close(self):
        await self.exchange.close()

    # ── Lấy danh sách cặp ────────────────────────────────────────────────
    async def get_top_pairs(self) -> List[str]:
        logger.info("Loading OKX swap markets …")
        markets = await self.exchange.load_markets()
        tickers = await self.exchange.fetch_tickers()

        pairs = []
        for sym, mkt in markets.items():
            if (mkt.get("swap")
                    and mkt.get("quote") == "USDT"
                    and mkt.get("settle") == "USDT"
                    and mkt.get("active")
                    and sym in tickers):
                vol = tickers[sym].get("quoteVolume") or 0
                if vol >= MIN_VOLUME_USDT:
                    pairs.append((sym, float(vol)))

        pairs.sort(key=lambda x: x[1], reverse=True)
        logger.info(f"Found {len(pairs)} pairs  →  capping at {MAX_PAIRS}")
        return [p[0] for p in pairs[:MAX_PAIRS]]

    # ── Fetch OHLCV với cache 60s ─────────────────────────────────────────
    async def _fetch(self, symbol: str, tf: str, limit: int = TF_BARS
                     ) -> Optional[pd.DataFrame]:
        key = f"{symbol}|{tf}"
        if key in self._cache:
            df, ts = self._cache[key]
            if time.time() - ts < 60:
                return df

        async with self._sem:
            try:
                raw = await self.exchange.fetch_ohlcv(symbol, tf, limit=limit)
                if not raw or len(raw) < 50:
                    return None
                df = pd.DataFrame(raw,
                                  columns=["ts", "open", "high", "low", "close", "volume"])
                df["ts"] = pd.to_datetime(df["ts"], unit="ms")
                df.set_index("ts", inplace=True)
                df = df.astype(float)
                self._cache[key] = (df, time.time())
                return df
            except Exception as e:
                logger.debug(f"fetch {symbol} {tf}: {e}")
                return None

    # ── Phân tích 1 TF (trả về bull_score, bear_score) ──────────────────
    def _analyze_tf(self, df: Optional[pd.DataFrame]) -> Tuple[int, int]:
        if df is None or len(df) < 60:
            return 0, 0
        c, h, l = df["close"], df["high"], df["low"]
        _, st_dir  = calc_supertrend(h, l, c, ST_PERIOD, ST_FACTOR)
        _, ut_pos  = calc_ut_bot(c, h, l, UT_KEY_VAL, UT_ATR_PERIOD)
        _, sar_b   = calc_psar(h, l, SAR_START, SAR_INC, SAR_MAX)
        e1 = calc_ema(c, EMA_FAST).iloc[-1]
        e2 = calc_ema(c, EMA_SLOW).iloc[-1]
        e3 = calc_ema(c, EMA_TREND).iloc[-1]
        ema_bull = bool(e1 > e2 > e3)
        ema_bear = bool(e1 < e2 < e3)
        sd  = int(st_dir.iloc[-1])
        up  = int(ut_pos.iloc[-1])
        sb  = bool(sar_b.iloc[-1])
        return (tf_score_bull(sd, up, sb, ema_bull),
                tf_score_bear(sd, up, sb, ema_bear))

    # ── Full phân tích 1 symbol ───────────────────────────────────────────
    async def analyze_symbol(self, symbol: str) -> Optional[SignalResult]:
        # Fetch tất cả TF cùng lúc
        dfs_list = await asyncio.gather(
            *[self._fetch(symbol, tf) for tf in TIMEFRAMES],
            return_exceptions=True
        )
        dfs: Dict[str, Optional[pd.DataFrame]] = {
            tf: (r if isinstance(r, pd.DataFrame) else None)
            for tf, r in zip(TIMEFRAMES, dfs_list)
        }

        df15 = dfs.get("15m")
        if df15 is None or len(df15) < MIN_BARS:
            return None

        c15, h15, l15, o15, v15 = (df15["close"], df15["high"],
                                    df15["low"],   df15["open"], df15["volume"])

        # ── Indicators 15M ───────────────────────────────────────────────
        _, st_dir15 = calc_supertrend(h15, l15, c15, ST_PERIOD, ST_FACTOR)
        _, ut_pos15 = calc_ut_bot(c15, h15, l15, UT_KEY_VAL, UT_ATR_PERIOD)
        _, sar_b15  = calc_psar(h15, l15, SAR_START, SAR_INC, SAR_MAX)
        rsi15       = calc_rsi(c15, RSI_PERIOD)
        atr15       = calc_atr(h15, l15, c15, ATR_PERIOD)
        e1_15       = calc_ema(c15, EMA_FAST)
        e2_15       = calc_ema(c15, EMA_SLOW)
        e3_15       = calc_ema(c15, EMA_TREND)
        _, bb_up, bb_dn = calc_bollinger(c15, BB_PERIOD, BB_MULT)
        bull_vol, bear_vol = calc_volume_balance(c15, o15, v15, VOL_LOOKBACK)
        fvg_b, fvg_be  = has_recent_fvg(h15, l15, c15)

        price  = float(c15.iloc[-1])
        atr_v  = float(atr15.iloc[-1])
        atr_p  = atr_v / price * 100 if price > 0 else 0
        rsi_v  = float(rsi15.iloc[-1])
        bvol   = float(bull_vol.iloc[-1])
        bevol  = float(bear_vol.iloc[-1])

        sd15   = int(st_dir15.iloc[-1])
        up15   = int(ut_pos15.iloc[-1])
        sb15   = bool(sar_b15.iloc[-1])
        e1v    = float(e1_15.iloc[-1])
        e2v    = float(e2_15.iloc[-1])
        e3v    = float(e3_15.iloc[-1])
        ema_b  = e1v > e2v > e3v
        ema_be = e1v < e2v < e3v

        in_premium  = price > e3v * 1.02
        in_discount = price < e3v * 0.98

        # ── SXL-style momentum (close vs close[4]) ────────────────────────
        mom = float(c15.iloc[-1] - c15.iloc[-5]) if len(c15) >= 5 else 0
        mom_acc = mom > float(c15.iloc[-1] - c15.iloc[-6]) if len(c15) >= 6 else False

        # ── Core BUY score /6 ─────────────────────────────────────────────
        ck_st_b  = sd15 == 1
        ck_ut_b  = up15 == 1
        ck_sar_b = sb15
        ck_ema_b = ema_b
        ck_pri_b = price > e2v          # price above EMA50
        ck_nprem = not in_premium

        buy_core = sum([ck_st_b, ck_ut_b, ck_sar_b, ck_ema_b, ck_pri_b, ck_nprem])

        # ── Core SELL score /6 ────────────────────────────────────────────
        ck_st_s  = sd15 == -1
        ck_ut_s  = up15 == -1
        ck_sar_s = not sb15
        ck_ema_s = ema_be
        ck_pri_s = price < e2v
        ck_ndisc = not in_discount

        sell_core = sum([ck_st_s, ck_ut_s, ck_sar_s, ck_ema_s, ck_pri_s, ck_ndisc])

        # ── MTF scores ───────────────────────────────────────────────────
        bull_5m,  bear_5m  = self._analyze_tf(dfs.get("5m"))
        bull_30m, bear_30m = self._analyze_tf(dfs.get("30m"))
        bull_1h,  bear_1h  = self._analyze_tf(dfs.get("1h"))
        bull_4h,  bear_4h  = self._analyze_tf(dfs.get("4h"))
        bull_1d,  bear_1d  = self._analyze_tf(dfs.get("1d"))

        mtm_b = bull_5m  >= 3;  mtm_s = bear_5m  >= 3
        brg_b = bull_30m >= 3;  brg_s = bear_30m >= 3
        ctx_b = bull_1h >= 3 and bull_4h >= 3 and bull_1d >= 3
        ctx_s = bear_1h >= 3 and bear_4h >= 3 and bear_1d >= 3

        # ── RSI MTF direction ─────────────────────────────────────────────
        rsi_bull_cnt = rsi_bear_cnt = 0
        for tf in TIMEFRAMES:
            df_tf = dfs.get(tf)
            if df_tf is not None and len(df_tf) >= 20:
                rsi_tf = calc_rsi(df_tf["close"], RSI_PERIOD)
                d = rsi_direction(rsi_tf, RSI_LOOKBACK, RSI_THRESHOLD)
                if d == 1:  rsi_bull_cnt += 1
                if d == -1: rsi_bear_cnt += 1

        # ── Total scores /11 ─────────────────────────────────────────────
        total_buy  = (buy_core
                      + (2 if ctx_b else 0)
                      + (1 if brg_b else 0)
                      + (1 if mtm_b else 0)
                      + (1 if rsi_bull_cnt >= 4 else 0))

        total_sell = (sell_core
                      + (2 if ctx_s else 0)
                      + (1 if brg_s else 0)
                      + (1 if mtm_s else 0)
                      + (1 if rsi_bear_cnt >= 4 else 0))

        # ── Verdict ──────────────────────────────────────────────────────
        if   total_buy  >= 9: verdict, emoji = "STRONG BUY",  "🚀"
        elif total_buy  >= 7: verdict, emoji = "BUY",         "✅"
        elif total_sell >= 9: verdict, emoji = "STRONG SELL", "🔻"
        elif total_sell >= 7: verdict, emoji = "SELL",        "🛑"
        elif total_buy  >= 5: verdict, emoji = "LEAN BUY",   "↑"
        elif total_sell >= 5: verdict, emoji = "LEAN SELL",  "↓"
        else:                 verdict, emoji = "NEUTRAL",    "⏳"

        # ── SL/TP ────────────────────────────────────────────────────────
        is_long = total_buy >= total_sell
        sl  = (price - atr_v * SL_MULT)  if is_long else (price + atr_v * SL_MULT)
        tp1 = (price + atr_v * TP1_MULT) if is_long else (price - atr_v * TP1_MULT)
        tp2 = (price + atr_v * TP2_MULT) if is_long else (price - atr_v * TP2_MULT)
        rr  = TP2_MULT / SL_MULT

        def _tf_arrow(bull: int, bear: int) -> str:
            return "▲" if bull >= 3 else ("▼" if bear >= 3 else "═")

        return SignalResult(
            symbol     = symbol,
            score_buy  = total_buy,
            score_sell = total_sell,
            verdict    = verdict,
            emoji      = emoji,
            price      = price,
            atr        = atr_v,
            atr_pct    = atr_p,
            rsi        = rsi_v,
            bull_vol   = bvol,
            bear_vol   = bevol,
            st_bull    = ck_st_b,
            ut_bull    = ck_ut_b,
            sar_bull   = ck_sar_b,
            ema_bull   = ck_ema_b,
            fvg_bull   = fvg_b,
            fvg_bear   = fvg_be,
            mtf_5m     = _tf_arrow(bull_5m,  bear_5m),
            mtf_30m    = _tf_arrow(bull_30m, bear_30m),
            mtf_1h     = _tf_arrow(bull_1h,  bear_1h),
            mtf_4h     = _tf_arrow(bull_4h,  bear_4h),
            mtf_1d     = _tf_arrow(bull_1d,  bear_1d),
            rsi_bull_cnt = rsi_bull_cnt,
            rsi_bear_cnt = rsi_bear_cnt,
            sl         = sl,
            tp1        = tp1,
            tp2        = tp2,
            rr         = rr,
            is_long    = is_long,
        )

    # ── Scan toàn bộ danh sách ────────────────────────────────────────────
    async def scan_all(self, symbols: List[str]) -> List[SignalResult]:
        logger.info(f"Scanning {len(symbols)} pairs …")
        results: List[SignalResult] = []

        BATCH = 15  # mỗi đợt 15 symbol
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i:i + BATCH]
            batch_res = await asyncio.gather(
                *[self.analyze_symbol(sym) for sym in batch],
                return_exceptions=True
            )
            for r in batch_res:
                if isinstance(r, SignalResult):
                    results.append(r)
                elif isinstance(r, Exception):
                    logger.debug(f"analyze error: {r}")
            if i + BATCH < len(symbols):
                await asyncio.sleep(0.5)

        results.sort(key=lambda x: x.best_score, reverse=True)
        logger.info(f"Scan done: {len(results)} analyzed")
        return results
