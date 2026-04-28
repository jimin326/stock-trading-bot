import time
from datetime import datetime, date, timedelta

from src.broker import get_account, get_position, get_positions, buy_market, sell_market, cancel_all_orders
from src.trade_logger import log_trade
from src.data_feed import get_bars
from src.indicators import add_indicators
from src.strategy import get_signal, Signal
from src.risk import position_size, check_exit_long, check_exit_short
from src.scanner import scan_market
import src.config as config


def is_market_open() -> bool:
    from alpaca.trading.client import TradingClient
    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING)
    return client.get_clock().is_open


def minutes_to_close() -> int:
    """장 마감까지 남은 분 (마감 후면 0)"""
    from alpaca.trading.client import TradingClient
    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER_TRADING)
    clock  = client.get_clock()
    if not clock.is_open:
        return 0
    remaining = (clock.next_close - clock.timestamp).total_seconds() / 60
    return int(remaining)


def close_all_for_eod():
    """장마감 10분 전 모든 포지션 강제 청산"""
    positions = get_positions()
    if not positions:
        return
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 장마감 임박 — 포지션 전체 청산")
    for p in positions:
        symbol = p.symbol
        qty    = abs(int(float(p.qty)))
        side   = "long" if float(p.qty) > 0 else "short"
        entry  = float(p.avg_entry_price)
        try:
            if side == "long":
                order = sell_market(symbol, qty)
            else:
                order = buy_market(symbol, qty)
            fill = float(order.filled_avg_price) if order.filled_avg_price else float(p.current_price)
            log_trade(symbol, side, entry, fill, qty, "장마감강제청산")
        except Exception as e:
            print(f"  [{symbol}] 청산 실패: {e}")


def run(interval_sec: int = 300):
    mode = "페이퍼" if config.PAPER_TRADING else "실전"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 트레이딩 봇 시작 [{mode}]")

    active_symbols: list[str] = list(config.TRADE_SYMBOLS)
    last_scan_date: date | None = None
    cooldown_until: dict[str, datetime] = {}
    eod_closed = False  # 오늘 장마감 청산 완료 여부

    while True:
        try:
            now   = datetime.now()
            today = date.today()

            if not is_market_open():
                eod_closed = False  # 날짜 바뀌면 초기화
                print(f"[{now.strftime('%H:%M:%S')}] 장 마감 — {interval_sec}초 후 재확인")
                time.sleep(interval_sec)
                continue

            # ── 장마감 10분 전 강제 청산 ────────────────────────
            mins_left = minutes_to_close()
            if mins_left <= 10 and not eod_closed:
                close_all_for_eod()
                eod_closed = True
                time.sleep(interval_sec)
                continue

            # ── 하루 1회 스캔 ────────────────────────────────────
            if last_scan_date != today:
                print(f"\n[{now.strftime('%H:%M:%S')}] 종목 스캔 중...")
                scan_results = scan_market()
                scanned = [r.symbol for r in scan_results if r.symbol not in config.TRADE_SYMBOLS]
                active_symbols = list(config.TRADE_SYMBOLS) + scanned
                if scanned:
                    print(f"  스캐너 추가 종목: {scanned}")
                    for r in scan_results:
                        if r.symbol in scanned:
                            print(f"    {r}")
                print(f"  전체 감시 ({len(active_symbols)}종목): {active_symbols}")
                last_scan_date = today
                cooldown_until.clear()  # 날짜 바뀌면 쿨다운 초기화

            acct   = get_account()
            equity = acct["equity"]
            print(f"\n[{now.strftime('%H:%M:%S')}] 자산 ${equity:,.2f} | 오늘 손익 ${acct['pnl']:+,.2f} | 장마감까지 {mins_left}분")

            # 기존 포지션 종목도 항상 체크
            held_symbols  = [p.symbol for p in get_positions()]
            watch_symbols = list(dict.fromkeys(held_symbols + active_symbols))
            print(f"  대상: {watch_symbols}")

            for symbol in watch_symbols:
                df = get_bars(symbol, days=5, timeframe=config.TIMEFRAME)
                if df.empty:
                    continue

                df_ind        = add_indicators(df)
                current_price = df_ind["close"].iloc[-1]
                ema9          = df_ind["ema9"].iloc[-1]
                cur_open      = df_ind["open"].iloc[-1]
                position      = get_position(symbol)

                # ── 포지션 청산 체크 ──────────────────────────────
                if position:
                    entry = float(position.avg_entry_price)
                    qty   = abs(int(float(position.qty)))
                    side  = "long" if float(position.qty) > 0 else "short"

                    if side == "long":
                        do_exit, _, reason = check_exit_long(
                            current_price, cur_open, current_price, ema9, entry,
                            strict=config.STRICT_EXIT)
                    else:
                        do_exit, _, reason = check_exit_short(
                            current_price, cur_open, current_price, ema9, entry,
                            strict=config.STRICT_EXIT)

                    if do_exit:
                        order = sell_market(symbol, qty) if side == "long" else buy_market(symbol, qty)
                        fill  = float(order.filled_avg_price) if order.filled_avg_price else current_price
                        print(f"  [{symbol}] 청산({reason}) | ${entry:.2f} → ${fill:.2f}")
                        log_trade(symbol, side, entry, fill, qty, reason)
                        cooldown_until[symbol] = datetime.now() + timedelta(seconds=config.COOLDOWN_BARS * interval_sec)
                        print(f"  [{symbol}] 쿨다운 {config.COOLDOWN_BARS}캔들 ({config.COOLDOWN_BARS * interval_sec // 60}분)")
                        continue
                    else:
                        pnl = (current_price - entry) * qty if side == "long" else (entry - current_price) * qty
                        print(f"  [{symbol}] 보유중 | ${entry:.2f} → ${current_price:.2f} ({pnl:+.2f}$)")
                    continue

                # ── 쿨다운 체크 ───────────────────────────────────
                if symbol in cooldown_until and datetime.now() < cooldown_until[symbol]:
                    remaining = int((cooldown_until[symbol] - datetime.now()).seconds / 60)
                    print(f"  [{symbol}] 쿨다운 중 ({remaining}분 남음)")
                    continue

                # ── 진입 신호 체크 ────────────────────────────────
                signal, reason, confidence = get_signal(df_ind)

                if signal == Signal.BUY:
                    qty  = position_size(equity, current_price, confidence)
                    cost = qty * current_price
                    if cost <= acct["cash"] * 0.95:
                        print(f"  [{symbol}] 매수(확신도{confidence}) | {reason}")
                        buy_market(symbol, qty)
                    else:
                        print(f"  [{symbol}] 매수신호 but 현금부족 | {reason}")
                elif signal == Signal.SELL:
                    print(f"  [{symbol}] HOLD (롱온리) | {reason}")
                else:
                    print(f"  [{symbol}] {reason}")

        except KeyboardInterrupt:
            print("\n봇 종료 — 미체결 주문 취소 중...")
            cancel_all_orders()
            break
        except Exception as e:
            print(f"[오류] {e}")
            import traceback
            traceback.print_exc()

        time.sleep(interval_sec)


if __name__ == "__main__":
    run()
