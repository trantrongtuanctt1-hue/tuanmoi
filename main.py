"""
╔══════════════════════════════════════════════════════════╗
║    TREND METER BOT — Full Market Scanner                 ║
║    Quét TOÀN BỘ thị trường Binance USDT                  ║
║    Deploy: GitHub → Railway                              ║
╚══════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import ccxt.async_support as ccxt
import requests

from indicators import analyze

# ══════════════════════════════════════════════
#   ⚙️  CONFIG — Đọc từ Environment Variables
# ══════════════════════════════════════════════

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID          = os.getenv("CHAT_ID", "")
MIN_VOLUME_USDT  = float(os.getenv("MIN_VOLUME_USDT", "1000000"))   # $1M/24h min
SCAN_INTERVAL    = int(os.getenv("SCAN_INTERVAL", "600"))            # giây
BATCH_SIZE       = int(os.getenv("BATCH_SIZE", "30"))                # coin mỗi batch
BATCH_DELAY      = float(os.getenv("BATCH_DELAY", "1.5"))           # giây giữa batch
ALERT_ON_CHANGE  = os.getenv("ALERT_ON_CHANGE", "true").lower() == "true"
TIMEFRAMES       = ["1d", "4h"]                                      # Daily + 4H

# Coin ổn định loại trừ khỏi quét
STABLE_EXCLUDE = {
    "USDC", "BUSD", "TUSD", "USDP", "DAI", "FRAX",
    "FDUSD", "PYUSD", "USDD", "GUSD", "SUSD",
}

# ══════════════════════════════════════════════
#   LOGGING
# ══════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════
#   TELEGRAM
# ══════════════════════════════════════════════

def tg_send(text: str, silent: bool = False) -> bool:
    """Gửi tin nhắn Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.warning("Chưa cấu hình TELEGRAM_TOKEN / CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id":              CHAT_ID,
                "text":                 text[:4096],
                "parse_mode":           "Markdown",
                "disable_notification": silent,
            },
            timeout=12,
        )
        return resp.status_code == 200
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


def tg_send_batch(messages: list[str]):
    """Gửi nhiều tin nhắn, ghép nếu ngắn."""
    chunk = ""
    for msg in messages:
        if len(chunk) + len(msg) + 2 > 4000:
            tg_send(chunk)
            time.sleep(0.8)
            chunk = msg
        else:
            chunk += ("\n\n" if chunk else "") + msg
    if chunk:
        tg_send(chunk)


# ══════════════════════════════════════════════
#   SYMBOL FETCHER
# ══════════════════════════════════════════════

async def fetch_all_usdt_symbols(exchange: ccxt.binance) -> list[str]:
    """Lấy tất cả cặp USDT có volume > MIN_VOLUME_USDT."""
    log.info("📥 Đang tải danh sách symbol từ Binance...")
    try:
        tickers = await exchange.fetch_tickers()
    except Exception as e:
        log.error(f"Lỗi fetch tickers: {e}")
        return []

    symbols = []
    for symbol, data in tickers.items():
        if not symbol.endswith("/USDT"):
            continue
        base = symbol.replace("/USDT", "")
        if base in STABLE_EXCLUDE:
            continue
        quote_vol = data.get("quoteVolume") or 0
        if quote_vol >= MIN_VOLUME_USDT:
            symbols.append(symbol)

    symbols.sort()
    log.info(f"✅ Tìm thấy {len(symbols)} cặp USDT đủ điều kiện (vol > ${MIN_VOLUME_USDT:,.0f})")
    return symbols


# ══════════════════════════════════════════════
#   OHLCV FETCHER
# ══════════════════════════════════════════════

async def fetch_ohlcv_safe(
    exchange: ccxt.binance, symbol: str, timeframe: str, limit: int = 150
):
    """Fetch OHLCV với error handling."""
    try:
        raw = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not raw or len(raw) < 50:
            return None
        return raw
    except ccxt.BadSymbol:
        return None
    except ccxt.RateLimitExceeded:
        await asyncio.sleep(5)
        return None
    except Exception:
        return None


# ══════════════════════════════════════════════
#   MESSAGE BUILDER
# ══════════════════════════════════════════════

TF_LABEL = {"1d": "🕯 D", "4h": "⏰ 4H"}


