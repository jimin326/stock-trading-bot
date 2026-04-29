"""
롱온리 vs 롱+숏 백테스트 비교
실행: python compare_long_short.py [--days 60]
"""
import argparse
import numpy as np
from src.backtest import run_scanner_backtest


def print_table(rows):
    W = 80
    print("\n" + "=" * W)
    print(f"  {'전략':<18} │ {'거래':>4} {'승':>4} {'패':>4} {'승률':>6} {'수익률':>8} {'MDD':>8} {'샤프':>6}")
    print("  " + "─" * 18 + "─┼─" + "─" * 47)
    for r in rows:
        print(
            f"  {r['label']:<18} │"
            f" {r['trades']:4d} {r['wins']:4d} {r['losses']:4d}"
            f" {r['win_rate']:5.1f}%"
            f" {r['total_return']:+7.2f}%"
            f" {r['mdd']:+7.2f}%"
            f" {r['sharpe']:6.2f}"
        )
    print("=" * W)

    # 롱/숏 거래 비중 (both 케이스만)
    for r in rows:
        if "long" in r and "short" in r:
            print(f"\n  [{r['label']}] 방향별 상세:")
            for side, stats in [("long", r["long"]), ("short", r["short"])]:
                if stats["n"] == 0:
                    print(f"    {side:5s} : 거래 없음")
                    continue
                print(
                    f"    {side:5s} : {stats['n']:3d}건  "
                    f"승률 {stats['wr']:5.1f}%  "
                    f"평균수익 {stats['avg']:+6.2f}%  "
                    f"총수익 ${stats['total']:+.2f}"
                )
    print()


def side_stats(trades, side):
    t = [x for x in trades if x.side == side]
    if not t:
        return {"n": 0, "wr": 0, "avg": 0, "total": 0}
    wins = [x for x in t if x.pnl > 0]
    return {
        "n": len(t),
        "wr": len(wins) / len(t) * 100,
        "avg": np.mean([x.pnl_pct for x in t]),
        "total": sum(x.pnl for x in t),
    }


def main(days: int = 60):
    scenarios = [
        {"label": "롱온리",    "side_filter": "long_only"},
        {"label": "롱+숏",    "side_filter": "both"},
    ]

    rows = []
    result_cache = None

    for sc in scenarios:
        print(f"\n▶ [{sc['label']}] 백테스트 시작 (최근 {days}일)...")
        result = run_scanner_backtest(days=days, side_filter=sc["side_filter"])

        trades = result.trades
        wins   = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        row = {
            "label":        sc["label"],
            "trades":       len(trades),
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     result.win_rate,
            "total_return": result.total_return_pct,
            "mdd":          result.mdd,
            "sharpe":       result.sharpe,
        }
        if sc["side_filter"] == "both":
            row["long"]  = side_stats(trades, "long")
            row["short"] = side_stats(trades, "short")

        rows.append(row)

    print_table(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    main(days=args.days)
