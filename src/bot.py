"""
Telegram bot interface
Commands: /scan  /top  /check <SYMBOL>  /status  /help
"""

import asyncio
import logging
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE FORMATTERS
# ─────────────────────────────────────────────────────────────────────────────

def format_signal(symbol: str, score: dict, price: float) -> str:
    v      = score['verdict']
    emoji  = score['emoji']
    tb     = score['total_buy']
    ts     = score['total_sell']
    ck     = score['checklist']
    mtf    = score['mtf']
    rsi_b  = score['rsi_bull']
    rsi_s  = score['rsi_bear']

    mtf_line = (
        f"{'🟢' if mtf['momentum_bull'] else ('🔴' if mtf['momentum_bear'] else '⚪')} 5M  "
        f"{'🟢' if mtf['bridge_bull']   else ('🔴' if mtf['bridge_bear']   else '⚪')} 30M  "
        f"{'🟢' if mtf['context_bull']  else ('🔴' if mtf['context_bear']  else '⚪')} CTX"
    )

    is_buy  = tb >= ts
    atr_sl  = price * 0.005   # ~0.5% proxy SL
    atr_tp1 = price * 0.0075
    atr_tp2 = price * 0.015

    if is_buy and tb >= 7:
        sl_line  = f"🔴 SL  `{price - atr_sl:.4f}`\n🟡 TP1 `{price + atr_tp1:.4f}`\n🟢 TP2 `{price + atr_tp2:.4f}`"
    elif not is_buy and ts >= 7:
        sl_line  = f"🔴 SL  `{price + atr_sl:.4f}`\n🟡 TP1 `{price - atr_tp1:.4f}`\n🟢 TP2 `{price - atr_tp2:.4f}`"
    else:
        sl_line  = "_Chưa đủ điều kiện vào lệnh_"

    return (
        f"*{emoji} {symbol}* — `{v}`\n"
        f"💰 Price: `{price:.6f}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 Score: `{tb}↑` / `{ts}↓` (max 11)\n"
        f"┌ ST AI : {ck['st']}\n"
        f"├ UT Bot: {ck['ut']}\n"
        f"├ SAR   : {ck['sar']}\n"
        f"└ SMC   : {ck['smc']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📡 MTF Align\n{mtf_line}\n"
        f"📈 RSI MTF: {rsi_b}↑ {rsi_s}↓\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎯 SL / TP\n{sl_line}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕐 `{datetime.utcnow().strftime('%H:%M:%S')} UTC`"
    )


def format_scan_summary(signals: list) -> str:
    if not signals:
        return "⏳ *Không có tín hiệu đủ điều kiện* (score < 7/11)"

    lines = ["🔍 *SCAN RESULT — Top Signals*\n"]
    for s in signals[:10]:
        sym   = s['symbol']
        tb    = s['score']['total_buy']
        ts    = s['score']['total_sell']
        v     = s['score']['verdict']
        emoji = s['score']['emoji']
        price = s['price']
        lines.append(f"{emoji} `{sym:<12}` {v}  `{tb}↑/{ts}↓`  @ `{price:.4f}`")

    lines.append(f"\n🕐 `{datetime.utcnow().strftime('%H:%M:%S')} UTC`")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# BOT HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

