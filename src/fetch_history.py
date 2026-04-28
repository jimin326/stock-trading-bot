"""
알파카 체결 내역을 가져와서 logs/trades.csv 로 저장
매수-매도 쌍을 맞춰 수익 계산
"""
from datetime import datetime, timezone
from collections import defaultdict
import csv, os

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

import src.config as config

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "trades.csv")
HEADERS  = ["날짜", "종목", "방향", "매수가", "매도가", "수량", "수익금($)", "수익률(%)", "사유"]


def fetch_and_save():
    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True)

    req    = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500)
    orders = client.get_orders(req)

    # 체결 완료된 주문만 필터
    filled = [o for o in orders if o.status.value == "filled"]
    filled.sort(key=lambda o: o.filled_at)

    # 종목별로 매수→매도 쌍 맞추기 (FIFO)
    queues: dict[str, list] = defaultdict(list)
    trades = []

    for o in filled:
        symbol     = o.symbol
        qty        = int(float(o.filled_qty))
        price      = float(o.filled_avg_price)
        side       = o.side.value   # "buy" | "sell"
        filled_at  = o.filled_at

        if side == "buy":
            queues[symbol].append({"price": price, "qty": qty, "time": filled_at})
        else:  # sell → 매수 큐에서 FIFO 매칭
            remaining = qty
            while remaining > 0 and queues[symbol]:
                entry     = queues[symbol][0]
                match_qty = min(remaining, entry["qty"])

                profit     = (price - entry["price"]) * match_qty
                profit_pct = (price - entry["price"]) / entry["price"] * 100

                trades.append({
                    "날짜":     filled_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "종목":     symbol,
                    "방향":     "롱",
                    "매수가":   f"{entry['price']:.2f}",
                    "매도가":   f"{price:.2f}",
                    "수량":     match_qty,
                    "수익금($)": f"{profit:+.2f}",
                    "수익률(%)": f"{profit_pct:+.2f}",
                    "사유":     "",
                })

                entry["qty"] -= match_qty
                remaining    -= match_qty
                if entry["qty"] == 0:
                    queues[symbol].pop(0)

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS)
        w.writeheader()
        for t in trades:
            w.writerow(t)

    print(f"총 {len(trades)}건 저장 → {LOG_PATH}")
    for t in trades:
        print(f"  {t['날짜']} | {t['종목']:6s} | {t['매수가']} → {t['매도가']} | {t['수익금($)']}$ ({t['수익률(%)']}%)")


if __name__ == "__main__":
    fetch_and_save()
