"""
Config — đọc từ biến môi trường Railway
"""
import os

class Config:
    # ── Telegram ──────────────────────────────────────────────────────────
    BOT_TOKEN: str = os.environ["BOT_TOKEN"]          # bắt buộc
    CHAT_ID:   str = os.environ["CHAT_ID"]            # bắt buộc (chat_id nhận alert)

    # ── Scan ──────────────────────────────────────────────────────────────
    SCAN_INTERVAL: int   = int(os.getenv("SCAN_INTERVAL", "30"))    # phút
    TOP_N:         int   = int(os.getenv("TOP_N", "200"))            # số token scan
    TIMEFRAME:     str   = os.getenv("TIMEFRAME", "15m")             # 5m 15m 1h 4h
    MIN_SCORE:     int   = int(os.getenv("MIN_SCORE", "6"))          # 0-10

    # ── Volume ────────────────────────────────────────────────────────────
    VOL_LEN:       int   = int(os.getenv("VOL_LEN", "20"))          # EMA length
    VOL_MULT:      float = float(os.getenv("VOL_MULT", "2.5"))      # spike threshold
    VOL_MEGA_X:    float = float(os.getenv("VOL_MEGA_X", "4.0"))    # mega threshold

    # ── CVD ───────────────────────────────────────────────────────────────
    CVD_LEN:       int   = int(os.getenv("CVD_LEN", "14"))

    # ── Bollinger Bands ───────────────────────────────────────────────────
    BB_LEN:            int   = int(os.getenv("BB_LEN", "20"))
    BB_MULT:           float = float(os.getenv("BB_MULT", "2.0"))
    BB_SQUEEZE_THRESH: float = float(os.getenv("BB_SQUEEZE_THRESH", "3.0"))  # %

    # ── SMC ───────────────────────────────────────────────────────────────
    SMC_LEN:       int   = int(os.getenv("SMC_LEN", "10"))          # swing lookback

    # ── EMA Trend ─────────────────────────────────────────────────────────
    EMA_FAST:      int   = int(os.getenv("EMA_FAST", "50"))
    EMA_SLOW:      int   = int(os.getenv("EMA_SLOW", "200"))

    # ── Exchange ──────────────────────────────────────────────────────────
    EXCHANGE:      str   = os.getenv("EXCHANGE", "binanceusdm")     # binanceusdm / bybit
    CONCURRENCY:   int   = int(os.getenv("CONCURRENCY", "10"))      # async semaphore
