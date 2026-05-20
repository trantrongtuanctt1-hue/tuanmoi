"""
Telegram bot — Ceez Prime + Buy Sell Signal
Commands:
  /scan        — Quét toàn market (4H ctx + 1H entry)
  /scan4h1h    — 4H ctx + 1H entry  (default)
  /scan1d4h    — 1D ctx + 4H entry  (swing)
  /scan1h15m   — 1H ctx + 15m entry (intraday)
  /top         — Top signal dạng rút gọn
  /check BTC   — Phân tích chi tiết 1 token
  /status      — Trạng thái bot
  /debug       — Test kết nối
  /help        — Danh sách lệnh
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
    return "✅" if v else "❌"

def _arr(v: bool) -> str:
    return "▲" if v else "▼"


def _score_bar(score: int, total: int = 7) -> str:
    filled = min(score, total)
    return "█" * filled + "░" * (total - filled)


def _dir_emoji(direction: str) -> str:
    return {"LONG": "🟢", "SHORT": "🔴"}.get(direction, "⚪")


def _fresh_tag(r: SignalResult) -> str:
    if r.signal_fresh:
        return f"🆕FRESH({r.cross_bars_ago}n)"
    return f"📊{r.cross_bars_ago}n ago"


def _fib_icon(zone: str) -> str:
    return {
        "DISC": "🟢", "EQ↓": "🟡", "EQ": "⚪",
        "EQ↑": "🟡", "PREM": "🔴",
    }.get(zone, "⚪")


# ══════════════════════════════════════════════════════════════════════════
# FORMAT FULL  (/check, /scan)
# ══════════════════════════════════════════════════════════════════════════

def _fmt(r: SignalResult, ctx_tf: str = "4H", entry_tf: str = "1H") -> str:
    de   = _dir_emoji(r.direction)
    bar  = _score_bar(r.score)
    ftag = _fresh_tag(r)

    # ── SL/TP block ───────────────────────────────────────────────────────
    sl_tp_block = ""
    if r.direction != "NEUTRAL":
        sl_tp_block = (
            f"{'─' * 30}\n"
            f"💰 Entry  : `{r.price}`\n"
            f"🛑 SL     : `{r.sl}`  (-{r.risk_pct:.2f}%)\n"
            f"🎯 TP1(1R): `{r.tp1}`\n"
            f"🎯 TP2(2R): `{r.tp2}`\n"
            f"🏁 TP Final({r.rr:.1f}R): `{r.tp_final}`\n"
            f"📐 ATR    : `{r.atr:.6f}`\n"
        )

    # ── Context block (Ceez Prime) ────────────────────────────────────────
    struct_str = "/".join(r.struct_labels) if r.struct_labels else "N/A"
    fib_icon   = _fib_icon(r.fib_zone)

    ctx_block = (
        f"{'─' * 30}\n"
        f"📊 *Ceez Prime — {ctx_tf} Context* `{r.score}/7`\n"
        f"  `{bar}`\n"
        f"  EMA Stack : {_yn(r.ema_stack)}  "
        f"13={r.ema_e13:.4f} 20={r.ema_e20:.4f}\n"
        f"  50={r.ema_e50:.4f} 200={r.ema_e200:.4f}\n"
        f"  LinReg    : {_yn(r.linreg_bull)} slope={r.linreg_slope:.8f}\n"
        f"  Structure : {_yn(r.struct_ok)}  [{struct_str}]\n"
        f"  Fib Zone  : {fib_icon} {r.fib_zone} ({r.fib_pct:.1f}%)  {_yn(r.fib_ok)}\n"
        f"  CCI(20)   : {_yn(r.cci_ok)}  val={r.cci_val:.1f}\n"
        f"  ADX(14)   : {_yn(r.adx_ok)}  ADX={r.adx_val:.1f}  "
        f"DI+={r.di_plus:.1f}  DI-={r.di_minus:.1f}\n"
    )

    # ── Entry block (Buy Sell Signal) ─────────────────────────────────────
    entry_block = (
        f"{'─' * 30}\n"
        f"🎯 *Buy Sell Signal — {entry_tf} Entry*\n"
        f"  EMA5×13 Cross  : {_yn(r.entry_cross)}\n"
        f"  Candle Confirm : {_yn(r.candle_confirm)}\n"
        f"  Signal Status  : {ftag}\n"
    )

    # ── Reasons ───────────────────────────────────────────────────────────
    tags = " | ".join(r.reasons[:8]) if r.reasons else "—"

    msg = (
        f"{de} *{r.symbol}*  [{r.direction}]  Score: *{r.score}/7*\n"
        f"{sl_tp_block}"
        f"{ctx_block}"
        f"{entry_block}"
        f"{'─' * 30}\n"
        f"📌 {tags}"
    )
    return msg


# ══════════════════════════════════════════════════════════════════════════
# FORMAT SHORT  (/top, /scan list)
# ══════════════════════════════════════════════════════════════════════════

def _fmt_short(r: SignalResult) -> str:
    de   = _dir_emoji(r.direction)
    ftag = _fresh_tag(r)
    fib  = _fib_icon(r.fib_zone)
    bar  = _score_bar(r.score)

    ctx_icons = (
        f"EMA{_yn(r.ema_stack)} "
        f"LR{_yn(r.linreg_bull)} "
        f"MS{_yn(r.struct_ok)} "
        f"Fib{fib}{_yn(r.fib_ok)} "
        f"CCI{_yn(r.cci_ok)} "
        f"ADX{_yn(r.adx_ok)}"
    )

    sl_tp = ""
    if r.direction != "NEUTRAL":
        sl_tp = (
            f"  💰`{r.price}` 🛑`{r.sl}`(-{r.risk_pct:.1f}%) "
            f"🎯`{r.tp1}` 🏁`{r.tp_final}`\n"
        )

    return (
        f"{de} *{r.symbol}*  {r.direction}  `{r.score}/7`  {ftag}\n"
        f"  `{bar}`\n"
        f"  {ctx_icons}\n"
        f"{sl_tp}"
    )


# ══════════════════════════════════════════════════════════════════════════
# BOT
# ══════════════════════════════════════════════════════════════════════════

class TelegramBot:
    def __init__(self, token: str, scanner: Scanner):
        self.token   = token
        self.scanner = scanner
        self.app     = Application.builder().token(token).build()

        cmds = [
            ("start",    self._start),
            ("help",     self._help),
            ("scan",     self._scan),
            ("scan4h1h", self._scan_4h1h),
            ("scan1d4h", self._scan_1d4h),
            ("scan1h15m",self._scan_1h15m),
            ("top",      self._top),
            ("check",    self._check),
            ("status",   self._status),
            ("debug",    self._debug),
        ]
        for cmd, fn in cmds:
            self.app.add_handler(CommandHandler(cmd, fn))

    # ── Start / Help ───────────────────────────────────────────────────────

    async def _start(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            "🤖 *Ceez Prime + Buy Sell Signal Bot* sẵn sàng!\n"
            "Dùng /help xem danh sách lệnh.",
            parse_mode="Markdown"
        )

    async def _help(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        text = (
            "📖 *Danh sách lệnh*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔍 *Quét toàn market*\n"
            "/scan      — 4H context + 1H entry  (default)\n"
            "/scan4h1h  — 4H context + 1H entry\n"
            "/scan1d4h  — 1D context + 4H entry  (swing)\n"
            "/scan1h15m — 1H context + 15m entry (intraday)\n"
            "/top       — Top signal rút gọn\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔎 *Phân tích 1 token*\n"
            "/check `BTC`   — Dashboard đầy đủ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ *Hệ thống*\n"
            "/status  — Trạng thái bot\n"
            "/debug   — Test kết nối OKX\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*Logic vào lệnh:*\n"
            "① Ceez Prime xác nhận context (6 điểm)\n"
            "   EMA Stack 13/20/50/200\n"
            "   LinReg slope\n"
            "   Structure HH/HL hoặc LH/LL\n"
            "   Fibonacci zone (0.382–0.618)\n"
            "   CCI > 0 hoặc < 0\n"
            "   ADX > 20 + DI xác nhận\n"
            "② Buy Sell Signal kích hoạt (1 điểm)\n"
            "   EMA 5 cross EMA 13 + nến xác nhận\n"
            "*Ngưỡng vào: score ≥ 4/7 + ADX trending*"
        )
        await u.message.reply_text(text, parse_mode="Markdown")

    # ── Scan helpers ──────────────────────────────────────────────────────

    async def _do_scan(
        self,
        u:        Update,
        ctx_tf:   str,
        entry_tf: str,
        label:    str,
    ):
        await u.message.reply_text(
            f"🔍 Đang quét *{label}* (~60–90s)...",
            parse_mode="Markdown"
        )

        if ctx_tf == self.scanner.ctx_tf and entry_tf == self.scanner.entry_tf:
            signals = await self.scanner.scan_all()
        else:
            signals = await self.scanner.scan_tf(ctx_tf, entry_tf)

        if not signals:
            await u.message.reply_text(
                f"❌ Không có tín hiệu [{label}] lúc này.\n"
                f"Thử /debug kiểm tra kết nối."
            )
            return

        long_s  = [r for r in signals if r.direction == "LONG"]
        short_s = [r for r in signals if r.direction == "SHORT"]
        fresh_s = [r for r in signals if r.signal_fresh]
        full_s  = [r for r in signals if r.score == 7]

        await u.message.reply_text(
            f"📊 *{label}* — {len(signals)} tín hiệu\n"
            f"🟢 LONG: {len(long_s)}  🔴 SHORT: {len(short_s)}\n"
            f"🆕 Fresh: {len(fresh_s)}  ⭐ Full(7/7): {len(full_s)}\n"
            f"_(Gửi từng signal bên dưới…)_",
            parse_mode="Markdown"
        )

        for r in signals:
            try:
                await u.message.reply_text(
                    _fmt(r, ctx_tf.upper(), entry_tf.upper()),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"send {r.symbol}: {e}")

        await u.message.reply_text(
            f"✅ *Xong!* Đã gửi {len(signals)} tín hiệu.",
            parse_mode="Markdown"
        )

    async def _scan(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, self.scanner.ctx_tf, self.scanner.entry_tf,
                            f"{self.scanner.ctx_tf.upper()} ctx + {self.scanner.entry_tf.upper()} entry")

    async def _scan_4h1h(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, "4h", "1h", "4H ctx + 1H entry")

    async def _scan_1d4h(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, "1d", "4h", "1D ctx + 4H entry  [SWING]")

    async def _scan_1h15m(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, "1h", "15m", "1H ctx + 15m entry  [INTRADAY]")

    # ── /top ──────────────────────────────────────────────────────────────

    async def _top(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔍 Đang lấy top tín hiệu...")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text("❌ Không có tín hiệu. Dùng /debug kiểm tra.")
            return

        lines = [f"🏆 *Top Tín Hiệu* — {len(signals)} token\n"]
        for i, r in enumerate(signals, 1):
            badge = "⭐" if r.score == 7 else ("🔥" if r.score >= 5 else "📌")
            lines.append(f"*#{i}* {badge} {_fmt_short(r)}\n")

        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 3800:
                await u.message.reply_text(chunk, parse_mode="Markdown")
                chunk = line
            else:
                chunk += line
        if chunk:
            await u.message.reply_text(chunk, parse_mode="Markdown")

    # ── /check ────────────────────────────────────────────────────────────

    async def _check(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        args = c.args
        if not args:
            await u.message.reply_text("⚠️ Dùng: /check BTC hoặc /check BTCUSDT")
            return
        sym = args[0].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        await u.message.reply_text(
            f"🔍 Đang phân tích *{sym}* "
            f"({self.scanner.ctx_tf.upper()} ctx + {self.scanner.entry_tf.upper()} entry)...",
            parse_mode="Markdown"
        )
        r = await self.scanner.scan_symbol(sym)
        if r is None:
            await u.message.reply_text(
                f"❌ Không lấy được data cho {sym}.\nDùng /debug kiểm tra kết nối."
            )
            return
        await u.message.reply_text(
            _fmt(r, self.scanner.ctx_tf.upper(), self.scanner.entry_tf.upper()),
            parse_mode="Markdown"
        )

    # ── /status ───────────────────────────────────────────────────────────

    async def _status(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            f"✅ *Bot Running*\n"
            f"📊 Context TF : `{self.scanner.ctx_tf}` (Ceez Prime)\n"
            f"🎯 Entry TF   : `{self.scanner.entry_tf}` (Buy Sell Signal)\n"
            f"📐 Min Score  : {self.scanner.min_score}/7\n"
            f"📈 Min ADX    : {self.scanner.min_adx}\n"
            f"🔢 Max Symbols: {self.scanner.max_symbols}\n"
            f"⏳ Cooldown   : {len(self.scanner._last_alert)} tokens\n\n"
            f"*Logic Ceez Prime:*\n"
            f"① EMA Stack 13/20/50/200\n"
            f"② LinReg Slope\n"
            f"③ Market Structure HH/HL | LH/LL\n"
            f"④ Fibonacci 0.382–0.618\n"
            f"⑤ CCI Zero-line\n"
            f"⑥ ADX + DI direction\n"
            f"*Entry Buy Sell Signal:*\n"
            f"⑦ EMA 5×13 cross + Candle confirm\n"
            f"*SL: ATR×{self.scanner.atr_mult_sl}  R:R {self.scanner.rr}:1*",
            parse_mode="Markdown"
        )

    # ── /debug ────────────────────────────────────────────────────────────

    async def _debug(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔧 Đang debug...")
        import aiohttp
        import fetcher as fm
        base    = getattr(fm, "BASE", "https://www.okx.com")
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
                df_ctx, df_entry = await asyncio.gather(
                    fetcher.fetch_ohlcv(sym, self.scanner.ctx_tf,   50),
                    fetcher.fetch_ohlcv(sym, self.scanner.entry_tf, 50),
                )
                ok_ctx   = f"{len(df_ctx)} bars"   if df_ctx   is not None else "FAIL"
                ok_entry = f"{len(df_entry)} bars"  if df_entry is not None else "FAIL"
                price    = df_entry["close"].iloc[-1] if df_entry is not None else "?"
                lines.append(
                    f"✅ {sym}: {self.scanner.ctx_tf}={ok_ctx} "
                    f"{self.scanner.entry_tf}={ok_entry} | price={price}"
                )
            except Exception as e:
                lines.append(f"❌ {sym}: {type(e).__name__}: {str(e)[:80]}")

        syms = await fetcher.fetch_top_symbols(10)
        lines.append(f"\n📋 Symbols (total): {syms[:5]}")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # ── Auto alert ────────────────────────────────────────────────────────

    async def send_signal(self, chat_id: str, result: SignalResult):
        try:
            prefix = "🚨⭐ *AUTO ALERT — PERFECT*" if result.score == 7 else \
                     "🚨🔥 *AUTO ALERT — STRONG*"  if result.score >= 5 else \
                     "🚨 *AUTO ALERT*"
            if result.signal_fresh:
                prefix += " 🆕"
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=f"{prefix}\n\n{_fmt(result, self.scanner.ctx_tf.upper(), self.scanner.entry_tf.upper())}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"send_signal {chat_id}: {e}")

    def run_polling(self):
        self.app.run_polling(drop_pending_updates=True)


import asyncio  # noqa: E402 — dùng cho _debug
