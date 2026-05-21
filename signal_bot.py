"""
Telegram bot — Ceez Prime + Buy Sell Signal (HIGH WIN-RATE)
Commands:
  /scan        — Quét toàn market
  /scan4h1h    — 4H ctx + 1H entry (default)
  /scan1d4h    — 1D ctx + 4H entry (swing)
  /scan1h15m   — 1H ctx + 15m entry (intraday)
  /top         — Top signal rút gọn
  /check BTC   — Phân tích chi tiết
  /status      — Trạng thái bot
  /debug       — Test kết nối
  /help        — Danh sách lệnh
"""

import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scanner import Scanner
from signals import SignalResult

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# FORMAT HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _yn(v: bool) -> str:  return "✅" if v else "❌"
def _de(d: str)  -> str:  return {"LONG": "🟢", "SHORT": "🔴"}.get(d, "⚪")

def _score_bar(score: int, total: int = 11) -> str:
    filled = min(score, total)
    return "█" * filled + "░" * (total - filled)

def _grade(score: int) -> str:
    if score >= 10: return "⭐⭐⭐ PERFECT"
    if score >= 8:  return "🔥🔥 STRONG"
    if score >= 6:  return "🔥 GOOD"
    return "📌 OK"

def _fib_icon(zone: str) -> str:
    return {"DISC": "🟢", "EQ↓": "🟡", "EQ": "⚪", "EQ↑": "🟡", "PREM": "🔴"}.get(zone, "⚪")

def _risk_icon(risk_pct: float) -> str:
    if risk_pct < 0.5: return "⚠️"   # quá chặt
    if risk_pct > 3.0: return "⚠️"   # quá rộng
    return "✅"


# ══════════════════════════════════════════════════════════════════════════
# FORMAT FULL (/check, /scan)
# ══════════════════════════════════════════════════════════════════════════

def _cross_tag(r: SignalResult) -> str:
    if r.has_fresh_cross:
        return f"🆕 FRESH ({r.cross_bars_ago}bar)"
    elif r.has_recent_cross:
        return f"📍 RECENT ({r.cross_bars_ago}bar)"
    else:
        return "⏳ SETUP (chờ cross)"

