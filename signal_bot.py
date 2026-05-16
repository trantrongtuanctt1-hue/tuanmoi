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
from signals import SignalResult

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

    # ── Ultra score bar ──────────────────────────────────────────────────
    ultra_max    = max(r.ultra_buy_score, r.ultra_sell_score)
    ultra_bar    = "█" * ultra_max + "░" * (11 - ultra_max)
    ultra_side   = "↑" if r.ultra_buy_score >= r.ultra_sell_score else "↓"
    ultra_color  = "🟢" if r.ultra_verdict_color == "green" else ("🔴" if r.ultra_verdict_color == "red" else "⬜")

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
        f"🏆 *ULTRA Score*\n"
        f"  {ultra_color} BUY {r.ultra_buy_score}↑ / SELL {r.ultra_sell_score}↓ /11\n"
        f"  `{ultra_bar}` {ultra_side}\n"
        f"  Verdict: *{r.ultra_verdict}*\n"
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

    return (
        f"{dir_emoji} *{r.symbol}*{prem}  SXL:`{r.score}/10`  ULTRA:`{r.ultra_buy_score}↑{r.ultra_sell_score}↓`{spk}\n"
        f"  {v_em} *{r.ultra_verdict}*\n"
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
            ("start",  self._start),
            ("help",   self._help),
            ("scan",   self._scan),
            ("top",    self._top),
            ("check",  self._check),
            ("status", self._status),
            ("debug",  self._debug),
            ("source", self._source),
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
            "/scan — Quét tất cả token, alert signal đủ điều kiện\n"
            "/top  — Top 5 tín hiệu mạnh nhất\n"
            "/check BTC — Phân tích chi tiết 1 token\n"
            "/debug — Kiểm tra kết nối API\n"
            "/source — Xem API đang dùng\n"
            "/status — Trạng thái bot\n\n"
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
                "❌ Không có tín hiệu đủ mạnh lúc này.\n"
                "Dùng /debug để kiểm tra kết nối."
            )
            return
        for r in signals[:10]:
            await u.message.reply_text(_fmt(r), parse_mode="Markdown")
        spikes   = [r for r in signals if r.is_spike]
        premiums = [r for r in signals if r.is_premium]
        strong   = [r for r in signals if max(r.ultra_buy_score, r.ultra_sell_score) >= 9]
        summary = (
            f"✅ *Xong!* Tổng: {len(signals)} tín hiệu\n"
            f"🚀 STRONG (ULTRA≥9): {len(strong)}\n"
            f"⭐ Premium SXL: {len(premiums)}\n"
            f"⚡ Spike alerts: {len(spikes)}"
        )
        await u.message.reply_text(summary, parse_mode="Markdown")

    async def _top(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔍 Đang lấy top tín hiệu...")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text("❌ Không có tín hiệu. Dùng /debug kiểm tra.")
            return
        lines = ["🏆 *Top 5 Tín Hiệu Mạnh Nhất*\n"]
        for i, r in enumerate(signals[:5], 1):
            lines.append(f"*#{i}* {_fmt_short(r)}\n")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

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
            ultra_max = max(result.ultra_buy_score, result.ultra_sell_score)
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
