import argparse
from src.trader import run
from src.broker import get_account, get_positions
from src.backtest import run_backtest
from src.data_feed import get_bars
from src.config import TRADE_SYMBOLS


def cmd_status():
    acct = get_account()
    print(f"=== 계좌 현황 ===")
    print(f"총 자산    : ${acct['equity']:,.2f}")
    print(f"현금       : ${acct['cash']:,.2f}")
    print(f"오늘 손익  : ${acct['pnl']:+,.2f}")

    positions = get_positions()
    if positions:
        print(f"\n=== 보유 포지션 ===")
        for p in positions:
            print(f"  {p.symbol:6s} | {p.qty}주 | 평균가 ${float(p.avg_entry_price):.2f} | 손익 ${float(p.unrealized_pl):+.2f}")
    else:
        print("\n보유 포지션 없음")


def cmd_backtest(days: int):
    for symbol in TRADE_SYMBOLS:
        df = get_bars(symbol, days=days)
        result = run_backtest(df, symbol)
        result.summary()


def cmd_run(interval: int):
    run(interval_sec=interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Trading Bot")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="계좌 현황 확인")

    bt = sub.add_parser("backtest", help="백테스트 실행")
    bt.add_argument("--days", type=int, default=90, help="백테스트 기간(일)")

    bot = sub.add_parser("run", help="봇 실행")
    bot.add_argument("--interval", type=int, default=300, help="체크 주기(초)")

    args = parser.parse_args()

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "backtest":
        cmd_backtest(args.days)
    elif args.cmd == "run":
        cmd_run(args.interval)
    else:
        parser.print_help()
