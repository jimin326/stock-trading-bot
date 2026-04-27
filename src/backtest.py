import pandas as pd
import numpy as np
from dataclasses import dataclass, field

from src.indicators import add_indicators
from src.config import (
    RSI_OVERSOLD, RSI_OVERBOUGHT,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, MAX_POSITION_PCT
)


@dataclass
class Trade:
    symbol: str
    entry_time: pd.Timestamp
    entry_price: float
    qty: int
    exit_time: pd.Timestamp = None
    exit_price: float = None
    reason: str = ""

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def pnl_pct(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price * 100


@dataclass
class BacktestResult:
    symbol: str
    initial_equity: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return self.initial_equity + sum(t.pnl for t in self.trades)

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity - self.initial_equity) / self.initial_equity * 100

    @property
    def win_rate(self) -> float:
        wins = [t for t in self.trades if t.pnl > 0]
        return len(wins) / len(self.trades) * 100 if self.trades else 0

    @property
    def mdd(self) -> float:
        if not self.equity_curve:
            return 0.0
        curve = np.array(self.equity_curve)
        peak = np.maximum.accumulate(curve)
        drawdown = (curve - peak) / peak * 100
        return float(drawdown.min())

    @property
    def sharpe(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        returns = [t.pnl_pct for t in self.trades]
        mean = np.mean(returns)
        std = np.std(returns)
        return round(mean / std * np.sqrt(252) if std > 0 else 0.0, 2)

    def summary(self):
        print(f"\n{'='*45}")
        print(f"  백테스트 결과: {self.symbol}")
        print(f"{'='*45}")
        print(f"  초기 자본    : ${self.initial_equity:>10,.2f}")
        print(f"  최종 자본    : ${self.final_equity:>10,.2f}")
        print(f"  총 수익률    : {self.total_return_pct:>+9.2f}%")
        print(f"  최대 낙폭    : {self.mdd:>+9.2f}%")
        print(f"  샤프 비율    : {self.sharpe:>10.2f}")
        print(f"  총 거래 수   : {len(self.trades):>10}건")
        print(f"  승률         : {self.win_rate:>9.1f}%")
        if self.trades:
            avg_pnl = np.mean([t.pnl_pct for t in self.trades])
            print(f"  평균 수익률  : {avg_pnl:>+9.2f}%")
        print(f"{'='*45}")


def run_backtest(df: pd.DataFrame, symbol: str, initial_equity: float = 10000.0) -> BacktestResult:
    df = add_indicators(df).dropna()
    result = BacktestResult(symbol=symbol, initial_equity=initial_equity)

    equity = initial_equity
    position: Trade | None = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        price = row["close"]
        result.equity_curve.append(equity)

        # 포지션 보유 중 → 손절/익절 체크
        if position:
            sl = position.entry_price * (1 - STOP_LOSS_PCT)
            tp = position.entry_price * (1 + TAKE_PROFIT_PCT)

            if price <= sl:
                position.exit_time = row.name
                position.exit_price = price
                position.reason = "손절"
                equity += position.pnl
                result.trades.append(position)
                position = None
                continue

            if price >= tp:
                position.exit_time = row.name
                position.exit_price = price
                position.reason = "익절"
                equity += position.pnl
                result.trades.append(position)
                position = None
                continue

            # 매도 신호
            sell_rsi = row["rsi"] > RSI_OVERBOUGHT
            sell_macd = row["macd_diff"] < 0 and prev["macd_diff"] >= 0
            if sell_rsi or sell_macd:
                position.exit_time = row.name
                position.exit_price = price
                position.reason = "RSI과매수" if sell_rsi else "MACD음전환"
                equity += position.pnl
                result.trades.append(position)
                position = None

        # 포지션 없음 → 매수 신호 체크
        else:
            buy_rsi = row["rsi"] < RSI_OVERSOLD
            buy_macd = row["macd_diff"] > 0 and prev["macd_diff"] <= 0
            buy_ma = row["ma_short"] > row["ma_long"] and prev["ma_short"] <= prev["ma_long"]
            buy_bb = price <= row["bb_lower"] * 1.01

            if (buy_rsi or buy_bb) and (buy_macd or buy_ma):
                qty = max(int(equity * MAX_POSITION_PCT / price), 1)
                if equity >= price * qty:
                    position = Trade(
                        symbol=symbol,
                        entry_time=row.name,
                        entry_price=price,
                        qty=qty,
                    )

    # 마지막에 포지션 남아있으면 강제 청산
    if position:
        last = df.iloc[-1]
        position.exit_time = last.name
        position.exit_price = last["close"]
        position.reason = "강제청산"
        equity += position.pnl
        result.trades.append(position)

    result.equity_curve.append(equity)
    return result


if __name__ == "__main__":
    from src.data_feed import get_bars

    symbols = ["AAPL", "TSLA", "NVDA", "MSFT"]

    for symbol in symbols:
        df = get_bars(symbol, days=90)
        result = run_backtest(df, symbol)
        result.summary()

        if result.trades:
            print(f"\n  최근 거래 5건:")
            for t in result.trades[-5:]:
                print(f"    {t.entry_time.strftime('%m/%d')} → {t.exit_time.strftime('%m/%d')} "
                      f"| {t.pnl_pct:+.2f}% | {t.reason}")
