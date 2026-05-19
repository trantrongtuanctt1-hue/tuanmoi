"""
Telegram bot v3.0
Commands: /scan /top /check /status /debug /source /help

Dashboard đầy đủ:
  ① SXL Sniper (5 confluences Long/Short)
  ② MSB-OB + Vol Balance + Spike + Leverage  (giữ từ v2)
  ③ 15M ULTRA panel (NEW):
       ST AI | UT Bot | SAR | SMC Swing | SMC Internal
       Zone (PREM/EQ↑/EQ/EQ↓/DISC)
       RSI MTF (6 TF)
       MTF 3 tầng (Momentum 5m / Bridge 30m / Context 1h+4h+1d)
       ULTRA Score 0–11 → Verdict
"""
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scanner import Scanner
from signals import SignalResult, detect_fvg

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# FORMAT HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _yn(v: bool) -> str:
    return "✓" if v else "✗"

def _arr(v: int | bool) -> str:
    """1/True→▲  -1/False→▼  0→●"""
    if v is True  or v == 1:  return "▲"
    if v is False or v == -1: return "▼"
    return "●"

def _rsi_bar(bull: int, bear: int) -> str:
    """Tạo thanh RSI MTF 6 ô, ví dụ ▲▲▲▼●●"""
    # placeholder: chỉ hiển thị count
    return f"▲{bull}/6  ▼{bear}/6"

def _score_bar(n: int, total: int = 6) -> str:
    filled = min(n, total)
    return "█" * filled + "░" * (total - filled)

def _mtf_line(momentum_b, momentum_bm, bridge_b, bridge_bm, ctx_b, ctx_bm) -> str:
    def _flag(bull, bear):
        if bull: return "✅"
        if bear: return "🔴"
        return "⬜"
    return (
        f"5m{_flag(momentum_b, momentum_bm)} "
        f"30m{_flag(bridge_b,   bridge_bm)} "
        f"1h+4h+1d{_flag(ctx_b, ctx_bm)}"
    )


# ══════════════════════════════════════════════════════════════════════════
# FORMAT FULL (dùng cho /check và /scan)
# ══════════════════════════════════════════════════════════════════════════

