"""
Scanner — Ceez Prime (4H) + Buy Sell Signal (1H)
═════════════════════════════════════════════════
Pass filter (theo thứ tự ưu tiên):
  HARD (bắt buộc):
    • direction != NEUTRAL   (có cross, không cần fresh)
    • adx_ok                 (ADX trending + DI đúng chiều)
    • risk_ok                (0.2% ≤ SL ≤ 5%)
    • ctx_score ≥ 3/6        (ít nhất 3 context ok)
    • entry_score ≥ 2/5      (ít nhất 2 entry ok)

  SOFT (tính vào score để sort):
    • signal_fresh           +1 điểm bonus khi cross ≤ 2 bar
    • score ≥ min_score      (default 5/11)

Signals được sort: fresh trước → score desc → risk_pct asc
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

CTX_MIN_HARD  = 4   # hard: ít nhất 4/6 context
ENTRY_MIN_HARD = 2  # hard: ít nhất 2/5 entry (cross + 1 nữa)


class Scanner:
    def __init__(
        self,
        fetcher:     BybitFetcher,
        min_score:   int   = 7,        # tổng ≥ 7/11
        max_symbols: int   = 500,
        ctx_tf:      str   = "4h",
        entry_tf:    str   = "1h",
        min_adx:     float = 25.0,     # ADX đủ mạnh
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

    def _in_cooldown(self, symbol: str) -> bool:
        return (time.time() - self._last_alert.get(symbol, 0)) < COOLDOWN_SECONDS

    def _mark_alert(self, symbol: str):
        self._last_alert[symbol] = time.time()

    def _pass_filter(self, r: SignalResult) -> bool:
        """Filter 2 lớp: HARD bắt buộc, SOFT tính score."""

        # ── HARD: bắt buộc ────────────────────────────────────────────────
        if r.direction == "NEUTRAL":
            return False

        if not r.adx_ok:
            return False

        if not r.risk_ok:
            return False

        # Context sub-check
        ctx_score = sum([
            r.ema_stack, r.linreg_bull, r.struct_ok,
            r.fib_ok, r.cci_ok, r.adx_ok,
        ])
        if ctx_score < CTX_MIN_HARD:
            return False

        # Entry sub-check
        entry_score = sum([
            r.entry_cross, r.candle_strong,
            r.volume_spike, r.rsi_ok, r.price_side_ok,
        ])
        if entry_score < ENTRY_MIN_HARD:
            return False

        # ── SOFT: score tổng ─────────────────────────────────────────────
        if r.score < self.min_score:
            return False

        return True

    def _effective_score(self, r: SignalResult) -> int:
        """Score thực tế = score + bonus fresh."""
        bonus = 2 if r.signal_fresh else (1 if r.cross_bars_ago <= 3 else 0)
        return r.score + bonus

    async def _analyse_one(
        self,
        symbol:           str,
        ignore_threshold: bool = False,
    ) -> Optional[SignalResult]:
        try:
            df_ctx, df_entry = await asyncio.gather(
                self.fetcher.fetch_ohlcv(symbol, self.ctx_tf,   200),
                self.fetcher.fetch_ohlcv(symbol, self.entry_tf, 100),
            )
            if df_ctx   is None or len(df_ctx)   < 60:
                return None
            if df_entry is None or len(df_entry) < 30:
                return None

            result = score_symbol(
                symbol,
                df_ctx      = df_ctx,
                df_entry    = df_entry,
                min_adx     = self.min_adx,
                atr_mult_sl = self.atr_mult_sl,
                rr          = self.rr,
            )

            if ignore_threshold:
                return result
            return result if self._pass_filter(result) else None

        except Exception as e:
            logger.debug(f"{symbol}: {e}")
            return None

    async def _run_scan(self) -> list[SignalResult]:
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(
            f"Scanning {len(symbols)} symbols "
            f"({self.ctx_tf}+{self.entry_tf} | "
            f"score≥{self.min_score}/11 ctx≥{CTX_MIN_HARD} entry≥{ENTRY_MIN_HARD} ADX≥{self.min_adx})…"
        )

        sem = asyncio.Semaphore(CONCURRENCY)

        async def limited(sym):
            async with sem:
                return await self._analyse_one(sym)

        results = await asyncio.gather(*[limited(s) for s in symbols])
        signals = [r for r in results if r is not None]

        # Sort: fresh trước → effective_score desc → risk_pct asc
        signals.sort(key=lambda x: (
            0 if x.signal_fresh else (1 if x.cross_bars_ago <= 3 else 2),
            -self._effective_score(x),
            x.risk_pct,
        ))

        l = sum(1 for r in signals if r.direction == "LONG")
        s = sum(1 for r in signals if r.direction == "SHORT")
        f = sum(1 for r in signals if r.signal_fresh)
        logger.info(
            f"Pass: {len(signals)} (LONG:{l} SHORT:{s} FRESH:{f}) "
            f"from {len(symbols)} symbols"
        )
        return signals

    async def scan_all(self) -> list[SignalResult]:
        return await self._run_scan()

    async def scan_for_alert(self) -> list[SignalResult]:
        all_s   = await self._run_scan()
        to_send = [r for r in all_s if not self._in_cooldown(r.symbol)]
        for r in to_send:
            self._mark_alert(r.symbol)
        logger.info(f"Alert: send={len(to_send)} skip={len(all_s)-len(to_send)}")
        return to_send

    async def scan_symbol(self, symbol: str) -> Optional[SignalResult]:
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return await self._analyse_one(sym, ignore_threshold=True)

    async def scan_tf(self, ctx_tf: str, entry_tf: str) -> list[SignalResult]:
        orig_ctx, orig_entry = self.ctx_tf, self.entry_tf
        self.ctx_tf, self.entry_tf = ctx_tf, entry_tf
        try:
            return await self._run_scan()
        finally:
            self.ctx_tf, self.entry_tf = orig_ctx, orig_entry
