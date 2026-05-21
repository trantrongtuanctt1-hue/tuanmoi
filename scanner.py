"""
Scanner — Ceez Prime (4H) + Buy Sell Signal (1H)
══════════════════════════════════════════════════
Hard filter (bắt buộc):
  • direction != NEUTRAL
  • adx_ok  (ADX ≥ 20 + DI đúng chiều)
  • risk_ok  (0.2% ≤ SL ≤ 5%)
  • ctx_score ≥ 3/6  (ít nhất 3 context ok)
  • entry_score ≥ 3/5  (ít nhất 3 entry ok)
  • score tổng ≥ min_score (default 6/11)

Sort priority:
  1. Fresh cross (≤3 bar) — vào lệnh ngay
  2. Recent cross (4–8 bar) — setup đang diễn ra
  3. No cross — setup tốt, chờ cross
  Trong mỗi nhóm: score desc → risk_pct asc
"""

import asyncio
import logging
import time
from typing import Optional

from fetcher import BybitFetcher
from signals import SignalResult, score_symbol

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 900
CONCURRENCY      = 30


class Scanner:
    def __init__(
        self,
        fetcher:     BybitFetcher,
        min_score:   int   = 6,
        max_symbols: int   = 500,
        ctx_tf:      str   = "4h",
        entry_tf:    str   = "1h",
        min_adx:     float = 20.0,
        atr_mult_sl: float = 0.5,
        rr:          float = 3.0,
    ):
        self.fetcher     = fetcher
        self.min_score   = min_score
        self.max_symbols = max_symbols
        self.ctx_tf      = ctx_tf
        self.entry_tf    = entry_tf
        self.min_adx     = min_adx
        self.atr_mult_sl = atr_mult_sl
        self.rr          = rr
        self._last_alert: dict[str, float] = {}

    def _in_cooldown(self, s: str) -> bool:
        return (time.time() - self._last_alert.get(s, 0)) < COOLDOWN_SECONDS

    def _mark_alert(self, s: str):
        self._last_alert[s] = time.time()

    def _pass_filter(self, r: SignalResult) -> bool:
        if r.direction == "NEUTRAL":  return False
        if not r.adx_ok:              return False
        if not r.risk_ok:             return False

        ctx_score = sum([r.ema_stack, r.linreg_bull, r.struct_ok,
                         r.fib_ok, r.cci_ok, r.adx_ok])
        if ctx_score < 3:             return False

        entry_score = sum([r.entry_cross, r.rsi_ok, r.candle_strong,
                           r.volume_spike, r.price_side_ok])
        if entry_score < 3:           return False

        if r.score < self.min_score:  return False
        return True

    def _sort_key(self, r: SignalResult):
        # Nhóm: 0=fresh, 1=recent, 2=no cross
        if r.has_fresh_cross:   grp = 0
        elif r.has_recent_cross: grp = 1
        else:                    grp = 2
        return (grp, -r.score, r.risk_pct)

    async def _analyse_one(self, symbol: str, ignore_threshold: bool = False) -> Optional[SignalResult]:
        try:
            df_ctx, df_entry = await asyncio.gather(
                self.fetcher.fetch_ohlcv(symbol, self.ctx_tf,   200),
                self.fetcher.fetch_ohlcv(symbol, self.entry_tf, 100),
            )
            if df_ctx   is None or len(df_ctx)   < 60: return None
            if df_entry is None or len(df_entry) < 30: return None

            result = score_symbol(
                symbol, df_ctx=df_ctx, df_entry=df_entry,
                min_adx=self.min_adx, atr_mult_sl=self.atr_mult_sl, rr=self.rr,
            )
            if ignore_threshold: return result
            return result if self._pass_filter(result) else None
        except Exception as e:
            logger.debug(f"{symbol}: {e}")
            return None

    async def _run_scan(self) -> list[SignalResult]:
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"Scanning {len(symbols)} symbols ({self.ctx_tf}+{self.entry_tf} | score≥{self.min_score})…")

        sem = asyncio.Semaphore(CONCURRENCY)
        async def limited(sym):
            async with sem:
                return await self._analyse_one(sym)

        results = await asyncio.gather(*[limited(s) for s in symbols])
        signals = sorted([r for r in results if r is not None], key=self._sort_key)

        fresh  = sum(1 for r in signals if r.has_fresh_cross)
        recent = sum(1 for r in signals if r.has_recent_cross)
        no_x   = len(signals) - fresh - recent
        l = sum(1 for r in signals if r.direction == "LONG")
        s = sum(1 for r in signals if r.direction == "SHORT")
        logger.info(f"Pass: {len(signals)} (L:{l} S:{s} | Fresh:{fresh} Recent:{recent} Setup:{no_x})")
        return signals

    async def scan_all(self)                        -> list[SignalResult]: return await self._run_scan()
    async def scan_for_alert(self)                  -> list[SignalResult]:
        all_s   = await self._run_scan()
        to_send = [r for r in all_s if not self._in_cooldown(r.symbol)]
        for r in to_send: self._mark_alert(r.symbol)
        return to_send
    async def scan_symbol(self, symbol: str)        -> Optional[SignalResult]:
        sym = symbol.upper()
        if not sym.endswith("USDT"): sym += "USDT"
        return await self._analyse_one(sym, ignore_threshold=True)
    async def scan_tf(self, ctx_tf: str, entry_tf: str) -> list[SignalResult]:
        orig_ctx, orig_entry = self.ctx_tf, self.entry_tf
        self.ctx_tf, self.entry_tf = ctx_tf, entry_tf
        try:    return await self._run_scan()
        finally: self.ctx_tf, self.entry_tf = orig_ctx, orig_entry

    async def scan_dual(
        self,
        ctx_tf_a: str, entry_tf_a: str,
        ctx_tf_b: str, entry_tf_b: str,
    ) -> list[tuple[SignalResult, str]]:
        """
        Chạy song song 2 TF pair, merge & dedup.
        Trả về list[(SignalResult, tf_label)] đã sort.
        tf_label ví dụ: "1D+4H" hoặc "1H+15m"
        Nếu cùng symbol xuất hiện ở cả 2 pair → giữ cái score cao hơn.
        """
        label_a = f"{ctx_tf_a.upper()}+{entry_tf_a.upper()}"
        label_b = f"{ctx_tf_b.upper()}+{entry_tf_b.upper()}"

        results_a, results_b = await asyncio.gather(
            self.scan_tf(ctx_tf_a, entry_tf_a),
            self.scan_tf(ctx_tf_b, entry_tf_b),
        )

        # Merge: ưu tiên score cao hơn, ghi nhận TF của từng signal
        merged: dict[str, tuple[SignalResult, str]] = {}
        for r in results_a:
            merged[r.symbol] = (r, label_a)
        for r in results_b:
            if r.symbol not in merged or r.score > merged[r.symbol][0].score:
                merged[r.symbol] = (r, label_b)

        # Sort: fresh → recent → setup; trong nhóm score desc → risk asc
        sorted_list = sorted(merged.values(), key=lambda x: self._sort_key(x[0]))
        logger.info(
            f"scan_dual({label_a} | {label_b}): "
            f"{len(results_a)} + {len(results_b)} → merged {len(sorted_list)}"
        )
        return sorted_list