def _fmt(r: SignalResult) -> str:
    dir_emoji = "🟢" if r.direction == "LONG" else ("🔴" if r.direction == "SHORT" else "⚪")
    premium_line = f"⭐ *PREMIUM SIGNAL*\n" if r.is_premium else ""

    spike_line = (
        f"⚡ *Spike {'▲' if r.spike_direction == 'BULL' else '▼'} {r.spike_pct}%* — Cẩn thận!\n"
        if r.is_spike else f"⚡ Spike: OK ({r.spike_pct}%)\n"
    )

    vol_icon    = "📈" if r.bull_pct > r.bear_pct else "📉"
    vol_dom     = " ⚠️ Dominant" if max(r.bull_pct, r.bear_pct) >= 65 else ""
    vol_conf    = "✓ Confirms" if r.vol_confirm else "✗ Against"
    lev_bar     = "█" * min(r.leverage, 10) + "░" * max(0, 10 - r.leverage)
    tags        = " | ".join(r.reasons[:8]) if r.reasons else "—"

    # ── UT Bot text ──────────────────────────────────────────────────────
    ut_txt = "LONG" if r.ut_pos_val == 1 else ("SHORT" if r.ut_pos_val == -1 else "FLAT")

    # ── Zone color hint ──────────────────────────────────────────────────
    zone_icon = {
        "PREM": "🔴", "EQ↑": "🟡", "EQ": "⚪",
        "EQ↓":  "🟡", "DISC": "🟢",
    }.get(r.zone, "⚪")

    # ── RSI bar ──────────────────────────────────────────────────────────
    rsi_bar = _rsi_bar(r.rsi_bull_count, r.rsi_bear_count)

    # ── MTF 3 tầng ───────────────────────────────────────────────────────
    mtf_txt = _mtf_line(
        r.mtf_momentum_bull, r.mtf_momentum_bear,
        r.mtf_bridge_bull,   r.mtf_bridge_bear,
        r.mtf_context_bull,  r.mtf_context_bear,
    )

    # ── Ultra score bar (15m) ─────────────────────────────────────────────
    ultra_max    = max(r.ultra_buy_score, r.ultra_sell_score)
    ultra_bar    = "█" * ultra_max + "░" * (11 - ultra_max)
    ultra_side   = "↑" if r.ultra_buy_score >= r.ultra_sell_score else "↓"
    ultra_color  = "🟢" if r.ultra_verdict_color == "green" else ("🔴" if r.ultra_verdict_color == "red" else "⬜")

    # ── Ultra 1h / 4h ────────────────────────────────────────────────────
    def _uc(color): return "🟢" if color == "green" else ("🔴" if color == "red" else "⬜")
    def _ubar(b, s): m = max(b, s); return "█" * m + "░" * (11 - m)

    u1h_color = _uc(r.ultra_1h_color)
    u4h_color = _uc(r.ultra_4h_color)
    u1d_color = _uc(r.ultra_1d_color)
    u1h_bar   = _ubar(r.ultra_1h_buy, r.ultra_1h_sell)
    u4h_bar   = _ubar(r.ultra_4h_buy, r.ultra_4h_sell)
    u1d_bar   = _ubar(r.ultra_1d_buy, r.ultra_1d_sell)

    msg = (
        f"{dir_emoji} *{r.symbol}*  [{r.direction}]  SXL: *{r.score}/10*\n"
        f"{premium_line}"
        f"{'─' * 30}\n"
        f"💰 Price  : `{r.price}`\n"
        f"🛑 SL     : `{r.sl}`\n"
        f"🎯 TP1    : `{r.tp1}`\n"
        f"🎯 TP2    : `{r.tp2}`\n"
        f"{'─' * 30}\n"
        f"📐 *SXL Confluences*\n"
        f"  LONG {r.l_score}/5 | SHORT {r.s_score}/5\n"
        f"  MSB Bias: {r.market_bias} | OB/BB Zone: {_yn(r.in_ob_zone)}\n"
        f"{'─' * 30}\n"
        f"⚡ *15M ULTRA Indicators*\n"
        f"  ST-AI : {_arr(r.st_ai_bull)} (factor {r.st_ai_factor:.1f})\n"
        f"  UT Bot: {_arr(r.ut_pos_val)} ({ut_txt})\n"
        f"  SAR   : {_arr(r.sar_bull_val)}\n"
        f"  SMC Sw: {_arr(r.smc_swing_bull)} | SMC In: {_arr(r.smc_int_bull)}\n"
        f"  Zone  : {zone_icon} *{r.zone}* ({r.zone_pct}%)\n"
        f"{'─' * 30}\n"
        f"📊 *RSI MTF*  {rsi_bar}\n"
        f"{'─' * 30}\n"
        f"🔗 *MTF 3 Tầng*\n"
        f"  {mtf_txt}\n"
        f"{'─' * 30}\n"
        f"🏆 *ULTRA Score (15m)*\n"
        f"  {ultra_color} BUY {r.ultra_buy_score}↑ / SELL {r.ultra_sell_score}↓ /11\n"
        f"  `{ultra_bar}` {ultra_side}\n"
        f"  Verdict: *{r.ultra_verdict}*\n"
        f"{'─' * 30}\n"
        f"⏱ *ULTRA Score 1H*\n"
        f"  {u1h_color} BUY {r.ultra_1h_buy}↑ / SELL {r.ultra_1h_sell}↓ /11\n"
        f"  `{u1h_bar}`\n"
        f"  Verdict: *{r.ultra_1h_verdict}*\n"
        f"{'─' * 30}\n"
        f"⏱ *ULTRA Score 4H*\n"
        f"  {u4h_color} BUY {r.ultra_4h_buy}↑ / SELL {r.ultra_4h_sell}↓ /11\n"
        f"  `{u4h_bar}`\n"
        f"  Verdict: *{r.ultra_4h_verdict}*\n"
        f"{'─' * 30}\n"
        f"📅 *ULTRA Score 1D*\n"
        f"  {u1d_color} BUY {r.ultra_1d_buy}↑ / SELL {r.ultra_1d_sell}↓ /11\n"
        f"  `{u1d_bar}`\n"
        f"  Verdict: *{r.ultra_1d_verdict}*\n"
        f"{'─' * 30}\n"
        f"{vol_icon} *Volume Balance*\n"
        f"  ▲ Bull: {r.bull_pct}%  |  ▼ Bear: {r.bear_pct}%{vol_dom}\n"
        f"  Vol {vol_conf}\n"
        f"{'─' * 30}\n"
        f"{spike_line}"
        f"{'─' * 30}\n"
        f"🎚 *Leverage Advisor*\n"
        f"  Gợi ý: *{r.leverage}x*  {r.lev_risk}\n"
        f"  ATR% = {r.atr_pct}%  [{lev_bar}]\n"
        f"{'─' * 30}\n"
        f"📌 {tags}"
    )
    return msg


# ══════════════════════════════════════════════════════════════════════════
# FORMAT SHORT (dùng cho /top)
# ══════════════════════════════════════════════════════════════════════════

