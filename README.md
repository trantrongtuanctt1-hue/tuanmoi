# 🎯 Pump Scanner Bot

Telegram bot tự động scan và phát hiện token có khả năng pump cao dựa trên:
- 📊 Volume Spike (3đ)
- 📈 CVD Trend + Divergence (3đ)
- 📉 Bollinger Bands Squeeze (2đ)
- 🏛️ SMC CHoCH/BOS (2đ)
- 🔭 EMA Trend Filter (1đ)

---

## 📦 Cài đặt

### 1. Tạo Telegram Bot

1. Nhắn `@BotFather` trên Telegram → `/newbot`
2. Đặt tên bot → nhận **BOT_TOKEN**
3. Nhắn `/start` với bot của bạn
4. Lấy **CHAT_ID**: truy cập `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`

### 2. Push lên GitHub

```bash
git init
git add .
git commit -m "init pump scanner bot"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/pump-scanner-bot.git
git push -u origin main
```

### 3. Deploy Railway

1. Vào [railway.app](https://railway.app) → **New Project**
2. Chọn **Deploy from GitHub repo** → chọn repo vừa tạo
3. Vào **Variables** → thêm các biến sau:

| Biến | Bắt buộc | Mô tả | Ví dụ |
|------|----------|-------|-------|
| `BOT_TOKEN` | ✅ | Token từ BotFather | `7123456789:AAH...` |
| `CHAT_ID` | ✅ | ID chat nhận alert | `-1001234567890` |
| `SCAN_INTERVAL` | | Phút giữa mỗi lần scan | `30` |
| `TOP_N` | | Số token scan | `200` |
| `TIMEFRAME` | | Khung thời gian | `15m` |
| `MIN_SCORE` | | Ngưỡng điểm alert | `6` |
| `VOL_MULT` | | Ngưỡng volume spike | `2.5` |
| `VOL_MEGA_X` | | Ngưỡng volume mega | `4.0` |
| `BB_SQUEEZE_THRESH` | | BB Width % squeeze | `3.0` |
| `CONCURRENCY` | | Số request song song | `10` |
| `EXCHANGE` | | Sàn giao dịch | `binanceusdm` |

4. Railway sẽ tự deploy → bot bắt đầu chạy

---

## 🤖 Lệnh Bot

| Lệnh | Mô tả |
|------|-------|
| `/start` | Menu chính |
| `/scan` | Scan toàn bộ market ngay |
| `/top 7` | Top token có score ≥ 7 |
| `/check EDEN 15` | Phân tích token EDEN TF 15m |
| `/status` | Xem trạng thái bot |
| `/help` | Hướng dẫn |

---

## 📊 Hệ thống điểm (0–10)

```
🚀 Score ≥ 8  →  TÍN HIỆU RẤT MẠNH
⚡ Score ≥ 6  →  Tiềm năng cao
⚠️ Score ≥ 4  →  Cần theo dõi
😴 Score < 4  →  Yếu / bỏ qua
```

---

## ⚙️ Cấu trúc project

```
pump_scanner_bot/
├── bot.py              # Entry point, commands, auto-scan job
├── src/
│   ├── config.py       # Đọc biến môi trường
│   └── scanner.py      # Logic tính toán (Volume/CVD/BB/SMC/EMA)
├── requirements.txt
├── Procfile
├── railway.toml
└── README.md
```

---

## 🔄 Flow hoạt động

```
Railway start → bot.py
    ↓
JobQueue: mỗi SCAN_INTERVAL phút
    ↓
scanner.scan_all()
    → fetch top TOP_N token theo volume (USDT futures)
    → async semaphore CONCURRENCY requests song song
    → tính Volume/CVD/BB/SMC/EMA score cho từng token
    ↓
Lọc score >= MIN_SCORE
    ↓
Gửi alert Telegram → CHAT_ID
```