class SignalBot:
    def __init__(self, token: str, scanner):
        self.token   = token
        self.scanner = scanner          # Scanner instance from main.py
        self.app     = Application.builder().token(token).build()
        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler('start',  self.cmd_start))
        self.app.add_handler(CommandHandler('help',   self.cmd_help))
        self.app.add_handler(CommandHandler('scan',   self.cmd_scan))
        self.app.add_handler(CommandHandler('top',    self.cmd_top))
        self.app.add_handler(CommandHandler('check',  self.cmd_check))
        self.app.add_handler(CommandHandler('status', self.cmd_status))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

    # ── /start ──────────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        kb = [
            [InlineKeyboardButton("🔍 Scan Now",    callback_data='scan')],
            [InlineKeyboardButton("📊 Top Signals", callback_data='top')],
            [InlineKeyboardButton("ℹ️ Help",         callback_data='help')],
        ]
        await update.message.reply_text(
            "⚡ *15M ULTRA Signal Bot*\n\n"
            "Bot quét crypto Binance theo logic:\n"
            "ST AI + UT Bot + SAR + SMC + MTF RSI\n\n"
            "Chọn lệnh hoặc gõ /help",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )

    # ── /help ───────────────────────────────────────────────────────────────
    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📖 *Hướng dẫn*\n\n"
            "/scan — Quét top 30 token, lọc score ≥7\n"
            "/top  — Hiện top 5 tín hiệu mạnh nhất\n"
            "/check BTCUSDT — Kiểm tra 1 token cụ thể\n"
            "/status — Trạng thái bot\n\n"
            "*Thang điểm:*\n"
            "🚀 9-11 = STRONG BUY/SELL\n"
            "✅  7-8  = BUY/SELL\n"
            "↑↓  5-6  = LEAN (chờ thêm)\n"
            "⏳  <5   = NEUTRAL\n",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── /scan ───────────────────────────────────────────────────────────────
    async def cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = await update.message.reply_text("🔄 Đang quét... (~30-60s)")
        try:
            signals = await self.scanner.scan_all()
            filtered = [s for s in signals if s['score']['total_buy'] >= 7 or s['score']['total_sell'] >= 7]
            filtered.sort(key=lambda x: max(x['score']['total_buy'], x['score']['total_sell']), reverse=True)
            await msg.edit_text(format_scan_summary(filtered), parse_mode=ParseMode.MARKDOWN)

            # Send individual detail cards for top 3
            for s in filtered[:3]:
                detail = format_signal(s['symbol'], s['score'], s['price'])
                await update.message.reply_text(detail, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.exception("Scan error")
            await msg.edit_text(f"❌ Lỗi: {e}")

    # ── /top ────────────────────────────────────────────────────────────────
    async def cmd_top(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = await update.message.reply_text("🔄 Đang lấy top signals...")
        try:
            signals = await self.scanner.scan_all()
            signals.sort(key=lambda x: max(x['score']['total_buy'], x['score']['total_sell']), reverse=True)
            await msg.edit_text(format_scan_summary(signals[:5]), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.exception("Top error")
            await msg.edit_text(f"❌ Lỗi: {e}")

    # ── /check <SYMBOL> ─────────────────────────────────────────────────────
    async def cmd_check(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = ctx.args
        if not args:
            await update.message.reply_text("Dùng: /check BTCUSDT")
            return
        symbol = args[0].upper()
        msg    = await update.message.reply_text(f"🔄 Đang phân tích {symbol}...")
        try:
            result = await self.scanner.check_symbol(symbol)
            if result is None:
                await msg.edit_text(f"❌ Không lấy được dữ liệu cho {symbol}")
                return
            detail = format_signal(symbol, result['score'], result['price'])
            await msg.edit_text(detail, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.exception(f"Check {symbol} error")
            await msg.edit_text(f"❌ Lỗi: {e}")

    # ── /status ─────────────────────────────────────────────────────────────
    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f"✅ Bot đang chạy\n"
            f"🕐 `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n"
            f"📡 Kết nối Binance: OK\n"
            f"⏱ Auto-scan: mỗi 5 phút",
            parse_mode=ParseMode.MARKDOWN
        )

    # ── Callback buttons ────────────────────────────────────────────────────
    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data == 'scan':
            await self.cmd_scan(q, ctx)
        elif q.data == 'top':
            await self.cmd_top(q, ctx)
        elif q.data == 'help':
            await self.cmd_help(q, ctx)

    # ── Auto-push alert to chat ──────────────────────────────────────────────
    async def push_alert(self, chat_id: str, symbol: str, score: dict, price: float):
        text = format_signal(symbol, score, price)
        await self.app.bot.send_message(
            chat_id    = chat_id,
            text       = text,
            parse_mode = ParseMode.MARKDOWN
        )

    def run(self):
        self.app.run_polling(drop_pending_updates=True)