def build_alert(symbol: str, tf: str, r: dict) -> str:
    """Tạo tin nhắn alert."""

    def dot(v): return "🟢" if v else "🔴"

    if r["just_turned_green"]:
        signal = "🚀 *BUY* — 3 TM vừa chuyển XANH"
    elif r["just_turned_red"]:
        signal = "🔻 *SELL* — 3 TM vừa chuyển ĐỎ"
    elif r["all_green"]:
        signal = "✅ *3 TM XANH* — Xu hướng TĂNG"
    else:
        signal = "❌ *3 TM ĐỎ* — Xu hướng GIẢM"

    wt = ""
    if r["wt_cross_up"]   and r["all_green"]: wt = "\n⚡ WaveTrend Cross *UP*"
    if r["wt_cross_down"] and r["all_red"]:   wt = "\n⚡ WaveTrend Cross *DOWN*"

    tb_ok = (r["tb1"] and r["tb2"] and r["all_green"]) or \
            (not r["tb1"] and not r["tb2"] and r["all_red"])
    tb_confirm = " ✔️ TB xác nhận" if tb_ok else ""

    return (
        f"*{symbol}* {TF_LABEL[tf]}\n"
        f"{signal}{wt}{tb_confirm}\n"
        f"TM: {dot(r['tm1'])}MACD {dot(r['tm2'])}R13 {dot(r['tm3'])}R5 "
        f"| TB: {dot(r['tb1'])}1 {dot(r['tb2'])}2\n"
        f"RSI13:`{r['rsi13']}` RSI5:`{r['rsi5']}` "
        f"| 💰`{r['close']:,.4f}`"
    )


# ══════════════════════════════════════════════
#   SCAN ENGINE
# ══════════════════════════════════════════════

# state: symbol_tf → previous result
_state: dict[str, dict] = {}


async def scan_symbol(exchange, symbol: str) -> list[str]:
    """Quét 1 symbol trên tất cả TF, trả về danh sách alert."""
    alerts = []
    for tf in TIMEFRAMES:
        raw = await fetch_ohlcv_safe(exchange, symbol, tf)
        if raw is None:
            continue

        try:
            r = analyze(raw)
        except Exception:
            continue

        key = f"{symbol}_{tf}"
        prev = _state.get(key)

        should_alert = False

        if ALERT_ON_CHANGE:
            # Chỉ báo khi VỪA đổi màu
            if r["just_turned_green"] or r["just_turned_red"]:
                should_alert = True
            # Hoặc WaveTrend cross đồng chiều
            if (r["wt_cross_up"] and r["all_green"]) or \
               (r["wt_cross_down"] and r["all_red"]):
                should_alert = True
        else:
            # Báo khi 3 TM align + cả 2 TB cùng chiều
            if r["all_green"] and r["tb1"] and r["tb2"]:
                should_alert = True
            if r["all_red"] and not r["tb1"] and not r["tb2"]:
                should_alert = True

        # Tránh lặp cùng trạng thái
        if prev and prev.get("all_green") == r["all_green"] \
                 and prev.get("all_red")   == r["all_red"] \
                 and not r["just_turned_green"] \
                 and not r["just_turned_red"]:
            should_alert = False

        if should_alert:
            alerts.append(build_alert(symbol, tf, r))

        _state[key] = r

    return alerts


