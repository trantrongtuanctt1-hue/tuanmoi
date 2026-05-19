"""
Scanner — quét tối đa 500 token song song
v3.2:
  - Ngưỡng pass: ultra_buy hoặc ultra_sell >= 8
  - scan_all()       → trả TẤT CẢ đủ điều kiện, KHÔNG áp cooldown (dùng cho /scan manual)
  - scan_for_alert() → áp cooldown 15 phút (dùng cho auto alert 5 phút)
  - scan_symbol()    → quét 1 token, không cooldown, không ngưỡng
"""
import asyncio
import logging
import time
from typing import Optional

from fetcher import BybitFetcher
from signals import SignalResult, score_symbol, detect_fvg

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 900   # 15 phút, chỉ dùng cho auto alert
CONCURRENCY      = 30


class Scanner:
    def __init__(
        self,
        fetcher: BybitFetcher,
        min_score: int = 8,       # ultra score threshold, đọc từ env MIN_ALERT_SCORE
        max_symbols: int = 1000,
    ):
        self.fetcher      = fetcher
        self.min_score    = min_score
        self.max_symbols  = max_symbols
        self._last_alert: dict[str, float] = {}

    def _in_cooldown(self, symbol: str) -> bool:
        last = self._last_alert.get(symbol, 0)
        return (time.time() - last) < COOLDOWN_SECONDS

    def _mark_alert(self, symbol: str):
        self._last_alert[symbol] = time.time()

    async def _analyse_one(self, symbol: str, ignore_threshold: bool = False) -> Optional[SignalResult]:
        """Fetch 6 TF và score. ignore_threshold=True để luôn trả kết quả (dùng cho /check)."""
        try:
            df5, df15, df30, df1h, df4h, df1d = await asyncio.gather(
                self.fetcher.fetch_ohlcv(symbol, "5m",  100),
                self.fetcher.fetch_ohlcv(symbol, "15m",  60),
                self.fetcher.fetch_ohlcv(symbol, "30m",  60),
                self.fetcher.fetch_ohlcv(symbol, "1h",   60),
                self.fetcher.fetch_ohlcv(symbol, "4h",   60),
                self.fetcher.fetch_ohlcv(symbol, "1d",   60),
            )

            if df5 is None or len(df5) < 50:
                return None
            if df15 is None or len(df15) < 20:
                df15 = df5

            result = score_symbol(
                symbol,
                df_5m  = df5,
                df_15m = df15,
                df_1h  = df1h,
                df_30m = df30,
                df_4h  = df4h,
                df_1d  = df1d,
            )

            if ignore_threshold:
                return result

            # Pass nếu 15m ULTRA >= ngưỡng HOẶC 1h / 4h / 1d có STRONG BUY/SELL
            ultra_15m = max(result.ultra_buy_score, result.ultra_sell_score)
            ultra_1h  = max(result.ultra_1h_buy,    result.ultra_1h_sell)
            ultra_4h  = max(result.ultra_4h_buy,    result.ultra_4h_sell)
            ultra_1d  = max(result.ultra_1d_buy,    result.ultra_1d_sell)
            if ultra_15m >= self.min_score or ultra_1h >= self.min_score or ultra_4h >= self.min_score or ultra_1d >= self.min_score:
                return result
            return None

        except Exception as e:
            logger.debug(f"{symbol}: {e}")
            return None

    async def _run_scan(self) -> list[SignalResult]:
        """Core: quét toàn bộ symbols, trả tất cả đủ ngưỡng, sort theo score."""
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"Scanning {len(symbols)} symbols (6 TF, ultra>={self.min_score})…")

        sem = asyncio.Semaphore(CONCURRENCY)

        async def limited(sym):
            async with sem:
                return await self._analyse_one(sym)

        results = await asyncio.gather(*[limited(s) for s in symbols])

        signals = [r for r in results if r is not None]
        signals.sort(
            key=lambda x: (
                max(x.ultra_buy_score, x.ultra_sell_score,
                    x.ultra_1h_buy, x.ultra_1h_sell,
                    x.ultra_4h_buy, x.ultra_4h_sell,
                    x.ultra_1d_buy, x.ultra_1d_sell),
                x.score,
            ),
            reverse=True,
        )
        logger.info(f"Signals found: {len(signals)}")
        return signals

    async def scan_all(self) -> list[SignalResult]:
        """
        Dùng cho /scan manual.
        Trả TẤT CẢ signal ultra >= ngưỡng — KHÔNG áp cooldown, KHÔNG đánh dấu cooldown.
        """
        signals = await self._run_scan()
        logger.info(f"/scan → {len(signals)} signals (no cooldown filter)")
        return signals

    async def scan_for_alert(self) -> list[SignalResult]:
        """
        Dùng cho auto alert (background 5 phút).
        Áp cooldown 15 phút — token đã gửi gần đây bị skip.
        Chỉ đánh dấu cooldown cho token thực sự được gửi đi.
        """
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
        """Quét 1 token (/check), bỏ ngưỡng ultra, luôn trả kết quả."""
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        return await self._analyse_one(sym, ignore_threshold=True)

    async def scan_fvg(self, tf: str = "4h", limit: int = 100) -> list[dict]:
        """
        Quét toàn bộ market, tìm token có giá đang NẰM TRONG FVG của timeframe `tf`.
        Chỉ fetch 1 TF duy nhất → nhanh hơn nhiều so với full scan 6TF.

        Trả list[dict]:
          symbol, cur_price, fvg_type ("bull"|"bear"|"ifvg_bull"|"ifvg_bear"),
          fvg_top, fvg_bot, fvg_mid, gap_pct, dist_pct, age_bars
        Sort: dist_pct tăng dần (gần mid FVG nhất trước).
        """
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"FVG scan: {len(symbols)} symbols, tf={tf}")

        sem = asyncio.Semaphore(CONCURRENCY)

        async def _check_one(sym: str) -> list[dict]:
            async with sem:
                try:
                    df = await self.fetcher.fetch_ohlcv(sym, tf, limit=limit)
                    if df is None or len(df) < 3:
                        return []

                    res = detect_fvg(df, min_gap_pct=0.0, max_keep=10)
                    cur = res["cur_price"]
                    if cur <= 0:
                        return []

                    hits = []

                    def _check_fvg_list(fvgs: list, fvg_type: str):
                        for fvg in fvgs:
                            top = fvg["top"]
                            bot = fvg["bottom"]
                            # Giá đang NẰM TRONG vùng FVG
                            if bot <= cur <= top:
                                mid      = (top + bot) / 2
                                dist_pct = abs(cur - mid) / mid * 100 if mid > 0 else 0
                                hits.append({
                                    "symbol":    sym,
                                    "cur_price": cur,
                                    "fvg_type":  fvg_type,
                                    "fvg_top":   top,
                                    "fvg_bot":   bot,
                                    "fvg_mid":   round(mid, 6),
                                    "gap_pct":   fvg["gap_pct"],
                                    "dist_pct":  round(dist_pct, 2),
                                    "age_bars":  fvg["age_bars"],
                                })

                    _check_fvg_list(res["bull_fvgs"], "bull")
                    _check_fvg_list(res["bear_fvgs"], "bear")
                    for ifvg in res["ifvgs"]:
                        _check_fvg_list([ifvg], ifvg.get("status", "ifvg"))

                    return hits
                except Exception as e:
                    logger.debug(f"scan_fvg {sym}: {e}")
                    return []

        all_lists = await asyncio.gather(*[_check_one(s) for s in symbols])

        hits = [item for sublist in all_lists for item in sublist]
        # Sort: gần mid FVG nhất trước
        hits.sort(key=lambda x: x["dist_pct"])
        logger.info(f"FVG scan done: {len(hits)} tokens in FVG ({tf})")
        return hits

    async def scan_ft(self) -> list[dict]:
        """
        /ft — Quét toàn market, tìm token thỏa:
          1. Giá đang TRONG hoặc GẦN vùng BEAR FVG 4h (buffer ±0.5%)
             → chỉ Bear FVG + iFVG bear (vùng kháng cự, setup SHORT)
          2. 15m ULTRA SELL score >= 6

        Kết quả chia 3 tier:
          🔥 STRONG : sell >= 9  +  trong FVG (dist=0)
          ⚡ GOOD   : sell >= 8  +  trong hoặc gần FVG
          📌 WATCH  : sell >= 6  +  trong hoặc gần FVG
        Sort: sell_score cao → dist_pct gần nhất.
        """
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"FT scan: {len(symbols)} symbols (Bear FVG-4h + 15m SELL≥6)")

        sem = asyncio.Semaphore(CONCURRENCY)

        async def _check_one(sym: str) -> list[dict]:
            async with sem:
                try:
                    df4h, df15 = await asyncio.gather(
                        self.fetcher.fetch_ohlcv(sym, "4h",  100),
                        self.fetcher.fetch_ohlcv(sym, "15m", 100),
                    )
                    if df4h is None or len(df4h) < 3:
                        return []
                    if df15 is None or len(df15) < 50:
                        return []

                    # ── Bước 1: Bear FVG 4h — dùng buffer ±0.5% ──────────
                    fvg_res = detect_fvg(df4h, min_gap_pct=0.0, max_keep=15)
                    cur     = fvg_res["cur_price"]
                    if cur <= 0:
                        return []

                    # Chỉ lấy Bear FVG + iFVG bear (kháng cự, setup SHORT)
                    bear_fvgs = fvg_res["bear_fvgs"]
                    ifvg_bear = [f for f in fvg_res["ifvgs"]
                                 if f.get("status", "") == "ifvg_bear"]
                    candidates = [(f, "bear") for f in bear_fvgs] + \
                                 [(f, "ifvg_bear") for f in ifvg_bear]

                    BUFFER = 0.005  # 0.5% quanh vùng FVG
                    fvg_hits = []
                    for fvg, ftype in candidates:
                        top_buf = fvg["top"]    * (1 + BUFFER)
                        bot_buf = fvg["bottom"] * (1 - BUFFER)
                        if bot_buf <= cur <= top_buf:
                            mid      = (fvg["top"] + fvg["bottom"]) / 2
                            dist_pct = abs(cur - mid) / mid * 100 if mid > 0 else 0
                            inside   = fvg["bottom"] <= cur <= fvg["top"]
                            fvg_hits.append({**fvg, "dist_pct": round(dist_pct, 2),
                                             "inside": inside, "fvg_type": ftype})

                    if not fvg_hits:
                        return []

                    # ── Bước 2: 15m ULTRA SELL score ──────────────────────
                    result = score_symbol(
                        sym,
                        df_5m  = df15,
                        df_15m = df15,
                        df_1h  = None,
                        df_30m = None,
                        df_4h  = df4h,
                        df_1d  = None,
                    )

                    sell_score = result.ultra_sell_score
                    if sell_score < 6:
                        return []

                    # ── Bước 3: Build hit — lấy Bear FVG gần nhất ────────
                    fvg_hits.sort(key=lambda x: x["dist_pct"])
                    best = fvg_hits[0]
                    mid  = (best["top"] + best["bottom"]) / 2

                    tier = "🔥" if sell_score >= 9 and best["inside"] else (
                           "⚡" if sell_score >= 8 else "📌")

                    return [{
                        "symbol":     sym,
                        "cur_price":  cur,
                        "fvg_type":   best.get("fvg_type", "bear"),
                        "fvg_top":    best["top"],
                        "fvg_bot":    best["bottom"],
                        "fvg_mid":    round(mid, 6),
                        "gap_pct":    best["gap_pct"],
                        "dist_pct":   best["dist_pct"],
                        "inside":     best["inside"],
                        "age_bars":   best["age_bars"],
                        "sell_score": sell_score,
                        "tier":       tier,
                    }]

                except Exception as e:
                    logger.debug(f"scan_ft {sym}: {e}")
                    return []

        all_lists = await asyncio.gather(*[_check_one(s) for s in symbols])
        hits = [item for sublist in all_lists for item in sublist]
        hits.sort(key=lambda x: (-x["sell_score"], x["dist_pct"]))
        logger.info(f"FT scan done: {len(hits)} tokens (Bear FVG-4h + SELL≥6)")
        return hits

    async def scan_fb(self) -> list[dict]:
        """
        /fb — Quét toàn market, tìm token thỏa:
          1. Giá đang TRONG hoặc GẦN vùng BULL FVG 4h (buffer ±0.5%)
             → chỉ Bull FVG + iFVG bull (vùng hỗ trợ, setup LONG)
          2. 15m ULTRA BUY score >= 6

        Kết quả chia 3 tier:
          🔥 STRONG : buy >= 9  +  trong FVG (dist=0)
          ⚡ GOOD   : buy >= 8  +  trong hoặc gần FVG
          📌 WATCH  : buy >= 6  +  trong hoặc gần FVG
        Sort: buy_score cao → dist_pct gần nhất.
        """
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(f"FB scan: {len(symbols)} symbols (Bull FVG-4h + 15m BUY≥6)")

        sem = asyncio.Semaphore(CONCURRENCY)

        async def _check_one(sym: str) -> list[dict]:
            async with sem:
                try:
                    df4h, df15 = await asyncio.gather(
                        self.fetcher.fetch_ohlcv(sym, "4h",  100),
                        self.fetcher.fetch_ohlcv(sym, "15m", 100),
                    )
                    if df4h is None or len(df4h) < 3:
                        return []
                    if df15 is None or len(df15) < 50:
                        return []

                    # ── Bước 1: Bull FVG 4h — dùng buffer ±0.5% ──────────
                    fvg_res = detect_fvg(df4h, min_gap_pct=0.0, max_keep=15)
                    cur     = fvg_res["cur_price"]
                    if cur <= 0:
                        return []

                    # Chỉ lấy Bull FVG + iFVG bull (hỗ trợ, setup LONG)
                    bull_fvgs = fvg_res["bull_fvgs"]
                    ifvg_bull = [f for f in fvg_res["ifvgs"]
                                 if f.get("status", "") == "ifvg_bull"]
                    candidates = [(f, "bull") for f in bull_fvgs] + \
                                 [(f, "ifvg_bull") for f in ifvg_bull]

                    BUFFER = 0.005  # 0.5% quanh vùng FVG
                    fvg_hits = []
                    for fvg, ftype in candidates:
                        top_buf = fvg["top"]    * (1 + BUFFER)
                        bot_buf = fvg["bottom"] * (1 - BUFFER)
                        if bot_buf <= cur <= top_buf:
                            mid      = (fvg["top"] + fvg["bottom"]) / 2
                            dist_pct = abs(cur - mid) / mid * 100 if mid > 0 else 0
                            inside   = fvg["bottom"] <= cur <= fvg["top"]
                            fvg_hits.append({**fvg, "dist_pct": round(dist_pct, 2),
                                             "inside": inside, "fvg_type": ftype})

                    if not fvg_hits:
                        return []

                    # ── Bước 2: 15m ULTRA BUY score ───────────────────────
                    result = score_symbol(
                        sym,
                        df_5m  = df15,
                        df_15m = df15,
                        df_1h  = None,
                        df_30m = None,
                        df_4h  = df4h,
                        df_1d  = None,
                    )

                    buy_score = result.ultra_buy_score
                    if buy_score < 6:
                        return []

                    # ── Bước 3: Build hit — lấy Bull FVG gần nhất ────────
                    fvg_hits.sort(key=lambda x: x["dist_pct"])
                    best = fvg_hits[0]
                    mid  = (best["top"] + best["bottom"]) / 2

                    tier = "🔥" if buy_score >= 9 and best["inside"] else (
                           "⚡" if buy_score >= 8 else "📌")

                    return [{
                        "symbol":    sym,
                        "cur_price": cur,
                        "fvg_type":  best.get("fvg_type", "bull"),
                        "fvg_top":   best["top"],
                        "fvg_bot":   best["bottom"],
                        "fvg_mid":   round(mid, 6),
                        "gap_pct":   best["gap_pct"],
                        "dist_pct":  best["dist_pct"],
                        "inside":    best["inside"],
                        "age_bars":  best["age_bars"],
                        "buy_score": buy_score,
                        "tier":      tier,
                    }]

                except Exception as e:
                    logger.debug(f"scan_fb {sym}: {e}")
                    return []

        all_lists = await asyncio.gather(*[_check_one(s) for s in symbols])
        hits = [item for sublist in all_lists for item in sublist]
        hits.sort(key=lambda x: (-x["buy_score"], x["dist_pct"]))
        logger.info(f"FB scan done: {len(hits)} tokens (Bull FVG-4h + BUY≥6)")
        return hits
