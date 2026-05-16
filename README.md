# ⚡ 15M ULTRA Signal Bot

Bot Telegram tự động quét crypto Binance dựa trên logic **15M ULTRA indicator**:
ST AI + UT Bot + SAR + SMC Bias + MTF RSI → cho điểm 0-11.

---

## 🚀 Setup trong 10 phút

### Bước 1 — Tạo Telegram Bot

1. Mở Telegram, tìm **@BotFather**
2. Gõ `/newbot` → đặt tên → nhận **TOKEN**
3. Tìm **@userinfobot** → nhận **CHAT_ID** của bạn

### Bước 2 — Fork repo lên GitHub

```
Fork → Settings → Secrets and variables → Actions
```

Thêm các **Secrets**:

| Secret              | Giá trị                       |
|---------------------|-------------------------------|
| `TELEGRAM_TOKEN`    | Token từ BotFather            |
| `TELEGRAM_CHAT_IDS` | Chat ID của bạn (VD: 123456789) |
| `BINANCE_API_KEY`   | *(để trống — không bắt buộc)* |
| `BINANCE_SECRET`    | *(để trống — không bắt buộc)* |

Thêm các **Variables** (tuỳ chỉnh, có thể để mặc định):

| Variable                | Mặc định | Ý nghĩa                    |
|-------------------------|----------|----------------------------|
| `SCAN_INTERVAL_MINUTES` | `5`      | Quét mỗi N phút            |
| `MIN_ALERT_SCORE`       | `7`      | Ngưỡng alert (7=BUY/SELL)  |
| `MIN_VOLUME_USD`        | `50000000` | Volume tối thiểu 24h      |
| `MAX_SYMBOLS`           | `30`     | Số token quét mỗi chu kỳ  |

### Bước 3 — Kích hoạt GitHub Actions

```
Actions → "15M ULTRA Signal Bot" → Enable → Run workflow
```

Bot sẽ tự khởi động lại mỗi ~6 giờ (GitHub Actions limit).

---

## 💻 Chạy local (development)

```bash
git clone https://github.com/YOUR_USERNAME/crypto-signal-bot
cd crypto-signal-bot

pip install -r requirements.txt

cp .env.example .env
# Điền TELEGRAM_TOKEN và TELEGRAM_CHAT_IDS vào .env

python main.py
```

---

## 📱 Lệnh Telegram

| Lệnh | Chức năng |
|------|-----------|
| `/scan` | Quét top 30 token, hiện tín hiệu ≥7/11 |
| `/top` | Top 5 tín hiệu mạnh nhất |
| `/check BTCUSDT` | Phân tích 1 token cụ thể |
| `/status` | Kiểm tra bot có sống không |
| `/help` | Hướng dẫn |

---

## 📊 Cách tính điểm (0-11)

**6 điều kiện cơ bản (Section M):**
- SMC Swing bias ▲/▼
- ST AI (SuperTrend) ▲/▼  
- UT Bot ▲/▼
- Parabolic SAR ▲/▼
- SMC Internal bias ▲/▼
- Zone (not Premium/Discount)

**+5 điểm bonus MTF:**
- +2 CTX: 1H + 4H + 1D đồng thuận
- +1 BRG: 30M bridge
- +1 MTM: 5M momentum
- +1 RSI: ≥4/6 TF RSI cùng chiều

**Thang điểm:**
```
🚀 9-11 = STRONG BUY / STRONG SELL  
✅  7-8  = BUY / SELL  
↑↓  5-6  = LEAN (chưa đủ)  
⏳  <5   = NEUTRAL — chờ
```

---

## 🗂 Cấu trúc project

```
crypto-signal-bot/
├── main.py              # Entrypoint
├── src/
│   ├── signals.py       # Tính toán ST AI, UT Bot, SAR, SMC, RSI score
│   ├── fetcher.py       # Lấy OHLCV từ Binance
│   ├── scanner.py       # Quét nhiều token, dedup alert
│   └── bot.py           # Telegram bot handlers + formatter
├── .github/
│   └── workflows/
│       └── bot.yml      # GitHub Actions deploy
├── .env.example         # Template cấu hình
└── requirements.txt
```

---

## ⚠️ Lưu ý

- Binance public API **không cần API key** để đọc giá/OHLCV
- GitHub Actions free tier: 2000 phút/tháng → đủ cho bot 24/7
- Cooldown 15 phút/token để tránh spam alert
- Đây là **tín hiệu tham khảo**, không phải lời khuyên tài chính
