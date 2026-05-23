"""
Pump Scanner Bot - Telegram Bot
Tac gia: Tuan Trading System
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

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("PumpBot")

cfg = Config()
scanner = PumpScanner(cfg)


def score_bar(score: int, max_s: int = 10) -> str:
    filled = round(score / max_s * 10)
    return "🟩" * filled + "⬛" * (10 - filled)


def score_emoji(score: int) -> str:
    if score >= 8:
        return "🚀"
    if score >= 6:
        return "⚡"
    if score >= 4:
        return "⚠️"
    return "😴"


def format_signal(sig: dict) -> str:
    s = sig["score"]
    d = sig["detail"]
    ts = datetime.utcnow().strftime("%H:%M:%S UTC")

    vol_icon = "🔥" if d["vol_mega"] else "✅" if d["vol_spike"] else "❌"
    vol_line = vol_icon + " Volume: `" + str(round(d["vol_ratio"], 1)) + "x` EMA"

    cvd_dir = "Giam" if not d["cvd_rising"] else "Tang"
    cvd_icon = "✅" if d["cvd_rising"] else "❌"
    cvd_line = cvd_icon + " CVD: " + cvd_dir + (" | Divergence!" if d["cvd_div"] else "")

    bb_state = "Squeeze" if d["bb_squeeze"] else "No!" if d["bb_explode"] else "Binh thuong"
    bb_icon = "🤏" if d["bb_squeeze"] else "💥" if d["bb_explode"] else "⬜"
    bb_line = bb_icon + " BB Width: `" + str(round(d["bb_width"], 2)) + "%` (" + bb_state + ")"

    smc_state = "BOS Bull" if d["bos_bull"] else "CHoCH Bull" if d["choch_bull"] else "CHoCH Bear" if d["choch_bear"] else "Cho..."
    smc_icon = "🚀" if d["bos_bull"] else "✅" if d["choch_bull"] else "❌" if d["choch_bear"] else "⏳"
    smc_line = smc_icon + " SMC: " + smc_state

    tr_state = "Uptrend" if d["trend_up"] else "Downtrend" if d["trend_dn"] else "Sideways"
    tr_icon = "📈" if d["trend_up"] else "📉" if d["trend_dn"] else "↔️"
    trend_line = tr_icon + " Trend: " + tr_state

    breakdown = (
        "Vol:" + str(d["vol_score"]) +
        " CVD:" + str(d["cvd_score"] + d["cvd_div_bonus"]) +
        " BB:" + str(d["bb_score"]) +
        " SMC:" + str(d["smc_score"]) +
        " TR:" + str(d["trend_score"])
    )

    tv_symbol = sig["symbol"].replace("/", "")
    tv_link = "https://www.tradingview.com/chart/?symbol=BINANCE:" + tv_symbol

    lines = [
        score_emoji(s) + " *" + sig["symbol"] + "* Score: *" + str(s) + "/10*",
        score_bar(s),
        "Gia: `" + str(round(sig["price"], 6)) + "` USDT | TF: `" + sig["timeframe"] + "`",
        "Time: `" + ts + "`",
        "",
        vol_line,
        cvd_line,
        bb_line,
        smc_line,
        trend_line,
        "",
        "Breakdown: `" + breakdown + "` = *" + str(s) + "/10*",
        "[TradingView](" + tv_link + ")",
    ]
    return "\n".join(lines)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [
            InlineKeyboardButton("🔍 Scan Ngay", callback_data="scan_now"),
            InlineKeyboardButton("⚙️ Cai Dat", callback_data="settings"),
        ],
        [
            InlineKeyboardButton("📊 Top Signals", callback_data="top_signals"),
            InlineKeyboardButton("ℹ️ Huong dan", callback_data="help"),
        ],
    ]
    await update.message.reply_text(
        "*Pump Scanner Bot* by Tuan\n\n"
        "Bot scan phat hien token co kha nang pump:\n"
        "Volume Spike | CVD | BB Squeeze | SMC | EMA Trend\n\n"
        "Auto-scan moi `" + str(cfg.SCAN_INTERVAL) + "` phut\n"
        "Nguong alert: Score >= `" + str(cfg.MIN_SCORE) + "/10`\n"
        "Scan top `" + str(cfg.TOP_N) + "` token",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Dang scan... vui long cho")
    try:
        results = await scanner.scan_all()
        hot = sorted([r for r in results if r["score"] >= cfg.MIN_SCORE],
                     key=lambda x: x["score"], reverse=True)

        if not hot:
            await msg.edit_text(
                "Khong tim thay token nao dat >= " + str(cfg.MIN_SCORE) + "/10\n"
                "Da scan " + str(len(results)) + " token."
            )
            return

        header = "*Pump Scan - " + str(len(hot)) + " signals* | " + datetime.utcnow().strftime("%H:%M UTC") + "\n\n"
        first_batch = "\n\n".join([format_signal(r) for r in hot[:5]])
        await msg.edit_text(header + first_batch,
                            parse_mode=ParseMode.MARKDOWN,
                            disable_web_page_preview=True)

        for chunk in [hot[i:i+5] for i in range(5, len(hot), 5)]:
            await update.message.reply_text(
                "\n\n".join([format_signal(r) for r in chunk]),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error("Scan error: " + str(e))
        await msg.edit_text("Loi scan: `" + str(e) + "`", parse_mode=ParseMode.MARKDOWN)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    min_s = int(args[0]) if args and args[0].isdigit() else cfg.MIN_SCORE
    msg = await update.message.reply_text("Dang tim top signals (score >= " + str(min_s) + ")...")
    try:
        results = await scanner.scan_all()
        hot = sorted([r for r in results if r["score"] >= min_s],
                     key=lambda x: x["score"], reverse=True)[:10]

        if not hot:
            await msg.edit_text("Khong co signal nao >= " + str(min_s) + "/10")
            return

        lines = ["*Top Signals (score >= " + str(min_s) + ")* - " + str(len(hot)) + " ket qua\n"]
        for i, r in enumerate(hot, 1):
            d = r["detail"]
            smc_txt = "BOS" if d["bos_bull"] else "CHoCH" if d["choch_bull"] else "..."
            bb_txt = "Squeeze" if d["bb_squeeze"] else "OK"
            lines.append(
                str(i) + ". " + score_emoji(r["score"]) + " *" + r["symbol"] + "* `" + str(r["score"]) + "/10`"
                " | Vol:`" + str(round(d["vol_ratio"], 1)) + "x`"
                " | " + smc_txt +
                " | BB:`" + bb_txt + "`"
            )

        await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text("Loi: `" + str(e) + "`", parse_mode=ParseMode.MARKDOWN)


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: `/check BTCUSDT 15`", parse_mode=ParseMode.MARKDOWN)
        return

    symbol = args[0].upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    tf = args[1] if len(args) > 1 else cfg.TIMEFRAME

    msg = await update.message.reply_text("Dang phan tich `" + symbol + "` [" + tf + "]...",
                                           parse_mode=ParseMode.MARKDOWN)
    try:
        result = await scanner.scan_one(symbol, tf)
        await msg.edit_text(format_signal(result),
                             parse_mode=ParseMode.MARKDOWN,
                             disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text("Loi: `" + str(e) + "`\nKiem tra lai symbol.", parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Bot Status*\n\n"
        "Dang chay\n"
        "Interval: `" + str(cfg.SCAN_INTERVAL) + "` phut\n"
        "Min score: `" + str(cfg.MIN_SCORE) + "/10`\n"
        "Scan: top `" + str(cfg.TOP_N) + "` token\n"
        "Timeframe: `" + cfg.TIMEFRAME + "`\n"
        "Exchange: `" + cfg.EXCHANGE + "`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Huong dan su dung*\n\n"
        "/scan - Scan toan bo market\n"
        "/top [score] - Top signals, vd: /top 7\n"
        "/check EDEN 15 - Phan tich 1 token\n"
        "/status - Xem trang thai bot\n\n"
        "*He thong cham diem (0-10):*\n"
        "Volume Spike: 2-3d\n"
        "CVD Trend: 2d\n"
        "CVD Divergence: +1d\n"
        "BB Squeeze: 2d\n"
        "SMC CHoCH/BOS: 1-2d\n"
        "EMA Trend: +1d\n\n"
        "Score >=8 | >=6 | >=4 | <4",
        parse_mode=ParseMode.MARKDOWN,
    )


async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "scan_now":
        await q.message.reply_text("Dang scan...")
        fake_update = type("U", (), {"message": q.message})()
        await cmd_scan(fake_update, ctx)
    elif q.data == "top_signals":
        fake_update = type("U", (), {"message": q.message, "args": []})()
        await cmd_top(fake_update, ctx)
    elif q.data == "settings":
        await q.message.reply_text(
            "*Cai dat hien tai*\n\n"
            "Min Score: `" + str(cfg.MIN_SCORE) + "`\n"
            "Interval: `" + str(cfg.SCAN_INTERVAL) + "` phut\n"
            "Timeframe: `" + cfg.TIMEFRAME + "`\n"
            "Top N: `" + str(cfg.TOP_N) + "` token\n"
            "Volume x: `" + str(cfg.VOL_MULT) + "x`\n"
            "BB Squeeze: `<" + str(cfg.BB_SQUEEZE_THRESH) + "%`\n\n"
            "_Thay doi qua Variables tren Railway_",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif q.data == "help":
        fake_update = type("U", (), {"message": q.message})()
        await cmd_help(fake_update, ctx)


async def auto_scan_job(ctx: ContextTypes.DEFAULT_TYPE):
    logger.info("Auto-scan bat dau...")
    try:
        results = await scanner.scan_all()
        hot = sorted([r for r in results if r["score"] >= cfg.MIN_SCORE],
                     key=lambda x: x["score"], reverse=True)

        if not hot:
            logger.info("Khong co signal nao >= " + str(cfg.MIN_SCORE) + "/10")
            return

        logger.info(str(len(hot)) + " signals tim thay!")
        header = (
            "*Auto Scan* - " + datetime.utcnow().strftime("%H:%M UTC") + "\n"
            "Tim thay *" + str(len(hot)) + "* signal >= " + str(cfg.MIN_SCORE) + "/10\n"
            "----------------------------\n\n"
        )

        for i, chunk in enumerate([hot[j:j+5] for j in range(0, min(len(hot), 15), 5)]):
            text = (header if i == 0 else "") + "\n\n".join([format_signal(r) for r in chunk])
            await ctx.bot.send_message(
                chat_id=cfg.CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error("Auto-scan loi: " + str(e))
        await ctx.bot.send_message(
            cfg.CHAT_ID,
            "Auto-scan loi: `" + str(e) + "`",
            parse_mode=ParseMode.MARKDOWN,
        )


def main():
    logger.info("Pump Scanner Bot dang khoi dong...")

    app = Application.builder().token(cfg.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("check",  cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.job_queue.run_repeating(
        auto_scan_job,
        interval=cfg.SCAN_INTERVAL * 60,
        first=30,
        name="auto_scan",
    )

    logger.info("Bot ready | Scan moi " + str(cfg.SCAN_INTERVAL) + " phut | Min score: " + str(cfg.MIN_SCORE))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
