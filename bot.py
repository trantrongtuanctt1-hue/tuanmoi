"""
🎯 Pump Scanner Bot — Telegram Bot
Tác giả: Tuan Trading System
Deploy: Railway via GitHub
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, JobQueue
)
from telegram.constants import ParseMode

from src.scanner import PumpScanner
from src.config import Config

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("PumpBot")

# ── Config ────────────────────────────────────────────────────────────────
cfg = Config()
scanner = PumpScanner(cfg)

# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════

def score_bar(score: int, max_s: int = 10) -> str:
    filled = round(score / max_s * 10)
    return "🟩" * filled + "⬛" * (10 - filled)

def score_emoji(score: int) -> str:
    if score >= 8: return "🚀"
    if score >= 6: return "⚡"
    if score >= 4: return "⚠️"
    return "😴"

def format_signal(sig: dict) -> str:
    s = sig["score"]
    d = sig["detail"]
    ts = datetime.utcnow().strftime("%H:%M:%S UTC")

    vol_line = (
        f"{'🔥' if d['vol_mega'] else '✅' if d['vol_spike'] else '❌'} "
        f"Volume: `{d['vol_ratio']:.1f}x` EMA"
    )
    cvd_line = (
        f"{'✅' if d['cvd_rising'] else '❌'} CVD: "
        f"{'▲ Tăng' if d['cvd_rising'] else '▼ Giảm'}"
        + (f" | 🔄 *Divergence!*" if d['cvd_div'] else "")
    )
    bb_line = (
        f"{'🤏' if d['bb_squeeze'] else '💥' if d['bb_explode'] else '⬜'} "
        f"BB Width: `{d['bb_width']:.2f}%` "
        f"({'Squeeze' if d['bb_squeeze'] else 'Nổ!' if d['bb_explode'] else 'Bình thường'})"
    )
    smc_line = (
        f"{'🚀' if d['bos_bull'] else '✅' if d['choch_bull'] else '❌' if d['choch_bear'] else '⏳'} "
        f"SMC: {'BOS ↑' if d['bos_bull'] else 'CHoCH ↑' if d['choch_bull'] else 'CHoCH ↓' if d['choch_bear'] else 'Chờ...'}"
    )
    trend_line = (
        f"{'📈' if d['trend_up'] else '📉' if d['trend_dn'] else '↔️'} "
        f"Trend: {'Uptrend' if d['trend_up'] else 'Downtrend' if d['trend_dn'] else 'Sideways'}"
    )

    breakdown = (
        f"Vol:{d['vol_score']} "
        f"CVD:{d['cvd_score']+d['cvd_div_bonus']} "
        f"BB:{d['bb_score']} "
        f"SMC:{d['smc_score']} "
        f"TR:{d['trend_score']}"
    )

    return (
        f"{score_emoji(s)} *{sig['symbol']}* — Pump Score: *{s}/10*
"
        f"{score_bar(s)}
"
        f"💰 Giá: `{sig['price']:.6g}` USDT | 📊 TF: `{sig['timeframe']}`
"
        f"🕐 `{ts}`

"
        f"{vol_line}
"
        f"{cvd_line}
"
        f"{bb_line}
"
        f"{smc_line}
"
        f"{trend_line}

"
        f"📊 Breakdown: `{breakdown}` = *{s}/10*
"
        f"🔗 [TradingView](https://www.tradingview.com/chart/?symbol=BINANCE:{sig['symbol'].replace('/', '')})"
    )

# ══════════════════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [
            InlineKeyboardButton("🔍 Scan Ngay", callback_data="scan_now"),
            InlineKeyboardButton("⚙️ Cài Đặt", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("📊 Top Signals", callback_data="top_signals"),
            InlineKeyboardButton("ℹ️ Hướng dẫn", callback_data="help"),
        ],
    ]
    markup = InlineKeyboardMarkup(kb)
    await update.message.reply_text(
        "🎯 *Pump Scanner Bot* — by Tuan

"
        "Bot tự động scan và phát hiện token có khả năng pump dựa trên:
"
        "📊 Volume Spike | 📈 CVD | 📉 BB Squeeze
"
        "🏛️ SMC CHoCH/BOS | 🔭 EMA Trend

"
        f"⏱ Auto-scan mỗi `{cfg.SCAN_INTERVAL}` phút
"
        f"🎯 Ngưỡng alert: Score ≥ `{cfg.MIN_SCORE}/10`
"
        f"📋 Scan top `{cfg.TOP_N}` token",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
    )

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang scan... vui lòng chờ")
    try:
        results = await scanner.scan_all()
        hot = [r for r in results if r["score"] >= cfg.MIN_SCORE]
        hot.sort(key=lambda x: x["score"], reverse=True)

        if not hot:
            await msg.edit_text(
                f"😴 Không tìm thấy token nào đạt ≥ {cfg.MIN_SCORE}/10
"
                f"Đã scan {len(results)} token. Thử lại sau."
            )
            return

        header = f"🔥 *Pump Scan — {len(hot)} signals* | {datetime.utcnow().strftime('%H:%M UTC')}
{'─'*30}

"
        await msg.edit_text(header + "

".join([format_signal(r) for r in hot[:5]]),
                            parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True)

        # Nếu nhiều hơn 5 kết quả, gửi tiếp
        for chunk in [hot[i:i+5] for i in range(5, len(hot), 5)]:
            await update.message.reply_text(
                "

".join([format_signal(r) for r in chunk]),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"Scan error: {e}")
        await msg.edit_text(f"❌ Lỗi scan: `{e}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Top signals với filter theo score"""
    args = ctx.args
    min_s = int(args[0]) if args and args[0].isdigit() else cfg.MIN_SCORE

    msg = await update.message.reply_text(f"⏳ Đang tìm top signals (score ≥ {min_s})...")
    try:
        results = await scanner.scan_all()
        hot = sorted([r for r in results if r["score"] >= min_s],
                     key=lambda x: x["score"], reverse=True)[:10]

        if not hot:
            await msg.edit_text(f"😴 Không có signal nào ≥ {min_s}/10")
            return

        lines = [f"🏆 *Top Signals (score ≥ {min_s})* — {len(hot)} kết quả
"]
        for i, r in enumerate(hot, 1):
            d = r["detail"]
            lines.append(
                f"{i}. {score_emoji(r['score'])} *{r['symbol']}* `{r['score']}/10` "
                f"| Vol:`{d['vol_ratio']:.1f}x` "
                f"| {'🚀BOS' if d['bos_bull'] else '✅CHoCH' if d['choch_bull'] else '⏳'} "
                f"| BB:`{'Squeeze' if d['bb_squeeze'] else 'OK'}`"
            )

        await msg.edit_text("
".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: `{e}`", parse_mode=ParseMode.MARKDOWN)

async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Check 1 token cụ thể: /check BTCUSDT 15"""
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/check BTCUSDT 15`", parse_mode=ParseMode.MARKDOWN)
        return

    symbol = args[0].upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    tf = args[1] if len(args) > 1 else cfg.TIMEFRAME

    msg = await update.message.reply_text(f"⏳ Đang phân tích `{symbol}` [{tf}]...",
                                           parse_mode=ParseMode.MARKDOWN)
    try:
        result = await scanner.scan_one(symbol, tf)
        await msg.edit_text(format_signal(result),
                             parse_mode=ParseMode.MARKDOWN,
                             disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Lỗi: `{e}`
Kiểm tra lại symbol.", parse_mode=ParseMode.MARKDOWN)

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    next_scan = ctx.job_queue.jobs()[0].next_t if ctx.job_queue.jobs() else "N/A"
    await update.message.reply_text(
        f"📡 *Bot Status*

"
        f"✅ Đang chạy
"
        f"⏱ Interval: `{cfg.SCAN_INTERVAL}` phút
"
        f"🎯 Min score: `{cfg.MIN_SCORE}/10`
"
        f"📋 Scan: top `{cfg.TOP_N}` token
"
        f"⏰ Timeframe: `{cfg.TIMEFRAME}`
"
        f"🕐 Next scan: `{next_scan}`",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Hướng dẫn sử dụng*

"
        "🔹 `/scan` — Scan toàn bộ market
"
        "🔹 `/top [score]` — Top signals, vd: `/top 7`
"
        "🔹 `/check EDEN 15` — Phân tích 1 token
"
        "🔹 `/status` — Xem trạng thái bot

"
        "📊 *Hệ thống chấm điểm (0-10):*
"
        "├ Volume Spike: 2-3đ
"
        "├ CVD Trend: 2đ
"
        "├ CVD Divergence: +1đ
"
        "├ BB Squeeze: 2đ
"
        "├ SMC CHoCH/BOS: 1-2đ
"
        "└ EMA Trend: +1đ

"
        "🚀 Score ≥8 | ⚡ ≥6 | ⚠️ ≥4 | 😴 <4",
        parse_mode=ParseMode.MARKDOWN,
    )

# ══════════════════════════════════════════════════════════════════════════
#  CALLBACK BUTTONS
# ══════════════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "scan_now":
        await q.message.reply_text("⏳ Đang scan...")
        fake = type("obj", (object,), {"message": q.message, "effective_chat": q.message.chat})()
        await cmd_scan(fake, ctx)

    elif data == "top_signals":
        fake = type("obj", (object,), {"message": q.message, "args": []})()
        await cmd_top(fake, ctx)

    elif data == "settings":
        await q.message.reply_text(
            f"⚙️ *Cài đặt hiện tại*

"
            f"Min Score: `{cfg.MIN_SCORE}`
"
            f"Interval: `{cfg.SCAN_INTERVAL}` phút
"
            f"Timeframe: `{cfg.TIMEFRAME}`
"
            f"Top N token: `{cfg.TOP_N}`
"
            f"Volume x: `{cfg.VOL_MULT}x`
"
            f"BB Squeeze: `<{cfg.BB_SQUEEZE_THRESH}%`

"
            f"_Thay đổi qua biến môi trường Railway_",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "help":
        fake = type("obj", (object,), {"message": q.message})()
        await cmd_help(fake, ctx)

# ══════════════════════════════════════════════════════════════════════════
#  AUTO SCAN JOB
# ══════════════════════════════════════════════════════════════════════════

async def auto_scan_job(ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("🔄 Auto-scan bắt đầu...")
    try:
        results = await scanner.scan_all()
        hot = sorted([r for r in results if r["score"] >= cfg.MIN_SCORE],
                     key=lambda x: x["score"], reverse=True)

        if not hot:
            logger.info(f"😴 Không có signal nào ≥ {cfg.MIN_SCORE}/10")
            return

        logger.info(f"🚀 {len(hot)} signals tìm thấy!")
        header = (
            f"🔔 *Auto Scan* — {datetime.utcnow().strftime('%H:%M UTC')}
"
            f"Tìm thấy *{len(hot)}* signal ≥ {cfg.MIN_SCORE}/10
"
            f"{'─'*28}

"
        )

        # Gửi từng batch 5 signal
        for i, chunk in enumerate([hot[j:j+5] for j in range(0, min(len(hot), 15), 5)]):
            text = (header if i == 0 else "") + "

".join([format_signal(r) for r in chunk])
            await ctx.bot.send_message(
                chat_id=cfg.CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Auto-scan lỗi: {e}")
        await ctx.bot.send_message(cfg.CHAT_ID, f"❌ Auto-scan lỗi: `{e}`",
                                   parse_mode=ParseMode.MARKDOWN)

# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    logger.info("🚀 Pump Scanner Bot đang khởi động...")

    app = (
        Application.builder()
        .token(cfg.BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("check",  cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Auto scan job
    app.job_queue.run_repeating(
        auto_scan_job,
        interval=cfg.SCAN_INTERVAL * 60,
        first=30,  # chờ 30s sau khi start
        name="auto_scan",
    )

    logger.info(f"✅ Bot ready | Scan mỗi {cfg.SCAN_INTERVAL} phút | Min score: {cfg.MIN_SCORE}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
