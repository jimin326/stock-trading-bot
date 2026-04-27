import itertools
import pandas as pd
from dataclasses import dataclass

from src.data_feed import get_bars
from src.backtest import run_backtest
import src.config as config


@dataclass
class OptimResult:
    symbol: str
    rsi_oversold: int
    rsi_overbought: int
    ma_short: int
    ma_long: int
    stop_loss_pct: float
    take_profit_pct: float
    total_return: float
    win_rate: float
    mdd: float
    sharpe: float
    trades: int

    def score(self) -> float:
        # 수익률 높고, MDD 낮고, 샤프 높고, 거래 수 적당할수록 좋음
        if self.trades < 5 or self.mdd < -30:
            return -999
        return self.sharpe * 0.4 + self.total_return * 0.4 + (self.mdd * 0.2)


def optimize(symbol: str, days: int = 90) -> list[OptimResult]:
    df = get_bars(symbol, days=days)

    param_grid = {
        "rsi_oversold":   [20, 25, 30],
        "rsi_overbought": [70, 75, 80],
        "ma_short":       [5, 9, 12],
        "ma_long":        [21, 26, 34],
        "stop_loss_pct":  [0.01, 0.02, 0.03],
        "take_profit_pct":[0.02, 0.04, 0.06],
    }

    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    total = len(combos)
    results = []

    print(f"\n{symbol} 최적화 시작 — 총 {total}개 조합 테스트 중...")

    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))

        # config 임시 덮어쓰기
        config.RSI_OVERSOLD = params["rsi_oversold"]
        config.RSI_OVERBOUGHT = params["rsi_overbought"]
        config.MA_SHORT = params["ma_short"]
        config.MA_LONG = params["ma_long"]
        config.STOP_LOSS_PCT = params["stop_loss_pct"]
        config.TAKE_PROFIT_PCT = params["take_profit_pct"]

        try:
            result = run_backtest(df.copy(), symbol)
            results.append(OptimResult(
                symbol=symbol,
                **params,
                total_return=result.total_return_pct,
                win_rate=result.win_rate,
                mdd=result.mdd,
                sharpe=result.sharpe,
                trades=len(result.trades),
            ))
        except Exception:
            continue

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{total} 완료...")

    results.sort(key=lambda r: r.score(), reverse=True)
    return results


def print_top(results: list[OptimResult], n: int = 5):
    print(f"\n{'='*60}")
    print(f"  상위 {n}개 파라미터 조합")
    print(f"{'='*60}")
    for i, r in enumerate(results[:n], 1):
        print(f"\n  [{i}위] 점수: {r.score():.2f}")
        print(f"    수익률: {r.total_return:+.2f}%  MDD: {r.mdd:.2f}%  샤프: {r.sharpe:.2f}  거래: {r.trades}건  승률: {r.win_rate:.1f}%")
        print(f"    RSI: {r.rsi_oversold}/{r.rsi_overbought}  MA: {r.ma_short}/{r.ma_long}  SL: {r.stop_loss_pct*100:.0f}%  TP: {r.take_profit_pct*100:.0f}%")


def apply_best(result: OptimResult):
    config.RSI_OVERSOLD = result.rsi_oversold
    config.RSI_OVERBOUGHT = result.rsi_overbought
    config.MA_SHORT = result.ma_short
    config.MA_LONG = result.ma_long
    config.STOP_LOSS_PCT = result.stop_loss_pct
    config.TAKE_PROFIT_PCT = result.take_profit_pct
    print(f"\n최적 파라미터 적용 완료: {result.symbol}")


if __name__ == "__main__":
    symbol = "AAPL"
    results = optimize(symbol, days=90)
    print_top(results, n=5)
