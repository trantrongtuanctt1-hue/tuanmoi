"""
SWING CALLS BOT — Telegram Signal Bot
Replicate Pine Script indicator: SMA/EMA crossover + RSI + ATR SL/TP
Exchange: Binance Futures + OKX Futures | Timeframe: 1H
"""

import os
import asyncio
import logging
import time
from datetime import datetime
import pytz

import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID          = os.environ.get("CHAT_ID", "")
BINANCE_API_KEY  = os.environ.get("BINANCE_API_KEY", "")
BINANCE_SECRET   = os.environ.get("BINANCE_SECRET", "")
OKX_API_KEY      = os.environ.get("OKX_API_KEY", "")
OKX_SECRET       = os.environ.get("OKX_SECRET", "")
OKX_PASSPHRASE   = os.environ.get("OKX_PASSPHRASE", "")
SCAN_INTERVAL    = int(os.environ.get("SCAN_INTERVAL", "300"))   # seconds
VN_TZ            = pytz.timezone("Asia/Ho_Chi_Minh")

# ─── Indicator params (mirror Pine Script) ───
EMA_LEN   = 5
SMA_LEN   = 50
RSI_LEN   = 14
ATR_LEN   = 14
SL_MULT   = 1.5
TP1_MULT  = 1.0
TP2_MULT  = 2.2
OB_LEN    = 5
RSI_OB    = 85
RSI_OS    = 15
RSI_HL    = 80
RSI_LL    = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────
scan_running   = False
last_scan_time = None
signal_cache: dict = {}          # symbol → last signal type to avoid duplicate alerts
active_trades: dict = {}         # symbol → trade info
scan_stats = {"total": 0, "buy": 0, "sell": 0, "errors": 0}

# ─────────────────────────────────────────────
# EXCHANGE HELPERS
# ─────────────────────────────────────────────
async def get_binance_symbols() -> list[str]:
    exchange = ccxt.binanceusdm({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET,
        "options": {"defaultType": "future"},
    })
    try:
        markets = await exchange.load_markets()
        syms = [s for s in markets if s.endswith("/USDT") and markets[s].get("active")]
        log.info(f"Binance: {len(syms)} symbols")
        return [("binance", s) for s in syms]
    except Exception as e:
        log.error(f"Binance load_markets: {e}")
        return []
    finally:
        await exchange.close()


async def get_okx_symbols() -> list[str]:
    exchange = ccxt.okx({
        "apiKey": OKX_API_KEY,
        "secret": OKX_SECRET,
        "password": OKX_PASSPHRASE,
        "options": {"defaultType": "swap"},
    })
    try:
        markets = await exchange.load_markets()
        syms = [s for s in markets
                if s.endswith("/USDT:USDT") and markets[s].get("active")]
        log.info(f"OKX: {len(syms)} symbols")
        return [("okx", s) for s in syms]
    except Exception as e:
        log.error(f"OKX load_markets: {e}")
        return []
    finally:
        await exchange.close()


async def fetch_ohlcv(exchange_id: str, symbol: str, timeframe="1h", limit=200) -> pd.DataFrame | None:
    cfg = {
        "binance": lambda: ccxt.binanceusdm({
            "apiKey": BINANCE_API_KEY, "secret": BINANCE_SECRET,
            "options": {"defaultType": "future"}
        }),
        "okx": lambda: ccxt.okx({
            "apiKey": OKX_API_KEY, "secret": OKX_SECRET,
            "password": OKX_PASSPHRASE,
            "options": {"defaultType": "swap"}
        }),
    }
    if exchange_id not in cfg:
        return None

    exchange = cfg[exchange_id]()
    try:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not raw or len(raw) < SMA_LEN + 10:
            return None
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    except Exception as e:
        log.debug(f"fetch_ohlcv {exchange_id}:{symbol} → {e}")
        return None
    finally:
        await exchange.close()


# ─────────────────────────────────────────────
# INDICATOR CALCULATIONS
# ─────────────────────────────────────────────
def calc_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def calc_sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()

