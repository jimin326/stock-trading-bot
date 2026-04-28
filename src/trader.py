import time
from datetime import datetime, date

from src.broker import get_account, get_position, buy_market, sell_market, cancel_all_orders, is_shortable
from src.data_feed import get_bars
from src.strategy import get_signal, Signal
from src.risk import position_size, check_exit_long, check_exit_short
from src.scanner import scan_market
import src.config as config


def is_market_open() -> bool:
    from alpaca.trading.client import TradingClient
    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True)
    return client.get_clock().is_open


def run(interval_sec: int = 300):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 트레이딩 봇 시작")

    active_symbols: list[str] = config.TRADE_SYMBOLS
    last_scan_date: date | None = None

    while True:
        try:
            if not is_market_open():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 장 마감 — {interval_sec}초 후 재확인")
                time.sleep(interval_sec)
                continue

            today = date.today()

            if last_scan_date != today:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 종목 스캔 중...")
                scan_results = scan_market()
                if scan_results:
                    active_symbols = [r.symbol for r in scan_results]
                    print(f"  스캔 결과 ({len(active_symbols)}종목):")
                    for r in scan_results:
                        print(f"    {r}")
                else:
                    active_symbols = config.TRADE_SYMBOLS
                    print(f"  스캔 조건 미충족 → 기본 종목 사용: {active_symbols}")
                last_scan_date = today

            acct   = get_account()
            equity = acct["equity"]
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 자산 ${equity:,.2f} | 오늘 손익 ${acct['pnl']:+,.2f}")
            print(f"  대상: {active_symbols}")

            for symbol in active_symbols:
                df = get_bars(symbol, days=5, timeframe=config.TIMEFRAME)
                if df.empty:
                    continue

                from src.indicators import add_indicators
                df_ind        = add_indicators(df)
                current_price = df_ind["close"].iloc[-1]
                ema9          = df_ind["ema9"].iloc[-1]
                position      = get_position(symbol)

                if position:
                    entry    = float(position.avg_entry_price)
                    qty      = int(position.qty)
                    side     = "long" if float(position.qty) > 0 else "short"
                    cur_open = df_ind["open"].iloc[-1]

                    if side == "long":
                        do_exit, _, reason = check_exit_long(current_price, cur_open, current_price, ema9, entry)
                    else:
                        do_exit, _, reason = check_exit_short(current_price, cur_open, current_price, ema9, entry)

                    if do_exit:
                        print(f"  [{symbol}] 청산({reason}) | 진입 ${entry:.2f} → 현재 ${current_price:.2f}")
                        sell_market(symbol, qty)
                        continue

                signal, reason, confidence = get_signal(df)

                if signal == Signal.BUY and not position:
                    qty  = position_size(equity, current_price, confidence)
                    cost = qty * current_price
                    if cost <= acct["cash"] * 0.95:
                        print(f"  [{symbol}] 매수(확신도{confidence}) | {reason}")
                        buy_market(symbol, qty)

                elif signal == Signal.SELL and not position:
                    if is_shortable(symbol):
                        qty = position_size(equity, current_price, confidence)
                        print(f"  [{symbol}] 숏 진입(확신도{confidence}) | {reason}")
                    else:
                        print(f"  [{symbol}] HOLD (공매도 불가) | {reason}")

                else:
                    print(f"  [{symbol}] {signal.value} | {reason}")

        except KeyboardInterrupt:
            print("\n봇 종료 — 미체결 주문 취소 중...")
            cancel_all_orders()
            break
        except Exception as e:
            print(f"오류: {e}")

        time.sleep(interval_sec)


if __name__ == "__main__":
    run()
