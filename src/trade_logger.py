import csv
import os
from datetime import datetime


LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "trades.csv")
HEADERS  = ["날짜", "종목", "방향", "매수가", "매도가", "수량", "수익금($)", "수익률(%)", "사유"]


def _ensure_file():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    if not os.path.exists(LOG_PATH):
        with open(LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(HEADERS)


def log_trade(
    symbol: str,
    side: str,          # "long" | "short"
    entry_price: float,
    exit_price: float,
    qty: int,
    reason: str = "",
):
    _ensure_file()

    if side == "long":
        profit     = (exit_price - entry_price) * qty
        profit_pct = (exit_price - entry_price) / entry_price * 100
    else:
        profit     = (entry_price - exit_price) * qty
        profit_pct = (entry_price - exit_price) / entry_price * 100

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        symbol,
        "롱" if side == "long" else "숏",
        f"{entry_price:.2f}",
        f"{exit_price:.2f}",
        qty,
        f"{profit:+.2f}",
        f"{profit_pct:+.2f}",
        reason,
    ]

    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(row)

    print(f"  [기록] {symbol} {row[2]} | 진입 ${entry_price:.2f} → 청산 ${exit_price:.2f} | {profit:+.2f}$ ({profit_pct:+.2f}%)")
