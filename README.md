# 📡 Trend Meter Bot — Full Market Scanner

Quét **toàn bộ thị trường Binance USDT** theo logic **Trend Meter (Lij_MC)**  
Chạy 24/7 miễn phí trên **Railway** qua **GitHub**.

---

## ✨ Tính năng

- 🔍 Quét **toàn bộ** cặp USDT trên Binance (300–600 coin)
- 🕯 Khung thời gian: **Daily (1D)** và **4H**
- 📊 Logic **Trend Meter**: 3 TM + 2 TB + WaveTrend
- 🔔 Alert Telegram khi cả 3 TM **vừa đồng loạt đổi màu**
- ⚡ WaveTrend Cross để xác nhận tín hiệu mạnh
- 🔄 Tự động refresh danh sách coin mỗi 6 giờ
- 🚀 Deploy 1 click lên Railway

---

## 🚀 Deploy lên Railway (Bước từng bước)

### Bước 1 — Chuẩn bị Telegram Bot

1. Mở Telegram → tìm **[@BotFather](https://t.me/BotFather)**
2. Gõ `/newbot` → đặt tên → nhận **TOKEN**
3. Tìm **[@userinfobot](https://t.me/userinfobot)** → `/start` → nhận **CHAT_ID**

> Gửi vào nhóm: Thêm bot vào nhóm → tìm **[@getmyid_bot](https://t.me/getmyid_bot)**

---

### Bước 2 — Đẩy code lên GitHub

```bash
# Clone hoặc fork repo này
git clone https://github.com/YOUR_USERNAME/trend-meter-bot.git
cd trend-meter-bot

# Nếu tạo mới
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/trend-meter-bot.git
git push -u origin main
```

---

### Bước 3 — Deploy trên Railway

1. Vào **[railway.app](https://railway.app)** → Đăng nhập bằng GitHub
2. Nhấn **"New Project"** → **"Deploy from GitHub repo"**
3. Chọn repo `trend-meter-bot`
4. Railway tự detect `railway.toml` và build

---

### Bước 4 — Set Environment Variables trên Railway

Vào **project → Variables** → thêm:

| Variable | Giá trị | Bắt buộc |
|----------|---------|----------|
| `TELEGRAM_TOKEN` | Token từ BotFather | ✅ |
| `CHAT_ID` | ID của bạn hoặc nhóm | ✅ |
| `MIN_VOLUME_USDT` | `1000000` | Không |
| `SCAN_INTERVAL` | `600` | Không |
| `ALERT_ON_CHANGE` | `true` | Không |

Sau khi set → Railway tự động **redeploy**.

---

## 📊 Ý nghĩa tín hiệu

### 3 Trend Meters
| TM | Indicator | Xanh khi |
|----|-----------|----------|
| TM1 | Fast MACD (8, 21, 5) | Histogram > 0 |
| TM2 | RSI 13 | RSI 13 > 50 |
| TM3 | RSI 5 | RSI 5 > 50 |

### 2 Trend Bars (xác nhận)
| TB | Indicator | Xanh khi |
|----|-----------|----------|
| TB1 | EMA 5 / EMA 11 | EMA5 > EMA11 |
| TB2 | EMA 13 / SMA 36 | EMA13 > SMA36 |

### Loại alert
| Alert | Điều kiện |
|-------|-----------|
| 🚀 BUY | 3 TM vừa đồng loạt chuyển XANH |
| 🔻 SELL | 3 TM vừa đồng loạt chuyển ĐỎ |
| ⚡ WaveTrend Cross | Xác nhận thêm, tín hiệu mạnh hơn |

---

## 📩 Mẫu tin nhắn

```
📡 TREND METER ALERT
🕒 2024-01-15 08:30 UTC
━━━━━━━━━━━━━━━━━━━━

BTC/USDT 🕯 D
🚀 BUY — 3 TM vừa chuyển XANH ✔️ TB xác nhận
⚡ WaveTrend Cross UP
TM: 🟢MACD 🟢R13 🟢R5 | TB: 🟢1 🟢2
RSI13: 58.3 RSI5: 72.1 | 💰 68,420.0000

ETH/USDT ⏰ 4H
🔻 SELL — 3 TM vừa chuyển ĐỎ
TM: 🔴MACD 🔴R13 🔴R5 | TB: 🔴1 🔴2
RSI13: 42.1 RSI5: 28.5 | 💰 3,210.5000
```

---

## ⚙️ Tuỳ chỉnh nâng cao

### Đổi volume filter
```
MIN_VOLUME_USDT=5000000   # Chỉ lấy coin volume > $5M
```

### Quét nhanh hơn
```
SCAN_INTERVAL=300    # Quét mỗi 5 phút
BATCH_SIZE=50        # Tăng batch size
BATCH_DELAY=1.0      # Giảm delay giữa batch
```

### Tắt filter chỉ alert khi đổi màu
```
ALERT_ON_CHANGE=false   # Alert mỗi khi 3 TM đang align
```

---

## 💡 Lưu ý

- Railway **Free tier**: $5 credit/tháng, đủ chạy ~500 giờ
- **Hobby plan** ($5/tháng): Chạy không giới hạn 24/7
- Bot sẽ gửi **báo cáo định kỳ** mỗi 2 giờ (silent notification)
- Log xem trong Railway → **Deployments → View Logs**
