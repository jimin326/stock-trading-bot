import itertools
from dataclasses import dataclass

from src.data_feed import get_bars
from src.backtest import run_backtest
import src.config as config


@dataclass
class OptimResult:
    symbol: str
    timeframe: str
    ema_period: int
    total_return: float
    win_rate: float
    mdd: float
    sharpe: float
    trades: int

    def score(self) -> float:
        if self.trades < 5 or self.mdd < -30:
            return -999
        return self.sharpe * 0.4 + self.total_return * 0.4 + (self.mdd * 0.2)


def optimize(symbol: str, days: int = 90) -> list[OptimResult]:
    param_grid = {
        "timeframe":  ["5Min", "15Min", "1Hour"],
        "ema_period": [5, 9, 12, 21],
    }

    combos = list(itertools.product(*param_grid.values()))
    total  = len(combos)
    results = []

    print(f"\n{symbol} 최적화 시작 — 총 {total}개 조합...")

    for i, (tf, ema) in enumerate(combos):
        config.TIMEFRAME   = tf
        config.EMA_PERIOD  = ema

        try:
            df = get_bars(symbol, days=days, timeframe=tf)
            if len(df) < 30:
                continue
            result = run_backtest(df, symbol)
            results.append(OptimResult(
                symbol=symbol,
                timeframe=tf,
                ema_period=ema,
                total_return=result.total_return_pct,
                win_rate=result.win_rate,
                mdd=result.mdd,
                sharpe=result.sharpe,
                trades=len(result.trades),
            ))
        except Exception:
            continue

        print(f"  [{i+1}/{total}] {tf} EMA{ema} → "
              f"수익 {result.total_return_pct:+.2f}%  "
              f"샤프 {result.sharpe:.2f}  거래 {len(result.trades)}건")

    results.sort(key=lambda r: r.score(), reverse=True)
    return results


def apply_best(symbol: str, result: OptimResult):
    config.SYMBOL_TIMEFRAME[symbol] = result.timeframe
    config.SYMBOL_EMA[symbol] = result.ema_period
    print(f"[{symbol}] 최적 설정 → {result.timeframe} / EMA{result.ema_period}")


def run_all(days: int = 90):
    print("=" * 55)
    print("  전 종목 타임프레임 최적화")
    print("=" * 55)

    best_results = {}
    for symbol in config.TRADE_SYMBOLS:
        results = optimize(symbol, days=days)
        if not results:
            continue

        best = results[0]
        best_results[symbol] = best
        apply_best(symbol, best)

        print(f"\n  [{symbol}] 최적 결과")
        print(f"    타임프레임 : {best.timeframe}")
        print(f"    EMA 기간   : {best.ema_period}")
        print(f"    수익률     : {best.total_return:+.2f}%")
        print(f"    MDD        : {best.mdd:.2f}%")
        print(f"    샤프 비율  : {best.sharpe:.2f}")
        print(f"    거래 수    : {best.trades}건  승률 {best.win_rate:.1f}%")

    print("\n" + "=" * 55)
    print("  최종 종목별 타임프레임 요약")
    print("=" * 55)
    for sym, r in best_results.items():
        print(f"  {sym:6s} → {r.timeframe:6s}  EMA{r.ema_period}  "
              f"수익 {r.total_return:+.2f}%  샤프 {r.sharpe:.2f}")

    return best_results


if __name__ == "__main__":
    run_all(days=90)
