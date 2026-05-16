"""
Telegram bot — commands: /scan /top /check /status /debug /source /help
"""
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scanner import Scanner
from signals import SignalResult

logger = logging.getLogger(__name__)


def _fmt(r: SignalResult) -> str:
    emoji = "🟢" if r.direction == "LONG" else ("🔴" if r.direction == "SHORT" else "⚪")
    tags  = " | ".join(r.reasons[:8])
    return (
        f"{emoji} *{r.symbol}* [{r.direction}] Score: *{r.score}/10*\n"
        f"💰 Price : `{r.price}`\n"
        f"🛑 SL    : `{r.sl}`\n"
        f"🎯 TP1   : `{r.tp1}`\n"
        f"🎯 TP2   : `{r.tp2}`\n"
        f"📊 {tags}"
    )


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

    async def _start(self, u: Update, c):
        await u.message.reply_text("🤖 *15M ULTRA Signal Bot* sẵn sàng!\nDùng /help xem lệnh.", parse_mode="Markdown")

    async def _help(self, u: Update, c):
        await u.message.reply_text(
            "📖 *Lệnh*\n"
            "/scan — Quét token, alert score ≥5\n"
            "/top  — Top 5 tín hiệu mạnh nhất\n"
            "/check BTC — Phân tích 1 token\n"
            "/debug — Kiểm tra kết nối API\n"
            "/source — Xem API đang dùng\n"
            "/status — Trạng thái bot\n",
            parse_mode="Markdown"
        )

    async def _scan(self, u: Update, c):
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
        await u.message.reply_text(f"✅ Xong. Tổng: {len(signals)} tín hiệu.")

    async def _top(self, u: Update, c):
        await u.message.reply_text("🔍 Đang lấy top tín hiệu...")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text("❌ Không có tín hiệu. Dùng /debug kiểm tra.")
            return
        for r in signals[:5]:
            await u.message.reply_text(_fmt(r), parse_mode="Markdown")

    async def _check(self, u: Update, c):
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
            await u.message.reply_text(f"❌ Không lấy được data cho {sym}.\nDùng /debug kiểm tra kết nối.")
            return
        await u.message.reply_text(_fmt(r), parse_mode="Markdown")

    async def _source(self, u: Update, c):
        """Hiển thị API đang dùng và version."""
        import fetcher as f_module
        base = getattr(f_module, "BASE", "unknown")
        await u.message.reply_text(
            f"📡 *API Source*\n"
            f"Base URL: `{base}`\n"
            f"Class: `{self.scanner.fetcher.__class__.__name__}`",
            parse_mode="Markdown"
        )

    async def _debug(self, u: Update, c):
        """Kiểm tra kết nối OKX."""
        await u.message.reply_text("🔧 Đang debug...")
        import aiohttp
        import fetcher as f_module
        base = getattr(f_module, "BASE", "https://www.okx.com")
        fetcher = self.scanner.fetcher
        lines = [f"📡 API: `{base}`"]

        # 1. Ping
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

        # 2. Fetch OHLCV
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            try:
                df = await fetcher.fetch_ohlcv(sym, "5m", 5)
                if df is not None and len(df) > 0:
                    lines.append(f"✅ {sym}: {len(df)} bars | close={df['close'].iloc[-1]:.4f}")
                else:
                    lines.append(f"❌ {sym}: fetch trả về None/empty")
            except Exception as e:
                lines.append(f"❌ {sym}: {type(e).__name__}: {str(e)[:80]}")

        # 3. Symbol list
        syms = await fetcher.fetch_top_symbols(10)
        lines.append(f"\n📋 Symbols ({len(syms)} total): {syms[:5]}")
        lines.append(f"🎯 Min score: {self.scanner.min_score}")

        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _status(self, u: Update, c):
        await u.message.reply_text(
            f"✅ Bot running\n"
            f"📊 Cooldown tokens: {len(self.scanner._last_alert)}\n"
            f"🎯 Min score: {self.scanner.min_score}/10\n"
            f"🔢 Max tokens/scan: {self.scanner.max_symbols}\n\n"
            f"Dùng /debug để test kết nối API"
        )

    async def send_signal(self, chat_id: str, result: SignalResult):
        try:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"🚨 *AUTO ALERT*\n\n{_fmt(result)}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"send_signal {chat_id}: {e}")

    def run_polling(self):
        self.app.run_polling(drop_pending_updates=True)