def _fmt(r: SignalResult, ctx_tf: str = "4H", entry_tf: str = "1H") -> str:
    de    = _de(r.direction)
    grade = _grade(r.score)
    bar   = _score_bar(r.score)
    ri    = _risk_icon(r.risk_pct)
    xtag  = _cross_tag(r)

    # SL/TP block
    sl_tp = ""
    if r.direction != "NEUTRAL":
        sl_tp = (
            f"{'─'*30}\n"
            f"💰 Entry    : `{r.price}`\n"
            f"🛑 SL       : `{r.sl}`  {ri}(-{r.risk_pct:.2f}%)\n"
            f"🎯 TP1 (1R) : `{r.tp1}`\n"
            f"🎯 TP2 (2R) : `{r.tp2}`\n"
            f"🏁 TP Final ({r.rr:.1f}R): `{r.tp_final}`\n"
            f"📐 ATR      : `{r.atr:.6f}`\n"
        )

    # Context block
    struct_str = "/".join(r.struct_labels) if r.struct_labels else "N/A"
    fib_icon   = _fib_icon(r.fib_zone)
    ctx = (
        f"{'─'*30}\n"
        f"📊 *Ceez Prime [{ctx_tf}]* — 6 điểm context\n"
        f"  {_yn(r.ema_stack)} EMA Stack  13={r.ema_e13:.5f} 20={r.ema_e20:.5f}\n"
        f"             50={r.ema_e50:.5f} 200={r.ema_e200:.5f}\n"
        f"  {_yn(r.linreg_bull)} LinReg     slope={r.linreg_slope:.6f}\n"
        f"  {_yn(r.struct_ok)} Structure  [{struct_str}]\n"
        f"  {_yn(r.fib_ok)} Fib Zone   {fib_icon}{r.fib_zone} ({r.fib_pct:.1f}%)\n"
        f"  {_yn(r.cci_ok)} CCI(20)    val={r.cci_val:.1f}\n"
        f"  {_yn(r.adx_ok)} ADX(14)    ADX={r.adx_val:.1f} DI+={r.di_plus:.1f} DI-={r.di_minus:.1f}\n"
    )

    # Entry block
    ent = (
        f"{'─'*30}\n"
        f"🎯 *Buy Sell Signal [{entry_tf}]* — 5 điểm entry\n"
        f"  {_yn(r.entry_cross)}  EMA 5×13 Cross (fresh)\n"
        f"  {_yn(r.candle_strong)} Candle Body ≥55%  (body={r.body_ratio:.0%})\n"
        f"  {_yn(r.volume_spike)} Volume Spike ≥1.3×  (vol={r.vol_ratio:.1f}×)\n"
        f"  {_yn(r.rsi_ok)} RSI Filter  (RSI={r.rsi_val:.1f})\n"
        f"  {_yn(r.price_side_ok)} Price > EMA13 (long) / Price < EMA13 (short)\n"
    )

    # Reasons / Rejects
    ok_str  = " | ".join(r.reasons[:8])   if r.reasons  else "—"
    nok_str = " | ".join(r.rejects[:5])   if r.rejects  else "—"
    risk_str = f"{'─'*30}\n⚠️ *Risk không hợp lệ* (risk={r.risk_pct:.2f}%)\n" \
               if not r.risk_ok and r.direction != "NEUTRAL" else ""

    return (
        f"{de} *{r.symbol}*  [{r.direction}]  {grade}\n"
        f"  Score: *{r.score}/11*  `{bar}`\n"
        f"  {xtag}\n"
        f"{sl_tp}"
        f"{ctx}"
        f"{ent}"
        f"{risk_str}"
        f"{'─'*30}\n"
        f"✅ {ok_str}\n"
        f"❌ {nok_str}"
    )


# ══════════════════════════════════════════════════════════════════════════
# FORMAT SHORT (/top)
# ══════════════════════════════════════════════════════════════════════════

