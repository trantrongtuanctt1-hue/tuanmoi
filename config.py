"""
SXL + MTF Scanner Bot — Config
Tất cả cấu hình đọc từ biến môi trường (.env / Railway Variables)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── OKX (public endpoints không cần key) ──────────────────────────────────
OKX_API_KEY      = os.getenv("OKX_API_KEY", "")
OKX_SECRET       = os.getenv("OKX_SECRET", "")
OKX_PASSPHRASE   = os.getenv("OKX_PASSPHRASE", "")

# ── Scanner ────────────────────────────────────────────────────────────────
SCAN_INTERVAL_MIN = int(os.getenv("SCAN_INTERVAL_MIN", "15"))   # phút giữa mỗi lần scan
MAX_PAIRS         = int(os.getenv("MAX_PAIRS", "80"))            # tối đa bao nhiêu cặp
MIN_BUY_SCORE     = int(os.getenv("MIN_BUY_SCORE", "7"))         # ngưỡng alert (/ 11)
MIN_VOLUME_USDT   = float(os.getenv("MIN_VOLUME_USDT", "2000000"))  # khối lượng 24h tối thiểu
CONCURRENCY       = int(os.getenv("CONCURRENCY", "5"))           # request đồng thời
ALERT_COOLDOWN_H  = int(os.getenv("ALERT_COOLDOWN_H", "2"))      # giờ không alert lại cùng cặp

# ── Indicator params (giống Pine Script) ──────────────────────────────────
EMA_FAST      = 20
EMA_SLOW      = 50
EMA_TREND     = 200
RSI_PERIOD    = 14
ATR_PERIOD    = 14
BB_PERIOD     = 20
BB_MULT       = 2.0
ST_FACTOR     = 3.0     # SuperTrend multiplier
ST_PERIOD     = 10
UT_KEY_VAL    = 1.0
UT_ATR_PERIOD = 10
SAR_START     = 0.02
SAR_INC       = 0.02
SAR_MAX       = 0.2
VOL_LOOKBACK  = 100
VOL_THRESH    = 65.0
RSI_LOOKBACK  = 3       # nến để tính hướng RSI
RSI_THRESHOLD = 1.5     # điểm thay đổi tối thiểu để tính up/down

# ── R:R ───────────────────────────────────────────────────────────────────
SL_MULT  = 1.5
TP1_MULT = 1.5
TP2_MULT = 3.0

# ── Minimum candles cần thiết ─────────────────────────────────────────────
MIN_BARS = 250

# ── OKX timeframes ────────────────────────────────────────────────────────
TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"]
TF_BARS    = 300  # số nến lấy mỗi TF