def _fmt_short(r: SignalResult) -> str:
    dir_emoji = "🟢" if r.direction == "LONG" else ("🔴" if r.direction == "SHORT" else "⚪")
    prem  = " ★"           if r.is_premium else ""
    spk   = f" ⚡{r.spike_pct}%" if r.is_spike else ""
    vc    = r.ultra_verdict_color
    v_em  = "🟢" if vc == "green" else ("🔴" if vc == "red" else "⬜")
    zone_icon = {
        "PREM": "🔴", "EQ↑": "🟡", "EQ": "⚪", "EQ↓": "🟡", "DISC": "🟢",
    }.get(r.zone, "⚪")
    ut_txt = "L" if r.ut_pos_val == 1 else ("S" if r.ut_pos_val == -1 else "—")
    mtf_ctx = "✅" if (r.mtf_context_bull or r.mtf_context_bear) else "⬜"

    def _uc(c): return "🟢" if c == "green" else ("🔴" if c == "red" else "⬜")
    u1h_em = _uc(r.ultra_1h_color)
    u4h_em = _uc(r.ultra_4h_color)
    u1d_em = _uc(r.ultra_1d_color)

    return (
        f"{dir_emoji} *{r.symbol}*{prem}  SXL:`{r.score}/10`  15m:`{r.ultra_buy_score}↑{r.ultra_sell_score}↓`{spk}\n"
        f"  {v_em} *{r.ultra_verdict}*  "
        f"1H:{u1h_em}`{r.ultra_1h_buy}↑{r.ultra_1h_sell}↓` *{r.ultra_1h_verdict}*\n"
        f"  4H:{u4h_em}`{r.ultra_4h_buy}↑{r.ultra_4h_sell}↓` *{r.ultra_4h_verdict}*  "
        f"1D:{u1d_em}`{r.ultra_1d_buy}↑{r.ultra_1d_sell}↓` *{r.ultra_1d_verdict}*\n"
        f"  ST-AI:{_arr(r.st_ai_bull)} UT:{ut_txt} SAR:{_arr(r.sar_bull_val)} "
        f"Zone:{zone_icon}{r.zone}({r.zone_pct}%) CTX:{mtf_ctx}\n"
        f"  RSI▲{r.rsi_bull_count}/6 ▼{r.rsi_bear_count}/6 | "
        f"Vol▲{r.bull_pct}%/▼{r.bear_pct}% | Lev:{r.leverage}x {r.lev_risk}\n"
        f"  💰`{r.price}` 🛑`{r.sl}` 🎯`{r.tp1}`"
    )


# ══════════════════════════════════════════════════════════════════════════
# BOT
# ══════════════════════════════════════════════════════════════════════════

