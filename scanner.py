"""
Scanner — Ceez Prime (4H context) + Buy Sell Signal (1H entry)
══════════════════════════════════════════════════════════════
Mỗi symbol fetch 2 TF:
  ctx_tf   : 4H  (Ceez Prime — EMA stack, LinReg, Structure, Fib, CCI, ADX)
  entry_tf : 1H  (Buy Sell Signal — EMA 5/13 cross + candle confirm)

Điều kiện pass:
  • direction != NEUTRAL  (có cross trên entry TF)
  • score >= min_score     (default 4/7 — ít nhất 4 context ok)
  • ADX >= 20              (xu hướng đủ mạnh)

Cooldown 15 phút cho auto alert.
"""

import asyncio
import logging
import time
from typing import Optional

from fetcher  import BybitFetcher
from signals  import SignalResult, score_symbol

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 900    # 15 phút
CONCURRENCY      = 30


class Scanner:
    def __init__(
        self,
        fetcher:     BybitFetcher,
        min_score:   int   = 4,       # ngưỡng context points (0-6, không tính entry)
        max_symbols: int   = 500,
        ctx_tf:      str   = "4h",    # Ceez Prime TF
        entry_tf:    str   = "1h",    # Buy Sell Signal TF
        min_adx:     float = 20.0,
        atr_mult_sl: float = 0.5,
        rr:          float = 3.0,
    ):
        self.fetcher      = fetcher
        self.min_score    = min_score
        self.max_symbols  = max_symbols
        self.ctx_tf       = ctx_tf
        self.entry_tf     = entry_tf
        self.min_adx      = min_adx
        self.atr_mult_sl  = atr_mult_sl
        self.rr           = rr
        self._last_alert: dict[str, float] = {}

    # ── Cooldown helpers ──────────────────────────────────────────────────

    def _in_cooldown(self, symbol: str) -> bool:
        return (time.time() - self._last_alert.get(symbol, 0)) < COOLDOWN_SECONDS

    def _mark_alert(self, symbol: str):
        self._last_alert[symbol] = time.time()

    # ── Core analyse ──────────────────────────────────────────────────────

    async def _analyse_one(
        self,
        symbol:          str,
        ignore_threshold: bool = False,
    ) -> Optional[SignalResult]:
        """
        Fetch ctx_tf + entry_tf, chạy scorer.
        ignore_threshold=True → trả kết quả kể cả NEUTRAL (dùng cho /check).
        """
        try:
            df_ctx, df_entry = await asyncio.gather(
                self.fetcher.fetch_ohlcv(symbol, self.ctx_tf,   200),
                self.fetcher.fetch_ohlcv(symbol, self.entry_tf, 100),
            )

            if df_ctx   is None or len(df_ctx)   < 50:
                return None
            if df_entry is None or len(df_entry) < 20:
                return None

            result = score_symbol(
                symbol,
                df_ctx   = df_ctx,
                df_entry = df_entry,
                min_adx      = self.min_adx,
                atr_mult_sl  = self.atr_mult_sl,
                rr           = self.rr,
            )

            if ignore_threshold:
                return result

            # Filter: phải có cross + đủ score context + ADX trending
            if result.direction == "NEUTRAL":
                return None
            if result.score < self.min_score:
                return None
            if not result.adx_ok:
                return None

            return result

        except Exception as e:
            logger.debug(f"{symbol}: {e}")
            return None

    # ── Batch scan ────────────────────────────────────────────────────────

    async def _run_scan(self) -> list[SignalResult]:
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(
            f"Scanning {len(symbols)} symbols "
            f"({self.ctx_tf} context + {self.entry_tf} entry, score≥{self.min_score})…"
        )

        sem = asyncio.Semaphore(CONCURRENCY)

        async def limited(sym):
            async with sem:
                return await self._analyse_one(sym)

        results = await asyncio.gather(*[limited(s) for s in symbols])

        signals = [r for r in results if r is not None]

        # Sort: FRESH first → score desc → risk_pct asc
        signals.sort(
            key=lambda x: (
                0 if x.signal_fresh else 1,
                -x.score,
                x.risk_pct,
            )
        )

        long_cnt  = sum(1 for r in signals if r.direction == "LONG")
        short_cnt = sum(1 for r in signals if r.direction == "SHORT")
        fresh_cnt = sum(1 for r in signals if r.signal_fresh)
        logger.info(
            f"Signals: {len(signals)} "
            f"(LONG:{long_cnt} SHORT:{short_cnt} FRESH:{fresh_cnt})"
        )
        return signals

    # ── Public scan methods ───────────────────────────────────────────────

    async def scan_all(self) -> list[SignalResult]:
        """Dùng cho /scan manual — không áp cooldown."""
        return await self._run_scan()

    async def scan_for_alert(self) -> list[SignalResult]:
        """Dùng cho auto alert — áp cooldown 15 phút."""
        all_signals = await self._run_scan()
        to_send = []
        for r in all_signals:
            if not self._in_cooldown(r.symbol):
                self._mark_alert(r.symbol)
                to_send.append(r)
        skipped = len(all_signals) - len(to_send)
        logger.info(
            f"auto alert → gửi {len(to_send)} / skip {skipped} (cooldown) "
            f"/ tổng {len(all_signals)}"
        )
        return to_send

    async def scan_symbol(self, symbol: str) -> Optional[SignalResult]:
        """Dùng cho /check — bỏ ngưỡng, luôn trả kết quả."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return await self._analyse_one(sym, ignore_threshold=True)

    # ── Timeframe override helpers ─────────────────────────────────────────
    # Cho phép /scan4h, /scan1h… dùng TF khác tạm thời

    async def scan_tf(
        self,
        ctx_tf:   str,
        entry_tf: str,
    ) -> list[SignalResult]:
        """Scan với TF tùy chọn — không thay đổi cấu hình gốc."""
        orig_ctx, orig_entry = self.ctx_tf, self.entry_tf
        self.ctx_tf, self.entry_tf = ctx_tf, entry_tf
        try:
            return await self._run_scan()
        finally:
            self.ctx_tf, self.entry_tf = orig_ctx, orig_entry
