"""
Telegram bot — commands: /scan /top /check /status /help
"""
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.scanner import Scanner
from src.signals import SignalResult

logger = logging.getLogger(__name__)


def _format_signal(r: SignalResult) -> str:
    emoji  = "🟢" if r.direction == "LONG" else ("🔴" if r.direction == "SHORT" else "⚪")
    tags   = " | ".join(r.reasons[:6])
    return (
        f"{emoji} *{r.symbol}* [{r.direction}] Score: {r.score}/11\n"
        f"💰 Price : `{r.price}`\n"
        f"🛑 SL    : `{r.sl}`\n"
        f"🎯 TP1   : `{r.tp1}`\n"
        f"🎯 TP2   : `{r.tp2}`\n"
        f"📊 Tags  : {tags}"
    )


class TelegramBot:
    def __init__(self, token: str, scanner: Scanner):
        self.token   = token
        self.scanner = scanner
        self.app     = Application.builder().token(token).build()
        self._register()

    def _register(self):
        self.app.add_handler(CommandHandler("start",  self._start))
        self.app.add_handler(CommandHandler("help",   self._help))
        self.app.add_handler(CommandHandler("scan",   self._scan))
        self.app.add_handler(CommandHandler("top",    self._top))
        self.app.add_handler(CommandHandler("check",  self._check))
        self.app.add_handler(CommandHandler("status", self._status))

    # ── handlers ────────────────────────────────────────────────────────────

    async def _start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 *15M ULTRA Signal Bot* đã sẵn sàng!\n\n"
            "Dùng /help để xem lệnh.",
            parse_mode="Markdown",
        )

    async def _help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📖 *Lệnh*\n"
            "/scan — Quét toàn bộ 500 token, gửi tín hiệu mạnh\n"
            "/top — Top 5 tín hiệu mới nhất\n"
            "/check BTC — Phân tích 1 token cụ thể\n"
            "/status — Trạng thái bot\n",
            parse_mode="Markdown",
        )

    async def _scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Đang quét 500 token... (~60s)")
        signals = await self.scanner.scan_all()
        if not signals:
            await update.message.reply_text("❌ Không có tín hiệu đủ mạnh lúc này.")
            return
        for r in signals[:10]:
            await update.message.reply_text(_format_signal(r), parse_mode="Markdown")
        await update.message.reply_text(f"✅ Xong. Tổng: {len(signals)} tín hiệu.")

    async def _top(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Đang lấy top tín hiệu...")
        signals = await self.scanner.scan_all()
        if not signals:
            await update.message.reply_text("❌ Không có tín hiệu.")
            return
        for r in signals[:5]:
            await update.message.reply_text(_format_signal(r), parse_mode="Markdown")

    async def _check(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = ctx.args
        if not args:
            await update.message.reply_text("⚠️ Dùng: /check BTC hoặc /check BTCUSDT")
            return
        symbol = args[0].upper()
        await update.message.reply_text(f"🔍 Đang phân tích {symbol}...")
        r = await self.scanner.scan_symbol(symbol)
        if r is None:
            await update.message.reply_text(f"❌ Không đủ dữ liệu cho {symbol}.")
            return
        await update.message.reply_text(_format_signal(r), parse_mode="Markdown")

    async def _status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        cooldowns = len(self.scanner._last_alert)
        await update.message.reply_text(
            f"✅ Bot đang chạy\n"
            f"📊 Tokens trong cooldown: {cooldowns}\n"
            f"🎯 Min score: {self.scanner.min_score}/11\n"
            f"🔢 Max tokens/scan: {self.scanner.max_symbols}"
        )

    # ── public API ──────────────────────────────────────────────────────────

    async def send_signal(self, chat_id: str, result: SignalResult):
        """Gọi từ scheduler để push alert tự động"""
        try:
            await self.app.bot.send_message(
                chat_id    = chat_id,
                text       = f"🚨 *AUTO ALERT*\n\n{_format_signal(result)}",
                parse_mode = "Markdown",
            )
        except Exception as e:
            logger.error(f"send_signal {chat_id}: {e}")

    def run_polling(self):
        self.app.run_polling(drop_pending_updates=True)
