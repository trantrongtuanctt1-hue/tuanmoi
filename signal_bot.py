"""
Telegram bot — commands: /scan /top /check /status /debug /help
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
        ]:
            self.app.add_handler(CommandHandler(cmd, fn))

    async def _start(self, u: Update, c):
        await u.message.reply_text("🤖 *15M ULTRA Signal Bot* sẵn sàng!\nDùng /help xem lệnh.", parse_mode="Markdown")

    async def _help(self, u: Update, c):
        await u.message.reply_text(
            "📖 *Lệnh*\n"
            "/scan — Quét 200 token, alert score ≥5\n"
            "/top  — Top 5 tín hiệu mạnh nhất\n"
            "/check BTC — Phân tích 1 token\n"
            "/debug — Kiểm tra kết nối + score BTC/ETH/SOL\n"
            "/status — Trạng thái bot\n",
            parse_mode="Markdown"
        )

    async def _scan(self, u: Update, c):
        await u.message.reply_text("🔍 Đang quét 200 token... (~60s)")
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

    async def _debug(self, u: Update, c):
        """Kiểm tra fetch + score cho BTC/ETH/SOL."""
        await u.message.reply_text("🔧 Đang debug...")
        import aiohttp, traceback
        fetcher = self.scanner.fetcher
        lines = []

        # 1. Test raw HTTP tới Binance
        try:
            session = await fetcher._get_session()
            async with session.get(
                "https://fapi.binance.com/fapi/v1/ping", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                lines.append(f"🌐 Binance ping: HTTP {resp.status}")
        except Exception as e:
            lines.append(f"🌐 Binance ping FAILED: {type(e).__name__}: {e}")

        # 2. Test fetch OHLCV với error chi tiết
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            try:
                session = await fetcher._get_session()
                async with session.get(
                    "https://fapi.binance.com/fapi/v1/klines",
                    params={"symbol": sym, "interval": "5m", "limit": 5},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    status = resp.status
                    body = await resp.text()
                    if status == 200:
                        lines.append(f"✅ {sym}: HTTP 200 OK — {body[:80]}")
                    else:
                        lines.append(f"❌ {sym}: HTTP {status} — {body[:120]}")
            except Exception as e:
                lines.append(f"❌ {sym}: {type(e).__name__}: {str(e)[:120]}")

        # 3. Symbol list
        syms = await fetcher.fetch_top_symbols(10)
        lines.append(f"\n📋 Symbol list ({len(syms)} total): {syms[:5]}")
        lines.append(f"🎯 Min score: {self.scanner.min_score}")

        await u.message.reply_text("\n".join(lines))

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
