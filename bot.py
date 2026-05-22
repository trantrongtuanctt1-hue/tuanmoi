import os
import asyncio
import ccxt.pro as ccxt
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ==================== CẤU HÌNH BIẾN MÔI TRƯỜNG ====================
# Các biến này sẽ được cấu hình an toàn trên Railway, không hardcode vào đây
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SCAN_INTERVAL_MINS = int(os.getenv("SCAN_INTERVAL_MINS", "5")) # Mặc định quét mỗi 5 phút

# Khởi tạo Bot Telegram
tg_bot = Bot(token=TELEGRAM_TOKEN)

# Khởi tạo kết nối sàn OKX (Sử dụng CCXT công khai, không cần API Key)
exchange = ccxt.okx({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'} # Quét thị trường Giao ngay (Spot)
})

async def scan_okx_market():
    print("🔄 Đang bắt đầu quét toàn bộ thị trường OKX...")
    try:
        # 1. Lấy danh sách tất cả các cặp giao dịch công khai
        await exchange.load_markets()
        # Lọc ra các cặp có đuôi /USDT và đang hoạt động
        symbols = [s for s in exchange.symbols if s.endswith('/USDT') and exchange.markets[s]['active']]
        
        print(f"📊 Tìm thấy {len(symbols)} cặp USDT đang hoạt động. Tiến hành phân tích...")
        
        # 2. Duyệt qua từng cặp tiền để check điều kiện (Ví dụ: Volume Spike)
        for symbol in symbols:
            try:
                # Lấy dữ liệu 21 cây nến gần nhất khung 5m (hoặc thay bằng 1h, 4h tuỳ bạn)
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='5m', limit=21)
                if len(ohlcv) < 21:
                    continue
                
                # Nến hiện tại (chưa đóng cửa hoàn toàn) là ohlcv[-1]
                # Nến vừa đóng cửa là ohlcv[-2]
                current_volume = ohlcv[-2][5] 
                
                # Tính trung bình Volume của 20 nến trước đó (từ -22 đến -3)
                past_volumes = [candle[5] for candle in ohlcv[-21:-1]]
                avg_volume = sum(past_volumes) / len(past_volumes)
                
                if avg_volume == 0:
                    continue
                    
                vol_ratio = current_volume / avg_volume
                current_price = ohlcv[-2][4] # Giá đóng cửa nến gần nhất
                
                # ĐIỀU KIỆN LỌC: Volume nến vừa rồi gấp 2.5 lần trung bình 20 nến trước
                if vol_ratio >= 2.5:
                    message = (
                        f"🎯 *[OKX SCANNER] PUMP DETECTED!*\n\n"
                        f"🪙 **Token:** `{symbol.split('/')[0]}`\n"
                        f"💵 **Giá hiện tại:** `{current_price} USDT`\n"
                        f"📊 **Volume Spike:** 🔥 `{vol_ratio:.2f}x` (So với MA20)\n"
                        f"⏰ **Khung thời gian:** `5m`"
                    )
                    # Gửi thông báo về Telegram
                    await tg_bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
                    await asyncio.sleep(0.5) # Tránh bị Telegram chặn rate limit khi gửi nhiều
                    
            except Exception as e:
                # Bỏ qua lỗi của riêng lẻ từng coin (ví dụ mất thanh khoản, lỗi API tạm thời)
                continue
                
            # Nghỉ ngắn giữa các lần gọi API sàn để không bị OKX ban IP
            await asyncio.sleep(0.1)
            
        print("✅ Đã quét xong toàn bộ thị trường.")
        
    except Exception as e:
        print(f"❌ Lỗi hệ thống quét: {e}")

async def main():
    # Khởi chạy quét lần đầu ngay khi bật bot
    await scan_okx_market()
    
    # Thiết lập lịch trình tự động quét ngầm
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scan_okx_market, 'interval', minutes=SCAN_INTERVAL_MINS)
    scheduler.start()
    
    # Giữ cho bot chạy vô hạn trên Railway
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    # Đóng kết nối sàn an toàn khi tắt bot
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