class TelegramBot:
    def __init__(self, token: str, scanner: Scanner):
        self.token   = token
        self.scanner = scanner
        self.app     = Application.builder().token(token).build()
        for cmd, fn in [
            ("start",    self._start),
            ("help",     self._help),
            ("scan",     self._scan),
            ("top",      self._top),
            ("strong",   self._strong),
            ("fvg",      self._fvg),
            ("fvgscan",  self._fvgscan),
            ("ft",       self._ft),
            ("ft1h",     self._ft1h),
            ("ft1d",     self._ft1d),
            ("fb",       self._fb),
            ("fb1h",     self._fb1h),
            ("fb1d",     self._fb1d),
            ("check",    self._check),
            ("status",   self._status),
            ("debug",    self._debug),
            ("source",   self._source),
        ]:
            self.app.add_handler(CommandHandler(cmd, fn))

    async def _start(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            "🤖 *SXL Sniper + 15M ULTRA Bot* v3.0 sẵn sàng!\n"
            "Dùng /help xem lệnh.",
            parse_mode="Markdown"
        )

    async def _help(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            "📖 *Lệnh*\n"
            "/scan     — Quét tất cả token, signal đủ điều kiện\n"
            "/top      — Top 5 tín hiệu mạnh nhất\n"
            "/strong   — 1D STRONG BUY/SELL (ultra_1d ≥ 9)\n"
            "/ft       — 🔴 Bear FVG 4h  + 15m SELL ≥ 6 (setup SHORT)\n"
            "/ft1h     — 🔴 Bear FVG 1h  + 15m SELL ≥ 6 (setup SHORT)\n"
            "/ft1d     — 🔴 Bear FVG 1d  + 1h  SELL ≥ 6 (setup SHORT)\n"
            "/fb       — 🟢 Bull FVG 4h  + 15m BUY  ≥ 6 (setup LONG)\n"
            "/fb1h     — 🟢 Bull FVG 1h  + 15m BUY  ≥ 6 (setup LONG)\n"
            "/fb1d     — 🟢 Bull FVG 1d  + 1h  BUY  ≥ 6 (setup LONG)\n"
            "/fvgscan [tf] — Toàn market đang trong FVG (mặc định 4h)\n"
            "/fvg BTC [tf] — FVG của 1 token (tf: 5m 15m 1h 4h 1d)\n"
            "/check BTC — Phân tích chi tiết 1 token\n"
            "/debug    — Kiểm tra kết nối API\n"
            "/source   — Xem API đang dùng\n"
            "/status   — Trạng thái bot\n\n"
            "📊 *15M ULTRA Dashboard*\n"
            "• ⚡ SuperTrend AI (tự chọn factor tốt nhất)\n"
            "• UT Bot (trailing stop Long/Short)\n"
            "• Parabolic SAR\n"
            "• SMC Swing + Internal bias\n"
            "• Zone: PREM / EQ↑ / EQ / EQ↓ / DISC\n"
            "• RSI MTF — 6 timeframe (5m→1d)\n"
            "• MTF 3 tầng: Momentum 5m | Bridge 30m | Context 1h+4h+1d\n"
            "• ULTRA Score 0–11 → Verdict (STRONG BUY/BUY/LEAN/NEUTRAL)\n\n"
            "📐 *SXL Dashboard (v2)*\n"
            "• 5 confluences LONG/SHORT\n"
            "• MSB Market Bias + OB/BB Zone\n"
            "• Volume Balance + Spike + Leverage",
            parse_mode="Markdown"
        )

    async def _scan(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔍 Đang quét token (6 TF/symbol)... (~90s)")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text(
                "❌ Không có tín hiệu ultra≥8 lúc này.\n"
                "Dùng /debug để kiểm tra kết nối."
            )
            return

        strong   = [r for r in signals if max(r.ultra_buy_score, r.ultra_sell_score,
                                              r.ultra_1h_buy, r.ultra_1h_sell,
                                              r.ultra_4h_buy, r.ultra_4h_sell,
                                              r.ultra_1d_buy, r.ultra_1d_sell) >= 9]
        mid      = [r for r in signals if max(r.ultra_buy_score, r.ultra_sell_score,
                                              r.ultra_1h_buy, r.ultra_1h_sell,
                                              r.ultra_4h_buy, r.ultra_4h_sell,
                                              r.ultra_1d_buy, r.ultra_1d_sell) == 8]
        premiums = [r for r in signals if r.is_premium]
        spikes   = [r for r in signals if r.is_spike]

        # Gửi summary trước
        await u.message.reply_text(
            f"📊 *Kết quả scan* — {len(signals)} tín hiệu (ultra≥8)\n"
            f"🚀 STRONG (ULTRA≥9): {len(strong)}\n"
            f"✅ BUY/SELL (ULTRA=8): {len(mid)}\n"
            f"⭐ Premium: {len(premiums)}  ⚡ Spike: {len(spikes)}\n"
            f"_(Gửi từng signal bên dưới…)_",
            parse_mode="Markdown"
        )

        # Gửi TẤT CẢ signal — full format, không giới hạn số lượng
        for r in signals:
            await u.message.reply_text(_fmt(r), parse_mode="Markdown")

        await u.message.reply_text(
            f"✅ *Xong!* Đã gửi {len(signals)} tín hiệu.",
            parse_mode="Markdown"
        )

    async def _top(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔍 Đang lấy top tín hiệu (ultra≥8)...")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text("❌ Không có tín hiệu. Dùng /debug kiểm tra.")
            return
        lines = [f"🏆 *Top Tín Hiệu (ultra≥8)* — {len(signals)} token\n"]
        for i, r in enumerate(signals, 1):
            badge = "🚀" if max(r.ultra_buy_score, r.ultra_sell_score) >= 9 else "✅"
            lines.append(f"*#{i}* {badge} {_fmt_short(r)}\n")
        # Chia nhỏ nếu quá 4096 ký tự
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 3800:
                await u.message.reply_text(chunk, parse_mode="Markdown")
                chunk = line
            else:
                chunk += line
        if chunk:
            await u.message.reply_text(chunk, parse_mode="Markdown")

    async def _strong(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """
        /strong — hiển thị các token có ULTRA 1D STRONG BUY hoặc STRONG SELL (≥9).
        Dùng ngưỡng thấp hơn khi scan (bỏ qua min_score bình thường) để không bỏ sót.
        """
        await u.message.reply_text("📅 Đang quét 1D STRONG (ultra_1d ≥ 9)... (~90s)")

        # Scan toàn bộ với ignore_threshold để lấy mọi kết quả, sau đó tự lọc
        symbols = await self.scanner.fetcher.fetch_top_symbols(self.scanner.max_symbols)

        import asyncio
        from scanner import CONCURRENCY
        sem = asyncio.Semaphore(CONCURRENCY)

        async def _fetch_one(sym):
            async with sem:
                return await self.scanner._analyse_one(sym, ignore_threshold=True)

        results = await asyncio.gather(*[_fetch_one(s) for s in symbols])

        # Lọc chỉ giữ token có 1D STRONG BUY hoặc STRONG SELL
        strong_1d = [
            r for r in results
            if r is not None and (r.ultra_1d_buy >= 9 or r.ultra_1d_sell >= 9)
        ]

        # Sort: 1D score cao nhất trước
        strong_1d.sort(
            key=lambda x: max(x.ultra_1d_buy, x.ultra_1d_sell),
            reverse=True,
        )

        if not strong_1d:
            await u.message.reply_text(
                "❌ Không có token nào đạt 1D STRONG (ultra_1d ≥ 9) lúc này.\n"
                "Dùng /scan để xem tín hiệu ngắn hạn."
            )
            return

        buy_cnt  = sum(1 for r in strong_1d if r.ultra_1d_buy >= r.ultra_1d_sell)
        sell_cnt = len(strong_1d) - buy_cnt

        await u.message.reply_text(
            f"📅 *1D STRONG* — {len(strong_1d)} token\n"
            f"🟢 STRONG BUY: {buy_cnt}  |  🔴 STRONG SELL: {sell_cnt}\n"
            f"_(Gửi từng signal bên dưới…)_",
            parse_mode="Markdown"
        )

        for r in strong_1d:
            # Tạo prefix rõ hướng 1D
            if r.ultra_1d_buy >= 9 and r.ultra_1d_buy >= r.ultra_1d_sell:
                label = f"📅🟢 *1D STRONG BUY* — score {r.ultra_1d_buy}/11"
            else:
                label = f"📅🔴 *1D STRONG SELL* — score {r.ultra_1d_sell}/11"
            await u.message.reply_text(
                f"{label}\n\n{_fmt(r)}",
                parse_mode="Markdown"
            )

        await u.message.reply_text(
            f"✅ *Xong!* Đã gửi {len(strong_1d)} token 1D STRONG.",
            parse_mode="Markdown"
        )

    # ── Shared display helper ─────────────────────────────────────────────

    async def _send_fvg_hits(
        self,
        u: Update,
        hits: list[dict],
        direction: str,   # "sell" hoặc "buy"
        fvg_tf: str,
        score_tf: str,
    ):
        """
        Render và gửi kết quả FVG scan (dùng chung cho /ft* và /fb*).
        direction : "sell" → Bear FVG / "buy" → Bull FVG
        """
        is_sell  = (direction == "sell")
        dir_em   = "🔴" if is_sell else "🟢"
        fvg_lbl  = "Bear FVG" if is_sell else "Bull FVG"
        setup    = "SHORT"     if is_sell else "LONG"
        score_key = "sell_score" if is_sell else "buy_score"
        score_lbl = "SELL"       if is_sell else "BUY"

        strong = [h for h in hits if h["tier"] == "🔥"]
        good   = [h for h in hits if h["tier"] == "⚡"]
        watch  = [h for h in hits if h["tier"] == "📌"]

        def _row(h: dict) -> str:
            sym    = h["symbol"].replace("USDT", "")
            ftype  = h.get("fvg_type", direction)
            f_em   = "🔵" if "ifvg" in ftype else dir_em
            f_lbl  = (f"iFVG-{'Bear' if is_sell else 'Bull'}"
                      if "ifvg" in ftype
                      else f"{'Bear' if is_sell else 'Bull'}FVG")
            pos    = "✅trong" if h.get("inside") else "🔔gần"
            ab_mid = "↑" if h["cur_price"] >= h["fvg_mid"] else "↓"
            sc     = h.get(score_key, 0)
            return (
                f"{h['tier']} *{sym}*  `{h['cur_price']:.4f}`  {f_em}{f_lbl} {pos}\n"
                f"  FVG: `{h['fvg_bot']:.4f}` – `{h['fvg_top']:.4f}`  "
                f"Cách mid:`{h['dist_pct']:.2f}%`{ab_mid}  "
                f"{score_lbl}:`{sc}/11`  _{h['age_bars']}nến_\n"
            )

        thr_lbl = "sell≥9" if is_sell else "buy≥9"
        header = (
            f"{dir_em} *{fvg_lbl} {fvg_tf.upper()} + {score_tf} {score_lbl}*"
            f" — {len(hits)} token\n"
            f"🔥 Strong:{len(strong)}  ⚡ Good:{len(good)}  📌 Watch:{len(watch)}\n"
            f"_✅=giá trong FVG  🔔=gần FVG (±0.5%)  →  Setup {setup}_\n"
            f"{'─'*30}\n"
        )

        sections = []
        if strong:
            sections.append(f"🔥 *STRONG* — {thr_lbl} + trong FVG ({len(strong)})\n")
            for h in strong:
                sections.append(_row(h))
        if good:
            sc_thr = "sell≥8" if is_sell else "buy≥8"
            sections.append(f"\n⚡ *GOOD* — {sc_thr} ({len(good)})\n")
            for h in good:
                sections.append(_row(h))
        if watch:
            sc_thr = "sell≥6" if is_sell else "buy≥6"
            sections.append(f"\n📌 *WATCH* — {sc_thr} ({len(watch)})\n")
            for h in watch:
                sections.append(_row(h))

        chunk = header
        for line in sections:
            if len(chunk) + len(line) > 3900:
                await u.message.reply_text(chunk, parse_mode="Markdown")
                chunk = line
            else:
                chunk += line
        if chunk:
            await u.message.reply_text(chunk, parse_mode="Markdown")

    # ── /ft family (Bear FVG + SELL) ─────────────────────────────────────

    async def _ft(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """/ft — Bear FVG 4h + 15m SELL ≥ 6  →  setup SHORT"""
        await u.message.reply_text(
            "🔴 Đang quét *Bear FVG 4h + 15m SELL* toàn market (~60–90s)...",
            parse_mode="Markdown"
        )
        hits = await self.scanner.scan_ft()
        if not hits:
            await u.message.reply_text(
                "❌ Không có setup Bear FVG 4h + SELL 15m lúc này."
            )
            return
        await self._send_fvg_hits(u, hits, "sell", "4h", "15m")

    async def _ft1h(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """/ft1h — Bear FVG 1h + 15m SELL ≥ 6  →  setup SHORT"""
        await u.message.reply_text(
            "🔴 Đang quét *Bear FVG 1h + 15m SELL* toàn market (~60–90s)...",
            parse_mode="Markdown"
        )
        hits = await self.scanner.scan_ft1h()
        if not hits:
            await u.message.reply_text(
                "❌ Không có setup Bear FVG 1h + SELL 15m lúc này."
            )
            return
        await self._send_fvg_hits(u, hits, "sell", "1h", "15m")

    async def _ft1d(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """/ft1d — Bear FVG 1d + 1h SELL ≥ 6  →  setup SHORT"""
        await u.message.reply_text(
            "🔴 Đang quét *Bear FVG 1D + 1h SELL* toàn market (~60–90s)...",
            parse_mode="Markdown"
        )
        hits = await self.scanner.scan_ft1d()
        if not hits:
            await u.message.reply_text(
                "❌ Không có setup Bear FVG 1D + SELL 1h lúc này."
            )
            return
        await self._send_fvg_hits(u, hits, "sell", "1d", "1h")

    # ── /fb family (Bull FVG + BUY) ──────────────────────────────────────

    async def _fb(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """/fb — Bull FVG 4h + 15m BUY ≥ 6  →  setup LONG"""
        await u.message.reply_text(
            "🟢 Đang quét *Bull FVG 4h + 15m BUY* toàn market (~60–90s)...",
            parse_mode="Markdown"
        )
        hits = await self.scanner.scan_fb()
        if not hits:
            await u.message.reply_text(
                "❌ Không có setup Bull FVG 4h + BUY 15m lúc này."
            )
            return
        await self._send_fvg_hits(u, hits, "buy", "4h", "15m")

    async def _fb1h(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """/fb1h — Bull FVG 1h + 15m BUY ≥ 6  →  setup LONG"""
        await u.message.reply_text(
            "🟢 Đang quét *Bull FVG 1h + 15m BUY* toàn market (~60–90s)...",
            parse_mode="Markdown"
        )
        hits = await self.scanner.scan_fb1h()
        if not hits:
            await u.message.reply_text(
                "❌ Không có setup Bull FVG 1h + BUY 15m lúc này."
            )
            return
        await self._send_fvg_hits(u, hits, "buy", "1h", "15m")

    async def _fb1d(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """/fb1d — Bull FVG 1d + 1h BUY ≥ 6  →  setup LONG"""
        await u.message.reply_text(
            "🟢 Đang quét *Bull FVG 1D + 1h BUY* toàn market (~60–90s)...",
            parse_mode="Markdown"
        )
        hits = await self.scanner.scan_fb1d()
        if not hits:
            await u.message.reply_text(
                "❌ Không có setup Bull FVG 1D + BUY 1h lúc này."
            )
            return
        await self._send_fvg_hits(u, hits, "buy", "1d", "1h")

    async def _fvgscan(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """
        /fvgscan [tf]
        Quét toàn bộ market (chỉ fetch TF được chỉ định, mặc định 4h).
        Tìm tất cả token có giá hiện tại đang nằm TRONG vùng FVG.
        Sort theo khoảng cách tới mid FVG (gần nhất trước).
        """
        args    = c.args
        tf      = args[0].lower() if args else "4h"
        valid_tfs = {"5m", "15m", "30m", "1h", "4h", "1d"}
        if tf not in valid_tfs:
            await u.message.reply_text(
                f"⚠️ Timeframe `{tf}` không hợp lệ.\nDùng: 5m | 15m | 30m | 1h | 4h | 1d"
            )
            return

        await u.message.reply_text(
            f"📐 Đang quét *toàn market* — FVG `{tf}` (~60–90s)...\n"
            f"_Chỉ lấy token giá đang NẰM TRONG vùng FVG_",
            parse_mode="Markdown"
        )

        hits = await self.scanner.scan_fvg(tf=tf)

        if not hits:
            await u.message.reply_text(
                f"❌ Không có token nào đang nằm trong FVG {tf} lúc này."
            )
            return

        # Phân loại
        bull_hits  = [h for h in hits if h["fvg_type"] == "bull"]
        bear_hits  = [h for h in hits if h["fvg_type"] == "bear"]
        ifvg_hits  = [h for h in hits if h["fvg_type"] not in ("bull", "bear")]

        def _row(h: dict) -> str:
            t     = h["fvg_type"]
            emoji = "🟢" if t == "bull" else ("🔴" if t == "bear" else "🔵")
            side  = "Bull" if t == "bull" else ("Bear" if t == "bear" else "iFVG")
            sym   = h["symbol"].replace("USDT", "")
            above_mid = "↑mid" if h["cur_price"] >= h["fvg_mid"] else "↓mid"
            return (
                f"{emoji} *{sym}*  `{h['cur_price']:.4f}`  [{side}]\n"
                f"  Vùng: `{h['fvg_bot']:.4f}` – `{h['fvg_top']:.4f}`"
                f"  Gap:`{h['gap_pct']:.2f}%`  Cách mid:`{h['dist_pct']:.2f}%`{above_mid}"
                f"  _{h['age_bars']}nến_\n"
            )

        header = (
            f"📐 *FVG Scan {tf.upper()}* — {len(hits)} token trong FVG\n"
            f"🟢 Bull: {len(bull_hits)}  🔴 Bear: {len(bear_hits)}  🔵 iFVG: {len(ifvg_hits)}\n"
            f"{'─'*30}\n"
        )

        # Build các section, gửi theo chunk ≤ 4000 ký tự
        sections = []
        if bull_hits:
            sections.append(f"🟢 *Bullish FVG* ({len(bull_hits)} token)\n")
            for h in bull_hits:
                sections.append(_row(h))
        if bear_hits:
            sections.append(f"\n🔴 *Bearish FVG* ({len(bear_hits)} token)\n")
            for h in bear_hits:
                sections.append(_row(h))
        if ifvg_hits:
            sections.append(f"\n🔵 *iFVG* ({len(ifvg_hits)} token)\n")
            for h in ifvg_hits:
                sections.append(_row(h))

        # Gom thành các chunk
        chunk = header
        for line in sections:
            if len(chunk) + len(line) > 3900:
                await u.message.reply_text(chunk, parse_mode="Markdown")
                chunk = line
            else:
                chunk += line
        if chunk:
            await u.message.reply_text(chunk, parse_mode="Markdown")

    async def _fvg(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        """
        /fvg BTC [tf]
        tf mặc định: 15m. Hỗ trợ: 5m 15m 30m 1h 4h 1d
        Hiển thị Bullish FVG, Bearish FVG, iFVG còn hiệu lực gần giá nhất.
        Logic port đúng từ Pine Script Section T3.
        """
        args = c.args
        if not args:
            await u.message.reply_text(
                "⚠️ Dùng: /fvg BTC hoặc /fvg BTCUSDT 1h\n"
                "Timeframe hỗ trợ: 5m 15m 30m 1h 4h 1d"
            )
            return

        sym = args[0].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"

        tf_input = args[1].lower() if len(args) > 1 else "15m"
        valid_tfs = {"5m", "15m", "30m", "1h", "4h", "1d"}
        if tf_input not in valid_tfs:
            await u.message.reply_text(
                f"⚠️ Timeframe `{tf_input}` không hợp lệ.\n"
                f"Dùng: 5m | 15m | 30m | 1h | 4h | 1d"
            )
            return

        await u.message.reply_text(
            f"📐 Đang tính FVG cho *{sym}* ({tf_input})...",
            parse_mode="Markdown"
        )

        df = await self.scanner.fetcher.fetch_ohlcv(sym, tf_input, limit=100)
        if df is None or len(df) < 3:
            await u.message.reply_text(
                f"❌ Không lấy được dữ liệu {sym} ({tf_input}).\n"
                f"Dùng /debug để kiểm tra kết nối."
            )
            return

        result = detect_fvg(df, min_gap_pct=0.0, max_keep=5)
        cur    = result["cur_price"]
        bulls  = result["bull_fvgs"]
        bears  = result["bear_fvgs"]
        ifvgs  = result["ifvgs"]

        def _fmt_fvg(fvg: dict, label: str, emoji: str) -> str:
            top    = fvg["top"]
            bot    = fvg["bottom"]
            mid    = (top + bot) / 2
            gap    = fvg["gap_pct"]
            age    = fvg["age_bars"]
            dist   = abs(mid - cur) / cur * 100 if cur > 0 else 0
            above  = "⬆️ phía TRÊN" if mid > cur else "⬇️ phía DƯỚI"
            status = fvg.get("status", "active")
            status_tag = ""
            if status == "ifvg_bull":
                status_tag = " _(iFVG — đã phá lên)_"
            elif status == "ifvg_bear":
                status_tag = " _(iFVG — đã phá xuống)_"
            return (
                f"{emoji} *{label}*{status_tag}\n"
                f"  Top: `{top:.4f}` | Bot: `{bot:.4f}` | Mid: `{mid:.4f}`\n"
                f"  Gap: `{gap:.3f}%` | Cách giá: `{dist:.2f}%` {above}\n"
                f"  ⏳ {age} nến trước\n"
            )

        lines = [
            f"📐 *FVG — {sym}* `({tf_input})`\n"
            f"💰 Giá hiện tại: `{cur:.4f}`\n"
            f"{'─' * 30}\n"
        ]

        if bulls:
            lines.append(f"🟢 *Bullish FVG* ({len(bulls)} vùng)\n")
            for i, fvg in enumerate(bulls, 1):
                lines.append(_fmt_fvg(fvg, f"Bull FVG #{i}", "🟩"))
        else:
            lines.append("🟢 *Bullish FVG*: Không có vùng hiệu lực\n")

        lines.append(f"{'─' * 30}\n")

        if bears:
            lines.append(f"🔴 *Bearish FVG* ({len(bears)} vùng)\n")
            for i, fvg in enumerate(bears, 1):
                lines.append(_fmt_fvg(fvg, f"Bear FVG #{i}", "🟥"))
        else:
            lines.append("🔴 *Bearish FVG*: Không có vùng hiệu lực\n")

        lines.append(f"{'─' * 30}\n")

        if ifvgs:
            lines.append(f"🔵 *iFVG* ({len(ifvgs)} vùng — đã bị phá nhưng chưa hoàn toàn)\n")
            for i, fvg in enumerate(ifvgs, 1):
                dir_lbl = "Bull iFVG" if fvg.get("status") == "ifvg_bull" else "Bear iFVG"
                lines.append(_fmt_fvg(fvg, f"{dir_lbl} #{i}", "🔷"))
        else:
            lines.append("🔵 *iFVG*: Không có\n")

        lines.append(
            f"{'─' * 30}\n"
            f"_📌 Dùng /fvg {sym[:-4]} 1h hoặc /fvg {sym[:-4]} 4h để xem TF khác_"
        )

        msg = "".join(lines)
        # Chia nhỏ nếu quá dài
        if len(msg) > 4096:
            chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
            for chunk in chunks:
                await u.message.reply_text(chunk, parse_mode="Markdown")
        else:
            await u.message.reply_text(msg, parse_mode="Markdown")

    async def _check(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        args = c.args
        if not args:
            await u.message.reply_text("⚠️ Dùng: /check BTC hoặc /check BTCUSDT")
            return
        sym = args[0].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        await u.message.reply_text(f"🔍 Đang phân tích {sym} (6 TF)...")
        r = await self.scanner.scan_symbol(sym)
        if r is None:
            await u.message.reply_text(
                f"❌ Không lấy được data cho {sym}.\nDùng /debug kiểm tra kết nối."
            )
            return
        await u.message.reply_text(_fmt(r), parse_mode="Markdown")

    async def _source(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        import fetcher as f_module
        base = getattr(f_module, "BASE", "unknown")
        await u.message.reply_text(
            f"📡 *API Source*\n"
            f"Base URL: `{base}`\n"
            f"Class: `{self.scanner.fetcher.__class__.__name__}`",
            parse_mode="Markdown"
        )

    async def _debug(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔧 Đang debug...")
        import aiohttp
        import fetcher as f_module
        base    = getattr(f_module, "BASE", "https://www.okx.com")
        fetcher = self.scanner.fetcher
        lines   = [f"📡 API: `{base}`"]

        try:
            session = await fetcher._get_session()
            async with session.get(
                f"{base}/api/v5/public/time",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                body = await resp.json()
                lines.append(f"🌐 Ping: HTTP {resp.status} — {body.get('code','?')}")
        except Exception as e:
            lines.append(f"🌐 Ping FAILED: {type(e).__name__}: {e}")

        for sym in ["BTCUSDT", "ETHUSDT"]:
            try:
                df5  = await fetcher.fetch_ohlcv(sym, "5m",  10)
                df15 = await fetcher.fetch_ohlcv(sym, "15m", 10)
                df1d = await fetcher.fetch_ohlcv(sym, "1d",  10)
                ok5  = f"{len(df5)} bars"  if df5  is not None else "FAIL"
                ok15 = f"{len(df15)} bars" if df15 is not None else "FAIL"
                ok1d = f"{len(df1d)} bars" if df1d is not None else "FAIL"
                close = df5["close"].iloc[-1] if df5 is not None else "?"
                lines.append(f"✅ {sym}: 5m={ok5} 15m={ok15} 1d={ok1d} | close={close}")
            except Exception as e:
                lines.append(f"❌ {sym}: {type(e).__name__}: {str(e)[:80]}")

        syms = await fetcher.fetch_top_symbols(10)
        lines.append(f"\n📋 Symbols ({len(syms)} total): {syms[:5]}")
        lines.append(f"🎯 Min score: {self.scanner.min_score}")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _status(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            f"✅ *Bot v3.0 Running*\n"
            f"📊 Cooldown tokens: {len(self.scanner._last_alert)}\n"
            f"🎯 Min score: {self.scanner.min_score}\n"
            f"🔢 Max tokens/scan: {self.scanner.max_symbols}\n\n"
            f"🔧 *Engine*\n"
            f"• SXL Sniper (5 confluences, 0–10pt)\n"
            f"• ST AI + UT Bot + SAR + SMC\n"
            f"• RSI MTF 6 TF\n"
            f"• MTF 3 tầng (5m/30m/1h+4h+1d)\n"
            f"• ULTRA Score 0–11\n"
            f"• Zone Classifier\n"
            f"• Spike Detector + Leverage Advisor\n\n"
            f"Dùng /debug để test kết nối API",
            parse_mode="Markdown"
        )

    async def send_signal(self, chat_id: str, result: SignalResult):
        """Gửi auto alert — ưu tiên ULTRA verdict."""
        try:
            ultra_max = max(result.ultra_buy_score, result.ultra_sell_score,
                        result.ultra_1h_buy,    result.ultra_1h_sell,
                        result.ultra_4h_buy,    result.ultra_4h_sell,
                        result.ultra_1d_buy,    result.ultra_1d_sell)
            if ultra_max >= 9:
                prefix = "🚨🚀 *AUTO ALERT — STRONG*"
            elif ultra_max >= 7:
                prefix = "🚨✅ *AUTO ALERT*"
            else:
                prefix = "🚨 *AUTO ALERT*"
            if result.is_premium:
                prefix += " ⭐ PREMIUM"
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"{prefix}\n\n{_fmt(result)}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"send_signal {chat_id}: {e}")

    def run_polling(self):
        self.app.run_polling(drop_pending_updates=True)
