from enum import Enum
import pandas as pd

from src.config import RSI_OVERSOLD, RSI_OVERBOUGHT
from src.indicators import add_indicators, latest


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def get_signal(df: pd.DataFrame) -> tuple[Signal, str]:
    df = add_indicators(df)
    row = latest(df)

    rsi = row["rsi"]
    macd_diff = row["macd_diff"]
    ma_short = row["ma_short"]
    ma_long = row["ma_long"]
    close = row["close"]
    bb_lower = row["bb_lower"]
    bb_upper = row["bb_upper"]

    if pd.isna(rsi) or pd.isna(macd_diff):
        return Signal.HOLD, "지표 계산 데이터 부족"

    # 매수 조건: RSI 과매도 + 골든크로스 + MACD 양전환
    buy_rsi = rsi < RSI_OVERSOLD
    buy_ma = ma_short > ma_long
    buy_macd = macd_diff > 0
    buy_bb = close <= bb_lower * 1.01  # 볼린저 하단 근처

    # 매도 조건: RSI 과매수 또는 MACD 음전환 또는 볼린저 상단 돌파
    sell_rsi = rsi > RSI_OVERBOUGHT
    sell_macd = macd_diff < 0 and row["macd"] > 0
    sell_bb = close >= bb_upper * 0.99

    if buy_rsi and (buy_ma or buy_macd):
        return Signal.BUY, f"RSI={rsi:.1f}(과매도) + {'골든크로스' if buy_ma else 'MACD양전환'}"

    if buy_bb and buy_macd:
        return Signal.BUY, f"볼린저하단({bb_lower:.2f}) 반등 + MACD양전환"

    if sell_rsi and (sell_macd or sell_bb):
        return Signal.SELL, f"RSI={rsi:.1f}(과매수) + {'MACD음전환' if sell_macd else '볼린저상단'}"

    if sell_bb and sell_macd:
        return Signal.SELL, f"볼린저상단({bb_upper:.2f}) 돌파 + MACD음전환"

    return Signal.HOLD, f"RSI={rsi:.1f} | MACD={macd_diff:.4f} | MA{ma_short:.2f}/{ma_long:.2f}"


if __name__ == "__main__":
    from src.data_feed import get_bars

    for symbol in ["AAPL", "TSLA", "NVDA", "MSFT"]:
        df = get_bars(symbol, days=30)
        signal, reason = get_signal(df)
        print(f"[{signal.value:4s}] {symbol:5s} | {reason}")
