"""
bot.py — Telegram Bot handlers + auto-scan scheduler
Commands: /start /help /scan /top /symbol /status /pairs /pause /resume /settings
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import *
from scanner import OKXScanner, SignalResult

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────
# Formatter helpers
# ─────────────────────────────────────────────────────────────────────────
def _ck(b: bool) -> str:
    return "✅" if b else "❌"


def _fmt_price(v: float) -> str:
    if v >= 1000:   return f"{v:,.2f}"
    if v >= 1:      return f"{v:.4f}"
    if v >= 0.001:  return f"{v:.6f}"
    return f"{v:.8f}"


def format_signal(sig: SignalResult) -> str:
    """Chi tiết 1 tín hiệu — gửi khi alert / /symbol."""
    dir_hdr = "📈 LONG" if sig.is_long else "📉 SHORT"
    sep     = "─" * 32

    checklist = (
        f"  {_ck(sig.st_bull)}  SuperTrend   {'▲ Bull' if sig.st_bull else '▼ Bear'}\n"
        f"  {_ck(sig.ut_bull)}  UT Bot       {'▲ Long' if sig.ut_bull else ('▼ Short' if not sig.ut_bull else '= Flat')}\n"
        f"  {_ck(sig.sar_bull)} SAR          {'▲ Bull' if sig.sar_bull else '▼ Bear'}\n"
        f"  {_ck(sig.ema_bull)} EMA 20>50>200\n"
        f"  {_ck(sig.fvg_bull or sig.fvg_bear)} FVG          "
        f"{'▲ Bull' if sig.fvg_bull else ('▼ Bear' if sig.fvg_bear else '—'  )}\n"
    )

    mtf_row = (
        f"  5M {sig.mtf_5m}  "
        f"30M {sig.mtf_30m}  "
        f"1H {sig.mtf_1h}  "
        f"4H {sig.mtf_4h}  "
        f"1D {sig.mtf_1d}"
    )

    rsi_row = (
        f"  RSI MTF  ▲{sig.rsi_bull_cnt}/6  ▼{sig.rsi_bear_cnt}/6"
    )

    vol_row = (
        f"  Vol ▲{sig.bull_vol:.1f}%  /  ▼{sig.bear_vol:.1f}%"
    )

    rr_block = (
        f"  SL:  <code>{_fmt_price(sig.sl)}</code>\n"
        f"  TP1: <code>{_fmt_price(sig.tp1)}</code>\n"
        f"  TP2: <code>{_fmt_price(sig.tp2)}</code>  (R:R {sig.rr:.1f}x)"
    )

    return (
        f"{sig.emoji} <b>{sig.verdict}</b> — <code>{sig.symbol}</code>  {dir_hdr}\n"
        f"{sep}\n"
        f"💰 Giá: <b>{_fmt_price(sig.price)}</b>   "
        f"ATR: {_fmt_price(sig.atr)} ({sig.atr_pct:.2f}%)\n"
        f"📊 RSI: {sig.rsi:.1f}\n"
        f"{sep}\n"
        f"<b>Score:  BUY {sig.score_buy}/11   |   SELL {sig.score_sell}/11</b>\n"
        f"{sep}\n"
        f"📋 <b>Checklist 15M</b>\n"
        f"{checklist}"
        f"{sep}\n"
        f"📐 <b>MTF Alignment</b>\n"
        f"{mtf_row}\n"
        f"{rsi_row}\n"
        f"{vol_row}\n"
        f"{sep}\n"
        f"🎯 <b>Risk/Reward</b>\n"
        f"{rr_block}\n"
    )


def format_summary(results: List[SignalResult]) -> str:
    """Bảng tóm tắt top signals."""
    if not results:
        return "⏳ Không có tín hiệu nào."

    lines = [f"<b>📊 Kết quả Scan OKX — {time.strftime('%H:%M %d/%m')}</b>\n"]
    for s in results[:20]:
        bar_b = "█" * s.score_buy  + "░" * (11 - s.score_buy)
        bar_s = "█" * s.score_sell + "░" * (11 - s.score_sell)
        icon  = "🟢" if s.score_buy > s.score_sell else "🔴"
        name  = s.display_symbol().ljust(8)
        lines.append(
            f"{icon} <code>{name}</code> "
            f"B:{s.score_buy:2d} S:{s.score_sell:2d} "
            f"{s.emoji}{s.verdict[:12]}"
        )

    total = len(results)
    buy_count  = sum(1 for r in results if r.is_buy)
    sell_count = sum(1 for r in results if r.is_sell)
    lines.append(
        f"\n<i>Total: {total}  |  BUY≥7: {buy_count}  |  SELL≥7: {sell_count}</i>"
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Main Bot class
# ─────────────────────────────────────────────────────────────────────────
class TradingBot:

    def __init__(self):
        self.scanner       = OKXScanner()
        self.app           = Application.builder().token(TELEGRAM_TOKEN).build()
        self._pairs:  List[str]                 = []
        self._last_results: List[SignalResult]  = []
        self._last_scan_ts: float               = 0
        self._scanning:     bool                = False
        self._auto_scan:    bool                = True
        self._alerted: Dict[str, float]         = {}   # sym → timestamp
        self._cooldown = ALERT_COOLDOWN_H * 3600

        # Register handlers
        for cmd, fn in [
            ("start",   self.cmd_start),
            ("help",    self.cmd_help),
            ("scan",    self.cmd_scan),
            ("top",     self.cmd_top),
            ("symbol",  self.cmd_symbol),
            ("status",  self.cmd_status),
            ("pairs",   self.cmd_pairs),
            ("pause",   self.cmd_pause),
            ("resume",  self.cmd_resume),
            ("buy",     self.cmd_filter_buy),
            ("sell",    self.cmd_filter_sell),
        ]:
            self.app.add_handler(CommandHandler(cmd, fn))

    # ── Internal send ──────────────────────────────────────────────────────
    async def _send(self, text: str, chat_id: str = None, **kwargs):
        cid = chat_id or TELEGRAM_CHAT_ID
        if not cid:
            logger.warning("No TELEGRAM_CHAT_ID set")
            return
        try:
            await self.app.bot.send_message(
                chat_id=cid, text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                **kwargs
            )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    # ── Commands ───────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "🤖 <b>SXL + MTF Scanner Bot</b>\n\n"
            "Quét tín hiệu BUY / SELL trên <b>OKX Futures</b> dựa trên:\n"
            "  • SXL Sniper (EMA + RSI + FVG + Momentum)\n"
            "  • SuperTrend AI  |  UT Bot  |  Parabolic SAR\n"
            "  • MTF 5M / 30M / 1H / 4H / 1D alignment\n"
            "  • RSI MTF direction  |  Volume Balance\n\n"
            "Score /11 — Alert khi ≥ 7\n\n"
            "Gõ /help để xem lệnh."
        )

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "<b>📋 Lệnh Bot:</b>\n\n"
            "/scan   — Quét ngay tất cả cặp (1–3 phút)\n"
            "/top    — Xem kết quả scan gần nhất\n"
            "/buy    — Chỉ hiện tín hiệu BUY ≥7\n"
            "/sell   — Chỉ hiện tín hiệu SELL ≥7\n"
            "/symbol &lt;SYM&gt; — Phân tích 1 cặp\n"
            "         Ví dụ: /symbol BTC hoặc /symbol ETH/USDT:USDT\n"
            "/pairs  — Danh sách cặp đang theo dõi\n"
            "/status — Trạng thái bot\n"
            "/pause  — Tạm dừng auto-scan\n"
            "/resume — Tiếp tục auto-scan\n\n"
            f"<i>Auto-scan mỗi {SCAN_INTERVAL_MIN} phút  |  Alert ngưỡng {MIN_BUY_SCORE}/11</i>"
        )

    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if self._scanning:
            await update.message.reply_text("⏳ Đang scan rồi, vui lòng chờ…")
            return
        await update.message.reply_text("🔍 Đang quét… (khoảng 1–3 phút)")
        cid = str(update.effective_chat.id)
        asyncio.create_task(self._do_scan(chat_id=cid, send_all=True))

    async def cmd_top(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._last_results:
            await update.message.reply_text("Chưa có dữ liệu. Gõ /scan để quét.")
            return
        ago = int(time.time() - self._last_scan_ts)
        text = format_summary(self._last_results)
        text += f"\n\n<i>Scan lúc {ago}s trước</i>"
        await update.message.reply_html(text)

    async def cmd_filter_buy(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        signals = [r for r in self._last_results if r.is_buy]
        if not signals:
            await update.message.reply_text("Không có BUY ≥7 trong scan gần nhất.")
            return
        for sig in signals[:5]:
            await update.message.reply_html(format_signal(sig))
            await asyncio.sleep(0.3)

    async def cmd_filter_sell(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        signals = [r for r in self._last_results if r.is_sell]
        if not signals:
            await update.message.reply_text("Không có SELL ≥7 trong scan gần nhất.")
            return
        for sig in signals[:5]:
            await update.message.reply_html(format_signal(sig))
            await asyncio.sleep(0.3)

    async def cmd_symbol(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = ctx.args
        if not args:
            await update.message.reply_text("Dùng: /symbol BTC  hoặc  /symbol ETH/USDT:USDT")
            return
        raw = args[0].upper().strip()
        # Normalize: "BTC" → "BTC/USDT:USDT"
        if "/" not in raw:
            sym = f"{raw}/USDT:USDT"
        elif ":" not in raw:
            sym = raw + ":USDT"
        else:
            sym = raw
        await update.message.reply_text(f"🔍 Đang phân tích {sym}…")
        result = await self.scanner.analyze_symbol(sym)
        if result:
            await update.message.reply_html(format_signal(result))
        else:
            await update.message.reply_text(
                f"❌ Không lấy được dữ liệu cho {sym}\n"
                f"Kiểm tra tên cặp hoặc thử lại."
            )

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        ago    = int(time.time() - self._last_scan_ts) if self._last_scan_ts else -1
        s_ago  = f"{ago}s trước" if ago >= 0 else "Chưa scan"
        st     = "🔄 Đang scan" if self._scanning else ("🟢 Chạy" if self._auto_scan else "⏸ Paused")
        buy_n  = sum(1 for r in self._last_results if r.is_buy)
        sell_n = sum(1 for r in self._last_results if r.is_sell)
        await update.message.reply_html(
            f"<b>⚙️ Bot Status</b>\n"
            f"Trạng thái:    {st}\n"
            f"Pairs scan:    {len(self._pairs)}\n"
            f"Scan cuối:     {s_ago}\n"
            f"BUY≥7:         {buy_n}\n"
            f"SELL≥7:        {sell_n}\n"
            f"Interval:      {SCAN_INTERVAL_MIN} phút\n"
            f"Alert ngưỡng:  {MIN_BUY_SCORE}/11\n"
            f"Cooldown:      {ALERT_COOLDOWN_H}h / symbol"
        )

    async def cmd_pairs(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._pairs:
            await update.message.reply_text("Chưa load pairs. Gõ /scan trước.")
            return
        names = [s.split("/")[0] for s in self._pairs]
        chunks = [names[i:i+20] for i in range(0, len(names), 20)]
        await update.message.reply_html(
            f"<b>{len(self._pairs)} cặp đang theo dõi:</b>\n"
            + "  ".join(chunks[0])
            + (f"\n<i>… và {len(self._pairs)-20} cặp nữa</i>" if len(chunks) > 1 else "")
        )

    async def cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._auto_scan = False
        await update.message.reply_text("⏸ Auto-scan đã tạm dừng. /resume để tiếp tục.")

    async def cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._auto_scan = True
        await update.message.reply_text("▶️ Auto-scan đã tiếp tục.")

    # ── Core scan logic ────────────────────────────────────────────────────
    async def _do_scan(self, chat_id: str = None,
                       send_all: bool = False) -> None:
        if self._scanning:
            return
        self._scanning = True
        cid = chat_id or TELEGRAM_CHAT_ID

        try:
            # Load pairs nếu chưa có
            if not self._pairs:
                await self._send("📡 Đang load danh sách pairs từ OKX…", cid)
                self._pairs = await self.scanner.get_top_pairs()
                await self._send(f"✅ Loaded {len(self._pairs)} pairs", cid)

            results = await self.scanner.scan_all(self._pairs)
            self._last_results = results
            self._last_scan_ts = time.time()

            alerts = [r for r in results if r.best_score >= MIN_BUY_SCORE]

            if send_all:
                # Gửi summary
                await self._send(format_summary(results), cid)
                await asyncio.sleep(0.5)
                # Gửi top 8 signal mạnh nhất
                for sig in [r for r in alerts if r.is_buy or r.is_sell][:8]:
                    await self._send(format_signal(sig), cid)
                    await asyncio.sleep(0.4)
            else:
                # Auto mode: chỉ gửi signal mới, không duplicate trong cooldown
                for sig in alerts:
                    if not (sig.is_buy or sig.is_sell):
                        continue
                    last_t = self._alerted.get(sig.symbol, 0)
                    if time.time() - last_t > self._cooldown:
                        await self._send(format_signal(sig))
                        self._alerted[sig.symbol] = time.time()
                        await asyncio.sleep(0.4)

            logger.info(
                f"Scan done: {len(results)} pairs, "
                f"{sum(1 for r in results if r.is_buy)} BUY, "
                f"{sum(1 for r in results if r.is_sell)} SELL"
            )

        except Exception as exc:
            logger.exception(f"Scan error: {exc}")
            await self._send(f"❌ Lỗi scan: {exc}", cid)
        finally:
            self._scanning = False

    # ── Background auto-scan loop ──────────────────────────────────────────
    async def _auto_loop(self):
        # Load pairs lần đầu
        try:
            self._pairs = await self.scanner.get_top_pairs()
            logger.info(f"Loaded {len(self._pairs)} pairs")
        except Exception as e:
            logger.error(f"Initial pairs load failed: {e}")

        while True:
            if self._auto_scan:
                await self._do_scan()
            await asyncio.sleep(SCAN_INTERVAL_MIN * 60)

    # ── Start ──────────────────────────────────────────────────────────────
    async def run(self):
        logger.info("Initializing Telegram bot…")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

        await self._send(
            f"🤖 <b>SXL+MTF Scanner Bot khởi động!</b>\n"
            f"Exchange:  OKX Futures (USDT Margined)\n"
            f"Pairs:     top {MAX_PAIRS} theo volume ≥ ${MIN_VOLUME_USDT/1e6:.0f}M\n"
            f"Interval:  mỗi {SCAN_INTERVAL_MIN} phút\n"
            f"Alert:     score ≥ {MIN_BUY_SCORE}/11\n\n"
            f"/help để xem lệnh"
        )

        await self._auto_loop()

    async def stop(self):
        logger.info("Stopping…")
        try:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            await self.scanner.close()
        except Exception as e:
            logger.error(f"Stop error: {e}")
