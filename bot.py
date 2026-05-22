import os
import asyncio
import ccxt.pro as ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==================== CẤU HÌNH BIẾN MÔI TRƯỜNG ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))  # Chuyển về kiểu số nguyên để định tuyến chính xác
SCAN_INTERVAL_MINS = int(os.getenv("SCAN_INTERVAL_MINS", "5"))

# Khởi tạo kết nối sàn OKX
exchange = ccxt.okx({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# Biến trạng thái điều khiển Bot
bot_active = True

# ==================== HÀM LOGIC QUÉT THỊ TRƯỜNG ====================
async def run_market_scan():
    """Hàm lõi xử lý quét toàn bộ thị trường OKX"""
    try:
        await exchange.load_markets()
        symbols = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
        
        found_signals = []
        
        for symbol in symbols:
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='5m', limit=21)
                if len(ohlcv) < 21:
                    continue
                
                current_volume = ohlcv[-2][5] 
                past_volumes = [candle[5] for candle in ohlcv[-21:-1]]
                avg_volume = sum(past_volumes) / len(past_volumes)
                
                if avg_volume == 0:
                    continue
                    
                vol_ratio = current_volume / avg_volume
                current_price = ohlcv[-2][4]
                
                # Điều kiện lọc Volume Spike 2.5x
                if vol_ratio >= 2.5:
                    found_signals.append({
                        "symbol": symbol.split('/')[0],
                        "price": current_price,
                        "ratio": vol_ratio
                    })
            except:
                continue
            await asyncio.sleep(0.05) # Giảm nhẹ delay để quét nhanh hơn một chút
            
        return found_signals
    except Exception as e:
        print(f"Lỗi fetch dữ liệu sàn: {e}")
        return None

# ==================== HÀM CHẠY TỰ ĐỘNG THEO CHU KỲ ====================
async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Hàm chạy ngầm được JobQueue gọi tự động"""
    global bot_active
    if not bot_active:
        return  # Nếu bot đang tạm dừng thì bỏ qua chu kỳ này

    print("🔄 [Chu kỳ] Đang tự động quét thị trường OKX...")
    signals = await run_market_scan()
    
    if signals:
        for coin in signals:
            msg = (
                f"🎯 *[AUTO SCAN] PUMP DETECTED!*\n\n"
                f"🪙 **Token:** `{coin['symbol']}`\n"
                f"💵 **Giá:** `{coin['price']} USDT`\n"
                f"📊 **Volume:** 🔥 `{coin['ratio']:.2f}x` (So với MA20)\n"
                f"⏰ **Khung:** `5m`"
            )
            await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)

# ==================== CÁC LỆNH ĐIỀU KHIỂN (COMMANDS) ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start: Kiểm tra quyền truy cập và chào mừng"""
    if update.effective_chat.id != CHAT_ID:
        return # Bảo mật: Chỉ phản hồi đúng Chat ID của chủ sở hữu
        
    menu_text = (
        "🤖 *Hệ thống Quét OKX Pro đã sẵn sàng!*\n\n"
        "Các lệnh bạn có thể dùng để điều khiển:\n"
        "⚡ /scan - Kích hoạt quét toàn thị trường ngay lập tức\n"
        "⏸️ /pause - Tạm dừng tính năng tự động quét theo chu kỳ\n"
        "▶️ /resume - Tiếp tục tự động quét theo chu kỳ\n"
        "📊 /status - Kiểm tra tình trạng hoạt động hiện tại của Bot"
    )
    await update.message.reply_text(menu_text, parse_mode="Markdown")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /scan: Ép bot quét thị trường ngay lập tức"""
    if update.effective_chat.id != CHAT_ID:
        return
        
    await update.message.reply_text("🔍 Đang quét thủ công toàn bộ các cặp USDT trên OKX... Vui lòng đợi trong giây lát.")
    signals = await run_market_scan()
    
    if signals is None:
        await update.message.reply_text("❌ Quá trình quét thất bại do lỗi kết nối API sàn.")
    elif len(signals) == 0:
        await update.message.reply_text("✅ Đã quét xong. Hiện tại không có token nào đạt đủ điều kiện Volume Spike >= 2.5x.")
    else:
        await update.message.reply_text(f"🚀 Tìm thấy {len(signals)} token bất thường! Đang gửi danh sách...")
        for coin in signals:
            msg = (
                f"🎯 *[MANUAL SCAN] PUMP DETECTED!*\n\n"
                f"🪙 **Token:** `{coin['symbol']}`\n"
                f"💵 **Giá:** `{coin['price']} USDT`\n"
                f"📊 **Volume:** 🔥 `{coin['ratio']:.2f}x`\n"
                f"⏰ **Khung:** `5m`"
            )
            await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            await asyncio.sleep(0.5)

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /pause: Tạm dừng quét tự động"""
    if update.effective_chat.id != CHAT_ID:
        return
    global bot_active
    bot_active = False
    await update.message.reply_text("⏸️ Đã tạm dừng chế độ tự động quét theo chu kỳ.")

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /resume: Tiếp tục quét tự động"""
    if update.effective_chat.id != CHAT_ID:
        return
    global bot_active
    bot_active = True
    await update.message.reply_text("▶️ Đã kích hoạt lại chế độ tự động quét theo chu kỳ.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /status: Xem trạng thái hiện tại của bot"""
    if update.effective_chat.id != CHAT_ID:
        return
    status = "🟢 Đang tự động quét ngầm" if bot_active else "⏸️ Đang tạm dừng quét ngầm"
    await update.message.reply_text(
        f"📊 *BÁO CÁO TRẠNG THÁI BOT:*\n"
        f"▪️ Tình trạng: {status}\n"
        f"▪️ Chu kỳ quét: `{SCAN_INTERVAL_MINS} phút / lần`\n"
        f"▪️ Sàn giao dịch mục tiêu: `OKX (Spot)`", 
        parse_mode="Markdown"
    )

# ==================== HÀM KHỞI CHẠY CHÍNH ====================
def main():
    # Tạo ứng dụng bot tích hợp sẵn hệ thống xử lý vòng lặp (loop)
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Đăng ký các bộ xử lý lệnh (Commands)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("pause", pause_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))

    # Đăng ký Job quét ngầm tự động chạy theo chu kỳ thời gian
    job_queue = application.job_queue
    job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL_MINS * 60, first=10)

    # Kích hoạt chế độ Long Polling để giữ Bot luôn lắng nghe lệnh
    print("🚀 Bot Telegram đã được kích hoạt và đang lắng nghe lệnh trên Railway...")
    application.run_polling()

if __name__ == "__main__":
    main()
