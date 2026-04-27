import time
from datetime import datetime, timezone

from src.broker import get_account, get_position, buy_market, sell_market, cancel_all_orders
from src.data_feed import get_bars
from src.strategy import get_signal, Signal
from src.risk import position_size, should_stop_loss, should_take_profit
from src.config import TRADE_SYMBOLS, get_timeframe, get_ema_period


def is_market_open() -> bool:
    from alpaca.trading.client import TradingClient
    from src.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
    client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    clock = client.get_clock()
    return clock.is_open


def run(symbols: list[str] = TRADE_SYMBOLS, interval_sec: int = 300):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 트레이딩 봇 시작")
    print(f"대상 종목: {symbols}")
    print(f"체크 주기: {interval_sec}초\n")

    while True:
        try:
            if not is_market_open():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 장 마감 — {interval_sec}초 후 재확인")
                time.sleep(interval_sec)
                continue

            acct = get_account()
            equity = acct["equity"]
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 자산 ${equity:,.2f} | 오늘 손익 ${acct['pnl']:+,.2f}")

            for symbol in symbols:
                df = get_bars(symbol, days=5, timeframe=get_timeframe(symbol))
                if df.empty:
                    continue

                current_price = df["close"].iloc[-1]
                position = get_position(symbol)

                # 포지션 보유 중 → 손절/익절 체크
                if position:
                    entry = float(position.avg_entry_price)
                    qty = int(position.qty)

                    if should_stop_loss(entry, current_price):
                        print(f"  [{symbol}] 손절 실행 | 진입 ${entry:.2f} → 현재 ${current_price:.2f}")
                        sell_market(symbol, qty)
                        continue

                    if should_take_profit(entry, current_price):
                        print(f"  [{symbol}] 익절 실행 | 진입 ${entry:.2f} → 현재 ${current_price:.2f}")
                        sell_market(symbol, qty)
                        continue

                # 신호 확인
                signal, reason = get_signal(df, ema_period=get_ema_period(symbol))

                if signal == Signal.BUY and not position:
                    qty = position_size(equity, current_price)
                    cost = qty * current_price
                    if cost <= acct["cash"] * 0.95:
                        print(f"  [{symbol}] 매수 신호 | {reason}")
                        buy_market(symbol, qty)

                elif signal == Signal.SELL and position:
                    qty = int(position.qty)
                    print(f"  [{symbol}] 매도 신호 | {reason}")
                    sell_market(symbol, qty)

                else:
                    print(f"  [{symbol}] {signal.value} | {reason}")

        except KeyboardInterrupt:
            print("\n봇 종료 — 미체결 주문 취소 중...")
            cancel_all_orders()
            break
        except Exception as e:
            print(f"오류 발생: {e}")

        time.sleep(interval_sec)


if __name__ == "__main__":
    run()
