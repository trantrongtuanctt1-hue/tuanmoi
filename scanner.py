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

    # ──────────────────────────────────────────────────────────────────────
    # CORE ENGINE — Bear/Bull FVG scan với bất kỳ TF nào
    # ──────────────────────────────────────────────────────────────────────

    # Buffer scale theo TF — FVG 1D rộng hơn nhiều so với 1h
    _FVG_BUFFER = {"1h": 0.003, "4h": 0.005, "1d": 0.010}

    # Mapping score_tf → kwargs đúng cho score_symbol
    @staticmethod
    def _score_kwargs(score_tf: str, df_score, fvg_tf: str, df_fvg) -> dict:
        """
        Build kwargs cho score_symbol:
          - df_5m + df_15m luôn được set = df_score (base bắt buộc)
          - slot đúng với score_tf cũng được set = df_score
          - slot đúng với fvg_tf được set = df_fvg (nếu khác score_tf)
          - các slot còn lại = None

        Lý do set cả df_5m/df_15m: score_symbol dùng chúng làm
        base tính toán; nếu None thì ultra_score trả 0 dù có df_1h.
        """
        TF_SLOT = {
            "5m": "df_5m", "15m": "df_15m", "30m": "df_30m",
            "1h": "df_1h", "4h":  "df_4h",  "1d":  "df_1d",
        }
        kwargs = dict(df_5m=None, df_15m=None, df_30m=None,
                      df_1h=None, df_4h=None,  df_1d=None)

        # Base bắt buộc — score_symbol cần ít nhất df_5m hoặc df_15m
        kwargs["df_5m"]  = df_score
        kwargs["df_15m"] = df_score

        # Override đúng slot score_tf
        slot_score = TF_SLOT.get(score_tf)
        if slot_score:
            kwargs[slot_score] = df_score

        # Điền df_fvg vào đúng slot fvg_tf (tránh ghi đè slot score)
        slot_fvg = TF_SLOT.get(fvg_tf)
        if slot_fvg and slot_fvg != slot_score:
            kwargs[slot_fvg] = df_fvg

        return kwargs

    async def _scan_bear_fvg(self, fvg_tf: str, score_tf: str) -> list[dict]:
        """
        Core engine cho /ft, /ft1h, /ft1d — setup SHORT.

        Logic SMC đúng:
          • Bear FVG   : vùng kháng cự gốc (giá rớt mạnh tạo ra)
          • iFVG bull  : Bull FVG đã bị giá phá xuống → đổi vai trò thành kháng cự

        Fix so với phiên bản cũ:
          [1] iFVG đúng vai trò  → lấy ifvg_bull thay vì ifvg_bear
          [2] df_4h pass đúng TF → dùng _score_kwargs()
          [3] Buffer scale theo TF → _FVG_BUFFER[fvg_tf]
        """
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(
            f"FT scan: {len(symbols)} symbols "
            f"(Bear FVG-{fvg_tf} + {score_tf} SELL≥6)"
        )
        BUFFER = self._FVG_BUFFER.get(fvg_tf, 0.005)   # [Fix 3]
        sem    = asyncio.Semaphore(CONCURRENCY)

        async def _check_one(sym: str) -> list[dict]:
            async with sem:
                try:
                    df_fvg, df_score = await asyncio.gather(
                        self.fetcher.fetch_ohlcv(sym, fvg_tf,   100),
                        self.fetcher.fetch_ohlcv(sym, score_tf, 100),
                    )
                    if df_fvg is None or len(df_fvg) < 3:
                        return []
                    if df_score is None or len(df_score) < 50:
                        return []

                    # ── Bước 1: Chọn đúng FVG kháng cự ───────────────────
                    fvg_res = detect_fvg(df_fvg, min_gap_pct=0.0, max_keep=15)
                    cur     = fvg_res["cur_price"]
                    if cur <= 0:
                        return []

                    # [Fix 1] Bear FVG gốc  +  iFVG bull (bull FVG bị phá xuống
                    #         → giờ đóng vai kháng cự)
                    bear_fvgs = fvg_res["bear_fvgs"]
                    ifvg_bull_as_res = [f for f in fvg_res["ifvgs"]
                                        if f.get("status", "") == "ifvg_bull"]
                    candidates = [(f, "bear")      for f in bear_fvgs] + \
                                 [(f, "ifvg_bull") for f in ifvg_bull_as_res]

                    fvg_hits = []
                    for fvg, ftype in candidates:
                        top_buf = fvg["top"]    * (1 + BUFFER)   # [Fix 3]
                        bot_buf = fvg["bottom"] * (1 - BUFFER)
                        if bot_buf <= cur <= top_buf:
                            mid      = (fvg["top"] + fvg["bottom"]) / 2
                            dist_pct = abs(cur - mid) / mid * 100 if mid > 0 else 0
                            inside   = fvg["bottom"] <= cur <= fvg["top"]
                            fvg_hits.append({**fvg, "dist_pct": round(dist_pct, 2),
                                             "inside": inside, "fvg_type": ftype})
                    if not fvg_hits:
                        return []

                    # ── Bước 2: SELL score — pass đúng TF ─────────────────
                    kwargs = self._score_kwargs(score_tf, df_score,   # [Fix 2]
                                               fvg_tf,   df_fvg)
                    result     = score_symbol(sym, **kwargs)
                    sell_score = result.ultra_sell_score
                    if sell_score < 6:
                        return []

                    # ── Bước 3: FVG kháng cự gần giá nhất ────────────────
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
                    logger.debug(f"scan_bear_fvg {sym}: {e}")
                    return []

        all_lists = await asyncio.gather(*[_check_one(s) for s in symbols])
        hits = [item for sublist in all_lists for item in sublist]
        hits.sort(key=lambda x: (-x["sell_score"], x["dist_pct"]))
        logger.info(
            f"FT ({fvg_tf}) done: {len(hits)} tokens "
            f"(Bear FVG + {score_tf} SELL≥6)"
        )
        return hits

    async def _scan_bull_fvg(self, fvg_tf: str, score_tf: str) -> list[dict]:
        """
        Core engine cho /fb, /fb1h, /fb1d — setup LONG.

        Logic SMC đúng:
          • Bull FVG   : vùng hỗ trợ gốc (giá tăng mạnh tạo ra)
          • iFVG bear  : Bear FVG đã bị giá phá lên → đổi vai trò thành hỗ trợ

        Fix so với phiên bản cũ:
          [1] iFVG đúng vai trò  → lấy ifvg_bear thay vì ifvg_bull
          [2] df_4h pass đúng TF → dùng _score_kwargs()
          [3] Buffer scale theo TF → _FVG_BUFFER[fvg_tf]
        """
        symbols = await self.fetcher.fetch_top_symbols(self.max_symbols)
        logger.info(
            f"FB scan: {len(symbols)} symbols "
            f"(Bull FVG-{fvg_tf} + {score_tf} BUY≥6)"
        )
        BUFFER = self._FVG_BUFFER.get(fvg_tf, 0.005)   # [Fix 3]
        sem    = asyncio.Semaphore(CONCURRENCY)

        async def _check_one(sym: str) -> list[dict]:
            async with sem:
                try:
                    df_fvg, df_score = await asyncio.gather(
                        self.fetcher.fetch_ohlcv(sym, fvg_tf,   100),
                        self.fetcher.fetch_ohlcv(sym, score_tf, 100),
                    )
                    if df_fvg is None or len(df_fvg) < 3:
                        return []
                    if df_score is None or len(df_score) < 50:
                        return []

                    # ── Bước 1: Chọn đúng FVG hỗ trợ ─────────────────────
                    fvg_res = detect_fvg(df_fvg, min_gap_pct=0.0, max_keep=15)
                    cur     = fvg_res["cur_price"]
                    if cur <= 0:
                        return []

                    # [Fix 1] Bull FVG gốc  +  iFVG bear (bear FVG bị phá lên
                    #         → giờ đóng vai hỗ trợ)
                    bull_fvgs = fvg_res["bull_fvgs"]
                    ifvg_bear_as_sup = [f for f in fvg_res["ifvgs"]
                                        if f.get("status", "") == "ifvg_bear"]
                    candidates = [(f, "bull")      for f in bull_fvgs] + \
                                 [(f, "ifvg_bear") for f in ifvg_bear_as_sup]

                    fvg_hits = []
                    for fvg, ftype in candidates:
                        top_buf = fvg["top"]    * (1 + BUFFER)   # [Fix 3]
                        bot_buf = fvg["bottom"] * (1 - BUFFER)
                        if bot_buf <= cur <= top_buf:
                            mid      = (fvg["top"] + fvg["bottom"]) / 2
                            dist_pct = abs(cur - mid) / mid * 100 if mid > 0 else 0
                            inside   = fvg["bottom"] <= cur <= fvg["top"]
                            fvg_hits.append({**fvg, "dist_pct": round(dist_pct, 2),
                                             "inside": inside, "fvg_type": ftype})
                    if not fvg_hits:
                        return []

                    # ── Bước 2: BUY score — pass đúng TF ──────────────────
                    kwargs = self._score_kwargs(score_tf, df_score,   # [Fix 2]
                                               fvg_tf,   df_fvg)
                    result    = score_symbol(sym, **kwargs)
                    buy_score = result.ultra_buy_score
                    if buy_score < 6:
                        return []

                    # ── Bước 3: FVG hỗ trợ gần giá nhất ──────────────────
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
                    logger.debug(f"scan_bull_fvg {sym}: {e}")
                    return []

        all_lists = await asyncio.gather(*[_check_one(s) for s in symbols])
        hits = [item for sublist in all_lists for item in sublist]
        hits.sort(key=lambda x: (-x["buy_score"], x["dist_pct"]))
        logger.info(
            f"FB ({fvg_tf}) done: {len(hits)} tokens "
            f"(Bull FVG + {score_tf} BUY≥6)"
        )
        return hits

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC WRAPPERS — mỗi lệnh bot gọi 1 trong các hàm này
    # ──────────────────────────────────────────────────────────────────────

    # /ft  — Bear FVG 4h  + 15m SELL
    async def scan_ft(self)   -> list[dict]:
        return await self._scan_bear_fvg("4h",  "15m")

    # /ft1h — Bear FVG 1h  + 15m SELL
    async def scan_ft1h(self) -> list[dict]:
        return await self._scan_bear_fvg("1h",  "15m")

    # /ft1d — Bear FVG 1d  + 1h  SELL  (khung daily → dùng 1h score)
    async def scan_ft1d(self) -> list[dict]:
        return await self._scan_bear_fvg("1d",  "1h")

    # /fb   — Bull FVG 4h  + 15m BUY
    async def scan_fb(self)   -> list[dict]:
        return await self._scan_bull_fvg("4h",  "15m")

    # /fb1h — Bull FVG 1h  + 15m BUY
    async def scan_fb1h(self) -> list[dict]:
        return await self._scan_bull_fvg("1h",  "15m")

    # /fb1d — Bull FVG 1d  + 1h  BUY   (khung daily → dùng 1h score)
    async def scan_fb1d(self) -> list[dict]:
        return await self._scan_bull_fvg("1d",  "1h")