async def scan_market(exchange, symbols: list[str]) -> tuple[int, int]:
    """Quét toàn thị trường theo batch. Trả về (coin quét được, alert gửi)."""
    total_scanned = 0
    total_alerts  = 0
    all_alerts    = []

    log.info(f"🔍 Bắt đầu quét {len(symbols)} coin theo batch {BATCH_SIZE}...")

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        tasks = [scan_symbol(exchange, s) for s in batch]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                all_alerts.extend(res)
                total_scanned += 1

        progress = min(i + BATCH_SIZE, len(symbols))
        log.info(f"  → {progress}/{len(symbols)} coin | alerts: {len(all_alerts)}")

        await asyncio.sleep(BATCH_DELAY)

    # Gửi tất cả alert
    if all_alerts:
        header = (
            f"📡 *TREND METER ALERT*\n"
            f"🕒 `{now_utc()}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        tg_send(header + all_alerts[0] if all_alerts else header, silent=False)
        time.sleep(0.5)
        if len(all_alerts) > 1:
            tg_send_batch(all_alerts[1:])

        total_alerts = len(all_alerts)

    return total_scanned, total_alerts


# ══════════════════════════════════════════════
#   STARTUP SUMMARY
# ══════════════════════════════════════════════

async def send_startup_summary(exchange, symbols: list[str]):
    """Gửi bảng tổng quan khi khởi động."""
    log.info("📊 Tạo bảng tổng quan khởi động...")

    # Lấy mẫu 20 coin hàng đầu
    sample = symbols[:20]
    lines  = [
        "🤖 *TREND METER BOT — Online*",
        f"🕒 `{now_utc()}`",
        f"📊 Đang theo dõi: *{len(symbols)} coin* USDT",
        f"⏱ Quét mỗi: `{SCAN_INTERVAL//60} phút`",
        f"📌 Vol tối thiểu: `${MIN_VOLUME_USDT/1_000_000:.1f}M/24h`",
        "━━━━━━━━━━━━━━━━━━━━",
        "📋 *Snapshot 20 coin đầu:*",
    ]

    for symbol in sample:
        row = f"`{symbol.replace('/USDT',''):>8}`"
        for tf in TIMEFRAMES:
            raw = await fetch_ohlcv_safe(exchange, symbol, tf, limit=100)
            if raw is None:
                row += f" {TF_LABEL[tf]}❓"
                continue
            try:
                r = analyze(raw)
                if r["all_green"]:
                    row += f" {TF_LABEL[tf]}🟢"
                elif r["all_red"]:
                    row += f" {TF_LABEL[tf]}🔴"
                else:
                    g = r["green_count"]
                    row += f" {TF_LABEL[tf]}🟡{g}/3"
            except Exception:
                row += f" {TF_LABEL[tf]}⚠️"
            await asyncio.sleep(0.1)
        lines.append(row)

    lines += [
        "━━━━━━━━━━━━━━━━━━━━",
        "✅ Bot đang chạy và theo dõi thị trường!",
    ]
    tg_send("\n".join(lines))


# ══════════════════════════════════════════════
#   HELPERS
# ══════════════════════════════════════════════

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ══════════════════════════════════════════════
#   MAIN LOOP
# ══════════════════════════════════════════════

async def main():
    log.info("=" * 55)
    log.info("  TREND METER BOT — FULL MARKET SCANNER")
    log.info("=" * 55)

    if not TELEGRAM_TOKEN or not CHAT_ID:
        log.error("❌ Thiếu TELEGRAM_TOKEN hoặc CHAT_ID!")
        log.error("   Set environment variables trên Railway.")
        return

    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})

    # Lấy danh sách symbol lần đầu
    symbols = await fetch_all_usdt_symbols(exchange)
    if not symbols:
        log.error("Không lấy được danh sách symbol!")
        await exchange.close()
        return

    # Gửi tóm tắt khởi động
    await send_startup_summary(exchange, symbols)

    # Tracking thời điểm refresh danh sách
    last_symbol_refresh = time.time()
    SYMBOL_REFRESH_INTERVAL = 6 * 3600  # 6 giờ refresh lại list

    scan_count = 0

    while True:
        try:
            loop_start = time.time()
            scan_count += 1

            # Refresh symbol list mỗi 6 giờ
            if time.time() - last_symbol_refresh > SYMBOL_REFRESH_INTERVAL:
                log.info("🔄 Refresh danh sách symbol...")
                new_symbols = await fetch_all_usdt_symbols(exchange)
                if new_symbols:
                    symbols = new_symbols
                    last_symbol_refresh = time.time()

            log.info(f"\n{'='*50}")
            log.info(f"🔍 Lần quét #{scan_count} — {now_utc()}")
            log.info(f"{'='*50}")

            scanned, alerts = await scan_market(exchange, symbols)

            elapsed = time.time() - loop_start
            log.info(
                f"✅ Xong! Quét: {scanned} coin | "
                f"Alert: {alerts} | Thời gian: {elapsed:.0f}s"
            )

            # Summary mỗi 12 lần (mỗi 2 giờ nếu interval=10min)
            if scan_count % 12 == 0:
                tg_send(
                    f"📊 *Báo cáo định kỳ*\n"
                    f"🕒 `{now_utc()}`\n"
                    f"✅ Đã quét `{scanned}` coin\n"
                    f"📬 Đã gửi `{alerts}` alert lần này\n"
                    f"🔄 Lần quét #{scan_count}",
                    silent=True,
                )

            # Tính thời gian chờ còn lại
            wait = max(0, SCAN_INTERVAL - elapsed)
            log.info(f"⏳ Chờ {wait:.0f}s đến lần quét tiếp theo...")
            await asyncio.sleep(wait)

        except asyncio.CancelledError:
            break
        except KeyboardInterrupt:
            log.info("Bot dừng.")
            break
        except Exception as e:
            log.error(f"Lỗi vòng lặp: {e}", exc_info=True)
            tg_send(f"⚠️ Bot gặp lỗi: `{str(e)[:200]}`\nĐang thử lại...", silent=True)
            await asyncio.sleep(60)

    await exchange.close()
    log.info("Bot đã tắt.")


if __name__ == "__main__":
    asyncio.run(main())