def calc_rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=length - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=length - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_atr(df: pd.DataFrame, length: int) -> pd.Series:
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift()).abs()
    lc  = (df["low"]  - df["close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(com=length - 1, adjust=False).mean()


def analyze(df: pd.DataFrame) -> dict | None:
    """
    Replicate Pine Script logic — return signal dict or None.
    """
    if len(df) < SMA_LEN + 5:
        return None

    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    open_ = df["open"]

    ema1 = calc_ema(close, EMA_LEN)
    sma2 = calc_sma(close, SMA_LEN)
    rsi  = calc_rsi(close, RSI_LEN)
    atr  = calc_atr(df, ATR_LEN)

    # ── Current bar index (last confirmed bar = -2, current = -1) ──
    i = -1   # last closed bar

    sma_c  = sma2.iloc[i]
    ema_c  = ema1.iloc[i]
    sma_p  = sma2.iloc[i - 1]
    ema_p  = ema1.iloc[i - 1]
    rsi_c  = rsi.iloc[i]
    rsi_p  = rsi.iloc[i - 1]
    close_c = close.iloc[i]
    open_c  = open_.iloc[i]
    high_c  = high.iloc[i]
    atr_c   = atr.iloc[i]

    # ── buycall: SMA crossunder EMA AND high > SMA ──
    buycall  = (sma_p >= ema_p) and (sma_c < ema_c) and (high_c > sma_c)
    # ── sellcall: SMA crossover EMA AND open > close (bearish candle) ──
    sellcall = (sma_p <= ema_p) and (sma_c > ema_c) and (open_c > close_c)

    # ── RSI reversal alerts ──
    buyexit  = (rsi_p >= RSI_HL) and (rsi_c < RSI_HL)   # RSI crossunder 80
    sellexit = (rsi_p <= RSI_LL) and (rsi_c > RSI_LL)   # RSI crossover  20

    # ── RSI extreme ──
    rsi_overbought  = rsi_c >= RSI_OB
    rsi_oversold    = rsi_c <= RSI_OS

    if not (buycall or sellcall or buyexit or sellexit):
        return None

    signal_type = None
    if buycall:
        signal_type = "BUY"
    elif sellcall:
        signal_type = "SELL"
    elif buyexit:
        signal_type = "RSI_REVERSAL_BEAR"
    elif sellexit:
        signal_type = "RSI_REVERSAL_BULL"

    entry = close_c
    if signal_type == "BUY":
        sl  = entry - atr_c * SL_MULT
        tp1 = entry + atr_c * TP1_MULT
        tp2 = entry + atr_c * TP2_MULT
    elif signal_type == "SELL":
        sl  = entry + atr_c * SL_MULT
        tp1 = entry - atr_c * TP1_MULT
        tp2 = entry - atr_c * TP2_MULT
    else:
        sl = tp1 = tp2 = None

    # ── RSI color logic (mirror Pine) ──
    if rsi_overbought or rsi_oversold:
        rsi_zone = "⚠️ EXTREME"
    elif low.iloc[i] > sma_c:
        rsi_zone = "🟢 BULLISH ZONE"
    elif high.iloc[i] < sma_c:
        rsi_zone = "🔴 BEARISH ZONE"
    else:
        rsi_zone = "🟡 NEUTRAL"

    return {
        "signal":   signal_type,
        "entry":    entry,
        "sl":       sl,
        "tp1":      tp1,
        "tp2":      tp2,
        "rsi":      round(rsi_c, 2),
        "rsi_zone": rsi_zone,
        "atr":      round(atr_c, 6),
        "sma":      round(sma_c, 6),
        "ema":      round(ema_c, 6),
        "close":    close_c,
        "ts":       df["ts"].iloc[i],
    }


# ─────────────────────────────────────────────
# MESSAGE FORMATTER
# ─────────────────────────────────────────────
def fmt_price(p, symbol="") -> str:
    if p is None:
        return "—"
    # auto-detect decimals based on price magnitude
    if p >= 1000:
        return f"{p:,.2f}"
    elif p >= 1:
        return f"{p:.4f}"
    else:
        return f"{p:.6f}"


def build_signal_message(exchange_id: str, symbol: str, sig: dict) -> str:
    emoji_map = {
        "BUY":               "🟢",
        "SELL":              "🔴",
        "RSI_REVERSAL_BEAR": "⚠️",
        "RSI_REVERSAL_BULL": "💡",
    }
    signal_name = {
        "BUY":               "📈 BUY SIGNAL",
        "SELL":              "📉 SELL SIGNAL",
        "RSI_REVERSAL_BEAR": "⚠️ RSI ĐẢO CHIỀU GIẢM",
        "RSI_REVERSAL_BULL": "💡 RSI ĐẢO CHIỀU TĂNG",
    }
    ex_label = "🔷 Binance" if exchange_id == "binance" else "🔶 OKX"
    sym_clean = symbol.replace("/USDT:USDT", "").replace("/USDT", "")
    e = emoji_map.get(sig["signal"], "⚡")
    now_vn = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")

    lines = [
        f"{e} <b>{signal_name.get(sig['signal'], sig['signal'])}</b>",
        f"{'─' * 28}",
        f"💎 <b>{sym_clean}/USDT</b>  |  {ex_label}  |  1H",
        f"⏰ {now_vn} (VN)",
        f"{'─' * 28}",
    ]

    if sig["signal"] in ("BUY", "SELL"):
        dir_arrow = "⬆️" if sig["signal"] == "BUY" else "⬇️"
        lines += [
            f"⚡ Entry   :  <code>{fmt_price(sig['entry'])}</code>  {dir_arrow}",
            f"✅ TP1     :  <code>{fmt_price(sig['tp1'])}</code>",
            f"🎯 TP2     :  <code>{fmt_price(sig['tp2'])}</code>",
            f"🛑 SL      :  <code>{fmt_price(sig['sl'])}</code>",
            f"{'─' * 28}",
        ]
        # RR ratio
        if sig["tp2"] and sig["sl"] and sig["entry"]:
            risk   = abs(sig["entry"] - sig["sl"])
            reward = abs(sig["tp2"]   - sig["entry"])
            rr     = reward / risk if risk > 0 else 0
            lines.append(f"📊 R/R     :  <b>1 : {rr:.1f}</b>")

    lines += [
        f"📈 RSI     :  <b>{sig['rsi']}</b>  {sig['rsi_zone']}",
        f"📐 ATR     :  <code>{fmt_price(sig['atr'])}</code>",
        f"〽️ SMA50   :  <code>{fmt_price(sig['sma'])}</code>",
        f"〽️ EMA5    :  <code>{fmt_price(sig['ema'])}</code>",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# SCANNER
# ─────────────────────────────────────────────
async def scan_all(bot: Bot):
    global last_scan_time, scan_running
    if scan_running:
        log.info("Scan đang chạy, bỏ qua lượt này")
        return

    scan_running = True
    scan_start   = time.time()
    log.info("🔍 Bắt đầu scan toàn bộ USDT pairs...")

    try:
        # Lấy danh sách symbols song song
        results = await asyncio.gather(
            get_binance_symbols(),
            get_okx_symbols(),
            return_exceptions=True
        )
        all_symbols = []
        for r in results:
            if isinstance(r, list):
                all_symbols.extend(r)

        log.info(f"Tổng cộng {len(all_symbols)} symbols")

        # Scan theo batch để tránh rate limit
        BATCH = 30
        signals_found = []

        for batch_start in range(0, len(all_symbols), BATCH):
            batch = all_symbols[batch_start: batch_start + BATCH]
            tasks = [fetch_and_analyze(ex, sym) for ex, sym in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in batch_results:
                if isinstance(res, dict) and res:
                    signals_found.append(res)

            await asyncio.sleep(0.3)   # nhẹ rate limit

        # Gửi signals
        new_signals = 0
        for sig_data in signals_found:
            key = f"{sig_data['exchange']}:{sig_data['symbol']}:{sig_data['signal']}"
            prev = signal_cache.get(f"{sig_data['exchange']}:{sig_data['symbol']}")

            # Tránh gửi duplicate cùng loại signal liên tiếp
            if prev == sig_data["signal"] and sig_data["signal"] in ("BUY", "SELL"):
                continue

            signal_cache[f"{sig_data['exchange']}:{sig_data['symbol']}"] = sig_data["signal"]

            msg = build_signal_message(sig_data["exchange"], sig_data["symbol"], sig_data)
            try:
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode=ParseMode.HTML,
                )
                new_signals += 1
                scan_stats["total"] += 1
                if sig_data["signal"] == "BUY":
                    scan_stats["buy"] += 1
                elif sig_data["signal"] == "SELL":
                    scan_stats["sell"] += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                log.error(f"Telegram send error: {e}")
                scan_stats["errors"] += 1

        elapsed = time.time() - scan_start
        last_scan_time = datetime.now(VN_TZ)
        log.info(f"✅ Scan xong: {new_signals} signals mới | {len(all_symbols)} pairs | {elapsed:.1f}s")

        if new_signals == 0:
            log.info("Không có tín hiệu mới")

    except Exception as e:
        log.error(f"scan_all error: {e}")
        scan_stats["errors"] += 1
    finally:
        scan_running = False


async def fetch_and_analyze(exchange_id: str, symbol: str) -> dict | None:
    df = await fetch_ohlcv(exchange_id, symbol, timeframe="1h", limit=200)
    if df is None:
        return None
    sig = analyze(df)
    if sig is None:
        return None
    return {"exchange": exchange_id, "symbol": symbol, **sig}


# ─────────────────────────────────────────────
# TELEGRAM COMMANDS
# ─────────────────────────────────────────────
async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Scan Ngay", callback_data="scan_now"),
         InlineKeyboardButton("📊 Thống Kê",  callback_data="stats")],
        [InlineKeyboardButton("ℹ️ Trạng Thái Bot", callback_data="status")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🚀 <b>SWING CALLS BOT</b>\n\n"
        "Bot tự động scan tín hiệu <b>BUY/SELL</b> từ indicator\n"
        "<i>SMA(50)/EMA(5) Crossover + RSI + ATR SL/TP</i>\n\n"
        "📡 <b>Exchange:</b> Binance Futures + OKX Futures\n"
        "⏱ <b>Timeframe:</b> 1H\n"
        "🔁 <b>Scan mỗi:</b> 5 phút\n\n"
        "Chọn lệnh bên dưới:",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def cmd_scan(update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Đang scan... vui lòng chờ")
    await scan_all(context.bot)
    await msg.edit_text("✅ Scan hoàn tất! Kiểm tra các tin nhắn signal phía trên.")


async def cmd_stats(update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")
    last = last_scan_time.strftime("%d/%m/%Y %H:%M") if last_scan_time else "Chưa scan"
    status = "🟢 Đang chạy" if scan_running else "✅ Sẵn sàng"
    text = (
        f"📊 <b>THỐNG KÊ BOT</b>\n"
        f"{'─' * 25}\n"
        f"🕐 Giờ hiện tại : {now}\n"
        f"🔄 Lần scan cuối: {last}\n"
        f"⚙️ Trạng thái   : {status}\n"
        f"{'─' * 25}\n"
        f"📈 Tổng signal  : {scan_stats['total']}\n"
        f"🟢 BUY signals  : {scan_stats['buy']}\n"
        f"🔴 SELL signals : {scan_stats['sell']}\n"
        f"❌ Lỗi          : {scan_stats['errors']}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>HƯỚNG DẪN SỬ DỤNG</b>\n\n"
        "/start  — Màn hình chính\n"
        "/scan   — Scan tín hiệu ngay lập tức\n"
        "/stats  — Xem thống kê bot\n"
        "/help   — Hướng dẫn\n\n"
        "<b>Giải thích tín hiệu:</b>\n"
        "📈 <b>BUY</b>  — SMA50 cắt xuống EMA5 + High > SMA50\n"
        "📉 <b>SELL</b> — SMA50 cắt lên EMA5 + Nến giảm\n"
        "⚠️ <b>RSI Đảo Chiều Giảm</b> — RSI cắt xuống 80\n"
        "💡 <b>RSI Đảo Chiều Tăng</b> — RSI cắt lên 20\n\n"
        "<b>Thông số indicator:</b>\n"
        f"• EMA: {EMA_LEN} | SMA: {SMA_LEN} | RSI: {RSI_LEN}\n"
        f"• ATR: {ATR_LEN} | SL: {SL_MULT}x | TP1: {TP1_MULT}x | TP2: {TP2_MULT}x",
        parse_mode=ParseMode.HTML,
    )


async def callback_handler(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "scan_now":
        await query.edit_message_text("🔍 Đang scan toàn bộ USDT pairs...")
        await scan_all(context.bot)
        await query.edit_message_text("✅ Scan hoàn tất! Xem các signal phía trên.")

    elif query.data == "stats":
        now  = datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")
        last = last_scan_time.strftime("%d/%m/%Y %H:%M") if last_scan_time else "Chưa scan"
        await query.edit_message_text(
            f"📊 <b>THỐNG KÊ</b>\n"
            f"🕐 Hiện tại: {now}\n"
            f"🔄 Scan cuối: {last}\n"
            f"📈 Tổng: {scan_stats['total']} | 🟢 {scan_stats['buy']} | 🔴 {scan_stats['sell']}",
            parse_mode=ParseMode.HTML,
        )

    elif query.data == "status":
        st = "🟢 Đang scan" if scan_running else "✅ Idle"
        await query.edit_message_text(
            f"ℹ️ <b>TRẠNG THÁI BOT</b>\n\n"
            f"⚙️ Status: {st}\n"
            f"⏱ Scan interval: {SCAN_INTERVAL}s\n"
            f"📡 Exchange: Binance + OKX\n"
            f"📊 Timeframe: 1H",
            parse_mode=ParseMode.HTML,
        )


# ─────────────────────────────────────────────
# SCHEDULED JOB (dùng PTB job_queue — tránh event loop conflict)
# ─────────────────────────────────────────────
async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    await scan_all(context.bot)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN chưa được set!")
    if not CHAT_ID:
        raise ValueError("CHAT_ID chưa được set!")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("scan",  cmd_scan))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Dùng PTB job_queue tích hợp — chạy cùng event loop, không conflict
    job_queue = app.job_queue
    job_queue.run_repeating(
        scheduled_scan,
        interval=SCAN_INTERVAL,
        first=5,        # scan lần đầu sau 5 giây khởi động
        name="auto_scan",
    )
    log.info(f"⏰ Job queue: scan mỗi {SCAN_INTERVAL}s")
    log.info("🚀 SWING CALLS BOT khởi động...")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