def _fmt_short(r: SignalResult) -> str:
    de  = _de(r.direction)
    bar = _score_bar(r.score)
    fi  = _fib_icon(r.fib_zone)
    ri  = _risk_icon(r.risk_pct)
    # Cross status tag
    if r.has_fresh_cross:
        xtag = f"🆕FRESH({r.cross_bars_ago}bar)"
    elif r.has_recent_cross:
        xtag = f"📍RECENT({r.cross_bars_ago}bar)"
    else:
        xtag = "⏳SETUP(no cross)"

    flags = (
        f"EMA{_yn(r.ema_stack)} LR{_yn(r.linreg_bull)} MS{_yn(r.struct_ok)} "
        f"Fib{fi}{_yn(r.fib_ok)} CCI{_yn(r.cci_ok)} ADX{_yn(r.adx_ok)}"
        f" | Cnd{_yn(r.candle_strong)} Vol{_yn(r.volume_spike)} "
        f"RSI{_yn(r.rsi_ok)} Side{_yn(r.price_side_ok)}"
    )
    sl_tp = ""
    if r.direction != "NEUTRAL":
        sl_tp = (
            f"  💰`{r.price}` 🛑`{r.sl}`{ri}(-{r.risk_pct:.1f}%) "
            f"TP1`{r.tp1}` 🏁`{r.tp_final}`\n"
        )
    return (
        f"{de} *{r.symbol}*  {r.direction}  `{r.score}/11`  {xtag}\n"
        f"  `{bar}`\n"
        f"  {flags}\n"
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
        for cmd, fn in [
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
        ]:
            self.app.add_handler(CommandHandler(cmd, fn))

    async def _start(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            "🤖 *Ceez Prime + Buy Sell Signal Bot*\n"
            "Score 11 điểm · Filter nghiêm chỉ lấy lệnh chất\n"
            "/help xem lệnh.",
            parse_mode="Markdown"
        )

    async def _help(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            "📖 *Lệnh*\n"
            "/scan      — Quét toàn market (4H+1H)\n"
            "/scan4h1h  — 4H context + 1H entry\n"
            "/scan1d4h  — 1D context + 4H entry (swing)\n"
            "/scan1h15m — 1H context + 15m entry (intraday)\n"
            "/top       — Top signal rút gọn\n"
            "/check BTC — Chi tiết 1 token\n"
            "/status    — Cấu hình bot\n"
            "/debug     — Test kết nối OKX\n\n"
            "*11 điểm filter:*\n"
            "Context (6): EMA Stack · LinReg · Structure · Fib · CCI · ADX\n"
            "Entry   (5): EMA5×13 Cross · Candle Body · Volume · RSI · Price Side\n\n"
            "*Pass khi:* score≥6/11 · ADX≥20 · SL 0.2-5% · ctx≥3/6 · entry≥3/5\n"
            "Sort: Fresh(<=3bar) -> Recent(4-8bar) -> Setup(cho cross)",
            parse_mode="Markdown"
        )

    async def _do_scan(self, u: Update, ctx_tf: str, entry_tf: str, label: str):
        await u.message.reply_text(
            f"🔍 Quét *{label}* · filter nghiêm (~60–90s)...",
            parse_mode="Markdown"
        )
        if ctx_tf == self.scanner.ctx_tf and entry_tf == self.scanner.entry_tf:
            signals = await self.scanner.scan_all()
        else:
            signals = await self.scanner.scan_tf(ctx_tf, entry_tf)

        if not signals:
            await u.message.reply_text(
                "❌ Không có tín hiệu đủ điều kiện.\n"
                "Thị trường có thể đang ranging, thử lại sau hoặc /debug kiểm tra."
            )
            return

        l_cnt  = sum(1 for r in signals if r.direction == "LONG")
        s_cnt  = sum(1 for r in signals if r.direction == "SHORT")
        p_cnt  = sum(1 for r in signals if r.score >= 10)
        st_cnt = sum(1 for r in signals if 8 <= r.score < 10)

        fresh_cnt  = sum(1 for r in signals if r.has_fresh_cross)
        recent_cnt = sum(1 for r in signals if r.has_recent_cross)
        setup_cnt  = len(signals) - fresh_cnt - recent_cnt

        await u.message.reply_text(
            f"📊 *{label}* — *{len(signals)} tín hiệu chất lượng*\n"
            f"🟢 LONG: {l_cnt}  🔴 SHORT: {s_cnt}\n"
            f"⭐ Perfect(≥10): {p_cnt}  🔥 Strong(8-9): {st_cnt}\n"
            f"🆕 Fresh(≤3bar): {fresh_cnt}  📍 Recent(4-8bar): {recent_cnt}  ⏳ Setup: {setup_cnt}",
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
            f"✅ Đã gửi {len(signals)} tín hiệu.", parse_mode="Markdown"
        )

    async def _scan(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, self.scanner.ctx_tf, self.scanner.entry_tf,
                            f"{self.scanner.ctx_tf.upper()}+{self.scanner.entry_tf.upper()}")

    async def _scan_4h1h(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, "4h", "1h", "4H+1H")

    async def _scan_1d4h(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, "1d", "4h", "1D+4H [SWING]")

    async def _scan_1h15m(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await self._do_scan(u, "1h", "15m", "1H+15m [INTRADAY]")

    async def _top(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text("🔍 Lấy top signal...")
        signals = await self.scanner.scan_all()
        if not signals:
            await u.message.reply_text("❌ Không có tín hiệu. /debug để kiểm tra.")
            return

        lines = [f"🏆 *Top {len(signals)} tín hiệu* (score desc)\n"]
        for i, r in enumerate(signals[:20], 1):
            badge = "⭐" if r.score >= 10 else ("🔥" if r.score >= 8 else "📌")
            lines.append(f"*#{i}* {badge}\n{_fmt_short(r)}\n")

        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 3800:
                await u.message.reply_text(chunk, parse_mode="Markdown")
                chunk = line
            else:
                chunk += line
        if chunk:
            await u.message.reply_text(chunk, parse_mode="Markdown")

    async def _check(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        if not c.args:
            await u.message.reply_text("⚠️ Dùng: /check BTC hoặc /check BTCUSDT")
            return
        sym = c.args[0].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        await u.message.reply_text(
            f"🔍 Phân tích *{sym}* ({self.scanner.ctx_tf.upper()}+{self.scanner.entry_tf.upper()})...",
            parse_mode="Markdown"
        )
        r = await self.scanner.scan_symbol(sym)
        if r is None:
            await u.message.reply_text(f"❌ Không lấy được data cho {sym}.")
            return
        await u.message.reply_text(
            _fmt(r, self.scanner.ctx_tf.upper(), self.scanner.entry_tf.upper()),
            parse_mode="Markdown"
        )

    async def _status(self, u: Update, c: ContextTypes.DEFAULT_TYPE):
        await u.message.reply_text(
            f"✅ *Bot Status*\n"
            f"📊 Context TF : `{self.scanner.ctx_tf}` (Ceez Prime)\n"
            f"🎯 Entry TF   : `{self.scanner.entry_tf}` (Buy Sell Signal)\n"
            f"📐 Min Score  : {self.scanner.min_score}/11\n"
            f"📈 Min ADX    : {self.scanner.min_adx}\n"
            f"🔢 Max Symbols: {self.scanner.max_symbols}\n"
            f"⏳ Cooldown   : {len(self.scanner._last_alert)} tokens\n\n"
            f"*Context (6pt):* EMA Stack · LinReg · Structure\n"
            f"  Fibonacci 0.45–0.65 · CCI zero · ADX≥{self.scanner.min_adx}\n\n"
            f"*Entry (5pt):* EMA5×13 Fresh · Candle≥55%\n"
            f"  Volume≥1.3× · RSI 30–70 · Price vs EMA13\n\n"
            f"*Risk filter:* SL 0.2–5%  R:R {self.scanner.rr}:1\n"
            f"*Sort:* Fresh cross → Score → Risk%",
            parse_mode="Markdown"
        )

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
                lines.append(f"🌐 Ping: HTTP {resp.status} code={body.get('code','?')}")
        except Exception as e:
            lines.append(f"🌐 Ping FAILED: {e}")

        for sym in ["BTCUSDT", "ETHUSDT"]:
            try:
                df_c, df_e = await asyncio.gather(
                    fetcher.fetch_ohlcv(sym, self.scanner.ctx_tf,   200),
                    fetcher.fetch_ohlcv(sym, self.scanner.entry_tf, 100),
                )
                ok_c = f"{len(df_c)} bars" if df_c is not None else "FAIL"
                ok_e = f"{len(df_e)} bars" if df_e is not None else "FAIL"
                pr   = df_e["close"].iloc[-1] if df_e is not None else "?"
                lines.append(f"✅ {sym}: ctx={ok_c} entry={ok_e} price={pr}")
            except Exception as e:
                lines.append(f"❌ {sym}: {e}")

        syms = await fetcher.fetch_top_symbols(10)
        lines.append(f"\n📋 Sample symbols: {syms[:5]}")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def send_signal(self, chat_id: str, result: SignalResult):
        try:
            grade = _grade(result.score)
            prefix = f"🚨 *AUTO ALERT* {grade}"
            await self.app.bot.send_message(
                chat_id    = chat_id,
                text       = f"{prefix}\n\n"
                             f"{_fmt(result, self.scanner.ctx_tf.upper(), self.scanner.entry_tf.upper())}",
                parse_mode = "Markdown",
            )
        except Exception as e:
            logger.error(f"send_signal {chat_id}: {e}")

    def run_polling(self):
        self.app.run_polling(drop_pending_updates=True)
