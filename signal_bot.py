"""
Telegram bot — commands: /scan /top /check /status /debug /source /help
Dashboard đầy đủ: SXL Sniper + MSB-OB + Vol Balance + Spike + Leverage
"""
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scanner import Scanner
from signals import SignalResult

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# FORMAT — dashboard chi tiết giống PineScript
# ══════════════════════════════════════════════════════════════════════════

def _fmt(r: SignalResult) -> str:
    """Format đầy đủ — 1 message/signal."""
    if r.direction == "LONG":
        dir_emoji = "🟢"
    elif r.direction == "SHORT":
        dir_emoji = "🔴"
    else:
        dir_emoji = "⚪"

    premium_tag = "★ PREMIUM" if r.is_premium else "Standard"
    premium_line = f"⭐ *{premium_tag}*\n" if r.is_premium else ""

    # SXL confluence bars (✓/✗)
    def _c(v): return "✓" if v else "✗"

    # Spike line
    if r.is_spike:
        spk_dir = "▲" if r.spike_direction == "BULL" else "▼"
        spike_line = f"⚡ *Spike {spk_dir} {r.spike_pct}%* — Cẩn thận vào lệnh!\n"
    else:
        spike_line = f"⚡ Spike: OK ({r.spike_pct}%)\n"

    # Volume line
    vol_icon = "📈" if r.bull_pct > r.bear_pct else "📉"
    vol_dom  = " ⚠️ Dominant" if max(r.bull_pct, r.bear_pct) >= 65 else ""
    vol_confirm_txt = "✓ Confirms" if r.vol_confirm else "✗ Against"

    # Leverage
    lev_bar = "█" * min(r.leverage, 10) + "░" * max(0, 10 - r.leverage)

    # Reasons
    tags = " | ".join(r.reasons[:8]) if r.reasons else "—"

    msg = (
        f"{dir_emoji} *{r.symbol}*  [{r.direction}]  Score: *{r.score}/10*\n"
        f"{premium_line}"
        f"{'─' * 30}\n"
        f"💰 Price  : `{r.price}`\n"
        f"🛑 SL     : `{r.sl}`\n"
        f"🎯 TP1    : `{r.tp1}`\n"
        f"🎯 TP2    : `{r.tp2}`\n"
        f"{'─' * 30}\n"
        f"📐 *SXL Confluences*\n"
        f"  LONG  {r.l_score}/5 | SHORT {r.s_score}/5\n"
        f"  MSB Bias : {r.market_bias}  |  OB/BB Zone: {'✓' if r.in_ob_zone else '✗'}\n"
        f"{'─' * 30}\n"
        f"{vol_icon} *Volume Balance*\n"
        f"  ▲ Bull: {r.bull_pct}%  |  ▼ Bear: {r.bear_pct}%{vol_dom}\n"
        f"  Vol {vol_confirm_txt} signal\n"
        f"{'─' * 30}\n"
        f"{spike_line}"
        f"{'─' * 30}\n"
        f"🎚 *Leverage Advisor*\n"
        f"  Gợi ý: *{r.leverage}x*  {r.lev_risk}\n"
        f"  ATR% = {r.atr_pct}%  [{lev_bar}]\n"
        f"{'─' * 30}\n"
        f"📊 {tags}"
    )
    return msg


def _fmt_short(r: SignalResult) -> str:
    """Format ngắn cho /top (list)."""
    dir_emoji = "🟢" if r.direction == "LONG" else ("🔴" if r.direction == "SHORT" else "⚪")
    prem = " ★" if r.is_premium else ""
    spk  = f" ⚡{r.spike_pct}%" if r.is_spike else ""
    return (
        f"{dir_emoji} *{r.symbol}*{prem}  [{r.direction}] `{r.score}/10`{spk}\n"
        f"  SXL L{r.l_score}/S{r.s_score} | MSB:{r.market_bias} | "
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
            "🤖 *SXL Sniper + MSB-OB + Vol Bot* sẵn sàng!\n"
            "Dùng /help xem lệnh.",
            parse_mode="Markdown"
        )

    async def _help(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            "📖 *Lệnh*\n"
            "/scan — Quét tất cả token, alert score ≥ threshold\n"
            "/top  — Top 5 tín hiệu mạnh nhất (format ngắn)\n"
            "/check BTC — Phân tích chi tiết 1 token\n"
            "/debug — Kiểm tra kết nối API\n"
            "/source — Xem API đang dùng\n"
            "/status — Trạng thái bot\n\n"
            "📊 *Dashboard bao gồm*\n"
            "• SXL Sniper (5 confluences Long/Short)\n"
            "• MSB Market Bias + OB/BB Zone\n"
            "• Volume Balance (Bull% vs Bear%)\n"
            "• ⚡ Spike Detector\n"
            "• 🎚 Leverage Advisor\n"
            "• ★ Premium Signal khi SXL + OB + MSB aligned",
            parse_mode="Markdown"
        )

    async def _scan(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔍 Đang quét token... (~60s)")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text(
                "❌ Không có tín hiệu đủ mạnh lúc này.\n"
                "Dùng /debug để kiểm tra kết nối."
            )
            return
        for r in signals[:10]:
            await u.message.reply_text(_fmt(r), parse_mode="Markdown")
        # Summary spike cảnh báo
        spikes = [r for r in signals if r.is_spike]
        premiums = [r for r in signals if r.is_premium]
        summary = (
            f"✅ *Xong!* Tổng: {len(signals)} tín hiệu\n"
            f"⭐ Premium: {len(premiums)}\n"
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
        await u.message.reply_text(f"🔍 Đang phân tích {sym}...")
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

        # Ping
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

        # Fetch OHLCV
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            try:
                df = await fetcher.fetch_ohlcv(sym, "5m", 5)
                if df is not None and len(df) > 0:
                    lines.append(f"✅ {sym}: {len(df)} bars | close={df['close'].iloc[-1]:.4f}")
                else:
                    lines.append(f"❌ {sym}: fetch trả về None/empty")
            except Exception as e:
                lines.append(f"❌ {sym}: {type(e).__name__}: {str(e)[:80]}")

        # Symbol list
        syms = await fetcher.fetch_top_symbols(10)
        lines.append(f"\n📋 Symbols ({len(syms)} total): {syms[:5]}")
        lines.append(f"🎯 Min score: {self.scanner.min_score}")

        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _status(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            f"✅ *Bot Running*\n"
            f"📊 Cooldown tokens: {len(self.scanner._last_alert)}\n"
            f"🎯 Min score: {self.scanner.min_score}/10\n"
            f"🔢 Max tokens/scan: {self.scanner.max_symbols}\n\n"
            f"📐 *Engine*: SXL Sniper + MSB-OB + Vol Balance\n"
            f"⚡ Spike Detector: ON\n"
            f"🎚 Leverage Advisor: ON\n\n"
            f"Dùng /debug để test kết nối API",
            parse_mode="Markdown"
        )

    async def send_signal(self, chat_id: str, result: SignalResult):
        """Gửi auto alert — Premium signal ưu tiên."""
        try:
            prefix = "🚨 *AUTO ALERT*" + (" ⭐ PREMIUM" if result.is_premium else "")
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"{prefix}\n\n{_fmt(result)}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"send_signal {chat_id}: {e}")

    def run_polling(self):
        self.app.run_polling(drop_pending_updates=True)
